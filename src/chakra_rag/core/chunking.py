"""Chia nhỏ tài liệu theo cấu trúc: heading trước, đoạn sau.

Dùng langchain_text_splitters:
- MarkdownHeaderTextSplitter tách theo heading (## / ###) để giữ ngữ cảnh section.
- RecursiveCharacterTextSplitter cắt nhỏ tiếp nếu section quá dài.

Mỗi chunk mang metadata đầy đủ (doc, section, char offset) — nền tảng của
trích dẫn chính xác: từ chunk_id luôn tra ngược về đúng đoạn trong tài liệu gốc.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

_HEADING_LEVELS = [("#", "h1"), ("##", "h2"), ("###", "h3")]


@dataclass(frozen=True)
class Chunk:
    """Một đoạn tài liệu đã cắt, kèm metadata để trích dẫn.

    chunk_id (dạng `<doc>#<section>#<idx>`) do tầng ingest gán vì cần thứ tự
    toàn cục trong file — xem `ingestion/worker.py`.
    """

    text: str
    doc: str          # tên file tài liệu
    section: str      # heading gần nhất (hoặc "(mở đầu)")
    char_start: int   # vị trí bắt đầu trong file gốc
    char_end: int


def chunk_markdown(text: str, doc: str, chunk_size: int = 300, chunk_overlap: int = 50) -> list[Chunk]:
    """Cắt một tài liệu markdown thành các Chunk có metadata."""
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=_HEADING_LEVELS,
        strip_headers=False,
    )
    section_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks: list[Chunk] = []
    for section_doc in header_splitter.split_text(text):
        section = " > ".join(section_doc.metadata.values()) or "(mở đầu)"
        content = getattr(section_doc, "page_content", None) or getattr(section_doc, "content", "")
        for piece in section_splitter.split_text(content):
            piece = piece.strip()
            if not piece:
                continue
            start = text.find(piece)
            chunks.append(
                Chunk(
                    text=piece,
                    doc=doc,
                    section=section,
                    char_start=start if start >= 0 else 0,
                    char_end=(start + len(piece)) if start >= 0 else len(piece),
                )
            )
    return chunks


def chunk_plain_text(text: str, doc: str, chunk_size: int = 300, chunk_overlap: int = 50) -> list[Chunk]:
    """Cắt tài liệu không có cấu trúc markdown (txt)."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks: list[Chunk] = []
    for piece in splitter.split_text(text):
        piece = piece.strip()
        if not piece:
            continue
        start = text.find(piece)
        chunks.append(
            Chunk(
                text=piece,
                doc=doc,
                section="(toàn văn)",
                char_start=start if start >= 0 else 0,
                char_end=(start + len(piece)) if start >= 0 else len(piece),
            )
        )
    return chunks
