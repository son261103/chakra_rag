"""Tool `read_chunk`: đọc đầy đủ một đoạn tài liệu theo chunk_id.

Khác với search_docs (pointer-first, chỉ trả excerpt), read_chunk là bước
"kéo nội dung vào context đúng lúc cần":
- Trả text đầy đủ của chunk được hỏi.
- Kèm `before`/`after`: các chunk liền kề trong cùng tài liệu (chunk 300 ký
  tự dễ cắt lỡ câu — ngữ cảnh kề giúp hiểu trọn ý, và cho agent cites gần đúng
  đoạn lân cận nếu cần).
Bằng chứng citation hợp lệ vẫn là bất kỳ chunk_id nào tool trả về.
"""

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
        """Đọc nội dung đầy đủ của một đoạn tài liệu theo chunk_id (id lấy từ kết quả search_docs), kèm các đoạn liền kề trước/sau trong cùng tài liệu để có ngữ cảnh."""  # noqa: E501
        if store is None:
            return json.dumps({"error": "Chưa có kho lưu trữ tài liệu."}, ensure_ascii=False)
        hood = store.get_chunk_neighborhood(chunk_id)
        if not hood:
            return json.dumps(
                {
                    "error": (
                        f"Không tìm thấy chunk '{chunk_id}'. "
                        "Hãy gọi search_docs để lấy chunk_id hợp lệ."
                    )
                },
                ensure_ascii=False,
            )
        chunk = hood["chunk"]
        payload = {
            "chunk_id": chunk["chunk_id"],
            "doc": chunk["doc"],
            "section": chunk["section"],
            "text": chunk["text"],
            "before": [
                {"chunk_id": n["chunk_id"], "text": n["text"]} for n in reversed(hood["before"])
            ],
            "after": [{"chunk_id": n["chunk_id"], "text": n["text"]} for n in hood["after"]],
        }
        return json.dumps(payload, ensure_ascii=False)

    return read_chunk