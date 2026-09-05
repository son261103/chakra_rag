"""Registry cho agent tools: mỗi tool là một factory nhận `ToolDeps`, trả về `BaseTool`.

Tool cần dependency injection (retriever, store...) nên khai báo dạng factory
bọc closure thay vì hàm module-level. Thêm tool mới:
1. Tạo file trong agent/tools/, đánh dấu factory bằng @register_tool("ten_tool").
2. Import module đó trong agent/tools/__init__.py (side-effect đăng ký).
Agent gọi build_tools() nên tự nhận tool mới, không cần sửa agent.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool

from core.retrieval import Retriever


@dataclass
class ToolDeps:
    """Dependency chung truyền vào các tool factory."""

    retriever: Retriever
    store: Any = None  # storage.Store — dùng Any để khỏi kéo thêm import kiểu


# Tên tool -> factory(deps) -> BaseTool
TOOL_FACTORIES: dict[str, Callable[[ToolDeps], BaseTool]] = {}


def register_tool(name: str):
    """Đăng ký factory tạo tool theo tên; trùng tên là lỗi cấu hình."""

    def deco(factory: Callable[[ToolDeps], BaseTool]) -> Callable[[ToolDeps], BaseTool]:
        if name in TOOL_FACTORIES:
            raise ValueError(f"Tool '{name}' đã được đăng ký trong TOOL_FACTORIES")
        TOOL_FACTORIES[name] = factory
        return factory

    return deco
