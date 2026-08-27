# Production Readiness + LangSmith Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make chakra_rag production-ready: reproducible deps, env-driven config, LangSmith observability replacing hand-rolled JSONL telemetry, dedup/typing/lint/tests cleanup.

**Architecture:** Three sequential phases — (1) dependency + config foundation, (2) LangSmith tracing replacing Telemetry JSONL (delete `telemetry.py`, add `tracing.py` helper module), (3) quality cleanup (dedup ask paths, narrow excepts, typed API, ruff, tests). Each phase independently verifiable and rollback-friendly.

**Tech Stack:** Python 3.11+, uv, langchain-core 1.6.0 / langgraph 1.2.11, langsmith >=0.11.1,<1.0, FastAPI, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-27-production-readiness-langsmith-design.md`

## Global Constraints

- Python >=3.11; repo uses `uv` for lock/sync (`uv lock`, `uv sync --locked`).
- Git convention: lowercase conventional commits, single-line messages.
- Keep UI (`ui/**`) untouched. `payload_json` in SQLite **stays written** (UI replays it, App.tsx:46-67).
- LangSmith env vars are the CURRENT names: `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`. No runtime wiring needed beyond env; langchain-core auto-attaches tracer.
- Never enable tracing without key at runtime: config warns once and continues untraced if `LANGSMITH_TRACING=true` but no `LANGSMITH_API_KEY`.
- All new helpers must be no-op safe when LangSmith is not configured (no exceptions surface to users).
- prompts (agent.py SYSTEM_PROMPT etc.) stay in code this round.
- Windows-safe? N/A (linux). Use `uv run ...` prefix for all python/pytest/ruff commands.

---

### Task 1: Deps consolidation in pyproject.toml

**Files:**
- Modify: `pyproject.toml`
- Regenerate artifact: `requirements.txt`

**Interfaces:**
- Produces: declared deps `openai`, `pydantic`, `langgraph-prebuilt`, `langsmith>=0.11.1,<1.0` importable from env; `pypdf` present in uv.lock.

- [ ] **Step 1: Edit pyproject.toml dependencies**

Replace the `[project] dependencies` block with:

```toml
dependencies = [
    "langchain-core",
    "langchain-openai",
    "langchain-text-splitters",
    "langgraph",
    "langgraph-prebuilt",
    "sqlite-vec",
    "sentence-transformers",
    "fastapi",
    "uvicorn[standard]",
    "numpy",
    "python-multipart",
    "pypdf",
    # Declared explicitly (previously only transitive / in requirements.txt):
    "openai",        # client SDK used indirectly by langchain-openai; pin visibility
    "pydantic>=2",   # models used by api layer
    "langsmith>=0.11.1,<1.0",  # direct SDK usage: Client/@traceable/ls.trace
]

[tool.uv]
# Lockfile consistency: everything resolvable from pyproject alone.
```

Do NOT remove existing comment style; keep description/version fields untouched.

- [ ] **Step 2: Regenerate lock & verify**

Run: `uv lock && uv sync --locked`
Expected: success exit 0. Then verify: `uv run python -c "import openai, pydantic, langsmith, pypdf; print('ok')"` prints ok. Check `rg -n 'name = "pypdf"' uv.lock` matches a package entry.

- [ ] **Step 3: Regenerate requirements.txt as export artifact**

Run: `uv export --format requirements-txt --no-hashes --output-file requirements.txt`
Expected: file rewritten containing all locked packages (incl. langsmith).

- [ ] **Step 4: Run smoke tests**

Run: `uv run pytest tests/test_smoke.py -q`
Expected: all pass (9 tests).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements.txt uv.lock
git commit -m "build: consolidate deps into pyproject with explicit openai/pydantic/langgraph-prebuilt/langsmith"
```

---

### Task 2: Config gains hardcoded constants

**Files:**
- Modify: `src/chakra_rag/config.py`
- Modify: `src/chakra_rag/interfaces/api.py:35` (drop ALLOWED_ORIGINS constant)
- Modify: `src/chakra_rag/ingestion/worker.py:29-30` (drop EMBED_BATCH_SIZE/SUPPORTED_SUFFIXES constants)
- Modify: `src/chakra_rag/core/verification.py:26` (drop SUPPORT_THRESHOLD)
- Test: `tests/test_smoke.py`

**Interfaces:**
- Produces on Config:
  - `api_allowed_origins: list[str]` field (default `["http://localhost:5173", "http://127.0.0.1:5173"]`)
  - `supported_suffixes: set[str]` (default `{".md", ".txt", ".pdf"}`)
  - `embed_batch_size: int` (default 16)
  - `support_threshold: float` (default 0.30)
- Consumers updated: api.py uses `get_config().api_allowed_origins`; worker uses `cfg.supported_suffixes` / `cfg.embed_batch_size`; verification's `verify_answer(answer, tool_returned, low_confidence, support_threshold=SUPPORT_THRESHOLD)` gets an explicit parameter defaulting to the old constant.

- [ ] **Step 1: Write failing test**

Append to `tests/test_smoke.py`:

```python
def test_config_has_new_fields():
    cfg = get_config()
    assert isinstance(cfg.api_allowed_origins, list) and cfg.api_allowed_origins
    assert cfg.supported_suffixes == {".md", ".txt", ".pdf"}
    assert cfg.embed_batch_size == 16
    assert cfg.support_threshold == 0.30
```

(Adjust import line to include `get_config` if missing.)

- [ ] **Step 2: Run test → fails**

Run: `uv run pytest tests/test_smoke.py::test_config_has_new_fields -q`
Expected: FAIL (AttributeError on api_allowed_origins).

- [ ] **Step 3: Implement Config fields**

In `config.py`, add to frozen dataclass after chat_history_turns:

```python
    # API/CORS
    api_allowed_origins: list[str] = field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    # Ingestion
    supported_suffixes: set[str] = field(default_factory=lambda: {".md", ".txt", ".pdf"})
    embed_batch_size: int = 16

    # Verification
    support_threshold: float = 0.30
```

In `get_config()` builder add:

```python
        api_allowed_origins=[
            s.strip()
            for s in _env("API_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if s.strip()
        ],
        supported_suffixes={
            s.strip().lower() for s in _env("SUPPORTED_SUFFIXES", ".md,.txt,.pdf").split(",") if s.strip()
        },
        embed_batch_size=_env_int("EMBED_BATCH_SIZE", 16),
        support_threshold=_env_float("SUPPORT_THRESHOLD", 0.30),
```

- [ ] **Step 4: Rewire consumers**

api.py: delete line 35 `ALLOWED_ORIGINS = [...]`; middleware becomes:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_config().api_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

worker.py lines 28-30: delete both module constants; replace usages (`if path.suffix.lower() not in SUPPORTED_SUFFIXES:` etc.). Worker methods already have `self.cfg`; where functions lack access (`_parse_file`/`_embed_chunks` if standalone funcs use these names), pass cfg through or read from an instance attr — check actual structure first; ingest_directory_sync has `cfg` param already. Replace `EMBED_BATCH_SIZE` usages inside methods via `self.cfg.embed_batch_size`; for any free function usage pass explicit arg. Update imports in api.py: drop `SUPPORTED_SUFFIXES` from worker import, keep `IngestWorker`.

verification.py: keep module-level `SUPPORT_THRESHOLD = 0.30` as default param value:

```python
def verify_answer(
    answer: str,
    tool_returned: dict[str, dict[str, Any]],
    low_confidence: bool = False,
    support_threshold: float = SUPPORT_THRESHOLD,
) -> VerifiedAnswer:
    ...
        if best < support_threshold:
```

rag_service.py call sites unchanged (defaults apply); optionally thread `self.cfg.support_threshold`:

```python
verified = verify_answer(..., support_threshold=self.cfg.support_threshold)
```

- [ ] **Step 5: Run tests → pass**

Run: `uv run pytest tests/test_smoke.py -q`
Expected: all pass incl. new test.

- [ ] **Step 6: Commit**

```bash
git add src/chakra_rag/config.py src/chakra_rag/interfaces/api.py src/chakra_rag/ingestion/worker.py src/chakra_rag/core/verification.py src/chakra_rag/service/rag_service.py tests/test_smoke.py .env.example
git commit -m "refactor: move hardcoded cors/suffix/batch/threshold values into config"
```

Also append the four new keys with defaults to `.env.example` under pipeline section.

---

### Task 3: LangSmith tracing module replaces telemetry

**Files:**
- Create: `src/chakra_rag/observability/tracing.py`
- Delete: `src/chakra_rag/observability/telemetry.py`
- Modify: `src/chakra_rag/service/rag_service.py` (remove Telemetry import/init/log calls)
- Test: `tests/test_tracing.py`

**Interfaces:**
- Consumes: nothing internal; wraps stdlib + langsmith SDK only.
- Produces:
  - `ls_client() -> Client | None` (None when unconfigured)
  - `submit_feedback(key: str, score: float | int | bool, comment: str = "") -> None`
  - `trace_metadata(conversation_id: str | None, mode: str, *, streamed: bool) -> dict` returning `{"metadata": {...}, "tags": [...]}` config dict for agent invoke/stream.
- rag_service keeps using existing `timed`/`elapsed_ms` — moved INTO `tracing.py` re-export or kept in telemetry? Decision: move `timed`/`elapsed_ms` into `observability/timing.py` (tiny new module) since telemetry.py is deleted; update rag_service import accordingly.

- [ ] **Step 1: Write failing tests first**

Create `tests/test_tracing.py`:

```python
"""Unit tests cho observability.tracing — không cần network/key."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from chakra_rag.observability.tracing import ls_client, submit_feedback, trace_metadata


def test_trace_metadata_shape():
    cfgdict = trace_metadata("conv-1", "agent", streamed=False)
    assert cfgdict == {
        "metadata": {"conversation_id": "conv-1", "mode": "agent", "streamed": False},
        "tags": ["sync"],
    }
    cfgdict2 = trace_metadata(None, "stuff", streamed=True)
    assert cfgdict2["metadata"]["conversation_id"] is None
    assert cfgdict2["tags"] == ["stream"]


def test_ls_client_none_without_key(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    assert ls_client() is None


def test_submit_feedback_noop_when_unconfigured(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    submit_feedback(key="low_confidence", score=True)  # must not raise


def test_submit_feedback_calls_client(monkeypatch):
    # Tracing phải "được cấu hình" thì ls_client mới trả về client
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-test")
    fake_rt = MagicMock()
    fake_rt.id = "run-1"
    fake_rt.trace_id = "trace-1"
    fake_rt.session_name = "chakra_rag"
    fake_client = MagicMock()
    fake_client.create_project.return_value.id = "proj-1"
    import chakra_rag.observability.tracing as tracing_mod
    with patch("chakra_rag.observability.tracing.get_current_run_tree", return_value=fake_rt):
        old = tracing_mod._client_cache
        tracing_mod._client_cache = fake_client
        try:
            submit_feedback(key="low_confidence", score=1, comment="below threshold")
        finally:
            tracing_mod._client_cache = old
    kwargs = fake_client.create_feedback.call_args.kwargs
    assert kwargs["key"] == "low_confidence"
    assert kwargs["score"] == 1
    assert kwargs["run_id"] == "run-1"
    assert kwargs["trace_id"] == "trace-1"
    assert kwargs["session_id"] == "proj-1"
```

- [ ] **Step 2: Run → fails**

Run: `uv run pytest tests/test_tracing.py -q`
Expected: FAIL ModuleNotFoundError chakra_rag.observability.tracing.

- [ ] **Step 3: Create timing.py + tracing.py**

Create `src/chakra_rag/observability/timing.py`:

```python
"""Helper đo latency dùng chung."""
from __future__ import annotations

import time


def timed() -> float:
    """t0 = timed(); ...; latency_ms = elapsed_ms(t0)."""
    return time.perf_counter()


def elapsed_ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)
```

Create `src/chakra_rag/observability/tracing.py`:

```python
"""LangSmith observability — thay hệ JSONL tự thu (telemetry.py cũ).

Thiết kế theo docs.langchain.com/langsmith (langsmith>=0.11.1):
- Tracing bật qua env LANGSMITH_* ; langchain-core tự gắn tracer vào graph runs,
  KHÔNG cần wiring runtime ở đây.
- Module này chỉ cung cấp: client factory (lazy, guard khi chưa cấu hình),
  metadata per-invocation tại ranh giới ask(), và submit feedback scores
  (invalid_citations/unsupported_claims/low_confidence) lên root run.
- Khi LANGSMITH không cấu hình: mọi hàm là no-op an toàn.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_client_cache: Any = None  # langsmith.Client | None — lazy singleton


def _tracing_requested() -> bool:
    return os.environ.get("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes")


def ls_client() -> Any | None:
    """Trả về langsmith.Client hoặc None nếu chưa cấu hình (auth từ env)."""
    global _client_cache
    if _client_cache is not None:
        return _client_cache
    if not (_tracing_requested() and os.environ.get("LANGSMITH_API_KEY")):
        return None
    try:
        import langsmith as ls

        _client_cache = ls.Client()  # đọc LANGSMITH_API_KEY/ENDPOINT từ env
        return _client_cache
    except Exception:  # noqa: BLE001 — không bao giờ làm hỏng flow chính vì tracing
        logger.exception("khởi tạo langsmith.Client thất bại — tiếp tục không trace")
        return None


def trace_metadata(
    conversation_id: str | None, mode: str, *, streamed: bool
) -> dict[str, Any]:
    """Config dict cho agent.invoke/stream: metadata + tags của cả trace."""
    return {
        "metadata": {
            "conversation_id": conversation_id,
            "mode": mode,
            "streamed": streamed,
        },
        "tags": ["stream" if streamed else "sync"],
    }


def submit_feedback(key: str, score: float | int | bool, comment: str = "") -> None:
    """Ghi feedback score lên root run hiện tại (nếu đang trong một trace).

    Mapping chất lượng: invalid_citations→số lượng cite sai,
    unsupported_claims→số claim thiếu đỡ, low_confidence→0/1.
    Không trace / chưa cấu hình → no-op im lặng.
    """
    client = ls_client()
    if client is None:
        return
    try:
        import langsmith as ls

        rt = ls.get_current_run_tree()
        if rt is None:
            return
        client.create_feedback(
            key=key,
            score=score,
            comment=comment,
            run_id=rt.id,
            trace_id=rt.trace_id,
            session_id=client.create_project(project_name=rt.session_name, upsert=True).id,
        )
    except Exception:  # noqa: BLE001 — feedback thất bại không được phá trả lời
        logger.warning("submit_feedback failed key=%s", key, exc_info=True)
```

- [ ] **Step 4: Run tests → pass**

Run: `uv run pytest tests/test_tracing.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chakra_rag/observability/tracing.py src/chakra_rag/observability/timing.py tests/test_tracing.py
git commit -m "feat: add langsmith tracing helpers (client factory, metadata, feedback)"
```

---

### Task 4: Wire LangSmith into service boundaries; delete Telemetry JSONL

**Files:**
- Modify: `src/chakra_rag/service/rag_service.py`
- Modify: `src/chakra_rag/core/retrieval.py:74`
- Modify: `src/chakra_rag/core/agent.py:157-165`
- Delete: `src/chakra_rag/observability/telemetry.py`
- Modify: `.env.example`, `README.md`, `DESIGN.md`
- Test: `tests/test_service_langsmith.py`

**Interfaces:**
- Consumes: Task 3 `trace_metadata`, `submit_feedback`, timing helpers.
- Produces: RagService.ask/ask_stream emit traces+feedback; Retriever.search decorated retriever span; search_docs tool decorated tool span. ask()/ask_stream() signatures unchanged.

- [ ] **Step 1: Write failing test**

Create `tests/test_service_langsmith.py`:

```python
"""RagService không còn phụ thuộc Telemetry; feedback được gọi với đúng metrics."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class _FakeEmbedder:
    dim = 4

    def __init__(self, model: str):
        pass

    def embed_one(self, text: str) -> list[float]:
        return [0.0] * 4

    def embed_many(self, texts):
        return [[0.0] * 4 for _ in texts]


@pytest.fixture()
def make_service(tmp_path, monkeypatch):
    """RagService với FakeEmbedder — không load model thật."""
    from chakra_rag.config import Config
    from chakra_rag.service import rag_service as rs
    from chakra_rag.service.rag_service import RagService

    monkeypatch.setattr(rs, "Embedder", _FakeEmbedder)

    def factory():
        cfg = Config(db_path=tmp_path / "t.db", uploads_dir=tmp_path, logs_dir=tmp_path / "logs")
        return RagService(cfg)

    return factory


class FakeAgentResult:
    answer = "trả lời [a1]"
    tool_returned = {"a1": {"chunk_id": "a1", "doc": "d", "section": "s", "text": "trả lời", "score": 0.9}}
    search_trace = []
    reasoning = ""
    low_confidence = False
    mode = "agent"


def test_telemetry_module_removed():
    with pytest.raises(ModuleNotFoundError):
        import chakra_rag.observability.telemetry  # noqa: F401


def test_ask_submits_feedback_scores(make_service):
    svc = make_service()
    fake_result = FakeAgentResult()
    with patch.object(svc, "agent") as mock_agent:
        mock_agent.ask.return_value = fake_result
        with patch("chakra_rag.service.rag_service.submit_feedback") as fb:
            payload = svc.ask("câu hỏi?", mode="agent")
    assert payload["answer"]
    called_keys = {c.args[0] for c in fb.call_args_list}
    assert {"invalid_citations", "unsupported_claims", "low_confidence"} <= called_keys


def test_ask_stream_yields_done_with_payload(make_service):
    svc = make_service()

    def events():
        yield {"type": "answer", "delta": "xin chào"}
        yield {"type": "_final", "result": FakeAgentResult()}

    with patch.object(svc, "agent") as mock_agent:
        mock_agent.stream_agent.return_value = iter(events())
        collected = list(svc.ask_stream("hi"))
    types = [e["type"] for e in collected]
    assert types[-1] == "done"
    done = collected[-1]
    assert done["answer"] == "trả lời [a1]"
```

NOTE: Test file above already uses `_FakeEmbedder` (monkeypatched into `rs.Embedder` before RagService construction) — no real embedding model loads; store still needs a valid `embed_dim` (4 is fine: sqlite-vec accepts any declared dim).

- [ ] **Step 2: Run → fail**

Run: `uv run pytest tests/test_service_langsmith.py -q`
Expected: FAIL (telemetry still importable; submit_feedback not imported in rag_service).

- [ ] **Step 3: Edit rag_service.py — wire tracing, drop telemetry**

Import changes:

```python
# REMOVE:
from chakra_rag.observability.telemetry import Telemetry, elapsed_ms, timed
# ADD:
from chakra_rag.observability.timing import elapsed_ms, timed
from chakra_rag.observability.tracing import submit_feedback, trace_metadata
```

__init__: delete `self.telemetry = Telemetry(self.cfg.logs_dir)` line.

ask(): after building `payload`, DELETE whole `self.telemetry.log_ask({...})` block (lines ~120-136). Insert feedback submissions right before final `logger.info`:

```python
        submit_feedback("invalid_citations", len(verified.invalid_citations),
                        comment=", ".join(verified.invalid_citations))
        submit_feedback("unsupported_claims", len(verified.unsupported_claims),
                        comment="; ".join(verified.unsupported_claims[:5]))
        submit_feedback("low_confidence", int(bool(verified.low_confidence)))
```

ask_stream(): same — delete log_ask block (~208-225), insert identical three submit_feedback calls after verify_answer/persist, replace metadata: build once per public method where agent invoked/streamed:

In ask() where `self.agent.ask(...)` invoked → becomes:

```python
        agent_cfg = trace_metadata(conversation_id, mode, streamed=False)
        agent_result: AgentResult = self.agent.ask(question, mode=mode, history=history, config=agent_cfg)
```

In ask_stream():

```python
        agent_cfg = trace_metadata(conversation_id, mode, streamed=True)
        for event in self.agent.stream_agent(question, history=history, config=agent_cfg):
```

⇒ REQUIRES extending RagAgent signatures (next step). Streaming span lifecycle is owned by RagAgent.stream_agent (it owns the generator). The graph run itself IS the streaming trace (langgraph traces complete when the stream finishes), so do NOT open a separate `ls.trace` span for it. Enrichment only: after building the final AgentResult, if a run tree is active, attach final outputs to it — guarded so nothing happens untraced:

```python
import langsmith as ls

try:
    rt = ls.get_current_run_tree()  # root run active while agent.stream runs
    if rt is not None:
        rt.add_outputs({"answer": result.answer})
except Exception:  # noqa: BLE001 — enrichment không được phá streaming
    pass
```

Place immediately BEFORE `yield {"type": "_final", "result": result}` in stream_agent.

- [ ] **Step 4: Extend core/agent.py signatures to accept & forward config**

`ask_agent(self, question, history=None, config: dict | None = None)`; merge:

```python
run_config = {"recursion_limit": recursion_limit}
if config:
    run_config.update(config)
result = agent.invoke({"messages": messages_in}, config=run_config)
```

Same for `stream_agent(..., config=None)` merging into its `agent.stream(..., config=run_config, stream_mode="messages")`.

Update `RagAgent.ask(question, mode, history, config=None)` passthrough.

Decorate the tool body inside `_get_agent` (keeps closure). Rationale: langgraph ToolNode already records its own tool run, so `@traceable` here adds a NESTED child span carrying clean query/k inputs — desired for readability:

```python
from langsmith import traceable

@traceable(run_type="retriever", name="search_docs_tool")
def search_docs(query: str, top_k: int = 5) -> str:
    ...
```

ALSO decorate `Retriever.search`:

```python
@traceable(run_type="retriever", name="retrieve_docs")
def search(self, query: str, top_k: int | None = None) -> RetrievalResult:
```

(import `from langsmith import traceable` in retrieval.py.)

Decorate verify path lightly: skip — verification runs inside service (already within trace tree context).

- [ ] **Step 5: Delete telemetry.py + fix remaining references**

```bash
git rm src/chakra_rag/observability/telemetry.py
rg -n "telemetry|log_ask" src/ --glob '!*.jsonl'
```

Only allowed leftover: none. cli.py check too.

- [ ] **Step 6: Full test suite green**

Run: `uv run pytest -q`
Expected: all green (old smoke tests may construct RagService — ensure no Telemetry references).

- [ ] **Step 7: Commit**

```bash
git add -A src tests
git commit -m "feat: replace jsonl telemetry with langsmith tracing and feedback scores"
```

---

### Task 5: Env docs + eval dataset export script

**Files:**
- Modify: `.env.example`, `README.md`, `DESIGN.md`
- Create: `scripts/export_eval_dataset.py`
- Create: `tests/test_export_eval_dataset.py`

**Interfaces:**
- Produces: `export_eval_dataset(project_name: str, dataset_name: str, limit: int | None = None) -> tuple[int, int]` (created examples count, skipped count). Script runnable via `uv run python scripts/export_eval_dataset.py`.

- [ ] **Step 1: Write failing test**

`tests/test_export_eval_dataset.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_export_skips_runs_missing_io():
    from scripts.export_eval_dataset import export_eval_dataset  # type: ignore[attr-defined]

    run_ok = MagicMock(inputs={"question": "q"}, outputs={"answer": "a"})
    run_bad = MagicMock(inputs=None, outputs={"answer": "a"})
    with patch("scripts.export_eval_dataset._client") as client:
        client.list_runs.return_value = [run_ok, run_bad]
        created, skipped = export_eval_dataset("proj", "ds")
    assert created == 1
    assert skipped == 1
```

Add empty `scripts/__init__.py` so import works.

- [ ] **Step 2: Run → fail** (`uv run pytest tests/test_export_eval_dataset.py -q`) Expected ImportError.

- [ ] **Step 3: Implement script**

`scripts/export_eval_dataset.py`:

```python
"""Xuất production traces thành dataset đánh giá trên LangSmith.

Thay thế read_all() của telemetry cũ: dataset gốc giờ sống trên LangSmith.
Usage: LANGSMITH_API_KEY=... uv run python scripts/export_eval_dataset.py \
    [--project chakra_rag] [--dataset rag-prod-eval] [--limit 200]
"""

from __future__ import annotations

import argparse


def _client():
    import langsmith as ls

    return ls.Client()


def export_eval_dataset(project_name: str, dataset_name: str, limit: int | None = None) -> tuple[int, int]:
    """Bulk-create dataset examples từ root runs của project. Trả về (created, skipped)."""
    client = _client()
    runs = list(client.list_runs(project_name=project_name, is_root=True, error=False, limit=limit))
    usable = [r for r in runs if getattr(r, "inputs", None) and getattr(r, "outputs", None)]
    dataset = client.create_dataset(dataset_name, description="prod runs → eval set")
    examples = [
        {
            "inputs": r.inputs,
            "outputs": r.outputs,
            "metadata": {"mode": (r.metadata or {}).get("mode"), "source_run_id": r.id},
        }
        for r in usable
    ]
    if examples:
        client.create_examples(dataset_id=dataset.id, examples=examples)
    return len(examples), len(runs) - len(usable)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default="chakra_rag")
    ap.add_argument("--dataset", default="rag-prod-eval")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    created, skipped = export_eval_dataset(args.project, args.dataset, args.limit)
    print(f"created={created} skipped={skipped} project={args.project} dataset={args.dataset}")
```

- [ ] **Step 4: Run → pass; run suite**

`uv run pytest tests/test_export_eval_dataset.py -q` → pass. `uv run pytest -q` → green.

- [ ] **Step 5: Update docs (.env.example / README / DESIGN)**

`.env.example` append:

```dotenv
# ===== Observability (LangSmith) =====
# Bật để gửi trace về LangSmith. Không set/false → chạy hoàn toàn offline, không gửi gì.
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=chakra_rag
```

README: replace section describing JSONL asks.jsonl (~line 160) with short LangSmith paragraph: how to enable (3 env vars), what you see (agent traces w/ tool+retriever spans, feedback scores invalid_citations/unsupported_claims/low_confidence), how to export eval dataset (script above), note that unset key = fully local behavior. DESIGN.md: replace sections 228-250 rationale similarly; keep honesty about trade-off (data goes to external SaaS when enabled).

- [ ] **Step 6: Commit**

```bash
git add .env.example README.md DESIGN.md scripts/ tests/
git commit -m "docs: document langsmith setup; add prod-trace-to-eval-dataset exporter"
```

---

### Task 6: Dedup ask/ask_stream payload builder

**Files:**
- Modify: `src/chakra_rag/service/rag_service.py`

**Interfaces:**
- Consumes: VerifiedAnswer fields, AgentResult fields.
- Produces: private `_build_payload(question, verified, result: AgentResult, latency_ms, conversation_id) -> dict` used by BOTH ask() and ask_stream(); outgoing payload shape UNCHANGED (keys: question, answer, mode, citations, invalid_citations, unsupported_claims, search_trace, reasoning, low_confidence, latency_ms, conversation_id).

- [ ] **Step 1: Extract builder (no behavior change)**

Inside RagService add:

```python
    def _build_payload(
        self,
        question: str,
        verified: VerifiedAnswer,
        result: AgentResult,
        latency_ms: int,
        conversation_id: str | None,
    ) -> dict[str, Any]:
        return {
            "question": question,
            "answer": verified.answer,
            "mode": result.mode,
            "citations": verified.citations,
            "invalid_citations": verified.invalid_citations,
            "unsupported_claims": verified.unsupported_claims,
            "search_trace": result.search_trace,
            "reasoning": result.reasoning,
            "low_confidence": verified.low_confidence,
            "latency_ms": latency_ms,
            "conversation_id": conversation_id,
        }
```

Replace both inline dict literals (`ask` ~line 104 and `ask_stream` ~line 192) with `payload = self._build_payload(question, verified, result_or_final, latency, conversation_id)`.

- [ ] **Step 2: Also extract shared prelude**

Both methods start identically (top_k clamp + history fetch + log). Add:

```python
    def _prepare_question(self, question: str, top_k: int | None, conversation_id: str | None):
        if top_k:
            self.retriever.top_k = top_k
        history = self._history_for_conversation(conversation_id)
        logger.info("ask start mode=%s conv=%s q=%r", ...)
        return history
```

(with exact current log text preserved), used by both.

- [ ] **Step 3: Verify tests & behavior unchanged**

Run: `uv run pytest -q` → green. Manual: streaming event order/types unchanged (same event dicts out of ask_stream).

- [ ] **Step 4: Commit**

```bash
git add src/chakra_rag/service/rag_service.py
git commit -m "refactor: unify ask/ask_stream payload construction"
```

---

### Task 7: Narrow broad exception handlers

**Files:**
- Modify: `src/chakra_rag/core/llm.py:49`
- Modify: `src/chakra_rag/core/agent.py:198,343`
- Modify: `src/chakra_rag/ingestion/worker.py:275,367`
- Modify: `src/chakra_rag/interfaces/api.py:144`

**Interfaces:**
- Behavior: intentional fallbacks REMAIN but now log full context via logger.exception; data-shape guards become specific-typed excepts. No silent swallows anywhere.

- [ ] **Step 1: llm.py `_create_chat_result`**

The `except Exception: return result` guard protects against odd response objects. Keep breadth intentionally BUT document + log:

```python
        except Exception:  # noqa: BLE001 — payload lạ từ provider: bỏ qua reasoning, không chặn flow chính
            logger.debug("reasoning_content extraction skipped: unexpected response shape", exc_info=True)
            return result
```

(add module `logger = logging.getLogger(__name__)`.)

- [ ] **Step 2: agent.py ask_agent fallback (line ~198)**

Intent: ANY failure must yield graceful degraded answer, never crash. Keep breadth, add logging + typed-priority notes:

```python
        except Exception as exc:  # noqa: BLE001 — muốn RẤT khó crash ask; lỗi nào cũng degrade an toàn
            logger.exception("agent loop failed — falling back to direct retrieve mode=%s", mode_hint_unused := "")
```

Correction — apply precisely to existing code (no walrus, preserve message):

```python
        except Exception as exc:  # noqa: BLE001 — mọi lỗi đều phải degrade an toàn, không crash
            logger.exception("agent loop failed — fallback to direct retrieve")
            fallback = self.retriever.search(question)
            ...unchanged...
```

add `logger = logging.getLogger(__name__)` module-level (agent.py currently lacks logging import? It does not import logging today → add).

- [ ] **Step 3: agent.py stream_agent error (~343)**

Currently yields `{"type":"error","message":str(exc)}` silently. Add BEFORE yield:

```python
        except Exception as exc:  # noqa: BLE001 — stream lỗi phải báo UI, không crash server
            logger.exception("agent stream failed")
            yield {"type": "error", "message": str(exc)}
            return
```

- [ ] **Step 4: worker.py two sites**

`_run` (~275): KEEP broad catch (worker must survive poisoned files) but it ALREADY logs traceback via format_exc — fine; just ensure pattern stays. Change only ingest_directory_sync (~367):

```python
        try:
            worker._process_file(path)  # noqa: SLF001 — chạy đồng bộ, không qua thread
        except Exception as exc:  # noqa: BLE001 — file lỗi không chặn các file sau
            logger.exception("sync ingest failed name=%s", path.name)
            store.set_file_status(fid, "failed", error=f"{type(exc).__name__}: {exc}")
```

(module logger exists: `logging.getLogger(__name__)` — confirm; if missing add it.)

- [ ] **Step 5: api.py list_file_chunks (~144)**

Narrow to what extract_text plausibly raises while keeping resilience:

```python
        except (OSError, ValueError, RuntimeError) as exc:
            full_text_error = str(exc)
            logger.warning("inspect extract failed file_id=%s err=%s", file_id, exc)
```

If extract_text internally raises other lib-specific exceptions (check pypdf exceptions), prefer catching those explicitly too: `from pypdf.errors import PdfReadError` guarded import:

```python
        try:
            full_text = extract_text(path)
        except (OSError, ValueError, RuntimeError) as exc:
            ...
        except Exception as exc:  # noqa: BLE001 — parser libs raise misc; log & degrade
            full_text_error = f"{type(exc).__name__}: {exc}"
            logger.warning("inspect extract failed (unexpected) file_id=%s", file_id, exc_info=True)
```

- [ ] **Step 6: Suite green + commit**

Run: `uv run pytest -q` green.

```bash
git add src/
git commit -m "refactor: log and document intentional broad excepts; narrow api extract guard"
```

---

### Task 8: Typed FastAPI responses + ruff config

**Files:**
- Modify: `src/chakra_rag/interfaces/api.py`
- Modify: `pyproject.toml` ([tool.ruff])
- Test: `tests/test_api.py` (new TestClient suite)

**Interfaces:**
- Produces: response_model declarations on main endpoints; `Response` models defined with Pydantic v2; ruff enforced with select `E,F,I,B,UP` line-length 100.

- [ ] **Step 1: Add ruff to dev deps + configure**

pyproject.toml:

```toml
[project.optional-dependencies]
dev = ["pytest", "ruff"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

Run: `uv sync --locked && uv run ruff check .` — expect findings list; autofix with `uv run ruff check --fix .` then manually clear leftovers (import sort etc.). Re-run until clean: `uv run ruff check .` exit 0.

NOTE: running `uv lock` again after adding dev dep (uv sync will want updated lock): run `uv lock && uv sync --locked`.

- [ ] **Step 2: Write failing API tests FIRST**

Create `tests/test_api.py`:

```python
"""FastAPI TestClient suite — index gating, upload validation, conversations CRUD-lite."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from chakra_rag.interfaces import api as api_mod


@pytest.fixture()
def client(tmp_path):
    """App instance với lifespan mocked: no real store/embedder/worker threads."""
    app = api_mod.app
    service = MagicMock(name="service")
    worker = MagicMock(name="worker")
    service.store.count_chunks.return_value = 7
    service.store.list_files.return_value = []
    service.store.list_conversations.return_value = []
    service.store.create_conversation.return_value = {"id": "c1", "title": "Hội thoại mới"}
    worker.progress.return_value = {"status": "ready", "percent": 100, "chunks_done": 1, "chunks_total": 1}
    # bypass lifespan init entirely:
    app.router.lifespan_context = _StaticLifespan(app, service=service, worker=worker)
    with TestClient(app) as c:
        c.service = service  # type: ignore[attr-defined]
        c.worker = worker  # type: ignore[attr-defined]
        yield c


class _StaticLifespan:
    def __init__(self, app, service, worker):
        self.app = app
        self.service = service
        self.worker = worker

    async def __aenter__(self):
        self.app.state.service = self.service
        self.app.state.worker = self.worker
        return None

    async def __aexit__(self, *exc):
        return False


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "chunks": 7}


def test_upload_rejects_bad_suffix(client):
    r = client.post("/files", files={"file": ("x.exe", b"MZ", "application/x-msdownload")})
    assert r.status_code == 400


def test_upload_accepts_md(client):
    client.worker.enqueue.return_value = "fid1"
    r = client.post("/files", files={"file": ("notes.md", "# hi".encode(), "text/markdown")})
    assert r.status_code == 200
    assert r.json()["file_id"] == "fid1"


def test_ask_503_when_index_not_ready(client):
    client.worker.progress.return_value = {"status": "parsing"}
    r = client.post("/ask", json={"question": "hi?"})
    assert r.status_code == 503


def test_conversations_roundtrip(client):
    r = client.post("/conversations", json={"title": "abc"})
    assert r.status_code == 200
    assert r.json()["id"] == "c1"
```

- [ ] **Step 3: Run → likely PASS immediately (endpoints exist); goal is regression safety + response-model forcing**

Run: `uv run pytest tests/test_api.py -q`
Expected: pass; if any fixture interplay breaks (module-level CORS middleware using get_config reads .env — ensure no tracing warning spam), adjust fixture ordering only.

- [ ] **Step 4: Type the endpoints (response models)**

Add Pydantic response models in api.py and attach to endpoints (keep behavior identical):

```python
class ChunkRef(BaseModel):
    chunk_id: str
    doc: str | None = None
    section: str | None = None
    score: float | None = None
    text: str | None = None


class AskResponseModel(BaseModel):
    question: str
    answer: str
    mode: str
    citations: list[ChunkRef]
    invalid_citations: list[str]
    unsupported_claims: list[str]
    search_trace: list[dict[str, Any]]
    reasoning: str
    low_confidence: bool
    latency_ms: int
    conversation_id: str | None


class HealthResponse(BaseModel):
    status: str
    chunks: int
```

Apply `@app.post("/ask", response_model=AskResponseModel)` and `@app.get("/health", response_model=HealthResponse)`. For SSE endpoint leave as StreamingResponse (no model). For file/conversation endpoints add light models OR annotate `-> dict[str, Any]` — choose annotation-only where output structure is loose (list endpoints) to avoid over-constraining worker dict shapes.

- [ ] **Step 5: Suite green + commit**

Run: `uv run pytest -q && uv run ruff check .`

```bash
git add pyproject.toml uv.lock src/chakra_rag/interfaces/api.py tests/test_api.py
git commit -m "feat: typed fastapi responses and ruff lint enforcement"
```

---

### Task 9: Dead code removal + stale doc refs

**Files:**
- Modify: `src/chakra_rag/core/agent.py` (AgentResult.n_tool_calls removal)
- Modify: `DESIGN.md`, `README.md`
- Test: existing suite must stay green

**Interfaces:**
- AgentResult loses unused `n_tool_calls` field (grep confirms only constructor sets + never read outside... VERIFY: rg shows ask_agent/stuff set it; rag_service ignores it). All constructors updated by removing args.

- [ ] **Step 1: Remove n_tool_calls everywhere**

rg -n "n_tool_calls" src/ → agent.py dataclass + ask_agent(216)+success path(231)+stream(356)+stuff(382). Remove field + each assignment occurrence.

- [ ] **Step 2: Grep dead doc refs**

rg -n "log_tool_call|asks.jsonl|read_all" README.md DESIGN.md src/ → remove/rewrite stale mentions (asks.jsonl gone since Task 4/5).

- [ ] **Step 3: Tests green + commit**

Run: `uv run pytest -q` green.

```bash
git add -A
git commit -m "chore: drop unused agentresult.n_tool_calls and stale doc references"
```

---

### Task 10: Service-layer verification tests (final gate)

**Files:**
- Test: `tests/test_service_flows.py`

**Interfaces:**
- Consumes: everything previous. This is the acceptance gate exercising service composition with mocked LLM/network.

- [ ] **Step 1: Write integration-ish tests**

`tests/test_service_flows.py`:

```python
"""Service flows với fake LLM + fake embedder: không mạng, chạy nhanh, deterministic."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from chakra_rag.config import Config


@pytest.fixture()
def service(tmp_path, monkeypatch):
    from chakra_rag.service import rag_service as rs

    fake_embedder = MagicMock(return_value=None)
    fake_embedder.dim = 4
    fake_embedder.embed_one = lambda t: [0.0] * 4
    monkeypatch.setattr(rs, "Embedder", MagicMock(return_value=fake_embedder))
    cfg = Config(db_path=tmp_path / "s.db", uploads_dir=tmp_path, logs_dir=tmp_path / "logs")
    svc = rs.RagService(cfg)
    yield svc
    svc.close()


def test_ask_happy_path_stores_turn(service):
    from chakra_rag.service.rag_service import AgentResult  # re-export check optional

    fr = MagicMock()
    fr.answer = "trả lời [c1]"
    fr.tool_returned = {"c1": {"chunk_id": "c1", "doc": "d", "section": "s", "text": "trả lời đây", "score": 0.8}}
    fr.search_trace = [{"query": "q", "n_results": 1, "chunk_ids": ["c1"], "max_score": 0.8}]
    fr.reasoning = ""
    fr.low_confidence = False
    fr.mode = "agent"

    cid = service.store.create_conversation()["id"]
    with patch.object(service, "agent") as ag:
        ag.ask.return_value = fr
        payload = service.ask("hỏi gì đó", conversation_id=cid)
    assert payload["low_confidence"] is False
    msgs = service.store.list_messages(cid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["payload"] is not None  # payload_json vẫn ghi (UI replay cần)


def test_stream_done_event_validated(service):
    fr = MagicMock()
    fr.answer = "ok"
    fr.tool_returned = {}
    fr.search_trace = []
    fr.reasoning = ""
    fr.low_confidence = True
    fr.mode = "agent"

    def gen():
        yield {"type": "thinking", "delta": "hm"}
        yield {"type": "_final", "result": fr}

    with patch.object(service, "agent") as ag:
        ag.stream_agent.return_value = iter(gen())
        events = list(service.ask_stream("x"))
    assert events[0]["type"] == "thinking"
    assert events[-1]["type"] == "done"
    assert events[-1]["low_confidence"] is True
```

NOTE: If MagicMock attribute mismatch bites (fr.mode compare etc.), use simple namespace classes instead of MagicMock for fake results.

- [ ] **Step 2: Run → pass/fail cycle, fix code-fixture mismatches only (no product changes expected)**

Run: `uv run pytest tests/test_service_flows.py -q` → green.

- [ ] **Step 3: Full suite + lint final gate**

Run: `uv run ruff check . && uv run pytest -q`
Expected: clean + all pass.

- [ ] **Step 4: Manual smoke (real model, optional but recommended)**

If LLM_API_KEY configured locally: start `uv run uvicorn chakra_rag.interfaces.api:app` briefly; POST one /ask; confirm server log line `ask done mode=... latency_ms=...`; with LANGSMITH key also set, verify trace visible on langsmith.com project `chakra_rag` including retriever span + 3 feedback records. Skip gracefully when keys absent (offline runs remain fully functional).

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: service flow coverage with fakes; final lint+suite gate"
```

---

## Execution Notes

- Order strictly 1→10 (each depends on prior interfaces: Task 4 needs Task 3 helpers; Task 6 refactor sits AFTER wiring so the diff review stays small; Tasks 8-10 close quality gates).
- Delegation plan (orchestrator): Phase A=Tasks1-2 → @fixer; Phase B=Tasks3-5 → @fixer (LangSmith specifics fully specified here); Phase C=Tasks6-9 → @fixer split by file-scope where parallelizable BUT task 6 touches rag_service.py which Task 4 modified — sequential. Task 10 = orchestrator-run final verification.
- Every task ends with commit; rollback granularity = phase-level git revert ranges.
