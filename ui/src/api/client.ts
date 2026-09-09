/** Gọi API backend qua dev proxy /api (xem vite.config.ts). */

import type {
  ChunkDetail,
  ConversationDetail,
  ConversationSummary,
  CreateEmbeddingIntegrationPayload,
  CreateIntegrationPayload,
  EmbeddingIntegrationEntry,
  FileChunksResponse,
  FileEntry,
  IngestProgress,
  IntegrationEntry,
  StreamEvent,
  TestEmbeddingIntegrationPayload,
  TestEmbeddingIntegrationResult,
  TestIntegrationPayload,
  TestIntegrationResult,
  UpdateEmbeddingIntegrationPayload,
  UpdateIntegrationPayload,
} from "./types";

const BASE = "/api";

/** Lỗi HTTP có status + detail — UI cần phân biệt 409 dimension_mismatch. */
export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const raw = await res.text().catch(() => "");
    let msg = raw;
    let detail: unknown = null;
    try {
      const parsed = JSON.parse(raw);
      if (parsed.detail !== undefined) {
        detail = parsed.detail;
        msg = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
      }
    } catch {
      // giữ nguyên raw
    }
    throw new ApiError(msg || `${res.status}`, res.status, detail);
  }
  return res.json() as Promise<T>;
}

/** Snapshot ingest do backend đẩy qua SSE /ingest/events. */
export interface IngestSnapshot {
  files: FileEntry[];
  progress: IngestProgress;
}

/**
 * Đăng ký nhận snapshot ingest qua SSE — thay cho polling: backend chỉ đẩy
 * khi ingest thực sự đổi trạng thái. EventSource tự reconnect khi mất kết nối,
 * server gửi lại snapshot đầu ngay sau khi nối lại nên state tự phục hồi.
 * onError bắn khi mất kết nối (đang reconnect) để UI hiện cảnh báo.
 * Trả về hàm đóng để useEffect cleanup.
 */
export function subscribeIngest(
  onSnapshot: (data: IngestSnapshot) => void,
  onError?: () => void,
  onOpen?: () => void
): () => void {
  const es = new EventSource(`${BASE}/ingest/events`);
  es.onopen = () => onOpen?.();
  es.onmessage = (ev) => {
    try {
      onSnapshot(JSON.parse(ev.data) as IngestSnapshot);
    } catch {
      // bỏ qua event lỗi parse
    }
  };
  es.onerror = () => onError?.();
  return () => es.close();
}

export async function uploadFile(file: File): Promise<{ file_id: string }> {
  const form = new FormData();
  form.append("file", file);
  return handle<{ file_id: string }>(
    await fetch(`${BASE}/files`, { method: "POST", body: form })
  );
}

export async function reingestFile(
  fileId: string
): Promise<{ file_id: string; name: string; status: string }> {
  return handle<{ file_id: string; name: string; status: string }>(
    await fetch(`${BASE}/files/${encodeURIComponent(fileId)}/reingest`, {
      method: "POST",
    })
  );
}

export async function deleteFile(fileId: string): Promise<{
  file_id: string;
  name: string;
  chunks_removed: number;
  disk_removed: boolean;
}> {
  return handle(
    await fetch(`${BASE}/files/${encodeURIComponent(fileId)}`, {
      method: "DELETE",
    })
  );
}

export async function listConversations(): Promise<ConversationSummary[]> {
  const data = await handle<{ conversations: ConversationSummary[] }>(
    await fetch(`${BASE}/conversations`)
  );
  return data.conversations;
}

export async function createConversation(
  title = "Hội thoại mới"
): Promise<ConversationSummary> {
  return handle<ConversationSummary>(
    await fetch(`${BASE}/conversations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    })
  );
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  return handle<ConversationDetail>(
    await fetch(`${BASE}/conversations/${encodeURIComponent(id)}`)
  );
}

export async function deleteConversation(id: string): Promise<void> {
  await handle<{ ok: boolean }>(
    await fetch(`${BASE}/conversations/${encodeURIComponent(id)}`, {
      method: "DELETE",
    })
  );
}

/** Streaming version: gọi /ask/stream, parse SSE, gọi onEvent cho từng event.
 *
 * Có watchdog im-lặng: nếu quá ASK_INACTIVITY_MS mà không nhận thêm byte nào
 * (server treo, provider ngậm kết nối không đóng) thì chủ động abort — nếu
 * không UI sẽ kẹt mãi ở trạng thái "đang hỏi", không chat lại được. Ngưỡng
 * 100s an toàn vì backend đã có timeout LLM 90s: chậm nhất ~90s phải có event
 * (kể cả event lỗi) gửi về.
 */
const ASK_INACTIVITY_MS = 100_000;

export async function askStream(
  question: string,
  onEvent: (ev: StreamEvent) => void,
  options?: { conversationId?: string | null; signal?: AbortSignal }
): Promise<void> {
  const conversationId = options?.conversationId ?? undefined;
  const controller = new AbortController();

  if (options?.signal) {
    if (options.signal.aborted) {
      controller.abort();
    } else {
      options.signal.addEventListener("abort", () => controller.abort(), { once: true });
    }
  }

  let timer: number | undefined;
  const armWatchdog = () => {
    if (timer !== undefined) window.clearTimeout(timer);
    timer = window.setTimeout(() => controller.abort(), ASK_INACTIVITY_MS);
  };
  armWatchdog();
  try {
    const res = await fetch(`${BASE}/ask/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        conversation_id: conversationId,
      }),
      signal: controller.signal,
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new Error(detail.trim() || `${res.status}`);
    }
    const reader = res.body?.getReader();
    if (!reader) throw new Error("No response body");
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      armWatchdog();
      buffer += decoder.decode(value, { stream: true });
      // SSE: mỗi event là "data: {...}\n\n"
      const lines = buffer.split("\n\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        const dataLine = line.trim();
        if (!dataLine.startsWith("data: ")) continue;
        try {
          const ev = JSON.parse(dataLine.slice(6)) as StreamEvent;
          onEvent(ev);
        } catch {
          // bỏ qua dòng lỗi parse
        }
      }
    }
  } catch (e) {
    if (controller.signal.aborted) {
      throw new Error("Mất kết nối — server không phản hồi. Hãy thử hỏi lại.");
    }
    throw e;
  } finally {
    if (timer !== undefined) window.clearTimeout(timer);
  }
}

export async function getChunk(chunkId: string): Promise<ChunkDetail> {
  return handle<ChunkDetail>(
    await fetch(`${BASE}/chunks/${encodeURIComponent(chunkId)}`)
  );
}

/** Chunks đã ingest của 1 file (DocumentDrawer). */
export async function getFileChunks(fileId: string): Promise<FileChunksResponse> {
  return handle<FileChunksResponse>(
    await fetch(`${BASE}/files/${encodeURIComponent(fileId)}/chunks`)
  );
}

/** Quản lý tích hợp LLM */
export async function listIntegrations(): Promise<IntegrationEntry[]> {
  const data = await handle<{ integrations: IntegrationEntry[] }>(await fetch(`${BASE}/integrations`));
  return data.integrations;
}

export async function getActiveIntegration(): Promise<IntegrationEntry> {
  return handle<IntegrationEntry>(await fetch(`${BASE}/integrations/active`));
}

export async function createIntegration(payload: CreateIntegrationPayload): Promise<IntegrationEntry> {
  return handle<IntegrationEntry>(
    await fetch(`${BASE}/integrations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

export async function updateIntegration(
  id: string,
  payload: UpdateIntegrationPayload
): Promise<IntegrationEntry> {
  return handle<IntegrationEntry>(
    await fetch(`${BASE}/integrations/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

export async function deleteIntegration(id: string): Promise<void> {
  await handle<{ ok: boolean }>(
    await fetch(`${BASE}/integrations/${encodeURIComponent(id)}`, {
      method: "DELETE",
    })
  );
}

export async function activateIntegration(id: string): Promise<IntegrationEntry> {
  return handle<IntegrationEntry>(
    await fetch(`${BASE}/integrations/${encodeURIComponent(id)}/activate`, {
      method: "POST",
    })
  );
}

export async function testIntegration(payload: TestIntegrationPayload): Promise<TestIntegrationResult> {
  return handle<TestIntegrationResult>(
    await fetch(`${BASE}/integrations/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

/** Quản lý tích hợp Embedding (API + chiều vector). force=true = xác nhận reset index khi đổi chiều. */
export async function listEmbeddingIntegrations(): Promise<EmbeddingIntegrationEntry[]> {
  const data = await handle<{ integrations: EmbeddingIntegrationEntry[] }>(
    await fetch(`${BASE}/embedding-integrations`)
  );
  return data.integrations;
}

export async function getActiveEmbeddingIntegration(): Promise<EmbeddingIntegrationEntry> {
  return handle<EmbeddingIntegrationEntry>(await fetch(`${BASE}/embedding-integrations/active`));
}

export async function createEmbeddingIntegration(
  payload: CreateEmbeddingIntegrationPayload
): Promise<EmbeddingIntegrationEntry> {
  return handle<EmbeddingIntegrationEntry>(
    await fetch(`${BASE}/embedding-integrations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

export async function updateEmbeddingIntegration(
  id: string,
  payload: UpdateEmbeddingIntegrationPayload
): Promise<EmbeddingIntegrationEntry> {
  return handle<EmbeddingIntegrationEntry>(
    await fetch(`${BASE}/embedding-integrations/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

export async function deleteEmbeddingIntegration(id: string, force = false): Promise<void> {
  await handle<{ ok: boolean }>(
    await fetch(
      `${BASE}/embedding-integrations/${encodeURIComponent(id)}${force ? "?force=true" : ""}`,
      { method: "DELETE" }
    )
  );
}

export async function activateEmbeddingIntegration(
  id: string,
  force = false
): Promise<EmbeddingIntegrationEntry> {
  return handle<EmbeddingIntegrationEntry>(
    await fetch(
      `${BASE}/embedding-integrations/${encodeURIComponent(id)}/activate${force ? "?force=true" : ""}`,
      { method: "POST" }
    )
  );
}

export async function testEmbeddingIntegration(
  payload: TestEmbeddingIntegrationPayload
): Promise<TestEmbeddingIntegrationResult> {
  return handle<TestEmbeddingIntegrationResult>(
    await fetch(`${BASE}/embedding-integrations/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}
