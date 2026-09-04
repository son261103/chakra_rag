# Thiết kế pipeline RAG nhỏ — Chitta AI Engineer Take-Home

## 1. Phân tích đề bài: chấm gì thì thiết kế nấy

Đề chấm 4 tiêu chí, mỗi tiêu chí ánh xạ thành một phần thiết kế phải "khoe" được:

| Tiêu chí chấm | Hệ quả thiết kế |
|---|---|
| Chất lượng truy xuất & mức liên quan | Không chỉ vector search: thêm lexical (FTS5) + fusion, threshold gate đánh dấu `low_confidence` |
| Grounding & trích dẫn đáng tin | Citation không phải chỉ là dòng nhắc trong prompt — phải có **bước kiểm tra trích dẫn sau khi sinh** (citation verification) |
| Mã sạch, thực dụng | Một package nhỏ, FastAPI mỏng, ít phụ thuộc, chạy được ngay |

Đề nói KHÔNG cần UI, cloud, dữ liệu lớn → thời gian ưu tiên tuyệt đối cho **retrieval quality + grounding** trước; UI (Vite + React + TS) làm **sau cùng như phần bonus** để demo trực quan — không để nó ăn vào ngân sách của phần lõi.

## 2. Kiến trúc tổng thể

```
data/docs/*.md (corpus nhỏ, tiếng Việt, tự soạn)
        │
        ▼
 ┌─────────────┐   ┌──────────────┐   ┌────────────────────────┐
 │  Chunking   │──▶│  Embedding   │──▶│  SQLite                │
 │ (section +  │   │ (multilingual│   │  - chunks: text+meta   │
 │  paragraph, │   │  MiniLM 384d)│   │  - vec_chunks: vec0    │
 │  ~300 tok,  │   └──────────────┘   │  - fts_chunks: FTS5    │
 │  overlap 50)│                      └────────────────────────┘
 └─────────────┘                                │
                                                ▼
 question ─────────────────────────────────────────────────────┐
                                                               ▼
                 ┌──────────────────────────────────────────────────────┐
                 │  AGENT LOOP (function calling, max 4 lượt)           │
                 │                                                      │
                 │  LLM đọc câu hỏi → quyết định gọi tool search_docs   │
                 │      │ tool_call {query, top_k}                      │
                 │      ▼                                               │
                 │  search_docs = hybrid retrieval                      │
                 │    (embed → vector top-k + FTS5 → RRF + threshold)   │
                 │      │ chunks [{chunk_id, score, text, nguồn}]       │
                 │      ▼                                               │
                 │  kết quả trả lại LLM (message role="tool")           │
                 │  → LLM tìm thêm lượt nữa, HOẶC chốt câu trả lời     │
                 └──────────────────────────────────────────────────────┘
                                                               │
                          final answer kèm [chunk_id] mỗi claim │
                                                               ▼
                 Citation verifier: cite có nằm trong tập chunk mà
                 tool THỰC SỰ trả về? claim có được chunk đỡ?
                                                               │
                                                               ▼
                     JSON { answer, citations[{chunk_id, doc, section,
                            span, score}], search_trace[],
                            unsupported_claims[] }
```

Lối vào: **FastAPI** (`POST /ask`) theo chuẩn RESTful API. Phía trên là **UI Vite + React + TS** gọi API để demo trực quan: khung hỏi đáp, hiển thị câu trả lời kèm citation **bấm được** để mở đúng đoạn tài liệu gốc, và bảng Cài đặt tích hợp LLM mã hóa KEK/DEK.

```
┌────────────────────────────────────────────────────────────┐
│  UI: Vite + React + TS (bonus)                             │
│  - upload file, danh sách file, tiến trình embedding %,    │
│    chấm xanh khi index sẵn sàng                            │
│  - ô hỏi, câu trả lời, citation chip [1][2]                │
│    → click mở panel chunk gốc                              │
│  - hiển thị low_confidence / unsupported_claims            │
└───────────────▲────────────────────────────────────────────┘
                │ fetch (REST/JSON, polling tiến trình)
┌───────────────┴────────────────────────────────────────────┐
│  FastAPI (mỏng): /files /ingest/progress /ask              │
│                  /chunks/{id} /health                      │
└───────────────▲────────────────────────────────────────────┘
                │
   ingest worker (nền): parse → chunk → embed → SQLite
   pipeline.ask(question) → agent loop ⇄ search_docs tool
```

## 3. Các quyết định thiết kế chính

### 3.1 Corpus: tự soạn, nhỏ, có chủ đích
- 3–4 tài liệu guideline tiếng Việt ngắn (ví dụ: chính sách nghỉ phép, quy trình hoàn phí, quy định bảo mật dữ liệu, chuẩn code nội bộ). Mỗi tài liệu vài section.
- **Lý do**: corpus tự soạn ⇒ kiểm soát được nội dung, và cố tình cài được các "bẫy" truy xuất:
  - 2 đoạn gần nghĩa ở 2 tài liệu khác nhau (test phân biệt),
  - câu hỏi cần ghép thông tin từ 2 chunk (test multi-hop nhẹ),
  - 1–2 câu hỏi **không có trong tài liệu** (test hành vi từ chối — anti-hallucination).
- Pipeline nhận bất kỳ `.md/.txt` nào; corpus demo chỉ là dữ liệu test. Ghi rõ giả định này trong README.

### 3.2 Chunking: theo cấu trúc tài liệu, không cắt mù
- Tách theo heading/section trước, sau đó tách đoạn trong section; target ~250–350 token, overlap ~50 token. Corpus nhỏ và có cấu trúc nên không cần semantic chunking.
- Mỗi chunk mang metadata đầy đủ — đây là nền tảng của trích dẫn chính xác:
  ```
  chunk_id (stable: doc#sec#idx), doc_title, section, char_start, char_end, text
  ```
- Trích dẫn trong câu trả lời luôn tra ngược về `(doc, section, span gốc)` — không chỉ ID.

### 3.3 Embedding: model đa ngôn ngữ chạy local
- Mặc định: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 chiều) — chạy offline, không cần API key, người chấm chạy được ngay; hỗ trợ tiếng Việt tốt ở quy mô này.
- Chuẩn hóa L2 vector trước khi lưu ⇒ khoảng cách L2 tương đương cosine, khỏi phụ thuộc option `distance_metric` của từng bản sqlite-vec.
- Cấu hình được qua env (đổi sang OpenAI embedding nếu muốn) nhưng default không cần key.

### 3.4 Vector store: SQLite + sqlite-vec (đúng lựa chọn của bạn)
Vì sao hợp với bài này:
- Corpus vài chục chunk → brute-force KNN là đủ, sqlite-vec quét tuyến tính là đúng chứ không phải "chữa cháy".
- Một file DB duy nhất, không hạ tầng; vector (`vec0`), metadata (bảng thường), và lexical (`FTS5`) **nằm cùng một database** → join ra citation rất gọn, transactional.
- Schema:
  ```sql
  CREATE TABLE chunks(id INTEGER PRIMARY KEY, chunk_id TEXT UNIQUE,
                      doc TEXT, section TEXT, text TEXT,
                      char_start INT, char_end INT);
  CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[384]);  -- rowid = chunks.id
  CREATE VIRTUAL TABLE fts_chunks USING fts5(text, content='chunks', content_rowid='id');
  ```
- Lưu ý: `pip sqlite-vec` bundle sẵn extension cho Linux x64; bật/tắt `enable_load_extension` ngay khi mở connection, đóng gói vào 1 module `store.py`.

### 3.5 Retrieval: hybrid vector + lexical, fusion bằng RRF
- Vector bắt nghĩa tốt nhưng hay trượt **từ khóa chính xác** (tên riêng, con số, mã hiệu — ví dụ "mức hoàn phí tối đa 5 triệu"). FTS5 bù đúng chỗ đó. Với tiếng Việt, FTS5 unicode61 không tách từ hoàn hảo nhưng vẫn bắt exact term tốt.
- Fusion: **Reciprocal Rank Fusion** (không cần chuẩn hóa score, 1 dòng code, ổn định):
  `score(d) = Σ 1/(60 + rank_i(d))`
- Lấy top 4–6 sau fusion; **threshold gate**: nếu score/độ phủ quá thấp → đánh dấu `low_confidence` và câu trả lời mặc định là từ chối một phần/toàn bộ.

### 3.6 Generation: agent loop bằng LangGraph — LLM tự gọi tool `search_docs`

**Mental model quan trọng nhất**: tool chỉ là một JSON schema khai báo với LLM. LLM **không tự chạy gì cả** — nó chỉ sinh ra yêu cầu có cấu trúc `{"name": "search_docs", "arguments": {...}}`; **code của mình** thực thi yêu cầu đó (chạy hybrid retrieval) rồi trả kết quả về cho LLM dưới dạng message `role="tool"`. Lặp lại cho đến khi LLM thôi gọi tool và chốt câu trả lời. LangGraph (`create_react_agent`) đóng gói đúng vòng lặp này — phần nghiệp vụ (retrieval, verifier) vẫn là code tự viết.

**Luồng thực tế** (trace một hội thoại):
```
1. system: "Trả lời dựa trên tài liệu nội bộ. Muốn tra cứu PHẢI gọi
   search_docs. Mỗi claim kèm [chunk_id]. Không đủ dữ liệu → nói rõ."
2. user:   "Mức hoàn phí tối đa là bao nhiêu?"
3. assistant: tool_call search_docs(query="mức hoàn phí tối đa", top_k=5)
4. tool:   [{chunk_id:"hoanphi#s2#1", score:0.82, text:"...tối đa 5 triệu..."}, ...]
5. assistant: tool_call search_docs(query="điều kiện áp dụng hoàn phí", top_k=5)
6. tool:   [{chunk_id:"hoanphi#s3#0", ...}, ...]
7. assistant: "Mức hoàn phí tối đa là 5 triệu đồng [hoanphi#s2#1],
   áp dụng khi... [hoanphi#s3#0]"   ← câu trả lời cuối
```

**Code xương sống** (LangChain + LangGraph, gọn hơn hẳn vòng lặp tự viết):
```python
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

@tool
def search_docs(query: str, top_k: int = 5) -> str:
    """Tìm kiếm tài liệu nội bộ; trả về các đoạn liên quan kèm chunk_id và điểm."""
    chunks = retrieve(query, top_k)          # hybrid: vector + FTS5 + RRF + threshold
    return json.dumps(chunks, ensure_ascii=False)

llm = ChatOpenAI(model=cfg.model, base_url=cfg.base_url, temperature=0)
agent = create_react_agent(llm, [search_docs], prompt=SYSTEM_PROMPT)

def ask(question, max_turns=4):
    result = agent.invoke(
        {"messages": [("user", question)]},
        config={"recursion_limit": 2 * max_turns + 1})   # mỗi lượt = 2 bước graph
    messages = result["messages"]
    answer = messages[-1].content
    tool_returned = extract_chunks_from_tool_messages(messages)  # bằng chứng hợp lệ
    trace = build_search_trace(messages)                          # cho UI
    return finalize(answer, tool_returned, trace)   # citation verification ở đây
```

Điểm gọn đáng giá của LangGraph ở đây: vòng lặp tool-calling, parse `tool_calls`, nối message — có sẵn; `search_trace` và tập bằng chứng chỉ cần **đọc lại danh sách messages** sau khi chạy xong, không cần side-channel.

**Guardrails (bắt buộc — agent thêm failure mode mới):**
- `recursion_limit = 2*max_turns + 1`: chống loop; quá lượt thì ép chốt bằng bằng chứng tốt nhất đã thu thập (parse từ messages), kèm cờ cảnh báo.
- Citation verifier **chỉ chấp nhận chunk_id xuất hiện trong các ToolMessage** của phiên — agent bịa nguồn là bị phát hiện ngay.
- `low_confidence` programmatic: max score trong mọi kết quả tool dưới ngưỡng → flag, bất kể LLM nói gì.
- LLM trả lời thẳng không gọi tool → phát hiện được (messages không có tool_call); có thể ép lượt đầu bằng `tool_choice` nếu cần.
- Model phải hỗ trợ function calling (GPT-4o-mini, Qwen, Claude...; model local nhỏ hỗ trợ thất thường) — giữ fallback `mode=stuff` để hệ thống chạy được với mọi model.

**Vì sao hướng này đáng làm cho bài test:**
- Agent tự reformulate query, tìm nhiều lượt, ghép thông tin từ nhiều chunk — lợi thế rõ với câu multi-hop.
- Search trace là demo hay: UI cho người xem "coi" agent gọi tool tìm gì.
- Thể hiện hiểu biết agentic RAG nhưng vẫn kiểm soát được: 1 tool, vòng lặp hữu hạn, verifier độc lập với LLM.
- Đánh đổi: 2–4 LLM call mỗi câu thay vì 1 (chi phí/độ trễ) — ghi rõ trong README.

**Giữ mode cổ điển để so sánh**: `ask(mode="stuff")` — retrieve một lần rồi nhét context vào prompt — dùng khi model không hỗ trợ function calling, và để so sánh chi phí/độ trễ với agent loop.

### 3.7 Citation verification — điểm khác biệt chính
Sau khi LLM trả lời, chạy bước hậu kiểm:
1. **Existence**: mọi `chunk_id` được cite phải nằm trong tập retrieved (chống bịa nguồn).
2. **Support check** (bản đơn giản, trung thực): tách câu trả lời thành từng claim, tính độ phủ token n-gram giữa claim và chunk được cite; claim nào dưới ngưỡng → vào `unsupported_claims` và bị flag (không âm thầm xóa).
3. Trả về citation kèm **span gốc trong tài liệu** để người đọc bấm là kiểm được.

Trong README nói rõ: support check bằng overlap là proxy rẻ tiền; nếu có thời gian sẽ nâng lên NLI model hoặc LLM-judge (ghi vào mục "nếu có thêm thời gian").

### 3.8 FastAPI: API mỏng + luồng ingest có tiến trình

Endpoints:
```
POST /files            — upload file (multipart: .md, .txt, tùy chọn .pdf)
GET  /files            — danh sách file: tên, status, số chunk, lỗi nếu có
GET  /ingest/progress  — {status, files_total, files_done,
                          chunks_done, chunks_total, percent}
POST /ask              — {question, top_k?, mode?} → {answer, citations[],
                          search_trace[], low_confidence, unsupported_claims[]}
GET  /chunks/{id}      — xem chunk gốc (phục vụ việc kiểm tra trích dẫn)
GET  /health
```

**Luồng ingest có tiến trình:**
- Upload lưu file vào `data/uploads/`, tạo bản ghi trong bảng `files` (SQLite): `(file_id, name, status, chunks_total, chunks_done, error)`. Corpus seed ở `data/docs/` cũng được đăng ký vào bảng này để UI hiển thị "đang có những file nào" thống nhất một chỗ.
- State machine mỗi file: `queued → parsing → chunking → embedding → ready` (hoặc `failed` + thông báo lỗi).
- Ingest chạy trong **worker nền 1 thread** (queue + thread) — cố tình 1 thread để tránh ghi SQLite đồng thời và để tiến trình deterministc. Sau mỗi batch embedding cập nhật `chunks_done` → UI đọc ra %.
- Status tổng = `ready` khi mọi file đã ready → UI bật chấm xanh, cho phép chat.
- `POST /ask` trả 503 khi index chưa ready — tránh trả lời với index dở dang (chi tiết nhỏ nhưng thể hiện kiểm soát chất lượng).
- Toàn bộ tương tác upload, xem tiến trình, cấu hình tích hợp LLM và hỏi đáp đều thông qua API và Web UI.

Chạy: `uvicorn chakra_rag.interfaces.api:app`. Logic nằm hết trong service/ingestion module, API không chứa nghiệp vụ. Thêm **CORS middleware** cho phép origin của dev server Vite (`http://localhost:5173`).

### 3.9 UI: Vite + React + TypeScript (phần bonus — làm sau cùng)

Mục tiêu: demo trực quan khả năng **grounding & trích dẫn** và luồng **upload → ingest → chat**, không phải làm sản phẩm. Vì đề nói rõ không kỳ vọng UI, phần này chỉ đáng làm khi pipeline đã xong và còn thời gian.

- **Stack**: Vite + React 18 + TypeScript, không UI framework nặng (CSS thuần hoặc Tailwind tùy chọn). Giữ tối giản: 1 màn hình duy nhất.
- **Layout 2 cột**:
  - Cột trái, từ trên xuống:
    1. **Khu tài liệu**: nút upload (kéo-thả hoặc chọn file `.md/.txt`), danh sách file đang có trong index (tên + trạng thái từng file).
    2. **Thanh tiến trình ingest**: phần trăm embedding (poll `GET /ingest/progress` mỗi 1–2s khi đang chạy). Khi toàn bộ file `ready` → **chấm xanh "Sẵn sàng"** và ô chat được bật; khi chưa xong thì ô chat disable kèm nhãn "Đang xử lý tài liệu…".
    3. **Ô hỏi + lịch sử hỏi đáp**: mỗi câu trả lời render markdown nhẹ, các citation `[1]`, `[2]` là chip bấm được. Bên dưới câu trả lời hiển thị **search trace** (từ `search_trace` của `/ask`): "🔍 Agent đã tìm kiếm 2 lần: 'mức hoàn phí tối đa' (3 kết quả) → 'điều kiện hoàn phí' (2 kết quả)" — người xem thấy trực tiếp agent gọi tool như thế nào.
  - Cột phải: panel "Nguồn trích dẫn" — click chip nào thì hiển thị chunk gốc tương ứng (doc, section, span text), highlight phần liên quan. Đây chính là tính năng "ăn điểm": người xem kiểm chứng được trích dẫn trỏ về đúng đoạn tài liệu.
  - Badge cảnh báo khi `low_confidence=true` hoặc `unsupported_claims` khác rỗng (ví dụ: "Câu trả lời có phần chưa được nguồn đỡ").
- **Gọi API**: `fetch` thuần (không cần axios) tới `POST /files`, `GET /ingest/progress`, `POST /ask`, `GET /chunks/{id}`; dev proxy trong `vite.config.ts` trỏ `/api` → `localhost:8000` để khỏi lo CORS khi dev. Polling đơn giản bằng `setInterval` — không cần WebSocket cho quy mô này.
- **Không làm**: auth phức tạp, routing nhiều trang, deploy cloud. Tập trung tối đa vào trải nghiệm Web UI + API phục vụ bài toán RAG.

### 3.10 Chọn framework: dùng LangChain + LangGraph; observability qua LangSmith (tùy chọn)

**Quyết định cuối cùng**: dùng LangChain + LangGraph để code gọn; observability bằng **LangSmith** khi operator bật (env `LANGSMITH_TRACING`/`LANGSMITH_API_KEY`), mặc định chạy hoàn toàn local không gửi gì. Nguyên tắc xuyên suốt: framework lo phần cơ khí (vòng lặp tool-calling, parse message, prompt template, tracing), **nghiệp vụ chấm điểm phải tự viết** (hybrid retrieval, RRF, citation verifier) — đây là phần thể hiện năng lực và là thứ bị hỏi xoáy khi phỏng vấn.

**Trade-off của LangSmith:** khi bật, trace/feedback được gửi lên SaaS ngoài (LangSmith) — chấp nhận được cho bài này và hữu ích để phân tích chất lượng; không bật thì không có gì rời khỏi máy. `scripts/export_eval_dataset.py` biến production runs thành dataset đánh giá.

**Dùng gì của LangChain/LangGraph, và vì sao:**

| Thành phần | Dùng | Lý do |
|---|---|---|
| `langgraph.prebuilt.create_react_agent` | ✅ | Thay vòng lặp tool-calling tự viết; parse `tool_calls`, nối message, giới hạn `recursion_limit` có sẵn. Đây là lý do chính để chọn LangGraph. |
| `langchain_core.tools.@tool` | ✅ | Khai báo `search_docs` từ 1 hàm Python — schema sinh tự động, gọn hơn viết JSON schema tay. |
| `langchain_openai.ChatOpenAI` | ✅ | Chat model + function calling qua `base_url` cấu hình được (OpenAI/OpenRouter/compatible). |
| `langchain_text_splitters` | ✅ | `MarkdownHeaderTextSplitter` + `RecursiveCharacterTextSplitter` cho chunking theo cấu trúc — chuẩn, ít code, dễ giải thích tham số. |
| Vector store abstraction của LangChain | ❌ | sqlite-vec không phải store first-class; hybrid retrieval + RRF là phần tự viết — giữ `store.py`/`retrieve.py` thuần Python để kiểm soát và giải thích được. |
| **LangSmith** | ✅ | Tracing qua env `LANGSMITH_API_KEY`/`LANGSMITH_TRACING`; `observability/tracing.py` cung cấp client factory lazy (warn-once khi thiếu key), metadata per-invocation và submit feedback scores (invalid_citations/unsupported_claims/low_confidence) lên root run. Không cấu hình → no-op an toàn. |

**Tracing + feedback qua LangSmith** (`observability/tracing.py`): mỗi lần `ask`/`ask_stream` chạy trong một trace (metadata: conversation_id/mode/streamed, tags: sync/stream); `Retriever.search` và tool `search_docs` được decorate `@traceable` tạo child spans; cuối lượt service submit 3 feedback scores lên root run: `invalid_citations` (số cite sai), `unsupported_claims` (số claim thiếu đỡ), `low_confidence` (0/1). Không có `LANGSMITH_API_KEY`/`LANGSMITH_TRACING` thì toàn bộ là no-op an toàn (warn 1 lần nếu bật tracing mà thiếu key). Vẫn giữ `payload_json` trong SQLite cho UI replay lịch sử hội thoại.

**Hạn chế đã biết:** mode `stuff` (fallback/ablation, đi qua `RagAgent.ask_stuff`) không thread trace config nên trace của nó thiếu metadata conversation/mode/streamed. Chỉ ảnh hưởng đường fallback/stuff; agent-mode (`ask_agent`/`stream_agent`) mang đủ metadata. Cố tình không wiring thêm code — chấp nhận vì stuff chỉ là fallback khi model không tool-call.

**Lưu ý bắt buộc khi dùng framework cho bài test này:**
- **Pin version** trong `requirements.txt` (họ LangChain đổi API liên tục) — ghi rõ version đã test.
- Đề yêu cầu *giải thích được mọi quyết định và mã nguồn* → phải nắm được những gì diễn ra **bên trong** `create_react_agent`: nó là graph 2 node (model → tools) lặp cho đến khi AIMessage không còn `tool_calls`; `recursion_limit` đếm số bước graph (mỗi lượt tool = 2 bước). Không nắm được điều này thì dùng framework thành điểm trừ.
- Nếu bị hỏi "sao không viết vòng lặp 20 dòng thuần SDK?" — câu trả lời: chọn LangGraph vì mở rộng sau này (thêm tool, checkpoint, human-in-the-loop) không phải viết lại; với 1 tool thì cả hai cách đều đúng, nhưng framework cho interface message chuẩn để trích `search_trace` và bằng chứng citation.

**Stack cuối cùng:**
- `langchain-core`, `langchain-openai`, `langchain-text-splitters`, `langgraph` — agent + chunking + LLM.
- `sqlite-vec` — vector store (tự viết lớp truy cập).
- `sentence-transformers` — embedding local, không cần key.
- `fastapi` + `uvicorn` — API.
- `pypdf` (tùy chọn) — nhận thêm PDF; mặc định chỉ `.md/.txt`.

## 4. Chiến lược chống hallucination (phần phải viết trong bài nộp)

Phòng thủ nhiều lớp:
1. **Retrieval gate** — không đủ bằng chứng thì không trả lời.
2. **Prompt ràng buộc** + temperature 0 — giảm sinh tự do.
3. **Citation bắt buộc + hậu kiểm** — verifier chỉ chấp nhận chunk_id nằm trong tập tool thực sự trả về trong phiên (bịa nguồn bị bắt ngay); claim không được chunk đỡ sẽ bị flag.
4. Trung thực về giới hạn: overlap-based support check là proxy, không phải NLI — ghi rõ trong README.

## 5. Cấu trúc thư mục

```
chakra_rag/
├── README.md                 # cách chạy, quyết định thiết kế, giả định, hướng mở rộng
├── DESIGN.md                 # file này
├── requirements.txt          # langchain-core/openai/text-splitters, langgraph, sqlite-vec,
│                             # sentence-transformers, fastapi, uvicorn, numpy (pin version)
├── .env.example              # LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, DB_PATH...
├── data/docs/*.md            # corpus seed (được đăng ký vào bảng files như file thường)
├── data/uploads/             # file người dùng upload qua UI
├── logs/                    # logs ứng dụng
├── src/chakra_rag/           # tổ chức theo tầng, dependency một chiều từ ngoài vào trong
│   ├── config.py             # đọc env, dataclass Config
│   ├── core/                 # nghiệp vụ lõi, không phụ thuộc framework
│   │   ├── chunking.py       #   dùng langchain_text_splitters
│   │   ├── embedding.py      #   sentence-transformers, chuẩn hóa L2
│   │   ├── retrieval.py      #   vector, fts, RRF, threshold (tự viết — phần chấm điểm)
│   │   ├── agent.py          #   LangGraph create_react_agent + fallback stuff
│   │   └── verification.py   #   citation verification (tự viết — phần chấm điểm)
│   ├── storage/store.py      # sqlite + vec0 + FTS5 + bảng files
│   ├── ingestion/worker.py   # worker nền: parse → chunk → embed, cập nhật tiến trình
│   ├── observability/tracing.py  # langsmith client factory, trace metadata, submit feedback
│   ├── observability/timing.py   # timed()/elapsed_ms() đo latency
│   ├── service/rag_service.py      # composition root: ask(question) -> Answer
│   └── interfaces/           # các lối vào, không chứa nghiệp vụ
│       └── api.py            #   FastAPI mỏng + CORS + endpoints files/progress/integrations
├── tests/test_smoke.py       # chunking + store + retrieve + verify chạy không cần LLM
└── ui/                       # BONUS — Vite + React + TS, tổ chức theo feature
    ├── package.json
    ├── vite.config.ts        # proxy /api → localhost:8000
    ├── index.html
    └── src/
        ├── main.tsx
        ├── app/App.tsx       # layout 2 cột: tài liệu+chat | panel nguồn
        ├── api/client.ts     # mọi fetch: /files, /ingest/progress, /ask, /chunks/{id}
        ├── api/types.ts      # type TS khớp response schema của API
        ├── hooks/useIngestStatus.ts  # poll danh sách file + tiến trình
        └── components/
            ├── documents/FilePanel.tsx   # upload + danh sách file + tiến trình % + chấm xanh
            ├── chat/AskBox.tsx
            ├── chat/AnswerCard.tsx       # render answer + citation chips + search trace
            └── sources/SourcePanel.tsx   # hiển thị chunk gốc khi click citation
```

## 6. Kế hoạch làm trong 48h (có buffer)

Nguyên tắc: **phần lõi xong trước, UI làm sau cùng**. Nếu chậm tiến độ, cắt UI đầu tiên — đề không yêu cầu.

| Bước | Nội dung | ~Thời gian |
|---|---|---|
| 1 | Corpus demo + scaffold project + requirements | 2h |
| 2 | chunking + embed + store (sqlite-vec, FTS5) + ingest worker | 4h |
| 3 | retrieve hybrid + RRF + threshold | 3h |
| 4 | agent loop (tool calling) + citation verification | 5h |
| 5 | FastAPI + CORS + ingest worker nền có tiến trình + smoke tests | 3h |
| 6 | UI Vite + React + TS (upload, tiến trình %, chấm xanh, citation chip, source panel) | 5h |
| 7 | README: cách chạy, quyết định, giả định, "nếu có thêm thời gian" | 3h |
| 8 | Buffer / rà soát lại toàn bộ, chạy sạch từ đầu | 4h+ |

## 7. Giả định & rủi ro

**Giả định** (ghi vào README bài nộp):
- Corpus demo tự soạn, tiếng Việt, quy mô vài chục chunk — đủ chứng minh pipeline; với corpus lớn sẽ phải tính lại chunk size, thêm reranker/ANN.
- LLM qua API OpenAI-compatible; người chấm cần 1 API key (hoặc trỏ vào Ollama local).
- Tài liệu đầu vào dạng text/markdown sạch (không xử lý PDF scan, bảng biểu phức tạp).

**Rủi ro kỹ thuật & cách xử lý:**
- sqlite-vec cần load extension → dùng package `sqlite-vec` chính chủ (bundle wheel Linux x64), gói gọn trong `store.py`, có test smoke để phát hiện sớm.
- FTS5 tokenizer không tách từ tiếng Việt → chấp nhận ở mức exact-term, ghi vào hạn chế; hướng mở rộng: tiền xử lý bằng `underthesea`.
- LLM trả lời sai format JSON → parse có fallback (regex kéo JSON), retry 1 lần; fail nữa thì trả về raw + cờ lỗi.
- Model không hỗ trợ function calling tốt (nhất là model local nhỏ) → giữ fallback `mode=stuff` (retrieve trước, nhét context vào prompt) để hệ thống vẫn chạy; mặc định dùng model có tool calling.
- Agent loop không hội tụ (gọi tool liên tục) → giới hạn `max_turns=4`, quá lượt thì ép chốt dựa trên bằng chứng tốt nhất đã thu thập, kèm cờ cảnh báo.

## 8. Nếu có thêm thời gian (ghi vào bài nộp)

- Reranker cross-encoder (đặc biệt hiệu quả với corpus nhỏ).
- Support check nâng cấp: NLI model hoặc LLM-judge từng claim thay vì n-gram overlap.
- Semantic chunking + chunk hierarchy (parent-document retrieval).
- Agent đa tool: thêm `list_documents`, `read_chunk` bên cạnh `search_docs` để agent tự điều hướng khi corpus lớn (hiện tại 1 tool là đủ cho corpus nhỏ) — LangGraph mở rộng việc này tự nhiên.
- LangSmith: tracing + feedback scores đã tích hợp sẵn (bật qua `LANGSMITH_TRACING`/`LANGSMITH_API_KEY`); có thể mở rộng thêm eval dataset từ production traces (scripts/export_eval_dataset.py) và so sánh prompt tập trung khi làm việc theo team.
