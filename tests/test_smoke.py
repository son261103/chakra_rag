"""Smoke tests: chạy không cần LLM, chỉ cần embedding model (tải 1 lần).

Test các tầng tự viết: chunking, store (sqlite-vec + FTS5), retrieve (RRF),
verify (citation check), ingest. Đây là phần nghiệp vụ chấm điểm nên phải có test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agent.tools import ToolDeps, build_tools  # noqa: E402
from config import get_config  # noqa: E402
from core.chunking import chunk_markdown  # noqa: E402
from core.embedding import Embedder  # noqa: E402
from core.retrieval import Retriever, reciprocal_rank_fusion  # noqa: E402
from core.verification import (  # noqa: E402
    extract_citations,
    support_score,
    verify_answer,
)
from ingestion.worker import _assign_chunk_ids  # noqa: E402
from storage.store import Store  # noqa: E402

EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

SAMPLE_MD = (
    "# Chính sách nghỉ phép\n"
    "\n"
    "## Số ngày phép năm\n"
    "\n"
    "Nhân viên chính thức được hưởng 12 ngày phép có lương mỗi năm. Cứ mỗi 3 năm làm việc "
    "liên tục, nhân viên được cộng thêm 1 ngày phép.\n"
    "\n"
    "## Quy trình xin nghỉ phép\n"
    "\n"
    "Nhân viên phải gửi đơn xin nghỉ phép trên hệ thống nội bộ ít nhất 3 ngày làm việc trước "
    "ngày bắt đầu nghỉ.\n"
)


@pytest.fixture(scope="module")
def embedder() -> Embedder:
    return Embedder(EMBED_MODEL)


@pytest.fixture
def store(tmp_path, embedder) -> Store:
    s = Store(tmp_path / "test.db", embed_dim=embedder.dim)
    yield s
    s.close()


# ---------- chunking ----------

def test_chunk_markdown_keeps_sections():
    chunks = chunk_markdown(SAMPLE_MD, "test.md")
    assert len(chunks) >= 2
    sections = {c.section for c in chunks}
    assert any("Số ngày phép năm" in s for s in sections)
    assert any("Quy trình xin nghỉ phép" in s for s in sections)
    assert all(c.text.strip() for c in chunks)


def test_chunk_ids_are_stable_and_unique():
    chunks = chunk_markdown(SAMPLE_MD, "test.md")
    ids = [cid for cid, _ in _assign_chunk_ids(chunks)]
    assert len(ids) == len(set(ids))
    assert all("#" in cid for cid in ids)


# ---------- store ----------

def test_store_roundtrip_and_search(store, embedder):
    chunks = chunk_markdown(SAMPLE_MD, "test.md")
    vectors = embedder.embed([c.text for c in chunks])
    for (cid, chunk), vec in zip(_assign_chunk_ids(chunks), vectors, strict=False):
        store.insert_chunk(cid, chunk.doc, chunk.section, chunk.text,
                           chunk.char_start, chunk.char_end, vec)

    assert store.count_chunks() == len(chunks)

    # vector search
    hits = store.vector_search(embedder.embed_one("nghỉ phép bao nhiêu ngày"), top_k=3)
    assert hits
    assert 0.0 <= hits[0]["score"] <= 1.0
    assert hits[0]["chunk_id"]

    # fts search — exact term
    fts_hits = store.fts_search("12 ngày phép", top_k=3)
    assert fts_hits
    assert "12 ngày phép" in fts_hits[0]["text"]

    # get_chunk
    chunk = store.get_chunk(hits[0]["chunk_id"])
    assert chunk and chunk["doc"] == "test.md"


def test_delete_chunks_by_doc(store, embedder):
    vec = embedder.embed_one("nội dung mẫu")
    store.insert_chunk("a#s#0", "a.md", "s", "nội dung mẫu", 0, 10, vec)
    assert store.count_chunks() == 1
    store.delete_chunks_by_doc("a.md")
    assert store.count_chunks() == 0


# ---------- retrieve ----------

def test_rrf_fusion_ranks_consensus_first():
    a = {"chunk_id": "x", "text": "x"}
    b = {"chunk_id": "y", "text": "y"}
    c = {"chunk_id": "z", "text": "z"}
    fused = reciprocal_rank_fusion([[a, b], [a, c]], k=60)
    assert fused[0]["chunk_id"] == "x"  # xuất hiện ở cả 2 danh sách


def test_retriever_returns_result_with_confidence(store, embedder):
    chunks = chunk_markdown(SAMPLE_MD, "test.md")
    vectors = embedder.embed([c.text for c in chunks])
    for (cid, chunk), vec in zip(_assign_chunk_ids(chunks), vectors, strict=False):
        store.insert_chunk(cid, chunk.doc, chunk.section, chunk.text,
                           chunk.char_start, chunk.char_end, vec)

    retriever = Retriever(store, embedder, top_k=3, min_score=0.25)
    result = retriever.search("nhân viên được nghỉ bao nhiêu ngày phép mỗi năm")
    assert result.chunks
    assert result.max_score > 0.25
    assert not result.low_confidence
    assert all("chunk_id" in c and "text" in c for c in result.chunks)


# ---------- agent tools ----------

def test_build_tools_registry_wires_search_docs(store, embedder):
    """build_tools tự nhận mọi tool đăng ký trong agent/tools (registry)."""
    retriever = Retriever(store, embedder, top_k=3, min_score=0.25)
    tools = build_tools(ToolDeps(retriever=retriever))
    by_name = {t.name: t for t in tools}
    assert "search_docs" in by_name
    # `config` xuất hiện trong schema do @traceable wrap thêm param (hành vi có sẵn).
    assert {"query", "top_k"} <= set(by_name["search_docs"].args.keys())


# ---------- verify ----------

def test_extract_citations():
    text = "Mức hoàn là 5 triệu [hoanphi#muc#0], áp dụng khi đủ điều kiện [hoanphi#dk#1]."
    assert extract_citations(text) == ["hoanphi#muc#0", "hoanphi#dk#1"]


def test_support_score():
    claim = "Nhân viên được hoàn tối đa 5.000.000 đồng mỗi khóa đào tạo."
    chunk = "Công ty hoàn tối đa 5.000.000 đồng mỗi khóa đào tạo đối với nhân viên dưới 2 năm."
    assert support_score(claim, chunk) > 0.5
    assert support_score(claim, "Thời tiết hôm nay đẹp.") < 0.2


def test_verify_answer_flags_fake_citation():
    tool_returned = {
        "doc#a#0": {
            "chunk_id": "doc#a#0",
            "text": "Mức hoàn tối đa 5.000.000 đồng mỗi khóa.",
            "doc": "doc.md",
            "section": "a",
            "score": 0.8,
        },
    }
    answer = "Mức hoàn tối đa là 5.000.000 đồng mỗi khóa [doc#a#0] [doc#b#1]."
    verified = verify_answer(answer, tool_returned)
    assert verified.invalid_citations == ["doc#b#1"]
    assert len(verified.citations) == 1


def test_verify_answer_flags_unsupported_claim():
    tool_returned = {
        "doc#a#0": {
            "chunk_id": "doc#a#0",
            "text": "Mức hoàn tối đa 5.000.000 đồng mỗi khóa.",
            "doc": "doc.md",
            "section": "a",
            "score": 0.8,
        },
    }
    answer = "Công ty tặng mỗi nhân viên một chiếc xe máy [doc#a#0]."
    verified = verify_answer(answer, tool_returned)
    assert verified.unsupported_claims  # claim không được chunk đỡ


def test_config_has_new_fields():
    cfg = get_config()
    assert isinstance(cfg.api_allowed_origins, list) and cfg.api_allowed_origins
    assert cfg.supported_suffixes == {".md", ".txt", ".pdf"}
    assert cfg.embed_batch_size == 16
    assert cfg.support_threshold == 0.30
