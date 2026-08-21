import { useRef, useState } from "react";
import { uploadFile } from "../../api/client";
import type { FileEntry, IngestProgress } from "../../api/types";

interface Props {
  files: FileEntry[];
  progress: IngestProgress | null;
  onUploaded: () => void;
}

const STATUS_LABEL: Record<FileEntry["status"], string> = {
  queued: "chờ xử lý",
  parsing: "đang đọc file",
  chunking: "đang cắt đoạn",
  embedding: "đang embedding",
  ready: "sẵn sàng",
  failed: "lỗi",
};

/** Sidebar trái kiểu ChatGPT: logo, trạng thái index, danh sách tài liệu, upload. */
export default function Sidebar({ files, progress, onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const ready = progress?.status === "ready" || progress?.status === "partial";
  const processing = progress?.status === "processing";

  const handleFiles = async (selected: FileList | null) => {
    if (!selected?.length) return;
    setUploading(true);
    setUploadError(null);
    try {
      for (const file of Array.from(selected)) {
        await uploadFile(file);
      }
      onUploaded();
    } catch (e) {
      setUploadError(String(e));
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="brand-logo">✦</span>
        <span className="brand-name">Chakra RAG</span>
      </div>

      <div className={`index-status ${ready ? "ready" : processing ? "busy" : "idle"}`}>
        <span className="status-dot" />
        <div className="index-status-text">
          <strong>{ready ? "Index sẵn sàng" : processing ? "Đang xử lý tài liệu…" : "Chưa có dữ liệu"}</strong>
          {progress && progress.chunks_total > 0 && (
            <span>
              {progress.chunks_done}/{progress.chunks_total} chunks · {progress.percent}%
            </span>
          )}
        </div>
      </div>

      {processing && progress && (
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${progress.percent}%` }} />
        </div>
      )}

      <button className="upload-btn" onClick={() => inputRef.current?.click()} disabled={uploading}>
        {uploading ? "Đang tải lên…" : "＋ Thêm tài liệu (.md, .txt)"}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".md,.txt"
        multiple
        hidden
        onChange={(e) => handleFiles(e.target.files)}
      />

      {uploadError && <div className="error-banner small">{uploadError}</div>}

      <div className="file-section">
        <div className="file-section-title">Tài liệu ({files.length})</div>
        <ul className="file-list">
          {files.map((f) => (
            <li key={f.file_id} className={`file-item status-${f.status}`} title={f.error ?? f.name}>
              <span className="file-icon">{f.status === "ready" ? "✓" : f.status === "failed" ? "✗" : "⋯"}</span>
              <span className="file-name">{f.name}</span>
              <span className="file-meta">
                {f.status === "embedding"
                  ? `${f.chunks_done}/${f.chunks_total}`
                  : STATUS_LABEL[f.status]}
              </span>
            </li>
          ))}
          {files.length === 0 && <li className="file-empty">Chưa có tài liệu nào</li>}
        </ul>
      </div>

      <div className="sidebar-footer">
        sqlite-vec · FTS5 · LangGraph agent
      </div>
    </aside>
  );
}
