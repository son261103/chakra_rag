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

/** Events từ POST /ask/stream (SSE). */
export type StreamEvent =
  | { type: "thinking"; delta: string }
  | { type: "tool_start"; name: string }
  | { type: "tool_call"; index: number; query: string; n_results: number; chunk_ids: (string | null)[]; max_score: number; chunks: Record<string, unknown>[] }
  | { type: "answer"; delta: string }
  | { type: "answer_clear" }
  | { type: "done" } & AskResponse
  | { type: "error"; message: string };
