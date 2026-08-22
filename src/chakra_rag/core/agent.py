"""Agent RAG dùng LangGraph: LLM tự gọi tool `search_docs` để lấy dữ liệu.

Hai mode:
- `agent` (mặc định): create_react_agent — LLM quyết định khi nào tìm, tìm gì,
  có thể tìm nhiều lượt rồi mới trả lời.
- `stuff`: fallback cổ điển — retrieve một lần, nhét context vào prompt.
  Dùng khi model không hỗ trợ function calling.

Guardrails:
- recursion_limit = 2*max_turns + 1 (mỗi lượt tool = 2 bước graph) chống loop.
- Bằng chứng hợp lệ = tập chunk_id xuất hiện trong ToolMessage của phiên;
  citation verifier ở core/verification.py chỉ chấp nhận tập này.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from chakra_rag.config import Config
from chakra_rag.core.llm import ThinkingChatOpenAI
from chakra_rag.core.retrieval import RetrievalResult, Retriever

SYSTEM_PROMPT = """\
Bạn là trợ lý trả lời câu hỏi dựa trên tài liệu nội bộ được cung cấp qua công cụ search_docs.

Quy tắc bắt buộc:
1. Mỗi câu hỏi của người dùng (kể cả câu hỏi tiếp theo trong hội thoại) đều PHẢI gọi search_docs trước khi trả lời. Không trả lời chỉ dựa vào kiến thức có sẵn hay chỉ dựa vào nội dung chat trước đó.
2. Hội thoại trước chỉ dùng để hiểu ngữ cảnh (người đang hỏi tiếp về ai/cái gì) — mọi sự kiện, con số, kỹ năng, kinh nghiệm vẫn phải lấy từ kết quả search_docs của lượt này.
3. Mỗi khẳng định trong câu trả lời phải kèm trích dẫn [chunk_id] của đoạn tài liệu đỡ cho nó (chunk_id từ tool lượt hiện tại).
4. Chỉ dùng thông tin trong kết quả search_docs. Nếu kết quả không đủ, nói rõ là tài liệu không có thông tin này — không suy diễn, không bịa.
5. Trả lời bằng tiếng Việt, ngắn gọn, đi thẳng vào câu hỏi.
6. Nếu cần, gọi search_docs nhiều lần với truy vấn khác nhau để đủ thông tin.
"""

STUFF_PROMPT_TEMPLATE = """\
Bạn là trợ lý trả lời câu hỏi dựa trên tài liệu nội bộ. Dưới đây là các đoạn tài liệu truy xuất được:

{context}

Quy tắc bắt buộc:
1. Chỉ trả lời dựa trên các đoạn tài liệu trên.
2. Mỗi khẳng định phải kèm trích dẫn [chunk_id] của đoạn đỡ cho nó.
3. Nếu tài liệu không đủ thông tin, nói rõ là không có thông tin — không suy diễn, không bịa.
4. Trả lời bằng tiếng Việt, ngắn gọn, đi thẳng vào câu hỏi.

Câu hỏi: {question}
"""


@dataclass
class AgentResult:
    """Kết quả một lần hỏi, chưa qua citation verification."""

    answer: str
    tool_returned: dict[str, dict[str, Any]] = field(default_factory=dict)  # chunk_id -> chunk
    search_trace: list[dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""  # nội dung "suy luận" của model (nếu provider trả về)
    low_confidence: bool = False
    mode: str = "agent"
    n_tool_calls: int = 0


def _build_search_trace(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Đọc lại messages để dựng trace: lượt nào tìm gì, được bao nhiêu kết quả."""
    trace: list[dict[str, Any]] = []
    pending_queries: list[str] = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                if call.get("name") == "search_docs":
                    pending_queries.append(str(call.get("args", {}).get("query", "")))
        elif isinstance(msg, ToolMessage):
            query = pending_queries.pop(0) if pending_queries else ""
            try:
                chunks = json.loads(msg.content) if isinstance(msg.content, str) else []
            except json.JSONDecodeError:
                chunks = []
            trace.append(
                {
                    "query": query,
                    "n_results": len(chunks),
                    "chunk_ids": [c.get("chunk_id") for c in chunks],
                    "max_score": max((c.get("score", 0.0) for c in chunks), default=0.0),
                }
            )
    return trace


def _collect_tool_chunks(messages: list[BaseMessage]) -> dict[str, dict[str, Any]]:
    """Tập bằng chứng hợp lệ: mọi chunk tool thực sự trả về trong phiên."""
    chunks: dict[str, dict[str, Any]] = {}
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        try:
            payload = json.loads(msg.content) if isinstance(msg.content, str) else []
        except json.JSONDecodeError:
            continue
        for chunk in payload:
            if isinstance(chunk, dict) and chunk.get("chunk_id"):
                chunks[chunk["chunk_id"]] = chunk
    return chunks


def _extract_reasoning(messages: list[BaseMessage]) -> str:
    """Gom nội dung suy luận (thinking) từ các AIMessage, nếu provider trả về.

    Một số provider OpenAI-compatible (DeepSeek, Qwen3...) trả reasoning_content;
    ThinkingChatOpenAI (core/llm.py) giữ nó trong additional_kwargs và gửi lại
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
    """Agent RAG với 1 tool search_docs, vòng lặp hữu hạn."""

    def __init__(self, cfg: Config, retriever: Retriever):
        self.cfg = cfg
        self.retriever = retriever
        self._agent = None

    def _make_llm(self) -> ThinkingChatOpenAI:
        return ThinkingChatOpenAI(
            model=self.cfg.llm_model,
            base_url=self.cfg.llm_base_url,
            api_key=self.cfg.llm_api_key or "not-needed",
            temperature=0,
            timeout=self.cfg.llm_timeout,
            # 502/5xx/connect fail (tokenrouter gateway) — SDK backoff + retry.
            max_retries=self.cfg.llm_max_retries,
            # Chặn vòng lặp thoái hóa: model free từng sinh rác "1 1 1 2 2 2..."
            # suốt 6 phút. 4096 đủ cho reasoning + câu trả lời ngắn, nhưng chặn loop.
            max_tokens=4096,
        )

    # ---------- agent mode ----------

    def _get_agent(self):
        if self._agent is None:
            retriever = self.retriever

            @tool
            def search_docs(query: str, top_k: int = 5) -> str:
                """Tìm kiếm tài liệu nội bộ. Trả về JSON danh sách các đoạn liên quan kèm chunk_id, nguồn và điểm."""
                result: RetrievalResult = retriever.search(query, top_k)
                return json.dumps(result.to_tool_payload(), ensure_ascii=False)

            llm = self._make_llm()
            self._agent = create_react_agent(llm, [search_docs], prompt=SYSTEM_PROMPT)
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
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> AgentResult:
        agent = self._get_agent()
        recursion_limit = 2 * self.cfg.max_agent_turns + 1
        messages_in = [*self._history_messages(history), ("user", question)]
        try:
            result = agent.invoke(
                {"messages": messages_in},
                config={"recursion_limit": recursion_limit},
            )
            messages: list[BaseMessage] = result["messages"]
            answer = str(messages[-1].content) if messages else ""
        except Exception as exc:  # noqa: BLE001 — GraphRecursionError, lỗi provider v.v.
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
                    "query": question,
                    "n_results": len(fallback.chunks),
                    "chunk_ids": [c["chunk_id"] for c in fallback.chunks],
                    "max_score": fallback.max_score,
                }],
                low_confidence=True,
                mode="agent",
                n_tool_calls=0,
            )

        tool_returned = _collect_tool_chunks(messages)
        trace = _build_search_trace(messages)
        max_score = max((t["max_score"] for t in trace), default=0.0)
        return AgentResult(
            answer=answer.strip(),
            tool_returned=tool_returned,
            search_trace=trace,
            reasoning=_extract_reasoning(messages),
            # Chỉ cảnh báo khi THỰC SỰ đã tra cứu mà điểm thấp. Câu chào hỏi
            # không gọi tool thì không có gì để đánh giá → không flag.
            low_confidence=bool(trace) and max_score < self.cfg.min_score,
            mode="agent",
            n_tool_calls=len(trace),
        )

    # ---------- streaming (ChatGPT/Claude-style) ----------

    def stream_agent(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> Iterator[dict[str, Any]]:
        """Stream từng bước của agent loop thay vì chờ kết quả cuối.

        Events yield ra (cho SSE):
        - {"type":"thinking","delta":str}      reasoning gõ dần
        - {"type":"tool_start",...}            LLM vừa phát tool_call (tool đang chạy)
        - {"type":"tool_call",...}             một lượt search_docs hoàn tất (kèm kết quả)
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
            for chunk, _meta in agent.stream(
                {"messages": messages_in},
                config={"recursion_limit": recursion_limit},
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
                    # Một lượt search_docs vừa hoàn tất → phát kết quả ngay.
                    try:
                        chunks = json.loads(chunk.content) if isinstance(chunk.content, str) else []
                    except json.JSONDecodeError:
                        chunks = []
                    idx = next(
                        (i for i, tid in tool_id_by_idx.items() if tid == chunk.tool_call_id),
                        0,
                    )
                    query = ""
                    raw_args = tool_args_by_idx.get(idx, "")
                    if raw_args:
                        try:
                            query = str(json.loads(raw_args).get("query", ""))
                        except json.JSONDecodeError:
                            pass
                    for c in chunks:
                        if isinstance(c, dict) and c.get("chunk_id"):
                            tool_returned[c["chunk_id"]] = c
                    entry = {
                        "query": query,
                        "n_results": len(chunks),
                        "chunk_ids": [c.get("chunk_id") for c in chunks if isinstance(c, dict)],
                        "max_score": max((c.get("score", 0.0) for c in chunks if isinstance(c, dict)), default=0.0),
                    }
                    trace.append(entry)
                    yield {"type": "tool_call", "index": len(trace), **entry, "chunks": chunks}

                    # Lượt AI kế tiếp là lượt mới: index tool_call reset về 0, nên
                    # phải xóa trạng thái per-lượt kẻo args/id của lượt trước nối
                    # lẫn vào lượt sau (gây query rỗng, bỏ sót answer_clear).
                    tool_name_by_idx.clear()
                    tool_args_by_idx.clear()
                    tool_id_by_idx.clear()
                    tool_started.clear()
                    turn_is_tool = False
                    pending_content = []
        except Exception as exc:  # noqa: BLE001 — GraphRecursionError, lỗi provider v.v.
            yield {"type": "error", "message": str(exc)}
            return

        max_score = max((t["max_score"] for t in trace), default=0.0)
        result = AgentResult(
            answer="".join(pending_content).strip(),
            tool_returned=tool_returned,
            search_trace=trace,
            reasoning="".join(reasoning_parts),
            # Giống ask_agent: không gọi tool thì không có cơ sở để cảnh báo.
            low_confidence=bool(trace) and max_score < self.cfg.min_score,
            mode="agent",
            n_tool_calls=len(trace),
        )
        yield {"type": "_final", "result": result}

    # ---------- stuff mode (fallback + ablation) ----------

    def ask_stuff(self, question: str) -> AgentResult:
        result = self.retriever.search(question)
        context = "\n\n".join(
            f"[{c['chunk_id']}] ({c['doc']} — {c['section']})\n{c['text']}"
            for c in result.chunks
        )
        llm = self._make_llm()
        prompt = STUFF_PROMPT_TEMPLATE.format(context=context or "(không có tài liệu nào)", question=question)
        response = llm.invoke(prompt)
        return AgentResult(
            answer=str(response.content).strip(),
            tool_returned={c["chunk_id"]: c for c in result.chunks},
            search_trace=[{
                "query": question,
                "n_results": len(result.chunks),
                "chunk_ids": [c["chunk_id"] for c in result.chunks],
                "max_score": result.max_score,
            }],
            low_confidence=result.low_confidence,
            mode="stuff",
            n_tool_calls=1,
        )

    def ask(
        self,
        question: str,
        mode: str = "agent",
        history: list[dict[str, str]] | None = None,
    ) -> AgentResult:
        if mode == "stuff":
            return self.ask_stuff(question)
        return self.ask_agent(question, history=history)
