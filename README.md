# Chakra RAG

Bài làm take-home **AI Engineer — Chitta Group** (Bộ phận Công nghệ & Dữ liệu).

Pipeline RAG nhỏ: chia tài liệu → embedding → truy xuất → trả lời 3–5 câu hỏi kèm trích dẫn nguồn → đánh giá chất lượng đơn giản.

> **Phạm vi theo đề:** UI / Cloud / dữ liệu lớn **không bắt buộc**. Phần demo chính là **CLI + eval**. UI (Vite/React) là phần bổ sung, có thể bỏ qua khi chấm.

---

## 1. Đề bài đã làm gì

| Yêu cầu đề | Cách đáp ứng trong repo |
|---|---|
| Chia nhỏ tài liệu | Heading + paragraph chunking (~300 token, overlap 50), giữ metadata nguồn |
| Tạo embeddings | `paraphrase-multilingual-MiniLM-L12-v2` (local, 384d, L2-normalize) |
| Truy xuất | Hybrid: vector (`sqlite-vec`) + lexical (FTS5) → Reciprocal Rank Fusion |
| Trả lời + trích dẫn | Agent gọi tool `search_docs` (LangGraph) hoặc mode `stuff`; mỗi claim kèm `[chunk_id]` |
| Hạn chế hallucination | Retrieval gate + prompt ràng buộc + citation verifier độc lập LLM |
| Đánh giá đơn giản | Golden set 8 câu + `scripts/run_eval.py` (Recall@k, MRR, token-F1, citation precision, refusal) |
| Mã chạy được + hướng dẫn | README này + CLI `ingest` / `ask` / `files` |

---

## 2. Yêu cầu môi trường

- **Python 3.11+** (khuyến nghị **3.12**; tránh 3.14 — torch/sentence-transformers có thể lỗi)
- **uv** (khuyến nghị) hoặc `pip` + `venv`
- Một **LLM API key** OpenAI-compatible (OpenAI / OpenRouter / Ollama local…)
- Model chạy mode `agent` cần **hỗ trợ function calling** (vd. `gpt-4o-mini`, Qwen tool-call). Không có thì dùng `--mode stuff`
- *(Tuỳ chọn UI)* Node.js 18+

---

## 3. Cài đặt & chạy nhanh (CLI — đường demo chính)

```bash
# Clone / vào thư mục project
cd chakra_rag

# 1) Tạo môi trường + cài dependency
uv venv --python 3.12 .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
# hoặc: python -m venv .venv && pip install -r requirements.txt

# 2) Cấu hình LLM
cp .env.example .env
# Sửa .env: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL

# 3) Ingest corpus mẫu (4 policy trong data/docs/)
PYTHONPATH=src python -m chakra_rag ingest

# 4) Hỏi thử (có trích dẫn nguồn)
PYTHONPATH=src python -m chakra_rag ask "Mức hoàn phí đào tạo tối đa là bao nhiêu?"
PYTHONPATH=src python -m chakra_rag ask "Một PR cần bao nhiêu approval trước khi merge?"
PYTHONPATH=src python -m chakra_rag ask "Công ty có hỗ trợ mua laptop cá nhân không?"   # unanswerable

# Mode không cần tool-calling (fallback / ablation)
PYTHONPATH=src python -m chakra_rag ask "..." --mode stuff

# Xem file đã index
PYTHONPATH=src python -m chakra_rag files
```

### Cấu hình `.env` (rút gọn)

```env
# OpenAI
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini

# OpenRouter
# LLM_BASE_URL=https://openrouter.ai/api/v1
# LLM_MODEL=<model-id>

# Ollama local
# LLM_BASE_URL=http://localhost:11434/v1
# LLM_API_KEY=ollama
# LLM_MODEL=qwen2.5:7b

EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
DB_PATH=data/chakra.db
DOCS_DIR=data/docs
MIN_SCORE=0.25
TOP_K=5
MAX_AGENT_TURNS=4
```

Lần đầu chạy embedding model sẽ **tải về máy** (cần mạng). DB nằm tại `data/chakra.db` (một file SQLite).

---

## 4. Đánh giá chất lượng

```bash
# Cần đã ingest data/docs (golden set trỏ vào 4 file seed đó)
PYTHONPATH=src python scripts/run_eval.py
PYTHONPATH=src python scripts/run_eval.py --judge   # thêm LLM-judge (tốn token hơn)
```

**Golden set** (`eval/golden.json`): 8 câu tự soạn

- 5 factoid (1 đoạn đủ)
- 1 multi-hop (ghép ≥2 chunk)
- 2 unanswerable (không có trong tài liệu → kỳ vọng từ chối)

**Metric đo:**

| Nhóm | Metric |
|---|---|
| Retrieval | Recall@k, MRR (trên câu trả lời được) |
| Answer | token-F1 so reference; LLM-judge correctness (`--judge`) |
| Grounding | citation precision; LLM-judge faithfulness (`--judge`) |
| Anti-hallucination | refusal accuracy trên câu unanswerable |
| Agent | số lượt tool trung bình; ablation `agent` vs `stuff` |

Tham chiếu retrieval trên corpus seed (đã đo): **Recall@5 = 6/6, MRR = 1.0** (mọi câu trả lời được hit hạng 1).

**Test không cần LLM:**

```bash
PYTHONPATH=src python -m pytest tests/ -v
```

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

## 6. Chống hallucination (4 lớp)

1. **Retrieval gate** — điểm vector cao nhất &lt; `MIN_SCORE` (mặc định 0.25) → `low_confidence`; hệ thống ưu tiên từ chối hơn bịa.
2. **Prompt ràng buộc + temperature 0** — chỉ dùng kết quả tool; mỗi claim phải có `[chunk_id]`; thiếu dữ liệu phải nói rõ.
3. **Citation verifier (code, không tin LLM)**  
   - cite phải nằm trong tập chunk tool *thực sự* trả về trong phiên  
   - claim phải được chunk đỡ (n-gram support)  
   - cite sai / claim không đỡ → `invalid_citations` / `unsupported_claims` (flag, không im lặng xóa)
4. **Eval faithfulness** — LLM-judge (`--judge`) + refusal accuracy trên unanswerable.

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

**Vì sao agent + mode stuff?** Agent tự reformulate / multi-hop; stuff rẻ hơn và dùng khi model không tool-call. Eval so hai mode bằng số, không cảm tính.

**Framework boundary:** LangChain/LangGraph lo cơ chế (agent loop, tool schema, splitter). **Retrieval + RRF + citation verify + eval là code tự viết** — phần thể hiện năng lực. Không dùng LangSmith; log JSONL tự thu (`logs/`).

Cấu trúc code (layered backend):

```
src/chakra_rag/
  config.py
  core/          # chunking, embedding, retrieval, llm, agent, verification
  storage/       # SQLite store
  ingestion/     # worker ingest
  observability/ # telemetry JSONL
  service/       # RagService composition root
  interfaces/    # cli + fastapi
scripts/run_eval.py
eval/golden.json
tests/test_smoke.py
```

Chi tiết thiết kế: xem `DESIGN.md`.

---

## 8. API + UI (tuỳ chọn — ngoài yêu cầu đề)

```bash
# Terminal 1 — API
PYTHONPATH=src uvicorn chakra_rag.interfaces.api:app --reload --port 8000

# Terminal 2 — UI
cd ui && npm install && npm run dev
# http://localhost:5173  (proxy /api → :8000)
```

- Upload `.md` / `.txt` từ sidebar → worker nền chunk + embed → chấm xanh khi ready  
- Chat streaming (SSE): thinking / tool calls / answer + citation chip mở đoạn gốc  
- **Không auto-seed** `data/docs` khi mở API: index chỉ gồm file user upload (hoặc đã `ingest` CLI trước đó)  
- Đổi `.env` cần **restart** backend (`--reload` chỉ theo dõi file `.py`)

---

## 9. Giả định

- Corpus demo tự soạn, tiếng Việt, quy mô nhỏ (vài chục chunk) — đủ chứng minh pipeline, không giả lập production scale.
- LLM qua endpoint OpenAI-compatible; người chấm cần 1 key hoặc Ollama.
- Đầu vào chính cho take-home: `.md` / `.txt` sạch (không OCR PDF scan / bảng phức tạp trong phạm vi 48h).
- Mode `agent` cần model function-calling; không thì `--mode stuff`.
- `data/docs` phục vụ **CLI demo + golden eval**. UI live index = những gì đã có trong DB sau upload/`ingest` của người dùng.
- Embedding chạy local CPU; lần đầu tải model chậm hơn.

---

## 10. Nếu có thêm thời gian

- Reranker cross-encoder (rất hiệu quả corpus nhỏ)
- Support check nâng NLI / LLM-judge từng claim
- Semantic chunking + parent-document retrieval
- Agent đa tool: `list_documents`, `read_chunk`
- Golden set lớn hơn + eval trong CI
- Hỗ trợ PDF (text layer) / lịch sử hội thoại bền vững trên UI
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
├── eval/golden.json          # bộ câu đánh giá
├── scripts/run_eval.py
├── tests/test_smoke.py
├── data/
│   ├── docs/                 # corpus seed (CLI + eval)
│   ├── uploads/              # file upload UI (tham chiếu)
│   └── cau_hoi_mau.txt       # gợi ý câu hỏi demo UI (không ingest)
└── ui/                       # frontend tuỳ chọn
```

---

## 12. Checklist nộp bài / demo nhanh

1. `uv venv` + `uv pip install -r requirements.txt` + điền `.env`
2. `PYTHONPATH=src python -m chakra_rag ingest`
3. Chạy 3–5 câu mục §5; chụp/ghi nhận answer + citations
4. `PYTHONPATH=src python scripts/run_eval.py` — ghi bảng metric ngắn
5. Sẵn sàng giải thích: hybrid+RRF, `create_react_agent`, citation verifier, vì sao `MIN_SCORE=0.25`

---

## 13. Ghi chú kỹ thuật nhỏ

- **Chunk ID ASCII** (`doc_slug#section-slug#0`): LLM phải tái tạo đúng id khi cite; tránh dấu tiếng Việt gây mismatch.
- **Model thinking** (DeepSeek-R1, Qwen3…): subclass `ThinkingChatOpenAI` giữ/gửi lại `reasoning_content` quanh tool-call — không cần tắt thinking.
- **Vector L2-normalize** trước khi lưu → khoảng cách L2 tương đương cosine.
- Smoke tests không gọi LLM; eval end-to-end cần key + đã ingest seed docs.
