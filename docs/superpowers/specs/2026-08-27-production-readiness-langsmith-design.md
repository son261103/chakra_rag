# Design: Production Readiness Refactor + LangSmith Observability

Date: 2026-08-27
Status: Approved (user, 2026-08-27)
Scope: src/chakra_rag/** backend only; UI untouched.

## Goals

1. Make dependency management reproducible and single-sourced.
2. Replace hand-rolled JSONL telemetry with LangSmith tracing + feedback.
3. Remove duplication, narrow exception handling, type the API, add lint config and real test coverage.

Non-goals: store/repository redesign, ingestion plugin architecture, UI changes.

## Chosen approach

Phased delivery (user-selected option A). Each phase is independently verifiable and rollback-friendly. Commits follow repo convention: lowercase conventional commits, one logical change per commit.

---

## Phase 1 — Foundation: deps + config

### Changes

- `pyproject.toml` becomes the single source of truth:
  - Add missing declarations currently only in requirements/lock: `openai`, `pydantic`, `langgraph-prebuilt`.
  - Add explicit SDK dep: `"langsmith>=0.11.1,<1.0"` (needed for direct Client/@traceable usage).
  - Ensure `pypdf` resolves into `uv.lock` (currently declared but absent; lazy-imported at worker.py:91 as pdftotext fallback).
- Regenerate lock: `uv lock && uv sync --locked`. Sync/copy `requirements.txt` from pyproject (generated artifact via `uv export`) so both stay consistent.
- Move hardcoded values into `Config` (env-driven fields in `config.py`, frozen dataclass):
  - `ALLOWED_ORIGINS` (api.py:35) → `api_allowed_origins: list[str]`
  - `SUPPORTED_SUFFIXES`, `EMBED_BATCH_SIZE` (worker.py:29-30) → config fields
  - `SUPPORT_THRESHOLD` (verification.py:26) → `support_threshold: float = 0.30`
  - Prompts (agent.py:30/42) intentionally stay in code for this phase.

### Verification

- `uv sync --locked` exits clean.
- `uv run pytest tests/test_smoke.py` passes.
- CLI roundtrip on existing data still works (`python -m chakra_rag files`).

---

## Phase 2 — LangSmith observability (replaces JSONL telemetry)

Reference docs: https://docs.langchain.com/langsmith (trace-with-langchain, annotate-code, attach-user-feedback, manage-datasets-programmatically). Verified against langsmith 0.11.1 (already transitive in uv.lock via langchain-core).

### Deletions

- `src/chakra_rag/observability/telemetry.py` entirely (Telemetry class, log_ask, read_all, timed).
- Telemetry call blocks at rag_service.py:120-136 (ask) and :208-225 (ask_stream).
- `payload_json` column writes in `store.add_message` (store.py:392) and reading in list_history_for_llm (store.py:449). Keep column in schema for zero-migration; stop writing (write NULL). Document that new deployments can drop it later.
- DESIGN.md section 228-250 and README:160 rationale describing JSONL choice — replace with LangSmith description.

### Additions

- New module `src/chakra_rag/observability/tracing.py`:
  - Lazy `get_client()` returning `langsmith.Client()` (auth from env only). Returns None if key missing or tracing disabled — all helpers must guard None.
  - `submit_feedback(key, score, comment)` using exact current API:
    ```python
    rt = ls.get_current_run_tree()          # Optional[RunTree]
    if rt is not None and client is not None:
        client.create_feedback(
            key=key, score=score, comment=comment,
            run_id=rt.id, trace_id=rt.trace_id,
            session_id=client.create_project(project_name=rt.session_name, upsert=True).id,
        )
    ```
    Mapping of removed metrics: `invalid_citations` → feedback score = count with comment listing ids; `unsupported_claims` → score = count; `low_confidence` → boolean score 0/1.
- Env vars (documented in .env.example / README):
  ```dotenv
  LANGSMITH_TRACING=true      # unset/false => complete no-op (safe offline)
  LANGSMITH_API_KEY=lsv2_...
  LANGSMITH_PROJECT=chakra_rag
  ```
  No runtime wiring needed; langchain-core attaches tracer automatically to graph runs. Never ship `LANGSMITH_TRACING=true` without a key (runtime warning + failed ingest, not import-time failure). Config warns once if tracing=true and no key detected, then continues untraced.
- Child spans via contextvars (no parent passing):
  - `@traceable(run_type="retriever", name="retrieve_docs")` on Retriever.search.
  - `@traceable(run_type="tool", name="search_docs")` wrapping the agent tool function body.
- Per-invocation metadata at service boundary — same config dict shape for invoke & stream:
  ```python
  cfg = {"metadata": {"conversation_id": cid, "mode": mode}, "tags": ["stream" if stream else "sync"]}
  agent.invoke(payload, config=cfg) / agent.stream(payload, config=cfg, stream_mode="messages")
  ```
- Streaming span: ask_stream's custom generator loop uses explicit trace context manager (@traceable on generators finalizes too early):
  ```python
  with ls.trace(name="stream_answer", run_type="chain", inputs={"question": q}) as rt:
      # yield tokens...
      rt.end(outputs={"answer": full_text})
  ```
- Eval dataset export replaces read_all(): script/function `export_eval_dataset(project, dataset_name)`:
  ```python
  runs = client.list_runs(project_name=project, is_root=True, error=False)
  dataset = client.create_dataset(dataset_name)
  client.create_examples(dataset_id=dataset.id, examples=[
      {"inputs": r.inputs, "outputs": r.outputs} for r in runs if r.inputs and r.outputs])
  ```

### Behavior when LangSmith unavailable

Identical runtime behavior minus traces; no exceptions surface to users; helper guards keep everything functional offline.

### Verification

- With key set: one real question shows root trace with llm/tool child runs + retriever span + metadata on dashboard; feedback entries visible on the run.
- Streaming question produces trace whose span closes after stream completes (not empty outputs).
- Without key: behavior identical to today; smoke tests pass.

---

## Phase 3 — Cleanup: dedup, excepts, typing, lint, tests

- Extract shared payload construction duplicated between ask (rag_service.py:104-136) and ask_stream (:192-225) into one internal builder used by both paths.
- Narrow broad `except Exception` swallow sites: llm.py:49, agent.py:198/343, worker.py:275/367, api.py:144 → catch specific expected types; where a fallback is intended, catch Exception but log with logger.exception and re-raise or convert deliberately (no silent pass).
- Type-hint all FastAPI endpoints + basic Pydantic response models; use typed request models instead of raw dicts where dicts are currently accepted.
- Add `[tool.ruff]` config (line-length compatible with existing style, select E,F,I,UP,B); fix findings; add ruff check step documented in README dev section.
- Dead code removal: AgentResult.n_tool_calls; update stale DESIGN.md references (log_tool_call etc.).
- Tests (target: service + api layers):
  - FastAPI TestClient suite covering main endpoints (health, files, conversations, ask happy-path with stubbed service).
  - Service-layer tests with monkeypatched LLM/retriever (no network, tiny fake embeddings).
  - Keep existing smoke tests green; mocking keeps suite fast.

### Verification

- `uv run ruff check .` clean; `uv run pytest` green including new suites.
- Manual: ingest a small file end-to-end + streaming ask through `/ask/stream`.

---

## Risks & mitigations

- Lock churn may upgrade transitive deps unexpectedly → review `uv lock --dry-run` diff before writing; pin any surprise bumps back.
- ThinkingChatOpenAI tracing safety confirmed (only overrides internal helpers called within callback-wrapped `_generate/_stream`) — do not bypass runnable methods later.
- astream_events would drop usage_metadata (known langgraph#8225) → we stay on stream_mode="messages".
- SQLite payload_json stop-write is backward compatible; old rows retain data.
