/** Gọi API backend qua dev proxy /api (xem vite.config.ts). */

import type {
  AskResponse,
  ChunkDetail,
  ConversationDetail,
  ConversationSummary,
  FileChunksResponse,
  FileEntry,
  IngestProgress,
  StreamEvent,
} from "./types";

const BASE = "/api";

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export async function listFiles(): Promise<FileEntry[]> {
  const data = await handle<{ files: FileEntry[] }>(await fetch(`${BASE}/files`));
  return data.files;
}

export async function getProgress(): Promise<IngestProgress> {
  return handle<IngestProgress>(await fetch(`${BASE}/ingest/progress`));
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

export async function ask(
  question: string,
  mode: "agent" | "stuff" = "agent",
  conversationId?: string | null
): Promise<AskResponse> {
  return handle<AskResponse>(
    await fetch(`${BASE}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        mode,
        conversation_id: conversationId ?? undefined,
      }),
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
  options?: { mode?: "agent" | "stuff"; conversationId?: string | null }
): Promise<void> {
  const mode = options?.mode ?? "agent";
  const conversationId = options?.conversationId ?? undefined;
  const controller = new AbortController();
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
        mode,
        conversation_id: conversationId,
      }),
      signal: controller.signal,
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new Error(`API ${res.status}: ${detail}`);
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
