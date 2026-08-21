import { useCallback, useEffect, useState } from "react";
import { getProgress, listFiles } from "../api/client";
import type { FileEntry, IngestProgress } from "../api/types";

/**
 * Poll trạng thái ingest của backend: danh sách file + tiến trình embedding.
 * Poll 1s khi đang xử lý (cần cập nhật % liên tục), 15s khi đã sẵn sàng
 * (lúc đó ít có thay đổi; upload mới đã có refresh() gọi ngay sau khi bấm).
 */
export function useIngestStatus() {
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [progress, setProgress] = useState<IngestProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [f, p] = await Promise.all([listFiles(), getProgress()]);
      setFiles(f);
      setProgress(p);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    const processing = progress?.status === "processing" || progress?.status === "empty";
    const interval = setInterval(refresh, processing ? 1000 : 15000);
    refresh();
    return () => clearInterval(interval);
  }, [progress?.status, refresh]);

  const ready = progress?.status === "ready" || progress?.status === "partial";

  return { files, progress, ready, error, refresh };
}
