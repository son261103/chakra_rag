"""Tool `read_chunk`: đọc đầy đủ nội dung một chunk theo chunk_id."""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, tool

from agent.tools.registry import ToolDeps, register_tool


@register_tool("read_chunk")
def make_read_chunk(deps: ToolDeps) -> BaseTool:
    """Factory tool read_chunk: closure giữ store của container hiện tại."""
    store = deps.store

    @tool
    def read_chunk(chunk_id: str) -> str:
        """Đọc nội dung đầy đủ của một đoạn tài liệu theo chunk_id (id lấy từ kết quả search_docs)."""  # noqa: E501
        if store is None:
            return json.dumps({"error": "Chưa có kho lưu trữ tài liệu."}, ensure_ascii=False)
        chunk = store.get_chunk(chunk_id)
        if not chunk:
            return json.dumps(
                {
                    "error": (
                        f"Không tìm thấy chunk '{chunk_id}'. "
                        "Hãy gọi search_docs để lấy chunk_id hợp lệ."
                    )
                },
                ensure_ascii=False,
            )
        payload = {
            "chunk_id": chunk["chunk_id"],
            "doc": chunk["doc"],
            "section": chunk["section"],
            "text": chunk["text"],
        }
        return json.dumps(payload, ensure_ascii=False)

    return read_chunk
