# Chakra RAG — Pipeline RAG nhỏ với Agentic Retrieval

Bài làm cho đề test AI Engineer (Chitta Group): xây dựng pipeline RAG nhỏ — chia nhỏ tài liệu, tạo embeddings, truy xuất, trả lời câu hỏi kèm trích dẫn nguồn, và đánh giá chất lượng.

## Điểm chính của bài làm

- **Agentic RAG**: LLM không được nhét sẵn context — nó **tự gọi tool `search_docs`** (function calling qua LangGraph) để tra cứu, có thể tìm nhiều lượt rồi mới trả lời. UI hiển thị search trace để xem agent đã tìm gì.
- **Hybrid retrieval**: vector (sqlite-vec) + lexical (SQLite FTS5), fusion bằng Reciprocal Rank Fusion.
- **Grounding có hậu kiểm**: mọi citation `[chunk_id]` được verify độc lập với LLM — cite phải nằm trong tập chunk tool *thực sự* trả về, và claim phải được chunk đỡ (support check).
- **Đánh giá bằng số liệu**: golden set 8 câu (factoid, multi-hop, unanswerable), đo Recall@k, MRR, token-F1, citation precision, refusal accuracy; kèm ablation `agent` vs `stuff`.
- **UI Vite + React + TS**: upload file, xem tiến trình embedding %, chấm xanh khi sẵn sàng, citation chip bấm xem nguồn gốc.

## Chạy nhanh

Yêu cầu: Python 3.11+, Node 18+, một LLM API key (OpenAI / OpenRouter / Ollama local).

```bash
# 1. Backend
uv venv --python 3.12 .venv            # hoặc python -m venv .venv
uv pip install -r requirements.txt     # hoặc pip install -r requirements.txt
cp .env.example .env                   # điền LLM_API_KEY / LLM_MODEL / LLM_BASE_URL

PYTHONPATH=src .venv/bin/python -m chakra_rag ingest   # ingest corpus seed
PYTHONPATH=src .venv/bin/python -m chakra_rag ask "Mức hoàn phí đào tạo tối đa là bao nhiêu?"

# 2. API
PYTHONPATH=src .venv/bin/uvicorn chakra_rag.interfaces.api:app --reload --port 8000

# 3. UI (tùy chọn)
cd ui && npm install && npm run dev    # http://localhost:5173

# 4. Đánh giá
PYTHONPATH=src .venv/bin/python scripts/run_eval.py            # ablation agent vs stuff
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --judge    # thêm LLM-judge

# 5. Tests
.venv/bin/python -m pytest tests/ -v
```

Cấu hình LLM qua `.env` (xem `.env.example`): OpenAI (`https://api.openai.com/v1`), OpenRouter (`https://openrouter.ai/api/v1`), hoặc Ollama local (`http://localhost:11434/v1`). Model cần hỗ trợ function calling cho mode `agent` (GPT-4o-mini, Qwen, Claude…); model local nhỏ không hỗ trợ tốt thì dùng `--mode stuff`.

**Model "thinking"** (DeepSeek-R1/V4, Qwen3…): các model này trả thêm trường `reasoning_content` và đòi hỏi nó được gửi lại ở lượt sau quanh tool-call — `ChatOpenAI` chuẩn của LangChain không làm việc này nên provider trả 400. Dự án dùng subclass `ThinkingChatOpenAI` (`src/chakra_rag/core/llm.py`) để giữ và gửi lại trường đó, nên **không cần tắt thinking mode** — cứ cấu hình endpoint OpenAI-compatible bình thường. Nội dung suy luận cũng được hiển thị trong UI.

## Kiến trúc

```
data/docs/*.md ─┐
upload (.md/.txt) ─┤→ chunking (heading + paragraph, ~300 token, overlap 50)
                │→ embedding (multilingual MiniLM 384d, local)
                │→ SQLite: chunks + vec0 (sqlite-vec) + FTS5 + files
                │   (ingest worker nền, cập nhật tiến trình từng batch)
                ▼
question → agent loop (LangGraph create_react_agent, max 4 lượt)
             │ tool_call search_docs(query, top_k)
             ▼
         hybrid retrieval: vector top-k + FTS5 top-k → RRF fusion → threshold
             │ chunks [{chunk_id, score, text, nguồn}] → message role="tool"
             ▼
         LLM chốt câu trả lời kèm [chunk_id] mỗi claim
             ▼
         citation verifier (độc lập với LLM):
           1. cite phải nằm trong tập tool thực sự trả về
           2. claim phải được chunk đỡ (n-gram support ≥ ngưỡng)
             ▼
         {answer, citations[], search_trace[], low_confidence, unsupported_claims[]}
```

### Cấu trúc code

Backend tổ chức theo tầng, dependency một chiều từ ngoài vào trong:

```
src/chakra_rag/
├── config.py                  # dataclass Config, đọc .env — mọi module nhận config qua đây
├── core/                      # nghiệp vụ lõi, không phụ thuộc framework
│   ├── chunking.py            #   cắt theo heading + paragraph, giữ metadata nguồn
│   ├── embedding.py           #   sentence-transformers, lazy-load, chuẩn hóa L2
│   ├── retrieval.py           #   hybrid vector+FTS5, RRF fusion, threshold gate
│   ├── llm.py                 #   ThinkingChatOpenAI: giữ & gửi lại reasoning_content
│   ├── agent.py               #   LangGraph create_react_agent + fallback stuff-context
│   └── verification.py        #   citation verification (existence + support check)
├── storage/
│   └── store.py               # SQLite: chunks + vec0 + FTS5 + files (1 file DB duy nhất)
├── ingestion/
│   └── worker.py              # worker nền 1 thread, state machine, tiến trình từng batch
├── observability/
│   └── telemetry.py           # logs JSONL tự thu (thay LangSmith)
├── service/
│   └── rag_service.py         # composition root: RagService.ask() ghép các tầng
└── interfaces/                # các lối vào, không chứa nghiệp vụ
    ├── api.py                 #   FastAPI: /files /ingest/progress /ask /chunks/{id}
    └── cli.py                 #   ingest / ask / files

scripts/run_eval.py   # đánh giá trên golden set + ablation
eval/golden.json      # 8 câu: factoid, multi-hop, unanswerable
tests/test_smoke.py   # 10 test cho phần nghiệp vụ tự viết, không cần LLM
```

Frontend tổ chức theo feature, giao diện kiểu ChatGPT (sidebar tài liệu + khung chat + drawer nguồn):

```
ui/src/
├── main.tsx                       # entry point
├── app/
│   ├── App.tsx                    # layout: sidebar | chat | source drawer
│   └── styles.css
├── api/
│   ├── client.ts                  # mọi fetch gọi backend (qua dev proxy /api)
│   └── types.ts                   # type TS khớp response schema của API
├── hooks/
│   └── useIngestStatus.ts         # poll danh sách file + tiến trình embedding
└── components/
    ├── sidebar/Sidebar.tsx        # upload + danh sách file + trạng thái index (chấm xanh)
    ├── chat/Composer.tsx          # ô nhập kiểu ChatGPT
    ├── chat/ChatMessage.tsx       # user bubble + reasoning + tool steps + answer + nguồn
    ├── chat/ToolCallStep.tsx      # hiển thị từng lượt gọi search_docs
    └── sources/SourceDrawer.tsx   # drawer trượt: đoạn tài liệu gốc khi click citation
```

Nguyên tắc cấu trúc: mỗi module một trách nhiệm; `interfaces` chỉ gọi `service`, `service` ghép `core`/`storage`/`ingestion`/`observability`; config tập trung; phần nghiệp vụ chấm điểm (retrieval, verification) là code tự viết có test riêng. FE: mọi API call đi qua `api/client.ts`, component không fetch trực tiếp.

## Quyết định thiết kế chính

**sqlite-vec + FTS5 trong một file SQLite.** Corpus vài chục chunk thì brute-force KNN là lựa chọn đúng, không cần ANN. Vector + metadata + lexical cùng một DB nên join ra citation gọn, transactional, không hạ tầng. Vector chuẩn hóa L2 trước khi lưu → khoảng cách L2 tương đương cosine.

**Hybrid retrieval + RRF.** Vector bắt nghĩa tốt nhưng trượt từ khóa chính xác (con số, tên riêng — "5.000.000 đồng"); FTS5 bù đúng chỗ đó. RRF chỉ cần thứ hạng, không cần chuẩn hóa score giữa cosine và BM25.

**Agent loop thay vì stuff-context.** LLM tự reformulate query, tìm nhiều lượt, ghép thông tin từ nhiều chunk — lợi thế rõ với câu multi-hop. Đổi lại: 2–4 LLM call mỗi câu. Vì vậy giữ mode `stuff` làm fallback và để ablation — số liệu trả lời câu hỏi "agent có đáng chi phí không", không phải cảm tính.

**Dùng LangChain + LangGraph, không dùng LangSmith.** `create_react_agent` thay vòng lặp tool-calling tự viết; `@tool` sinh schema tự động. Nhưng retrieval, RRF, citation verifier, eval là code tự viết — phần thể hiện năng lực. LangSmith (SaaS tracing) được thay bằng `telemetry.py` log JSONL: offline, tự sở hữu, đủ cho trace và eval.

**Chunk ID thuần ASCII** (`quy_dinh_hoan_phi_dao_tao#muc-hoan-phi-toi-da#0`): LLM phải tái tạo chính xác chunk_id khi trích dẫn; ID có dấu tiếng Việt dễ bị model viết sai ký tự gây mismatch citation.

## Chống hallucination — 4 lớp, mỗi lớp đo được

1. **Retrieval gate**: max score dưới ngưỡng → `low_confidence`, câu trả lời mặc định từ chối một phần/toàn bộ.
2. **Prompt ràng buộc + temperature 0**: chỉ dùng kết quả tool, mỗi claim kèm `[chunk_id]`, không đủ dữ liệu phải nói rõ.
3. **Citation verification độc lập với LLM**: cite không nằm trong tập tool thực sự trả về → `invalid_citations`; claim không được chunk đỡ → `unsupported_claims` (bị flag, không âm thầm xóa).
4. **Faithfulness metric trong eval**: LLM-judge chấm groundedness từng câu trả lời (`--judge`).

**Giới hạn trung thực**: support check bằng n-gram overlap là proxy rẻ tiền, không phải NLI — câu diễn đạt lại bằng từ khác có thể bị flag oan. Hướng nâng cấp: NLI model hoặc LLM-judge từng claim.

**Phát hiện thực tế từ eval**: câu unanswerable có retrieval score 0.42–0.55, chồng lấn với câu trả lời được thấp nhất (0.554) — threshold gate đơn thuần không tách được chúng. Tuyến phòng thủ chính cho câu không trả lời được là hành vi từ chối của LLM qua prompt, còn threshold chỉ là tín hiệu hỗ trợ.

## Đánh giá chất lượng

`eval/golden.json`: 8 câu tự soạn — 5 factoid, 1 multi-hop (ghép 2 chunk), 2 unanswerable (không có trong tài liệu). Gold chunks tham chiếu theo `doc + contains` để resolve ra chunk_id lúc chạy, tránh brittle.

`scripts/run_eval.py` đo:

| Nhóm | Metric |
|---|---|
| Retrieval | Recall@k, MRR trên câu trả lời được |
| Trả lời | token-F1 so reference; LLM-judge correctness 1–5 (`--judge`) |
| Grounding | citation precision (% cite trỏ đúng chunk gold); LLM-judge faithfulness |
| Anti-hallucination | refusal accuracy trên câu unanswerable |
| Agent | số lượt gọi tool trung bình; ablation `agent` vs `stuff` |

Kết quả retrieval hiện tại trên corpus seed: **Recall@5 = 6/6, MRR = 1.000** (mọi câu trả lời được đều hit hạng 1).

## Giả định

- Corpus demo tự soạn, tiếng Việt, quy mô vài chục chunk — đủ chứng minh pipeline. Corpus lớn sẽ cần tính lại chunk size, thêm reranker/ANN.
- LLM qua API OpenAI-compatible; người chấm cần 1 API key hoặc Ollama local.
- Tài liệu đầu vào dạng `.md`/`.txt` sạch (không xử lý PDF scan, bảng biểu phức tạp).
- Model chạy mode `agent` phải hỗ trợ function calling; nếu không, dùng mode `stuff`.

## Nếu có thêm thời gian

- Reranker cross-encoder (đặc biệt hiệu quả với corpus nhỏ).
- Support check nâng cấp: NLI model hoặc LLM-judge từng claim thay vì n-gram overlap.
- Semantic chunking + parent-document retrieval.
- Agent đa tool: `list_documents`, `read_chunk` bên cạnh `search_docs` — LangGraph mở rộng tự nhiên.
- Golden set lớn hơn + RAGAS/đánh giá liên tục trong CI.
- LangSmith nếu làm việc theo team và cần tracing tập trung; hiện tại logs JSONL tự thu là đủ.
