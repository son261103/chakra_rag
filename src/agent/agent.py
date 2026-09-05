"""Agent RAG dùng LangGraph: LLM tự gọi các tool (search_docs, read_chunk, list_documents).

Tool định nghĩa trong agent/tools/ (registry @register_tool) — thêm tool mới
chỉ cần tạo file ở đó, agent tự nhận qua build_tools().

Guardrails:
- recursion_limit = 2*max_turns + 1 (mỗi lượt tool = 2 bước graph) chống loop.
- Bằng chứng hợp lệ = tập chunk_id xuất hiện trong ToolMessage của phiên;
  citation verifier ở core/verification.py chỉ chấp nhận tập này.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langgraph.prebuilt import create_react_agent
from langsmith import get_current_run_tree

from agent.llm import ThinkingChatOpenAI
from agent.tools import ToolDeps, build_tools
from config import Config
from core.retrieval import Retriever
from core.security import decrypt_integration_key

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Bạn là trợ lý trả lời câu hỏi dựa trên tài liệu nội bộ kết hợp "
    "kiến thức chuyên môn.\n"
    "\n"
    "Công cụ tra cứu:\n"
    "- search_docs(query, top_k): tìm kiếm hybrid trên toàn bộ tài liệu — công cụ CHÍNH.\n"
    "- read_chunk(chunk_id): đọc đầy đủ một đoạn tài liệu theo chunk_id (lấy từ search_docs).\n"
    "- list_documents(): liệt kê tài liệu đang có trong hệ thống (tên, trạng thái, số đoạn).\n"
    "\n"
    "Quy tắc bắt buộc:\n"
    "1. Ưu tiên tra cứu tài liệu: Với câu hỏi về dữ liệu, hồ sơ, sự kiện, dự án hoặc thông tin "
    "nội bộ, PHẢI gọi search_docs trước để tìm bằng chứng.\n"
    "2. Trích dẫn nguồn: Mọi khẳng định lấy từ tài liệu nội bộ phải kèm mã trích dẫn [chunk_id] "
    "của đoạn tài liệu tương ứng (chunk_id từ kết quả search_docs hoặc read_chunk).\n"
    "3. Tự dừng và dùng kiến thức chung (tránh lặp tool): Chỉ tra cứu tối đa 1-2 lần. Nếu tài liệu "
    "không có thông tin phù hợp, hoặc câu hỏi là về lập trình, giải thích khái niệm, tư vấn ý "
    "tưởng chung ngoài tài liệu: PHẢI DỪNG việc gọi tool ngay, nêu rõ nếu tài liệu không đề cập "
    "và dùng kiến thức chung hữu ích để trả lời chu đáo cho người dùng (không gắn trích dẫn khi "
    "dùng kiến thức chung). Tuyệt đối không gọi tool lặp đi lặp lại với các từ khóa tương tự.\n"
    "4. Trả lời bằng tiếng Việt rõ ràng, mạch lạc, đi thẳng vào câu hỏi.\n"
)


@dataclass
class AgentResult:
    """Kết quả một lần hỏi, chưa qua citation verification."""

    answer: str
    tool_returned: dict[str, dict[str, Any]] = field(default_factory=dict)  # chunk_id -> chunk
    search_trace: list[dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""  # nội dung "suy luận" của model (nếu provider trả về)
    low_confidence: bool = False


def _parse_tool_payload(content: Any) -> Any:
    """Parse nội dung ToolMessage (chuỗi JSON) — trả None nếu không parse được."""
    try:
        return json.loads(content) if isinstance(content, str) else None
    except json.JSONDecodeError:
        return None


def _iter_chunks(payload: Any) -> list[dict[str, Any]]:
    """Các chunk hợp lệ trong payload tool: list kết quả (search) hoặc dict đơn (read_chunk).

    Mọi dict có chunk_id đều tính là bằng chứng citation; tool không trả chunk
    (như list_documents) tự động bị bỏ qua.
    """
    if isinstance(payload, list):
        return [c for c in payload if isinstance(c, dict) and c.get("chunk_id")]
    if isinstance(payload, dict) and payload.get("chunk_id"):
        return [payload]
    return []


def _tool_trace_entry(name: str, args: dict[str, Any], payload: Any) -> dict[str, Any] | None:
    """Entry trace cho một lượt tool hoàn tất — mỗi tool một shape, đánh dấu bằng `name`.

    Trả None với tool chưa có renderer; caller fallback về shape search.
    """
    if name == "read_chunk":
        chunk = payload if isinstance(payload, dict) and payload.get("chunk_id") else None
        return {
            "name": "read_chunk",
            "chunk_id": str(args.get("chunk_id", "")),
            "doc": str(chunk.get("doc", "")) if chunk else "",
            "section": str(chunk.get("section", "")) if chunk else "",
            "found": chunk is not None,
        }
    if name == "list_documents":
        docs = payload if isinstance(payload, list) else []
        return {
            "name": "list_documents",
            "n_docs": len(docs),
            "docs": [str(d.get("doc", "")) for d in docs if isinstance(d, dict)],
        }
    if name in ("", "search_docs"):
        chunks = _iter_chunks(payload)
        return {
            "name": "search_docs",
            "query": str(args.get("query", "")),
            "n_results": len(chunks),
            "chunk_ids": [c.get("chunk_id") for c in chunks],
            "max_score": max((c.get("score", 0.0) for c in chunks), default=0.0),
        }
    return None


def _build_tool_trace(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Dựng trace tool từ messages: mỗi ToolMessage một entry theo loại tool.

    Trace chứa TẤT CẢ tool (search/read/list) để UI hiển thị đủ; riêng điểm tin
    cậy (low_confidence) chỉ tính trên các entry search_docs. Khớp tool_call ↔
    ToolMessage bằng tool_call_id, thiếu id thì khớp theo thứ tự (fallback).
    """
    trace: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []  # tool_call đã phát, chờ ToolMessage tương ứng
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                pending.append(
                    {
                        "id": call.get("id"),
                        "name": call.get("name") or "",
                        "args": call.get("args") or {},
                    }
                )
        elif isinstance(msg, ToolMessage):
            call = next((c for c in pending if c["id"] and c["id"] == msg.tool_call_id), None)
            if call is not None:
                pending.remove(call)
            elif pending:
                call = pending.pop(0)
            else:
                call = {"name": "", "args": {}}
            entry = _tool_trace_entry(call["name"], call["args"], _parse_tool_payload(msg.content))
            if entry is not None:
                trace.append(entry)
    return trace


def _collect_tool_chunks(messages: list[BaseMessage]) -> dict[str, dict[str, Any]]:
    """Tập bằng chứng hợp lệ: mọi chunk tool thực sự trả về trong phiên."""
    chunks: dict[str, dict[str, Any]] = {}
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        for chunk in _iter_chunks(_parse_tool_payload(msg.content)):
            chunks[chunk["chunk_id"]] = chunk
    return chunks


def _extract_reasoning(messages: list[BaseMessage]) -> str:
    """Gom nội dung suy luận (thinking) từ các AIMessage, nếu provider trả về.

    Một số provider OpenAI-compatible (DeepSeek, Qwen3...) trả reasoning_content;
    ThinkingChatOpenAI (agent/llm.py) giữ nó trong additional_kwargs và gửi lại
    ở lượt sau để tool-call nhiều lượt không bị provider từ chối.
    """
    parts: list[str] = []
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        reasoning = msg.additional_kwargs.get("reasoning_content")
        if reasoning:
            parts.append(str(reasoning))
    return "\n\n".join(parts)


class RagAgent:
    """Agent RAG chạy vòng lặp hữu hạn trên tool registry (search_docs, read_chunk, list_documents)."""  # noqa: E501

    def __init__(self, cfg: Config, retriever: Retriever, store: Any = None):
        self.cfg = cfg
        self.retriever = retriever
        self.store = store
        self._agent = None
        self._current_integration_fingerprint: tuple[str, str, str] | None = None

    def resolve_active_llm_config(self) -> tuple[str, str, str]:
        """Lấy (model, base_url, api_key) từ active integration trong DB (hoặc fallback Config)."""
        if self.store is not None:
            active = self.store.get_active_integration()
            if active:
                try:
                    decrypted_key = decrypt_integration_key(
                        active.get("encrypted_api_key", ""),
                        active.get("encrypted_dek", ""),
                        self.cfg.encryption_key,
                    )
                except Exception as exc:
                    logger.warning("Không thể giải mã API key của active integration: %s", exc)
                    decrypted_key = ""
                model = str(active.get("model") or self.cfg.llm_model).strip()
                base_url = str(active.get("base_url") or self.cfg.llm_base_url).strip()
                return model, base_url, decrypted_key
        return self.cfg.llm_model, self.cfg.llm_base_url, self.cfg.llm_api_key

    def _make_llm(self) -> ThinkingChatOpenAI:
        model, base_url, api_key = self.resolve_active_llm_config()
        return ThinkingChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key or "not-needed",
            temperature=0,
            timeout=self.cfg.llm_timeout,
            # 502/5xx/connect fail (tokenrouter gateway) — SDK backoff + retry.
            max_retries=self.cfg.llm_max_retries,
            # Chặn vòng lặp thoái hóa: model free từng sinh rác "1 1 1 2 2 2..."
            # suốt 6 phút. 4096 đủ cho reasoning + câu trả lời ngắn, nhưng chặn loop.
            max_tokens=4096,
        )

    def invalidate_agent(self) -> None:
        """Xóa cache agent để khởi tạo lại với cấu hình LLM mới."""
        self._agent = None
        self._current_integration_fingerprint = None

    # ---------- agent mode ----------

    def _get_agent(self):
        model, base_url, api_key = self.resolve_active_llm_config()
        fingerprint = (model, base_url, api_key)
        if self._agent is None or self._current_integration_fingerprint != fingerprint:
            deps = ToolDeps(retriever=self.retriever, store=self.store)
            tools = build_tools(deps)
            llm = self._make_llm()
            self._agent = create_react_agent(llm, tools, prompt=SYSTEM_PROMPT)
            self._current_integration_fingerprint = fingerprint
        return self._agent

    def _history_messages(
        self, history: list[dict[str, str]] | None
    ) -> list[tuple[str, str]]:
        """Chuyển history [{role, content}] → list message LangChain (user/assistant)."""
        out: list[tuple[str, str]] = []
        if not history:
            return out
        for item in history:
            role = (item.get("role") or "").strip()
            content = (item.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                out.append(("user", content))
            elif role == "assistant":
                out.append(("assistant", content))
        return out

    def ask_agent(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        config: dict | None = None,
    ) -> AgentResult:
        agent = self._get_agent()
        recursion_limit = 2 * self.cfg.max_agent_turns + 1
        messages_in = [*self._history_messages(history), ("user", question)]
        run_config = {"recursion_limit": recursion_limit}
        if config:
            run_config.update(config)
        try:
            result = agent.invoke(
                {"messages": messages_in},
                config=run_config,
            )
            messages: list[BaseMessage] = result["messages"]
            answer = str(messages[-1].content) if messages else ""
        except Exception as exc:  # noqa: BLE001 — mọi lỗi đều phải degrade an toàn, không crash
            logger.exception("agent loop failed — fallback to direct retrieve")
            # Quá lượt hoặc lỗi runtime: không có messages hoàn chỉnh.
            # Trả về câu trả lời an toàn dựa trên 1 lượt retrieve trực tiếp.
            fallback = self.retriever.search(question)
            return AgentResult(
                answer=(
                    "Xin lỗi, tôi chưa hoàn tất được việc tra cứu cho câu hỏi này "
                    f"(lỗi: {exc})."
                ),
                tool_returned={c["chunk_id"]: c for c in fallback.chunks},
                search_trace=[{
                    "name": "search_docs",
                    "query": question,
                    "n_results": len(fallback.chunks),
                    "chunk_ids": [c["chunk_id"] for c in fallback.chunks],
                    "max_score": fallback.max_score,
                }],
                low_confidence=True,
            )

        tool_returned = _collect_tool_chunks(messages)
        trace = _build_tool_trace(messages)
        # Điểm tin cậy chỉ đánh giá các lượt search; read/list không có score
        # cosine nên không được kéo max_score về 0 (tránh flag oan).
        search_scores = [t["max_score"] for t in trace if t["name"] == "search_docs"]
        max_score = max(search_scores, default=0.0)
        return AgentResult(
            answer=answer.strip(),
            tool_returned=tool_returned,
            search_trace=trace,
            reasoning=_extract_reasoning(messages),
            # Chỉ cảnh báo khi THỰC SỰ đã tra cứu mà điểm thấp. Câu chào hỏi
            # không gọi tool thì không có gì để đánh giá → không flag.
            low_confidence=bool(search_scores) and max_score < self.cfg.min_score,
        )

    # ---------- streaming (ChatGPT/Claude-style) ----------

    def stream_agent(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        config: dict | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream từng bước của agent loop thay vì chờ kết quả cuối.

        Events yield ra (cho SSE):
        - {"type":"thinking","delta":str}      reasoning gõ dần
        - {"type":"tool_start",...}            LLM vừa phát tool_call (tool đang chạy)
        - {"type":"tool_call",...}             một lượt tool hoàn tất
                                               (kèm `name` + payload theo loại tool)
        - {"type":"answer","delta":str}        câu trả lời gõ dần
        - {"type":"answer_clear"}              xóa phần answer đã stream (do đó chỉ là
                                               lời dẫn trung gian trước một tool_call)
        - {"type":"_final","result":AgentResult}  event nội bộ cuối để service verify
        - {"type":"error","message":str}       lỗi runtime
        """
        agent = self._get_agent()
        recursion_limit = 2 * self.cfg.max_agent_turns + 1
        messages_in = [*self._history_messages(history), ("user", question)]

        # Gom args tool_call được stream thành mảnh JSON, khớp theo index.
        tool_name_by_idx: dict[int, str] = {}
        tool_args_by_idx: dict[int, str] = {}
        tool_id_by_idx: dict[int, str] = {}
        tool_started: set[int] = set()
        tool_returned: dict[str, dict[str, Any]] = {}
        trace: list[dict[str, Any]] = []
        reasoning_parts: list[str] = []
        # Content của lượt AI hiện tại, chưa "chốt". Chỉ khi lượt đó KHÔNG kèm
        # tool_call (tức lượt trả lời cuối) thì mới là câu trả lời thật.
        pending_content: list[str] = []
        # Lượt AI hiện tại có phải lượt gọi tool không.
        turn_is_tool = False

        try:
            run_config = {"recursion_limit": recursion_limit}
            if config:
                run_config.update(config)
            for chunk, _meta in agent.stream(
                {"messages": messages_in},
                config=run_config,
                stream_mode="messages",
            ):
                if isinstance(chunk, AIMessageChunk):
                    reasoning = chunk.additional_kwargs.get("reasoning_content")
                    if reasoning:
                        reasoning_parts.append(str(reasoning))
                        yield {"type": "thinking", "delta": str(reasoning)}
                    for tc in chunk.tool_call_chunks or []:
                        idx = tc.get("index", 0)
                        if tc.get("name"):
                            tool_name_by_idx[idx] = tc["name"]
                            if idx not in tool_started:
                                tool_started.add(idx)
                                # Lượt này sẽ gọi tool → mọi content trước đó trong
                                # cùng lượt chỉ là lời dẫn trung gian, không phải câu
                                # trả lời. Bỏ nó đi và báo UI xóa phần đã gõ.
                                turn_is_tool = True
                                if pending_content:
                                    pending_content = []
                                    yield {"type": "answer_clear"}
                                yield {"type": "tool_start", "name": tc["name"]}
                        if tc.get("id"):
                            tool_id_by_idx[idx] = tc["id"]
                        if tc.get("args"):
                            tool_args_by_idx[idx] = tool_args_by_idx.get(idx, "") + str(tc["args"])
                    if isinstance(chunk.content, str) and chunk.content:
                        # Lượt đang gọi tool thì content chỉ là lời dẫn → không gom.
                        # Bỏ qua whitespace đầu câu trả lời (model hay mở đầu bằng \n\n).
                        if not turn_is_tool and (pending_content or chunk.content.strip()):
                            pending_content.append(chunk.content)
                            yield {"type": "answer", "delta": chunk.content}

                elif isinstance(chunk, ToolMessage):
                    # Một lượt tool vừa hoàn tất → dựng entry theo loại tool, phát ngay.
                    idx = next(
                        (i for i, tid in tool_id_by_idx.items() if tid == chunk.tool_call_id),
                        0,
                    )
                    name = tool_name_by_idx.get(idx, "")
                    raw_args = tool_args_by_idx.get(idx, "")
                    args: dict[str, Any] = {}
                    if raw_args:
                        try:
                            parsed = json.loads(raw_args)
                            if isinstance(parsed, dict):
                                args = parsed
                        except json.JSONDecodeError:
                            args = {}
                    payload = _parse_tool_payload(chunk.content)
                    for c in _iter_chunks(payload):
                        tool_returned[c["chunk_id"]] = c
                    entry = _tool_trace_entry(name, args, payload)
                    if entry is None:
                        # Tool chưa có renderer riêng → fallback shape search để không vỡ UI.
                        entry = _tool_trace_entry("search_docs", args, payload)
                    trace.append(entry)
                    event: dict[str, Any] = {"type": "tool_call", "index": len(trace), **entry}
                    if entry["name"] == "search_docs":
                        event["chunks"] = _iter_chunks(payload)
                    yield event

                    # Lượt AI kế tiếp là lượt mới: index tool_call reset về 0, nên
                    # phải xóa trạng thái per-lượt kẻo args/id của lượt trước nối
                    # lẫn vào lượt sau (gây query rỗng, bỏ sót answer_clear).
                    tool_name_by_idx.clear()
                    tool_args_by_idx.clear()
                    tool_id_by_idx.clear()
                    tool_started.clear()
                    turn_is_tool = False
                    pending_content = []
        except Exception as exc:  # noqa: BLE001 — stream lỗi phải báo UI, không crash server
            logger.exception("agent stream failed")
            yield {"type": "error", "message": str(exc)}
            return

        search_scores = [t["max_score"] for t in trace if t["name"] == "search_docs"]
        max_score = max(search_scores, default=0.0)
        result = AgentResult(
            answer="".join(pending_content).strip(),
            tool_returned=tool_returned,
            search_trace=trace,
            reasoning="".join(reasoning_parts),
            # Giống ask_agent: không lượt search nào thì không có cơ sở để cảnh báo.
            low_confidence=bool(search_scores) and max_score < self.cfg.min_score,
        )
        try:
            rt = get_current_run_tree()  # root run active while agent.stream runs
            if rt is not None:
                rt.add_outputs({"answer": result.answer})
        except Exception:  # noqa: BLE001 — enrichment không được phá streaming
            logger.debug("trace enrichment skipped", exc_info=True)
        yield {"type": "_final", "result": result}

