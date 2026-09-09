import { useCallback, useEffect, useState } from "react";
import { subscribeIngest } from "../api/client";
import type { IngestSnapshot } from "../api/client";
import type { FileEntry, IngestProgress } from "../api/types";

/**
 * Trạng thái ingest thuần SSE — không poll: backend đẩy snapshot
 * {files, progress} ngay khi client nối vào và mỗi khi worker đổi trạng thái
 * (upload/reingest/delete/tiến trình embedding). Mất kết nối thì EventSource
 * tự reconnect và nhận lại snapshot đầu nên state tự phục hồi.
 */
export type ConnectionStatus = "connected" | "connecting" | "reconnecting";

export function useIngestStatus() {
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [progress, setProgress] = useState<IngestProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting");
  const [retryKey, setRetryKey] = useState(0);

  const apply = useCallback((data: IngestSnapshot) => {
    setFiles(data.files);
    setProgress(data.progress);
    setError(null);
    setConnectionStatus("connected");
  }, []);

  const handleOpen = useCallback(() => {
    setConnectionStatus("connected");
    setError(null);
  }, []);

  const handleError = useCallback(() => {
    setConnectionStatus("reconnecting");
    setError("Mất kết nối tới server — đang thử lại…");
  }, []);

  const retry = useCallback(() => {
    setConnectionStatus("connecting");
    setRetryKey((k) => k + 1);
  }, []);

  useEffect(
    () => subscribeIngest(apply, handleError, handleOpen),
    [apply, handleError, handleOpen, retryKey]
  );

  return { files, progress, error, connectionStatus, retry };
}
