"""Tool `list_documents`: liệt kê tài liệu đang có trong hệ thống."""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, tool

from agent.tools.registry import ToolDeps, register_tool


@register_tool("list_documents")
def make_list_documents(deps: ToolDeps) -> BaseTool:
    """Factory tool list_documents: closure giữ store của container hiện tại."""
    store = deps.store

    @tool
    def list_documents() -> str:
        """Liệt kê các tài liệu đang có trong hệ thống (tên, trạng thái, số đoạn). Dùng khi cần biết index đang có gì, hoặc khi search không ra kết quả để trả lời chính xác là tài liệu không có thông tin."""  # noqa: E501
        if store is None:
            return json.dumps([], ensure_ascii=False)
        files = store.list_files()
        payload = [
            {
                "doc": f["name"],
                "status": f["status"],
                "chunks_total": f["chunks_total"],
                "chunks_done": f["chunks_done"],
            }
            for f in files
        ]
        return json.dumps(payload, ensure_ascii=False)

    return list_documents
