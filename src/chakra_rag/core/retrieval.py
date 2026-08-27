"""Truy xuất hybrid: vector + lexical (FTS5), fusion bằng Reciprocal Rank Fusion.

Vì sao hybrid: vector bắt nghĩa tốt nhưng hay trượt từ khóa chính xác
(con số, tên riêng, mã hiệu — ví dụ "5.000.000 đồng"); FTS5 bù đúng chỗ đó.

Vì sao RRF: không cần chuẩn hóa score giữa 2 hệ thống (cosine vs BM25
khác thang đo), chỉ cần thứ hạng — 1 dòng công thức, ổn định, dễ giải thích.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langsmith import traceable

from chakra_rag.core.embedding import Embedder
from chakra_rag.storage.store import Store


@dataclass
class RetrievalResult:
    """Kết quả một lần truy xuất, kèm thông tin để đánh giá/debug."""

    chunks: list[dict[str, Any]] = field(default_factory=list)
    max_score: float = 0.0
    low_confidence: bool = False

    def to_tool_payload(self) -> list[dict[str, Any]]:
        """Dạng gọn trả về cho LLM trong tool message."""
        return [
            {
                "chunk_id": c["chunk_id"],
                "doc": c["doc"],
                "section": c["section"],
                "score": round(c["score"], 3),
                "text": c["text"],
            }
            for c in self.chunks
        ]


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, Any]]],
    k: int = 60,
) -> list[dict[str, Any]]:
    """Gộp nhiều danh sách xếp hạng theo RRF: score(d) = Σ 1/(k + rank_i(d))."""
    fused: dict[str, dict[str, Any]] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            entry = fused.setdefault(item["chunk_id"], {**item, "rrf": 0.0})
            entry["rrf"] += 1.0 / (k + rank)
    results = sorted(fused.values(), key=lambda x: x["rrf"], reverse=True)
    return results


class Retriever:
    """Hybrid retriever trên Store + Embedder."""

    def __init__(
        self,
        store: Store,
        embedder: Embedder,
        top_k: int = 5,
        rrf_k: int = 60,
        min_score: float = 0.25,
        use_fts: bool = True,
    ):
        self.store = store
        self.embedder = embedder
        self.top_k = top_k
        self.rrf_k = rrf_k
        self.min_score = min_score
        self.use_fts = use_fts

    @traceable(run_type="retriever", name="retrieve_docs")
    def search(self, query: str, top_k: int | None = None) -> RetrievalResult:
        top_k = top_k or self.top_k
        query_vec = self.embedder.embed_one(query)

        vector_hits = self.store.vector_search(query_vec, top_k * 2)
        ranked_lists = [vector_hits]
        if self.use_fts:
            fts_hits = self.store.fts_search(query, top_k * 2)
            ranked_lists.append(fts_hits)

        fused = reciprocal_rank_fusion(ranked_lists, k=self.rrf_k)[:top_k]

        # Điểm tin cậy: giữ score cosine tốt nhất của vector (thang [0,1],
        # dễ đặt ngưỡng) thay vì RRF score (không cùng thang).
        best_vector_score = max((c["score"] for c in vector_hits), default=0.0)
        low_confidence = best_vector_score < self.min_score

        for item in fused:
            item.pop("rrf", None)
            item.pop("rank", None)
            # Chunk chỉ đến từ FTS (không có trong vector hits) không có score
            # cosine — gán 0.0 để payload đồng nhất, tránh KeyError.
            item.setdefault("score", 0.0)

        return RetrievalResult(
            chunks=fused,
            max_score=best_vector_score,
            low_confidence=low_confidence,
        )
