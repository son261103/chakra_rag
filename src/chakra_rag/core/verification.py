"""Citation verification — bước hậu kiểm độc lập với LLM.

Hai lớp kiểm tra:
1. Existence: mọi [chunk_id] được cite phải nằm trong tập chunk mà tool
   THỰC SỰ trả về trong phiên (chống bịa nguồn).
2. Support: mỗi claim (câu) được cite phải có độ phủ token với chunk được cite
   vượt ngưỡng — dưới ngưỡng thì vào `unsupported_claims` (bị flag, không xóa).

Support check bằng n-gram overlap là proxy rẻ tiền, không phải NLI —
ghi rõ giới hạn này; hướng nâng cấp: NLI model hoặc LLM-judge từng claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# \w trong Python 3 là unicode-aware — match cả chunk_id chứa tiếng Việt có dấu
_CITATION_RE = re.compile(r"\[([\w#.\-]+)\]")
_STOPWORDS_VI = {
    "và", "của", "là", "có", "trong", "cho", "không", "được", "với", "này",
    "một", "các", "khi", "đã", "để", "từ", "đến", "theo", "như", "hoặc",
    "phải", "sẽ", "tại", "về", "những", "đó", "trên", "dưới",
}
SUPPORT_THRESHOLD = 0.30


@dataclass
class VerifiedAnswer:
    """Câu trả lời sau hậu kiểm trích dẫn."""

    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)   # cite không tồn tại trong bằng chứng  # noqa: E501
    unsupported_claims: list[str] = field(default_factory=list)  # claim không được chunk đỡ
    low_confidence: bool = False

    @property
    def ok(self) -> bool:
        return not self.invalid_citations and not self.unsupported_claims


def extract_citations(text: str) -> list[str]:
    """Kéo toàn bộ [chunk_id] khỏi câu trả lời, giữ thứ tự, bỏ trùng."""
    seen: list[str] = []
    for match in _CITATION_RE.findall(text):
        if match not in seen:
            seen.append(match)
    return seen


def _tokens(text: str) -> set[str]:
    text = text.lower()
    words = re.findall(r"[a-z0-9à-ỹ]+", text, flags=re.UNICODE)
    return {w for w in words if w not in _STOPWORDS_VI and len(w) > 1}


def support_score(claim: str, chunk_text: str) -> float:
    """Độ phủ token của claim trong chunk: |claim ∩ chunk| / |claim|."""
    claim_tokens = _tokens(claim)
    if not claim_tokens:
        return 1.0  # claim không có token nội dung (ví dụ câu dẫn) → không bắt lỗi
    chunk_tokens = _tokens(chunk_text)
    return len(claim_tokens & chunk_tokens) / len(claim_tokens)


def _split_claims(answer: str) -> list[str]:
    """Tách câu trả lời thành các claim theo câu."""
    sentences = re.split(r"(?<=[.!?])\s+", answer.strip())
    return [s.strip() for s in sentences if s.strip()]


def verify_answer(
    answer: str,
    tool_returned: dict[str, dict[str, Any]],
    low_confidence: bool = False,
    support_threshold: float = SUPPORT_THRESHOLD,
) -> VerifiedAnswer:
    """Hậu kiểm trích dẫn cho một câu trả lời."""
    cited_ids = extract_citations(answer)

    # Lớp 1: existence — cite phải nằm trong bằng chứng tool trả về
    valid_ids = [cid for cid in cited_ids if cid in tool_returned]
    invalid_ids = [cid for cid in cited_ids if cid not in tool_returned]

    # Lớp 2: support — mỗi câu có cite phải được chunk đỡ
    unsupported: list[str] = []
    for claim in _split_claims(answer):
        claim_citations = [cid for cid in extract_citations(claim) if cid in tool_returned]
        if not claim_citations:
            continue  # câu không cite: không bắt lỗi support (có thể là câu dẫn/kết)
        best = max(
            support_score(claim, tool_returned[cid]["text"]) for cid in claim_citations
        )
        if best < support_threshold:
            unsupported.append(claim)

    citations = []
    for cid in valid_ids:
        chunk = tool_returned[cid]
        citations.append(
            {
                "chunk_id": cid,
                "doc": chunk.get("doc"),
                "section": chunk.get("section"),
                "text": chunk.get("text"),
                "score": chunk.get("score"),
            }
        )

    return VerifiedAnswer(
        answer=answer,
        citations=citations,
        invalid_citations=invalid_ids,
        unsupported_claims=unsupported,
        low_confidence=low_confidence,
    )
