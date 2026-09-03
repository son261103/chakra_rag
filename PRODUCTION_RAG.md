# Kiến trúc & Vận hành RAG trong Thực tế (Production RAG Architecture)

Tài liệu này tổng hợp toàn diện cách các hệ thống RAG thực tế trong doanh nghiệp và sản phẩm quy mô lớn (Fintech, EdTech, LegalTech, Enterprise Search) được thiết kế và vận hành. Khác với các bản PoC hay Take-Home tập trung vào việc chạy được luồng cơ bản, hệ thống Production được xây dựng như một **phễu xử lý đa tầng (Multi-Stage Processing Funnel)** để giải quyết triệt để các vấn đề: dữ liệu bẩn, truy xuất trượt từ khóa/ngữ nghĩa, ảo giác (hallucination), độ trễ (latency), chi phí và bảo mật dữ liệu.

---

## 1. Sơ đồ Kiến trúc Tổng thể (The Production RAG Funnel)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                          INGESTION & INDEXING PIPELINE (OFFLINE / ASYNC)               │
└────────────────────────────────────────────────────────────────────────────────────────┘
  Tài liệu đa định dạng (PDF scan, Word, Excel, Confluence, GDrive, Notion, SQL...)
                            │
                            ▼
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │ 1. ADVANCED PARSING & EXTRACTION                                                 │
  │    • Layout Analysis & OCR (Docling / Unstructured / Azure Document Intelligence)│
  │    • Bảng biểu ➔ Markdown / HTML Table (giữ quan hệ hàng - cột)                  │
  │    • Loại bỏ boilerplate: header, footer, số trang thừa                          │
  └──────────────────────────────────────────────────────────────────────────────────┘
                            │
                            ▼
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │ 2. CHUNKING & ENRICHMENT                                                         │
  │    • Small-to-Big (Parent-Child): Child chunk (embed) ➔ Parent chunk (context)   │
  │    • Contextual Retrieval (Anthropic): Bổ sung ngữ cảnh tài liệu vào từng chunk   │
  │    • Metadata Tagging: document_id, section, department, access_level, updated_at│
  │    • Chunk Hashing (MD5): Hỗ trợ Incremental Sync (chỉ embed phần thay đổi)      │
  └──────────────────────────────────────────────────────────────────────────────────┘
                            │
                            ▼
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │ 3. HYBRID VECTOR & SEARCH STORAGE                                                │
  │    • Dense Vector Store: Qdrant / Milvus / pgvector (BGE-M3, Text-Embedding-3)   │
  │    • Sparse / Lexical Index: OpenSearch / Elasticsearch (BM25 + Tách từ TV)      │
  └──────────────────────────────────────────────────────────────────────────────────┘

──────────────────────────────────────────────────────────────────────────────────────────

┌────────────────────────────────────────────────────────────────────────────────────────┐
│                           QUERY & SERVING PIPELINE (ONLINE / SYNC)                     │
└────────────────────────────────────────────────────────────────────────────────────────┘
  Câu hỏi người dùng (kèm lịch sử hội thoại nếu có)
                            │
                            ▼
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │ 4. PRE-RETRIEVAL (TIỀN XỬ LÝ TRUY VẤN)                                           │
  │    • Query Condensation: Viết lại câu hỏi nối tiếp thành câu hỏi độc lập đủ nghĩa│
  │    • Semantic Router: Phân luồng (RAG tài liệu vs. Text-to-SQL vs. Direct Chat)   │
  │    • Query Decomposition: Tách câu hỏi multi-hop phức tạp thành các sub-queries  │
  │    • HyDE (tùy chọn): Sinh tài liệu giả định để tìm kiếm theo ngữ nghĩa gần nhất  │
  └──────────────────────────────────────────────────────────────────────────────────┘
                            │
                            ▼
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │ 5. MULTI-STAGE RETRIEVAL FUNNEL (PHỄU TRUY XUẤT 4 TẦNG)                          │
  │    ┌────────────────────────────────────────────────────────────────────────┐    │
  │    │ Stage 1: Broad Retrieval (Top 50-100)                                  │    │
  │    │ Dense Vector KNN + Sparse BM25 (có Vietnamese Word Segmentation)       │    │
  │    └──────────────────────────────────┬─────────────────────────────────────┘    │
  │                                       ▼                                          │
  │    ┌────────────────────────────────────────────────────────────────────────┐    │
  │    │ Stage 2: Fusion                                                        │    │
  │    │ Reciprocal Rank Fusion (RRF) hoặc Relative Score Fusion                │    │
  │    └──────────────────────────────────┬─────────────────────────────────────┘    │
  │                                       ▼                                          │
  │    ┌────────────────────────────────────────────────────────────────────────┐    │
  │    │ Stage 3: Cross-Encoder Reranking (Lọc còn Top 3-5)                     │    │
  │    │ BGE-Reranker-v2 / Cohere Rerank / FlashRank (so khớp toàn diện Q & P)  │    │
  │    └──────────────────────────────────┬─────────────────────────────────────┘    │
  │                                       ▼                                          │
  │    ┌────────────────────────────────────────────────────────────────────────┐    │
  │    │ Stage 4: Context Packing & Parent Resolution                           │    │
  │    │ Map Child Chunk ➔ Parent Chunk, xếp tài liệu quan trọng lên đầu/cuối   │    │
  │    └────────────────────────────────────────────────────────────────────────┘    │
  └──────────────────────────────────────────────────────────────────────────────────┘
                            │
                            ▼
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │ 6. GENERATION & AGENTIC WORKFLOW                                                 │
  │    • Corrective RAG (CRAG) / Self-RAG: Đánh giá tài liệu có đủ trả lời không    │
  │    • Generation: LLM suy luận, trích xuất thông tin, bắt buộc gắn trích dẫn cụ thể│
  └──────────────────────────────────────────────────────────────────────────────────┘
                            │
                            ▼
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │ 7. POST-GENERATION GUARDRAILS & VERIFICATION                                     │
  │    • Citation Check: Khẳng định có khớp với đoạn trích dẫn không?                │
  │    • Entailment & Negation Check (NLI / LLM Judge): Bắt lỗi đảo ngược phủ định   │
  │    • PII Masking: Ẩn thông tin nhạy cảm (CCCD, SĐT, số tài khoản)                │
  └──────────────────────────────────────────────────────────────────────────────────┘
                            │
                            ▼
  Câu trả lời hoàn chỉnh + Trích dẫn minh bạch (Document, Page, Chunk) + Telemetry
```

---

## 2. Bảng So Sánh: PoC / Take-Home vs. Thực Tế Production

| Tiêu chí | PoC / Dự án nhỏ / Take-Home | Thực tế Doanh nghiệp (Production) |
|---|---|---|
| **Định dạng dữ liệu** | `.md`, `.txt`, PDF text đơn giản (`pypdf`). | Đa định dạng: PDF scan 2 cột, bảng biểu Excel, Word phức tạp, Confluence, HTML... |
| **Bóc tách văn bản (Parsing)** | `file.read()` hoặc `split()`. Bỏ qua cấu trúc layout. | Layout-aware parsing (`Docling`, `Unstructured`), nhận diện bảng biểu, công thức, OCR. |
| **Chiến lược Chunking** | Cắt theo số ký tự/token cố định (vd: 300 token, overlap 50). | **Parent-Child Chunking** (Small-to-Big) và **Contextual Retrieval** (gắn tóm tắt vào chunk). |
| **Lưu trữ & Chỉ mục** | SQLite + sqlite-vec, ChromaDB chạy in-memory/file. | Cụm phân tán: **Qdrant / Milvus / pgvector** (vector) + **Elasticsearch / OpenSearch** (BM25). |
| **Xử lý tiếng Việt** | Dùng tokenizer mặc định của FTS5 (tách theo khoảng trắng). | **Word Segmentation** (`pyvi`, `underthesea`) để đánh chỉ mục từ ghép tiếng Việt chính xác. |
| **Xử lý câu hỏi (Pre-retrieval)**| Nhét trực tiếp câu hỏi người dùng vào tìm kiếm. | **Query Rewriting**, Condensation câu hỏi multi-turn, Semantic Routing, Query Decomposition. |
| **Phễu tìm kiếm (Retrieval)** | 1 lượt Vector Search hoặc Hybrid RRF lấy thẳng top-k. | **Multi-stage Funnel**: Kéo 50-100 ứng viên $\to$ RRF $\to$ **Cross-Encoder Reranker** lấy 3-5 đoạn tốt nhất. |
| **Kiểm tra trích dẫn** | Đếm từ trùng lặp (n-gram overlap) hoặc tin tưởng LLM. | Mô hình **NLI (Natural Language Inference)** hoặc **LLM-as-a-Judge** kiểm tra tính phụ thuộc logic. |
| **Cập nhật dữ liệu** | Xóa sạch database rồi ingest lại từ đầu. | **Incremental Ingestion**: Băm hash từng chunk, chỉ nhúng lại những đoạn văn bản có sửa đổi. |
| **Bảo mật & Quyền hạn** | Ai hỏi cũng tìm trên toàn bộ cơ sở dữ liệu. | **Role-Based Access Control (RBAC)**: Lọc theo metadata quyền hạn (`department`, `user_role`). |
| **Đo lường & Đánh giá** | Thử vài câu thủ công trên UI/CLI. | **CI/CD Eval tự động**: Chạy benchmark hàng tuần bằng Ragas/DeepEval (Faithfulness, Recall, Precision). |

---

## 3. Chi Tiết 6 Tầng Xử Lý Cốt Lõi

### Tầng 1: Advanced Ingestion & Parsing (Bóc tách Layout)
Trong thực tế, rác vào thì rác ra (*Garbage in, Garbage out*). 80% lỗi của RAG xuất phát từ việc bóc tách văn bản sai:
1. **Layout-aware Extraction**:
   - Sử dụng các thư viện phân tích bố cục chuyên sâu như `Docling` (IBM), `Unstructured.io` hoặc `LlamaParse`.
   - Nhận diện đúng thứ tự đọc của văn bản nhiều cột (tránh đọc hàng ngang cắt ngang 2 cột báo/tài liệu).
   - Tự động bỏ qua các thành phần lặp lại gây nhiễu: Header, Footer, số trang.
2. **Xử lý Bảng biểu (Tables)**:
   - Nếu cắt đôi một bảng biểu, vector search sẽ không bao giờ hiểu được quan hệ giữa các cột.
   - Production parse bảng biểu thành định dạng **Markdown Table** hoặc **HTML Table**, giữ nguyên cấu trúc dòng - cột để đưa vào context.
3. **OCR cho PDF Scan / Ảnh**:
   - Tích hợp OCR engine (`Surya`, `PaddleOCR` hoặc Cloud OCR) tự động kích hoạt khi phát hiện PDF không có text layer.

---

### Tầng 2: Chunking & Indexing Nâng Cao

#### 1. Kỹ thuật Small-to-Big (Parent-Child Retrieval)
- **Vấn đề cốt lõi**:
  - Chunk nhỏ (100–200 token): Rất tốt cho Vector Search vì vector tập trung vào một ý niệm ngữ nghĩa duy nhất, không bị loãng. Nhưng khi gửi cho LLM thì thiếu ngữ cảnh, câu trả lời bị cụt.
  - Chunk lớn (800–1200 token): Đủ ngữ cảnh cho LLM nhưng Vector Search lại kém chính xác vì vector bị pha loãng giữa nhiều ý khác nhau.
- **Giải pháp**:
  - Chia tài liệu thành các **Child Chunks** nhỏ (150 token).
  - Mỗi Child Chunk lưu ID tham chiếu tới **Parent Chunk** (500–800 token hoặc toàn bộ Section).
  - Đánh chỉ mục và tính embedding trên Child Chunk.
  - Khi tìm kiếm trúng Child Chunk, hệ thống lấy Parent Chunk đưa vào prompt cho LLM.

#### 2. Kỹ thuật Contextual Retrieval (Chuẩn hóa bởi Anthropic)
- **Vấn đề**: Khi cắt rời một đoạn văn bản:
  > *"Doanh thu quý này tăng 15% so với cùng kỳ năm trước nhờ mảng phần mềm."*
  Đoạn này hoàn toàn không chứa tên công ty, không chứa năm nào, khiến tìm kiếm ngữ nghĩa thất bại nếu user hỏi: *"Doanh thu năm 2024 của công ty X"*.
- **Giải pháp**:
  - Dùng một LLM nhẹ tóm tắt vị trí và bối cảnh tài liệu thành 1–2 câu ngắn gắn vào đầu mỗi chunk trước khi embed:
  > *"[Ngữ cảnh: Trích từ Báo cáo tài chính năm 2024 của Tập đoàn X, phần Kết quả hoạt động kinh doanh quý 3] Doanh thu quý này tăng 15% so với cùng kỳ năm trước nhờ mảng phần mềm."*
  - Nghiên cứu của Anthropic cho thấy kỹ thuật này kết hợp BM25 làm giảm tới 49% tỷ lệ tìm kiếm thất bại.

#### 3. Cập nhật gia tăng (Incremental Ingestion & Chunk Hashing)
- Mỗi chunk được tính mã băm: `chunk_hash = sha256(chunk_text + metadata)`.
- Khi tài liệu được cập nhật:
  - So sánh danh sách hash mới với danh sách trong DB.
  - Chunk nào giữ nguyên $\to$ không tính toán lại.
  - Chunk nào thay đổi $\to$ xóa chunk cũ, sinh embedding mới và nạp vào DB.
  - Tiết kiệm 90% chi phí embedding và thời gian indexing.

---

### Tầng 3: Pre-Retrieval (Xử lý Truy Vấn Trước Khi Tìm Kiếm)

Người dùng thực tế hiếm khi gõ một câu truy vấn hoàn hảo. Hệ thống cần "dọn dẹp" và định hướng câu hỏi trước:

#### 1. Query Condensation / Rewriting (Multi-turn Context)
Khi người dùng chat nhiều lượt:
- *Lượt 1*: "Mức hoàn phí đào tạo tối đa là bao nhiêu?"
- *Lượt 2*: "Thế nếu làm việc dưới 2 năm thì sao?"
- Nếu mang nguyên câu ở Lượt 2 đi tìm kiếm, hệ thống sẽ thất bại.
- **Xử lý**: Một LLM nhỏ (hoặc prompt hệ thống) tổng hợp ngữ cảnh để viết lại thành:
  > *"Mức hoàn phí đào tạo tối đa cho nhân viên làm việc dưới 2 năm là bao nhiêu?"*

#### 2. Semantic Router (Phân luồng truy vấn)
Không phải câu hỏi nào cũng cần chạy RAG:
- *"Chào bạn, bạn là ai?"* $\to$ Direct LLM (trả lời ngay, không tốn tài nguyên tìm kiếm).
- *"Doanh số tháng 10 của nhân viên A là bao nhiêu?"* $\to$ Text-to-SQL (truy vấn database cấu trúc, không dùng tài liệu text).
- *"Quy định về thời hạn nộp hồ sơ xin nghỉ phép?"* $\to$ RAG Pipeline (truy xuất tài liệu chính sách).
- *"Hôm nay thời tiết Hà Nội thế nào?"* $\to$ Web Search tool.

#### 3. Query Decomposition (Tách câu hỏi phức tạp)
- Câu hỏi: *"So sánh chính sách nghỉ ốm đau giữa nhân viên chính thức và nhân viên thử việc?"*
- Tách thành 2 truy vấn con độc lập:
  - Query A: *"Chính sách nghỉ ốm đau của nhân viên chính thức"*
  - Query B: *"Chính sách nghỉ ốm đau của nhân viên thử việc"*
- Chạy song song 2 query, gộp kết quả tài liệu lại trước khi trả lời.

---

### Tầng 4: Multi-Stage Retrieval & Reranking Funnel

Đây là "trái tim" của hệ thống truy xuất thông tin hiện đại.

```
                  [Toàn bộ Cơ sở Dữ liệu]
                             │
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │ 1. Dense Vector Search   +   Sparse BM25 Search        │
  │    (Bắt nghĩa tương đồng)    (Bắt số hiệu, mã, từ khóa)│
  └──────────────────────────┬─────────────────────────────┘
                             │ Kéo ra Top 50 - 100 ứng viên
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │ 2. Fusion (Reciprocal Rank Fusion - RRF)                │
  │    Gộp thứ hạng hai danh sách không phụ thuộc scale điểm│
  └──────────────────────────┬─────────────────────────────┘
                             │ Top 30 ứng viên
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │ 3. Cross-Encoder Reranker                              │
  │    So khớp sâu toàn bộ ngữ nghĩa cặp (Query, Passage)  │
  └──────────────────────────┬─────────────────────────────┘
                             │ Lọc ra Top 3 - 5 đoạn tốt nhất
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │ 4. Context Packing & Reordering                        │
  │    Xếp đoạn quan trọng nhất lên đầu và cuối prompt     │
  └────────────────────────────────────────────────────────┘
```

#### Vì sao Reranker là bắt buộc trong Production?
- **Bi-Encoder (Vector Embeddings)**: Tính vector cho Query và Document độc lập với nhau, sau đó chỉ so sánh bằng Cosine Similarity qua phép nhân vô hướng. Rất nhanh nhưng bị mất tương tác qua lại giữa từng từ.
- **Cross-Encoder (Reranker)**: Đưa đồng thời `(Query, Document)` vào cùng một mô hình transformer, áp dụng cơ chế Full Cross-Attention giữa mọi từ trong câu hỏi và tài liệu. Đo độ liên quan ngữ nghĩa chính xác hơn vượt trội, loại bỏ hoàn toàn các đoạn văn chỉ "trùng từ khóa bề ngoài" nhưng lạc đề.
- **Mô hình phổ biến**: `bge-reranker-v2-m3` (đa ngôn ngữ, tiếng Việt rất tốt), `Cohere Rerank v3`, `FlashRank` (cực nhẹ, chạy CPU).

#### Chống hiện tượng "Lost in the Middle"
Các nghiên cứu chỉ ra rằng LLM chú ý tốt nhất đến thông tin ở **đầu** và **cuối** của context, rất hay bỏ sót thông tin nằm ở giữa. Vì vậy, sau khi rerank, tài liệu thường được xếp theo thứ tự hình chữ U:
- Đoạn tốt nhất: Đặt ở đầu context.
- Đoạn tốt thứ nhì: Đặt ở cuối context.
- Các đoạn phụ: Đặt ở giữa.

---

### Tầng 5: Generation & Agentic Loops

Trong thực tế, mô hình tạo câu trả lời không thụ động mà hoạt động theo cơ chế phản xạ (Reflection):

1. **Corrective RAG (CRAG)**:
   - Sau khi truy xuất tài liệu, một bộ chấm điểm nhanh đánh giá:
     - **Tài liệu đủ và chính xác**: Tiến hành sinh câu trả lời.
     - **Tài liệu thiếu / mơ hồ**: Kích hoạt tìm kiếm bổ sung bằng từ khóa đồng nghĩa hoặc gọi Web Search.
     - **Tài liệu hoàn toàn không khớp**: Từ chối trả lời ngay lập tức (*"Tài liệu nội bộ không đề cập đến thông tin này"*), chặn đứng ảo giác sinh bừa.
2. **Structured Outputs & Trích dẫn bắt buộc**:
   - Yêu cầu LLM trả lời kèm trích dẫn định dạng JSON hoặc schema chuẩn, chỉ định rõ ràng từng câu khẳng định được hỗ trợ bởi chunk ID nào.

---

### Tầng 6: Post-Generation Guardrails & Verification

Hậu kiểm độc lập với LLM sinh câu trả lời, đảm bảo tính pháp lý và trung thực:

1. **Kiểm tra mức độ hỗ trợ (Entailment / Faithfulness Check)**:
   - Không dùng n-gram token overlap đơn giản vì n-gram không phát hiện được câu phủ định:
     - *Tài liệu*: "Không được phép sao chép dữ liệu."
     - *LLM viết*: "Được phép sao chép dữ liệu." (Token overlap đạt 95% nhưng nội dung trái ngược 100%).
   - Thay vào đó, dùng mô hình **Natural Language Inference (NLI)** hoặc **LLM-as-a-Judge** phân loại:
     - `Entailment` (Hỗ trợ logic): Chấp nhận.
     - `Contradiction` (Mâu thuẫn): Flag lỗi nghiêm trọng, chặn xuất ra người dùng.
     - `Neutral` (Không đủ cơ sở): Cảnh báo claim chưa được kiểm chứng.
2. **PII Masking (Bảo vệ thông tin định danh cá nhân)**:
   - Quét regex / NER trước khi trả kết quả về UI để ẩn các thông tin nhạy cảm: Số thẻ ngân hàng, CCCD/CMND, mật khẩu, API key.

---

## 4. Hạ Tầng, MLOps & Đánh Giá (Production Infrastructure)

### Cơ sở Dữ liệu & Tìm kiếm (Database Selection)
- **Vector DB chuyên dụng**:
  - **Qdrant**: Viết bằng Rust, hiệu năng cực cao, hỗ trợ payload filter (metadata) linh hoạt, hỗ trợ cả Dense và Sparse vectors.
  - **pgvector (PostgreSQL)**: Lựa chọn hàng đầu cho doanh nghiệp đã có hạ tầng Postgres, giữ trọn tính chất ACID và quan hệ bảng.
  - **Milvus**: Thích hợp cho quy mô cực lớn (hàng chục đến hàng trăm triệu vector).
- **Search Engine cho BM25**:
  - **OpenSearch / Elasticsearch**: Tích hợp các plugin phân tích tiếng Việt (như `elasticsearch-analysis-vietnamese`), xử lý stem/compound word chuyên nghiệp.

### Đánh giá tự động (RAG Evaluation Frameworks)
Trong doanh nghiệp, trước khi deploy một prompt mới hay đổi model embedding, toàn bộ hệ thống phải chạy qua bộ test benchmark tự động:
- **Công cụ**: `Ragas`, `DeepEval`, `Arize Phoenix`, `LangSmith`.
- **4 Chỉ số Vàng của RAG (The RAG Triad)**:
  1. **Faithfulness**: Câu trả lời có hoàn toàn dựa trên context không, hay có bịa đặt?
  2. **Answer Relevance**: Câu trả lời có đi đúng trọng tâm câu hỏi của người dùng không?
  3. **Context Precision**: Các đoạn văn bản tìm được có tỷ lệ liên quan cao không, có nhiều rác không?
  4. **Context Recall**: Hệ thống có lấy đủ mọi thông tin cần thiết trong kho dữ liệu để trả lời câu hỏi không?

---

## 5. Kế Hoạch Nâng Cấp Từng Bước Cho Project Hiện Tại (`chakra_rag`)

Từ codebase hiện tại của `chakra_rag`, bạn có thể nâng cấp theo lộ trình thực tế sau:

### Giai đoạn 1: Nâng cao độ chính xác truy xuất (Quick Wins - Làm ngay)
1. **Sửa lỗi tính offset ký tự trong `chunking.py`**:
   - Bỏ hàm `text.find(piece)` vốn luôn trả về vị trí đầu tiên, chuyển sang duyệt tuần tự hoặc dùng bộ chia có trả sẵn span offset.
2. **Thêm Reranker vào sau bước RRF trong `retrieval.py`**:
   - Tích hợp `FlashRank` (siêu nhẹ, không tốn GPU) hoặc `bge-reranker-v2-m3`. Lọc danh sách sau RRF từ top-10 xuống còn top-3 chất lượng nhất.
3. **Cải thiện tokenizer tiếng Việt cho FTS5**:
   - Sử dụng `underthesea` hoặc `pyvi` tách từ (`"chính sách"` $\to$ `"chính_sách"`) trước khi đưa vào FTS5, bỏ phép nối `OR` bừa bãi.

### Giai đoạn 2: Nâng cấp trải nghiệm hội thoại & Agent (Medium Term)
1. **Thêm module Query Condensation**:
   - Khi có `conversation_id`, trước khi gọi `search_docs`, viết lại câu hỏi dựa vào lịch sử để hỗ trợ hỏi đáp nhiều lượt mượt mà.
2. **Bổ sung công cụ cho Agent**:
   - Thêm tool `list_documents()` và tham số `doc_filter` vào `search_docs` để agent tự thu hẹp phạm vi tìm kiếm.
3. **Thay thế n-gram support check trong `verification.py`**:
   - Dùng prompt LLM mini dạng Judge để kiểm tra các claim phủ định thay cho công thức đếm từ trùng.

### Giai đoạn 3: Chuẩn hóa Production (Long Term)
1. **Áp dụng Small-to-Big Retrieval**:
   - Tách child chunks nhỏ để embed, lưu parent chunk vào SQLite để trả về cho LLM.
2. **Hỗ trợ trích xuất bảng biểu**:
   - Tích hợp thư viện parse PDF layout-aware (`docling` hoặc `pdfplumber`) để biến bảng trong tài liệu thành Markdown table.
3. **Thiết lập Benchmark Eval với Ragas**:
   - Tạo bộ 30 câu hỏi mẫu kèm ground-truth, đo lường điểm Faithfulness và Context Recall mỗi khi thay đổi code.
