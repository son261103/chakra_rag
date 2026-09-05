"""Tool `search_docs`: cửa sổ duy nhất để LLM tra cứu tài liệu nội bộ."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool, tool
from langsmith import traceable

from agent.tools.registry import ToolDeps, register_tool
from core.retrieval import RetrievalResult


def _to_tool_payload(result: RetrievalResult) -> list[dict[str, Any]]:
    """Dạng gọn trả về cho LLM trong tool message — wire format do tool layer quyết định."""
    return [
        {
            "chunk_id": c["chunk_id"],
            "doc": c["doc"],
            "section": c["section"],
            "score": round(c["score"], 3),
            "text": c["text"],
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
        """Tìm kiếm tài liệu nội bộ. Trả về JSON danh sách các đoạn liên quan kèm chunk_id, nguồn và điểm."""  # noqa: E501
        result: RetrievalResult = retriever.search(query, top_k)
        return json.dumps(_to_tool_payload(result), ensure_ascii=False)

    return search_docs
