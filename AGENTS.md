# AGENTS.md

Vietnamese-language RAG take-home project: hybrid retrieval (PostgreSQL pgvector + FTS → Reciprocal Rank Fusion), LangGraph agent with tools (`search_docs`, `read_chunk`, `list_documents` via the `agent/tools/` registry), and a code-level citation verifier. Optional React/Vite UI in `ui/`. `DESIGN.md` is the authoritative design rationale; `README.md` covers user-facing setup.

## Commands

Setup (editable install + dev tools into `.venv`, Python 3.11+ khuyến nghị 3.12):

```bash
uv sync --extra dev
```

Tests — no `PYTHONPATH=src` needed with `uv run`/`.venv` (project is installed editable; the `PYTHONPATH=src` prefix in README is only for pip-only setups):

```bash
uv run pytest tests/ -v                      # full suite
uv run pytest tests/test_smoke.py -k chunk   # single test
```

Gotcha: embedding là **API** (không còn model local trong RAM). `tests/test_smoke.py` dùng `DeterministicEmbedder` fake (vector rng seed theo text, L2-normalize) — không cần mạng, không cần API key. Test embedding API (`tests/test_embedder_api.py`) monkeypatch `langchain_openai.OpenAIEmbeddings`.

Lint (CI-equivalent gate, run before finishing):

```bash
uv run ruff check src tests scripts          # line-length 100, rules: E F I B UP
```

API + UI (two terminals):

```bash
uv run uvicorn api:app --reload --port 8000  # starts FastAPI backend on :8000
cd ui && npm install && npm run dev          # :5173
```
UI typecheck = `npm run build` (`tsc -b && vite build`); no eslint is configured.

LangSmith eval export: `uv run python scripts/export_eval_dataset.py --project chakra_rag --dataset rag-prod-eval [--limit 200]`

## Configuration

- `src/config.py` is the composition root for env/`.env` (custom loader, `os.environ.setdefault` → real env vars win over `.env` values). Add new settings to the `Config` dataclass; exceptions: `observability/` reads `LANGSMITH_*` and `LOG_LEVEL` directly.
- `.env` (from `.env.example`) defines `ENCRYPTION_KEY` (master key for integration storage). Model & API keys are managed dynamically via Settings UI.
- LangSmith tracing is opt-in via `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`. Without an API key, all tracing/feedback hooks are no-ops.

## Behavioral gotchas

- The API **never auto-seeds** — the index contains only user-uploaded files or existing database records.
- Embedding is an **API integration** (table `embedding_integrations`, Settings UI tab "Embedding"), NOT a local model, and there is **NO credential env, NO env fallback and NO default seed** — empty table means "not configured": `Embedder` (core/embedding.py) resolves the active integration per call and raises `EmbeddingConfigError` with a clear message if none. It caches the client by fingerprint, and L2-normalizes vectors with numpy so the pgvector `<->`/`1-d/2`/HNSW `vector_l2_ops` contract holds. The `dimension` field is user-declared (dropdown of common dims + custom) and is baked into the `chunks.embedding vector({dim})` DDL at startup (fresh DB with no integration yet → `cfg.embed_dim` from env `EMBED_DIM` = the DB's default dimension — the ONLY embedding env var; adding the first integration syncs the column). **Changing the active dimension with a non-empty index → `EmbeddingDimensionConflict` → HTTP 409**; UI confirms, retries `force=true` → `ChunkRepository.migrate_dimension` (drop HNSW → truncate → ALTER TYPE → recreate index) + `FileRepository.mark_all_stale` (all files → failed "cần nạp lại"); user reingests per-file (↻) — never auto-reingest.
- The only answering path is agent mode: the LLM calls tools (`search_docs` first per system prompt), so it requires a function-calling model.
- Multi-tool traces: `search_trace` entries are tagged `name` (`search_docs`/`read_chunk`/`list_documents`); old entries without `name` are treated as search. `low_confidence` is computed from search entries only; citation evidence = chunks from any tool — search pointer entries plus the read_chunk dict including its `before`/`after` neighbor chunks (search-only chunks are hydrated with full text from the DB by `_hydrate_evidence` before verification). UI renders a distinct card per tool kind.
- `search_docs` is pointer-first: it returns `chunk_id, doc, section, score, excerpt` (~150 chars, truncated with `…`) — never full text. Full text only comes from `read_chunk`, which returns the chunk + exactly 1 neighbor before/after in the same doc (`ChunkRepository.get_chunk_neighborhood`). Don't "simplify" this back to full text in search — that makes the LLM skip the read step entirely and bloats context with junk chunks.
- The citation verifier flags `invalid_citations` / `unsupported_claims` rather than silently dropping them, and its support check is a cheap n-gram proxy (not NLI) — paraphrased claims can be flagged. `MIN_SCORE=0.25` is a cosine threshold on L2-normalized vectors; each embedding model has its own score scale — retune via env if `low_confidence` misfires after switching models.
- Vite dev proxy strips the `/api` prefix when forwarding to :8000 — backend routes have no `/api`; CORS allowlist covers localhost:5173 only.

## Structure

- `src/` (flat layout, hatchling): `core/` (RAG domain: chunking, embedding (API client `Embedder`), retrieval+RRF, verification, security), `agent/` (LLM orchestration: `agent.py` LangGraph loop, `llm.py` reasoning pass-through, `tools/` — one file per tool, `@register_tool` registry; a new tool file imported in `agent/tools/__init__.py` is auto-wired via `build_tools`), `storage/` (PostgreSQL: `schema.py` = DDL bảng + index — nguồn sự thật duy nhất; `connection.py` = `Database` — SQLAlchemy engine (QueuePool, pgvector + tsvector), chạy schema lúc khởi tạo, **tự resolve số chiều vector từ `embedding_integrations` active** (DB mới chưa có integration → `cfg.embed_dim` từ env `EMBED_DIM` = chiều mặc định của DB, duy nhất biến embedding trong env; truy vấn KHÔNG nằm ở đây), `repositories/` (truy vấn theo domain bằng SQLAlchemy Core: `ChunkRepository` chunks với pgvector + tsvector + `vector_dimension()`/`migrate_dimension()`, `FileRepository` files, `ConversationRepository` conversations+messages, `IntegrationRepository` llm_integrations, `EmbeddingIntegrationRepository` embedding_integrations). Dependency direction: `agent → core`/`storage`/`repositories`, never the reverse.
- `scripts/` is a package (`__init__.py`) — pytest `pythonpath=["."]` in `pyproject.toml` lets tests import it.
- `data/`: `uploads/` = UI uploads (file gốc trên đĩa, cần cho reingest + inspector; xóa qua UI xóa cả DB + đĩa).

## Conventions

- Docs, comments, and docstrings are in Vietnamese; keep that for code comments.
- Commit messages: conventional commits in English (`feat:`, `fix:`, `test:`, `chore:`, `refactor:`).
