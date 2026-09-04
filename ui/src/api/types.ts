/** Type khớp response schema của backend FastAPI. */

export interface FileEntry {
  file_id: string;
  name: string;
  source: "seed" | "upload";
  status: "queued" | "parsing" | "chunking" | "embedding" | "ready" | "failed";
  chunks_total: number;
  chunks_done: number;
  error: string | null;
}

export interface IngestProgress {
  status: "empty" | "processing" | "ready" | "partial" | "failed";
  files_total: number;
  files_ready: number;
  chunks_total: number;
  chunks_done: number;
  percent: number;
}

export interface Citation {
  chunk_id: string;
  doc: string;
  section: string;
  text: string;
  score: number | null;
}

export interface SearchTraceEntry {
  query: string;
  n_results: number;
  chunk_ids: (string | null)[];
  max_score: number;
}

export interface AskResponse {
  question: string;
  answer: string;
  mode: "agent" | "stuff";
  citations: Citation[];
  invalid_citations: string[];
  unsupported_claims: string[];
  search_trace: SearchTraceEntry[];
  reasoning: string;
  low_confidence: boolean;
  latency_ms: number;
  conversation_id?: string | null;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  payload: AskResponse | null;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ConversationMessage[];
}

export interface ChunkDetail {
  id: number;
  chunk_id: string;
  doc: string;
  section: string;
  text: string;
  char_start: number;
  char_end: number;
}

export interface FileChunksResponse {
  file: FileEntry;
  chunks: ChunkDetail[];
  chunk_count: number;
  full_text?: string;
  full_text_chars?: number;
  full_text_error?: string | null;
}

/** Events từ POST /ask/stream (SSE). */
export type StreamEvent =
  | { type: "thinking"; delta: string }
  | { type: "tool_start"; name: string }
  | { type: "tool_call"; index: number; query: string; n_results: number; chunk_ids: (string | null)[]; max_score: number; chunks: Record<string, unknown>[] }
  | { type: "answer"; delta: string }
  | { type: "answer_clear" }
  | { type: "done" } & AskResponse
  | { type: "error"; message: string };

/** Cấu hình tích hợp LLM (model, provider, base_url, masked key). */
export interface IntegrationEntry {
  id: string;
  name: string;
  provider: string;
  base_url: string;
  model: string;
  masked_api_key: string;
  has_api_key: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateIntegrationPayload {
  name: string;
  provider?: string;
  base_url: string;
  model: string;
  api_key: string;
  is_active?: boolean;
}

export interface UpdateIntegrationPayload {
  name?: string;
  provider?: string;
  base_url?: string;
  model?: string;
  api_key?: string;
  is_active?: boolean;
}

export interface TestIntegrationPayload {
  model: string;
  base_url: string;
  api_key?: string;
  integration_id?: string;
}

export interface TestIntegrationResult {
  ok: boolean;
  model: string;
  response: string;
  latency_ms: number;
}
