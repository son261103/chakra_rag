/** Gọi API backend qua dev proxy /api (xem vite.config.ts). */

import type { AskResponse, ChunkDetail, FileEntry, IngestProgress, StreamEvent } from "./types";

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

export async function ask(
  question: string,
  mode: "agent" | "stuff" = "agent"
): Promise<AskResponse> {
  return handle<AskResponse>(
    await fetch(`${BASE}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, mode }),
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
  mode: "agent" | "stuff" = "agent"
): Promise<void> {
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
      body: JSON.stringify({ question, mode }),
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
