"""Smoke tests: chạy không cần LLM, chỉ cần embedding model (tải 1 lần).

Test các tầng tự viết: chunking, store (sqlite-vec + FTS5), retrieve (RRF),
verify (citation check), ingest. Đây là phần nghiệp vụ chấm điểm nên phải có test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402

from agent.agent import (  # noqa: E402
    _build_tool_trace,
    _collect_tool_chunks,
    _hydrate_evidence,
)
from agent.tools import ToolDeps, build_tools  # noqa: E402
from config import get_config  # noqa: E402
from core.chunking import chunk_markdown  # noqa: E402
from core.embedding import Embedder  # noqa: E402
from core.retrieval import RetrievalResult, Retriever, reciprocal_rank_fusion  # noqa: E402
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

def test_build_tools_registry_wires_all_tools(store, embedder):
    """build_tools tự nhận mọi tool đăng ký trong agent/tools (registry)."""
    retriever = Retriever(store, embedder, top_k=3, min_score=0.25)
    tools = build_tools(ToolDeps(retriever=retriever, store=store))
    by_name = {t.name: t for t in tools}
    assert {"search_docs", "read_chunk", "list_documents"} <= set(by_name)
    # `config` xuất hiện trong schema do @traceable wrap thêm param (hành vi có sẵn).
    assert {"query", "top_k"} <= set(by_name["search_docs"].args.keys())


class _StubRetriever:
    """Retriever giả: trả chunk cố định, text dài để test excerpt."""

    def search(self, query: str, top_k: int = 5):
        long_text = "Nội dung dài để kiểm tra excerpt. " * 20
        chunk = {
            "chunk_id": "doc#s#0",
            "doc": "doc.md",
            "section": "s",
            "score": 0.7,
            "text": long_text,
        }
        return RetrievalResult(chunks=[chunk], max_score=0.7, low_confidence=False)


def test_search_docs_returns_pointer_payload(store, embedder):
    """search_docs pointer-first: chỉ excerpt rút gọn + chunk_id, không full text."""
    tools = build_tools(ToolDeps(retriever=_StubRetriever(), store=store))
    search_docs = next(t for t in tools if t.name == "search_docs")

    payload = json.loads(search_docs.invoke({"query": "gì đó", "top_k": 1}))
    assert payload[0]["chunk_id"] == "doc#s#0"
    assert "excerpt" in payload[0]
    assert "text" not in payload[0]  # full text chỉ đến từ read_chunk
    assert len(payload[0]["excerpt"]) <= 152  # 150 + dấu … khi cắt
    assert payload[0]["excerpt"].endswith("…")


def test_read_chunk_tool_returns_chunk_with_neighbors(store, embedder):
    """read_chunk trả chunk chính + đúng 1 chunk kề trước/sau trong cùng doc."""
    texts = [
        ("doc#s#0", 0, "Đoạn đầu."),
        ("doc#s#1", 10, "Nội dung đầy đủ của đoạn giữa."),
        ("doc#s#2", 20, "Đoạn cuối."),
        ("other#x#0", 0, "Tài liệu khác."),
    ]
    for cid, start, text in texts:
        store.insert_chunk(
            cid,
            "doc.md" if cid.startswith("doc#") else "other.md",
            "s",
            text,
            start,
            start + len(text),
            embedder.embed_one(text),
        )
    retriever = Retriever(store, embedder, top_k=3, min_score=0.25)
    tools = build_tools(ToolDeps(retriever=retriever, store=store))
    read_chunk = next(t for t in tools if t.name == "read_chunk")

    payload = json.loads(read_chunk.invoke({"chunk_id": "doc#s#1"}))
    assert payload["chunk_id"] == "doc#s#1"
    assert "Nội dung đầy đủ" in payload["text"]
    assert [c["chunk_id"] for c in payload["before"]] == ["doc#s#0"]
    assert [c["chunk_id"] for c in payload["after"]] == ["doc#s#2"]

    # Chunk đầu doc: không có kề trước
    first = json.loads(read_chunk.invoke({"chunk_id": "doc#s#0"}))
    assert first["before"] == [] and [c["chunk_id"] for c in first["after"]] == ["doc#s#1"]

    missing = json.loads(read_chunk.invoke({"chunk_id": "khong#ton#tai"}))
    assert "error" in missing


def test_list_documents_tool_lists_files(store, embedder):
    store.upsert_file("f1", "cv.md", source="seed", status="ready", chunks_total=3)
    retriever = Retriever(store, embedder, top_k=3, min_score=0.25)
    tools = build_tools(ToolDeps(retriever=retriever, store=store))
    list_documents = next(t for t in tools if t.name == "list_documents")

    docs = json.loads(list_documents.invoke({}))
    assert {"doc": "cv.md", "status": "ready", "chunks_total": 3, "chunks_done": 0} in docs


def test_tool_trace_and_evidence_multi_tool():
    """Trace nhận diện đủ 3 loại tool; bằng chứng citation gồm chunk thật + chunk kề."""
    search_results = [
        {"chunk_id": "s#0", "doc": "a.md", "section": "a", "score": 0.7, "excerpt": "x…"}
    ]
    read_payload = {
        "chunk_id": "s#0",
        "doc": "a.md",
        "section": "a",
        "text": "x",
        "before": [{"chunk_id": "s#b", "text": "trước"}],
        "after": [{"chunk_id": "s#a", "text": "sau"}],
    }
    docs = [{"doc": "a.md", "status": "ready", "chunks_total": 1, "chunks_done": 1}]
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "search_docs", "args": {"query": "phép"}, "id": "c1", "type": "tool_call"}
            ],
        ),
        ToolMessage(content=json.dumps(search_results), tool_call_id="c1"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "read_chunk", "args": {"chunk_id": "s#0"}, "id": "c2", "type": "tool_call"}
            ],
        ),
        ToolMessage(content=json.dumps(read_payload), tool_call_id="c2"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "list_documents", "args": {}, "id": "c3", "type": "tool_call"}
            ],
        ),
        ToolMessage(content=json.dumps(docs), tool_call_id="c3"),
    ]

    trace = _build_tool_trace(messages)
    assert [t["name"] for t in trace] == ["search_docs", "read_chunk", "list_documents"]
    assert trace[0]["query"] == "phép" and trace[0]["max_score"] == 0.7
    # Trace read_chunk: chunk chính + 2 chunk ngữ cảnh, đánh dấu is_context đúng.
    assert trace[1]["found"] is True
    assert [(c["chunk_id"], c["is_context"]) for c in trace[1]["chunks"]] == [
        ("s#0", False),
        ("s#b", True),
        ("s#a", True),
    ]
    assert trace[2]["n_docs"] == 1

    evidence = _collect_tool_chunks(messages)
    # list_documents không thành bằng chứng; chunk kề trong read_chunk CÓ.
    assert set(evidence) == {"s#0", "s#b", "s#a"}


def test_hydrate_evidence_replaces_excerpt_with_full_text(store, embedder):
    """Evidence từ search_docs (excerpt) được nạp full text từ store; id lạ không được thêm."""
    store.insert_chunk(
        "doc#s#0", "doc.md", "s", "Nội dung đầy đủ của đoạn.", 0, 26,
        embedder.embed_one("nội dung"),
    )
    evidence = {
        "doc#s#0": {
            "chunk_id": "doc#s#0",
            "doc": "doc.md",
            "section": "s",
            "score": 0.7,
            "excerpt": "Nội dung đầy đủ…",
        }
    }
    hydrated = _hydrate_evidence(evidence, store)
    assert hydrated["doc#s#0"]["text"] == "Nội dung đầy đủ của đoạn."
    assert "excerpt" not in hydrated["doc#s#0"]

    # Chunk đã có text đầy đủ (từ read_chunk) → giữ nguyên, không đụng store.
    full = {"doc#s#0": {"chunk_id": "doc#s#0", "doc": "doc.md", "text": "đã đủ"}}
    assert _hydrate_evidence(full, store) is full
    # Store None (agent khởi tạo không kèm store) → trả nguyên vẹn.
    assert _hydrate_evidence(evidence, None) is evidence


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


def test_extract_citations_multi_id_group():
    """Model hay gộp nhiều nguồn chung một cặp [] — phải extract đủ từng id."""
    text = "Kinh nghiệm chứng minh qua 2 dự án [a#exp#0, b#exp#1] và 1 mảnh [c#skill#2]."
    assert extract_citations(text) == ["a#exp#0", "b#exp#1", "c#skill#2"]


def test_extract_citations_ignores_prose_inside_brackets():
    """Cặp [] chứa chữ tự do (không phải id) không bị coi là trích dẫn."""
    text = "Chi tiết ở phần kinh nghiệm [xem phần Experience], mức lương 5 triệu [luong#muc#0]."
    assert extract_citations(text) == ["luong#muc#0"]


def test_config_has_new_fields():
    cfg = get_config()
    assert isinstance(cfg.api_allowed_origins, list) and cfg.api_allowed_origins
    assert cfg.supported_suffixes == {".md", ".txt", ".pdf"}
    assert cfg.embed_batch_size == 16
    assert cfg.support_threshold == 0.30
