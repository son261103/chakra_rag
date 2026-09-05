# Chakra RAG
---
## 1. Đề bài đã làm gì

| Yêu cầu đề | Cách đáp ứng trong repo |
|---|---|
| Chia nhỏ tài liệu | Heading + paragraph chunking (~300 token, overlap 50), giữ metadata nguồn |
| Tạo embeddings | `paraphrase-multilingual-MiniLM-L12-v2` (local, 384d, L2-normalize) |
| Truy xuất | Hybrid: vector (`sqlite-vec`) + lexical (FTS5) → Reciprocal Rank Fusion |
| Trả lời + trích dẫn | Agent gọi tool `search_docs` (LangGraph); mỗi claim kèm `[chunk_id]` |
| Hạn chế hallucination | Retrieval gate + prompt ràng buộc + citation verifier độc lập LLM |
| Mã chạy được + hướng dẫn | README này + API / Web UI kèm tài liệu chi tiết |

---

## 2. Yêu cầu môi trường

- **Python 3.11+** (khuyến nghị **3.12**; tránh 3.14 — torch/sentence-transformers có thể lỗi)
- **uv** (khuyến nghị) hoặc `pip` + `venv`
- Một **LLM API key** OpenAI-compatible (OpenAI / OpenRouter / Ollama local…)
- Model **hỗ trợ function calling** (vd. `gpt-4o-mini`, Qwen tool-call) — agent gọi tool `search_docs` để tra cứu
- *(Tuỳ chọn UI)* Node.js 18+

---

## 3. Cài đặt & chạy nhanh (API + Web UI)

```bash
# 1) Cài đặt môi trường
uv sync --extra dev

# 2) Cấu hình .env
cp .env.example .env
# File .env lưu khóa chủ ENCRYPTION_KEY để mã hóa DEK của từng tích hợp

# 3) Khởi chạy Backend API (Terminal 1)
uv run uvicorn api:app --reload --port 8000

# 4) Khởi chạy Frontend UI (Terminal 2)
cd ui && npm install && npm run dev
# Truy cập: http://localhost:5173
```

> **Cấu hình Model & API Key:**
> Model và API Key được cấu hình trực tiếp trên Web UI thông qua nút **Cài đặt LLM** ở Sidebar.
> API Key được mã hóa an toàn bằng cơ chế **Envelope Encryption (KEK / DEK)** trước khi lưu vào SQLite, không cần lưu thô trong `.env`.

### Cấu hình `.env` (rút gọn)
```env
# Khóa chủ KEK để mã hóa DEK của từng tích hợp (Model & API Key cấu hình trên UI)
ENCRYPTION_KEY=zkniEH7RPIWhK3rtbR96-iqV30JHsnBZ_qnP2xofJcU=

EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
DB_PATH=data/chakra.db
DOCS_DIR=data/docs
MIN_SCORE=0.25
TOP_K=5
MAX_AGENT_TURNS=4
```

Lần đầu chạy embedding model sẽ **tải về máy** (cần mạng). DB nằm tại `data/chakra.db` (một file SQLite).

---

## 4. Kiểm tra chất lượng

**Test không cần LLM:**

```bash
PYTHONPATH=src python -m pytest tests/ -v
```

Test các tầng tự viết: chunking, store (sqlite-vec + FTS5), retrieve (RRF), citation verify, ingest.

---

## 5. Ví dụ câu hỏi demo (sau `ingest`)

Corpus seed (`data/docs/`):

1. `quy_dinh_hoan_phi_dao_tao.md`
2. `chinh_sach_nghi_phep.md`
3. `quy_dinh_bao_mat_du_lieu.md`
4. `chuan_code_va_review.md`

Gợi ý 5 câu (đúng tinh thần đề 3–5 câu + trích dẫn):

1. *Mức hoàn phí đào tạo tối đa cho nhân viên làm việc dưới 2 năm là bao nhiêu?*  
   → kỳ vọng: 5.000.000 đồng / khóa; cite chunk hoàn phí.
2. *Nhân viên phải gửi đơn xin nghỉ phép trước bao nhiêu ngày làm việc?*  
   → kỳ vọng: ít nhất 3 ngày làm việc.
3. *Nhân viên đã làm 3 năm, khóa 7 triệu — được hoàn tối đa bao nhiêu và nộp hồ sơ trong bao lâu?*  
   → multi-hop: 8.000.000 + 30 ngày.
4. *Khi rò rỉ dữ liệu mức 3, phải thông báo khách hàng trong bao lâu?*  
   → 72 giờ.
5. *Công ty có chính sách hỗ trợ mua laptop cá nhân không?*  
   → unanswerable: từ chối / nói không có trong tài liệu.

Mỗi câu trả lời in kèm **Nguồn** dạng `[chunk_id] doc — section`. Có thể thêm `--json` để xem full payload (citations, search_trace, low_confidence, unsupported_claims).

---

## 6. Chống hallucination (3 lớp)

1. **Retrieval gate** — điểm vector cao nhất &lt; `MIN_SCORE` (mặc định 0.25) → `low_confidence`; hệ thống ưu tiên từ chối hơn bịa.
2. **Prompt ràng buộc + temperature 0** — chỉ dùng kết quả tool; mỗi claim phải có `[chunk_id]`; thiếu dữ liệu phải nói rõ.
3. **Citation verifier (code, không tin LLM)**  
   - cite phải nằm trong tập chunk tool *thực sự* trả về trong phiên  
   - claim phải được chunk đỡ (n-gram support)  
   - cite sai / claim không đỡ → `invalid_citations` / `unsupported_claims` (flag, không im lặng xóa)

**Giới hạn trung thực:** support check n-gram là proxy rẻ, không phải NLI — diễn đạt lại bằng từ khác có thể bị flag oan. Nâng cấp tự nhiên: NLI hoặc LLM-judge từng claim.

**Hiệu chỉnh `MIN_SCORE=0.25`:** với MiniLM multilingual, cosine thường nén thang điểm (~0.3 ≈ nhiễu, ~0.5–0.6 ≈ liên quan, ≥0.7 ≈ gần exact). 0.25 nằm vừa trên noise floor.

---

## 7. Kiến trúc (ngắn)

```
data/docs/*.md
    → chunk (heading + paragraph)
    → embed (MiniLM local)
    → SQLite: files + chunks + vec0 (sqlite-vec) + FTS5

câu hỏi
    → agent (LangGraph create_react_agent, max 4 lượt)
         tool: search_docs(query, top_k)
         hybrid: vector top-k + FTS5 top-k → RRF → threshold
    → LLM trả lời + [chunk_id]
    → citation verifier
    → {answer, citations, search_trace, low_confidence, unsupported_claims}
```

**Vì sao hybrid + RRF?** Vector bắt nghĩa; FTS bắt số/tên riêng chính xác. RRF chỉ cần hạng, không cần chuẩn hóa cosine vs BM25-like.

**Vì sao agent?** Agent tự reformulate query / multi-hop, gọi `search_docs` nhiều lượt để gom đủ bằng chứng trước khi trả lời.

**Framework boundary:** LangChain/LangGraph lo cơ chế (agent loop, tool schema, splitter). **Retrieval + RRF + citation verify là code tự viết** — phần thể hiện năng lực.

**Observability (LangSmith):** bật bằng 3 biến môi trường `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY=...`, `LANGSMITH_PROJECT=chakra_rag` (xem `.env.example`). Khi bật, mỗi lần hỏi tạo một trace: vòng lặp agent + các span của tool `search_docs` và `Retriever.search`, kèm feedback scores `invalid_citations` / `unsupported_claims` / `low_confidence` trên root run. Production traces có thể xuất thành eval dataset bằng script `uv run python scripts/export_eval_dataset.py --project chakra_rag --dataset rag-prod-eval [--limit 200]`. Nếu không set `LANGSMITH_API_KEY`, mọi hook tracing/feedback là no-op — ứng dụng chạy hoàn toàn local, không gửi dữ liệu ra ngoài.

Cấu trúc code (layered backend):

```
src/
  api/           # fastapi app + modular routers (chat, files, conversations, integrations, health)
  core/          # chunking, embedding, retrieval, llm, agent, verification, security (KEK/DEK)
  storage/       # SQLite store (chunks, vec0, fts5, files, conversations, llm_integrations)
  ingestion/     # worker ingest
  service/       # domain services (chat, conversation, file, integration) + container
  observability/ # langsmith tracing + timing helpers
  config.py      # cấu hình tập trung
tests/
```

Chi tiết thiết kế: xem `DESIGN.md`.

---

## 8. API + UI

```bash
# Terminal 1 — API
uv run uvicorn api:app --reload --port 8000

# Terminal 2 — UI
cd ui && npm install && npm run dev
# http://localhost:5173  (proxy /api → :8000)
```

- Upload `.md` / `.txt` từ sidebar → worker nền chunk + embed → chấm xanh khi ready  
- Chat streaming (SSE): thinking / tool calls / answer + citation chip mở đoạn gốc  
- **Không auto-seed** `data/docs` khi mở API: index gồm file user upload qua Web UI
- Đổi `.env` cần **restart** backend (`--reload` chỉ theo dõi file `.py`)

---

## 9. Giả định

- Corpus demo tự soạn, tiếng Việt, quy mô nhỏ (vài chục chunk) — đủ chứng minh pipeline, không giả lập production scale.
- LLM qua endpoint OpenAI-compatible; người chấm cần 1 key hoặc Ollama.
- Đầu vào chính cho take-home: `.md` / `.txt` sạch (không OCR PDF scan / bảng phức tạp trong phạm vi 48h).
- Cần model hỗ trợ function calling (agent gọi tool `search_docs`).
- `data/docs` là corpus mẫu tham khảo. UI live index = những gì đã có trong DB sau upload của người dùng.
- Embedding chạy local CPU; lần đầu tải model chậm hơn.

---

## 10. Nếu có thêm thời gian

- Reranker cross-encoder
- Support check nâng NLI / LLM-judge từng claim
- Semantic chunking + parent-document retrieval
- Agent đa tool: `list_documents`, `read_chunk`
- Retry/backoff khi LLM gateway flaky

---

## 11. Cấu trúc thư mục quan trọng

```
chakra_rag/
├── README.md                 # file này
├── DESIGN.md                 # quyết định thiết kế chi tiết
├── requirements.txt          # dependency pin
├── .env.example
├── src/chakra_rag/           # backend
├── tests/test_smoke.py
├── data/
│   ├── docs/                 # corpus tài liệu mẫu tham khảo
│   ├── uploads/              # file upload UI (tham chiếu)
│   └── cau_hoi_mau.txt       # gợi ý câu hỏi demo UI (không ingest)
└── ui/                       # frontend tuỳ chọn
```
