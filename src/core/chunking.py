"""Chia nhỏ tài liệu theo cấu trúc: heading trước, đoạn sau.

Dùng langchain_text_splitters:
- MarkdownHeaderTextSplitter tách theo heading (## / ###) để giữ ngữ cảnh section.
- RecursiveCharacterTextSplitter cắt nhỏ tiếp nếu section quá dài.

Mỗi chunk mang metadata đầy đủ (doc, section, char offset) — nền tảng của
trích dẫn chính xác: từ chunk_id luôn tra ngược về đúng đoạn trong tài liệu gốc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

_HEADING_LEVELS = [("#", "h1"), ("##", "h2"), ("###", "h3")]

# Dòng tiêu đề kiểu CV/resume: OBJECTIVE, EDUCATION, SKILLS & INTERESTS, …
_ALL_CAPS_HEADING = re.compile(
    r"^[A-Z][A-Z0-9][A-Z0-9 &/,'+.–-]{0,58}[A-Z0-9)]$|"
    r"^[A-Z][A-Z0-9 &/,'+.–-]{2,58}$"
)
_PAGE_MARK = re.compile(r"^\[Trang\s+\d+\]$", re.I)


@dataclass(frozen=True)
class Chunk:
    """Một đoạn tài liệu đã cắt, kèm metadata để trích dẫn.

    chunk_id (dạng `<doc>#<section>#<idx>`) do tầng ingest gán vì cần thứ tự
    toàn cục trong file — xem `ingestion/worker.py`.
    """

    text: str
    doc: str  # tên file tài liệu
    section: str  # heading gần nhất (hoặc "(mở đầu)")
    char_start: int  # vị trí bắt đầu trong file gốc
    char_end: int


def chunk_markdown(
    text: str, doc: str, chunk_size: int = 300, chunk_overlap: int = 50
) -> list[Chunk]:
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


def structure_plain_document(text: str) -> str:
    """Gắn ## cho tiêu đề ALL-CAPS / [Trang N] để chunk_markdown giữ section.

    Dùng cho PDF/TXT kiểu CV, policy — không đụng nội dung, chỉ chèn marker.
    """
    out: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            out.append("")
            continue
        if _PAGE_MARK.match(line):
            out.append(f"## {line}")
            out.append("")
            continue
        letters = re.sub(r"[^A-Za-z]", "", line)
        if (
            2 <= len(line) <= 64
            and letters
            and letters.isupper()
            and len(line.split()) <= 8
            and not line.endswith(".")
            and _ALL_CAPS_HEADING.match(line)
        ):
            out.append(f"## {line}")
            out.append("")
            continue
        out.append(raw_line.rstrip())
    structured = "\n".join(out)
    structured = re.sub(r"([A-Za-z])\s*-\s*\n\s*([A-Za-z])", r"\1-\2", structured)
    structured = re.sub(r"[ \t]{2,}", " ", structured)
    return structured.strip() + "\n"


def chunk_plain_text(
    text: str, doc: str, chunk_size: int = 300, chunk_overlap: int = 50
) -> list[Chunk]:
    """Cắt tài liệu không markdown (txt/pdf đã extract).

    Nếu phát hiện tiêu đề cấu trúc → chuyển pseudo-markdown rồi cắt theo section
    (tránh cả file dính section '(toàn văn)' nhìn cụt trong UI).
    """
    structured = structure_plain_document(text)
    heading_hits = structured.count("\n## ") + (1 if structured.startswith("## ") else 0)
    if heading_hits >= 1:
        return chunk_markdown(structured, doc, chunk_size, chunk_overlap)

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
