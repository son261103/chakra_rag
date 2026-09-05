"""Tool `search_docs`: cửa sổ duy nhất để LLM tra cứu tài liệu nội bộ.

Pointer-first (pattern chuẩn của product agent thật — Claude Code, Perplexity,
Deep Research): search chỉ trả chunk_id + excerpt ngắn vừa đủ để LLM đánh giá
liên quan và quyết định đọc đoạn nào. Nội dung đầy đủ của đoạn nằm ở read_chunk.
Lợi ích: context window không bị ngốn bởi các chunk rác (context rot), mỗi lượt
search rẻ hơn, và vòng agent có ý nghĩa nhiều bước thật sự.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool, tool
from langsmith import traceable

from agent.tools.registry import ToolDeps, register_tool
from core.retrieval import RetrievalResult

# Chiều dài excerpt trả cho LLM — đủ đánh giá liên quan + khớp truy vấn,
# chưa đủ để trích dẫn chi tiết (đó là việc của read_chunk).
EXCERPT_CHARS = 150


def _excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """Rút gọn chunk thành excerpt 1 dòng; đánh dấu … khi bị cắt."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "…"


def _to_tool_payload(result: RetrievalResult) -> list[dict[str, Any]]:
    """Dạng gọn trả về cho LLM trong tool message — wire format do tool layer quyết định.

    `excerpt` là bản xem trước rút gọn; text đầy đủ phải lấy qua read_chunk
    — LLM KHÔNG cite dựa trên excerpt được.
    """
    return [
        {
            "chunk_id": c["chunk_id"],
            "doc": c["doc"],
            "section": c["section"],
            "score": round(c["score"], 3),
            "excerpt": _excerpt(c["text"]),
        }
        for c in result.chunks
    ]


@register_tool("search_docs")
def make_search_docs(deps: ToolDeps) -> BaseTool:
    """Factory tool search_docs: closure giữ retriever của container hiện tại."""
    retriever = deps.retriever

    @tool
    @traceable(run_type="retriever", name="search_docs_tool")
    def search_docs(query: str, top_k: int = 5) -> str:
        """Tìm kiếm tài liệu nội bộ. Trả về JSON danh sách các đoạn liên quan: mỗi đoạn gồm chunk_id, nguồn, điểm và excerpt xem trước (bản rút gọn ~150 ký tự). Muốn nội dung đầy đủ của đoạn nào thì gọi read_chunk với chunk_id đó."""  # noqa: E501
        result: RetrievalResult = retriever.search(query, top_k)
        return json.dumps(_to_tool_payload(result), ensure_ascii=False)

    return search_docs
