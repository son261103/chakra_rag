"""Khởi chạy API backend server: python -m chakra_rag"""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("chakra_rag.interfaces.api:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
