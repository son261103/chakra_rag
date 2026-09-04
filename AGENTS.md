# AGENTS.md

Vietnamese-language RAG take-home project: hybrid retrieval (sqlite-vec + FTS5 → Reciprocal Rank Fusion), LangGraph agent with a `search_docs` tool, and a code-level citation verifier. Optional React/Vite UI in `ui/`. `DESIGN.md` is the authoritative design rationale; `README.md` covers user-facing setup.

## Commands

Setup (editable install + dev tools into `.venv`, Python 3.12 — **avoid 3.14**, torch/sentence-transformers break):

```bash
uv sync --extra dev
```

Tests — no `PYTHONPATH=src` needed with `uv run`/`.venv` (project is installed editable; the `PYTHONPATH=src` prefix in README is only for pip-only setups):

```bash
uv run pytest tests/ -v                      # full suite
uv run pytest tests/test_smoke.py -k chunk   # single test
```

Gotcha: `tests/test_smoke.py` uses a real local `Embedder` (MiniLM) — first full-suite run downloads/loads the model (slow, needs network once). No LLM API key is needed; everything LLM-facing is mocked/faked.

Lint (CI-equivalent gate, run before finishing):

```bash
uv run ruff check src tests scripts          # line-length 100, rules: E F I B UP
```

API + UI (two terminals):

```bash
uv run python -m chakra_rag                  # starts FastAPI backend on :8000
# or: uv run uvicorn chakra_rag.interfaces.api:app --reload --port 8000
cd ui && npm install && npm run dev          # :5173
```
UI typecheck = `npm run build` (`tsc -b && vite build`); no eslint is configured.

LangSmith eval export: `uv run python scripts/export_eval_dataset.py --project chakra_rag --dataset rag-prod-eval [--limit 200]`

## Configuration

- `src/chakra_rag/config.py` is the composition root for env/`.env` (custom loader, `os.environ.setdefault` → real env vars win over `.env` values). Add new settings to the `Config` dataclass; exceptions: `observability/` reads `LANGSMITH_*` and `LOG_LEVEL` directly.
- `.env` (from `.env.example`) must define `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`. Editing `.env` requires a backend restart — `uvicorn --reload` watches only `.py` files.
- LangSmith tracing is opt-in via `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`. Without an API key, all tracing/feedback hooks are no-ops.

## Behavioral gotchas

- The API **never auto-seeds** `data/docs` — the index contains only user-uploaded files or existing database records.
- Agent mode requires a function-calling model; otherwise use `--mode stuff`.
- The citation verifier flags `invalid_citations` / `unsupported_claims` rather than silently dropping them, and its support check is a cheap n-gram proxy (not NLI) — paraphrased claims can be flagged. `MIN_SCORE=0.25` is tuned to MiniLM's compressed cosine scale (~0.3 ≈ noise).
- Vite dev proxy strips the `/api` prefix when forwarding to :8000 — backend routes have no `/api`; CORS allowlist covers localhost:5173 only.

## Structure

- `src/chakra_rag/` (src-layout, hatchling): `core/` (chunking, embedding, retrieval+RRF, llm, agent, verification — the hand-written capability code), `storage/` (SQLite: files + chunks + vec0 + FTS5 + llm_integrations), `ingestion/`, `observability/` (LangSmith), `service/` (`RagService` composition root), `interfaces/` (FastAPI `api.py` + `__main__.py`).
- `scripts/` is a package (`__init__.py`) — pytest `pythonpath=["."]` in `pyproject.toml` lets tests import it.
- `data/`: `docs/` = seed corpus, `uploads/` = UI uploads, `chakra.db` = runtime artifact (gitignored — don't commit DBs, uploads, or logs).

## Conventions

- Docs, comments, and docstrings are in Vietnamese; keep that for code comments.
- Commit messages: conventional commits in English (`feat:`, `fix:`, `test:`, `chore:`, `refactor:`).
