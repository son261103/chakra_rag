"""Gói tools của agent: registry + build_tools.

Thêm tool mới: tạo file trong thư mục này, dùng @register_tool("ten_tool")
và import module ở dưới — agent tự nhận qua build_tools().
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from agent.tools import (
    list_documents,  # noqa: F401  (side-effect: đăng ký tool)
    read_chunk,  # noqa: F401  (side-effect: đăng ký tool)
    search_docs,  # noqa: F401  (side-effect: đăng ký tool)
)
from agent.tools.registry import TOOL_FACTORIES, ToolDeps

__all__ = ["ToolDeps", "build_tools"]


def build_tools(deps: ToolDeps) -> list[BaseTool]:
    """Khởi tạo toàn bộ tool đã đăng ký — danh sách truyền vào create_react_agent."""
    return [factory(deps) for factory in TOOL_FACTORIES.values()]
