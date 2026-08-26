import { useRef, useState } from "react";
import { AlertCircle, Check, Loader2, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { deleteFile, reingestFile, uploadFile } from "../../api/client";
import type { FileEntry, IngestProgress } from "../../api/types";

interface Props {
  open: boolean;
  onClose: () => void;
  files: FileEntry[];
  progress: IngestProgress | null;
  onUploaded: () => void;
  onInspectFile?: (file: FileEntry) => void;
}

function statusTitle(f: FileEntry): string {
  if (f.error) return `${f.name}\n${f.error}`;
  if (f.status === "ready") {
    return `${f.name}\n${f.chunks_done} chunks · sẵn sàng`;
  }
  if (f.status === "embedding") {
    return `${f.name}\nđang embedding ${f.chunks_done}/${f.chunks_total}`;
  }
  const label: Record<FileEntry["status"], string> = {
    queued: "chờ xử lý",
    parsing: "đang đọc file",
    chunking: "đang cắt đoạn",
    embedding: "đang embedding",
    ready: "sẵn sàng",
    failed: "lỗi",
  };
  return `${f.name}\n${label[f.status]}`;
}

/** Drawer quản lý tài liệu: upload, danh sách file, nhúng lại / xóa. */
export default function FileDrawer({ open, onClose, files, progress, onUploaded, onInspectFile }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [busyFileId, setBusyFileId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const ready = progress?.status === "ready" || progress?.status === "partial";
  const processing = progress?.status === "processing";

  if (!open) return null;

  const handleFiles = async (selected: FileList | null) => {
    if (!selected?.length) return;
    setUploading(true);
    setActionError(null);
    try {
      for (const file of Array.from(selected)) {
        await uploadFile(file);
      }
      onUploaded();
    } catch (e) {
      setActionError(String(e));
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const handleReingestOne = async (fileId: string) => {
    if (processing || busyFileId) return;
    setBusyFileId(fileId);
    setActionError(null);
    try {
      await reingestFile(fileId);
      onUploaded();
    } catch (e) {
      setActionError(String(e));
    } finally {
      setBusyFileId(null);
    }
  };

  const handleDeleteOne = async (fileId: string, name: string) => {
    if (processing || busyFileId) return;
    if (!window.confirm(`Xóa «${name}» khỏi index và đĩa?`)) return;
    setBusyFileId(fileId);
    setActionError(null);
    try {
      await deleteFile(fileId);
      onUploaded();
    } catch (e) {
      setActionError(String(e));
    } finally {
      setBusyFileId(null);
    }
  };

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer file-drawer" role="dialog" aria-label="Quản lý tài liệu">
        <div className="drawer-header">
          <h3>Tài liệu</h3>
          <button type="button" className="drawer-close" onClick={onClose} aria-label="Đóng">
            <X size={15} />
          </button>
        </div>

        <div className="drawer-body file-drawer-body">
          {/* Index status */}
          <div className={`index-row ${ready ? "ready" : processing ? "busy" : "idle"}`}>
            <span className="status-dot" />
            <div className="index-status-text">
              <strong>
                {ready ? "Index sẵn sàng" : processing ? "Đang xử lý tài liệu…" : "Chưa có dữ liệu"}
              </strong>
              {progress && progress.chunks_total > 0 ? (
                <span>
                  {progress.chunks_done}/{progress.chunks_total} chunks · {progress.percent}%
                </span>
              ) : (
                <span>Upload PDF / MD / TXT để bắt đầu</span>
              )}
            </div>
          </div>

          {processing && progress && (
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${progress.percent}%` }} />
            </div>
          )}

          {/* Upload */}
          <div className="knowledge-actions">
            <button
              className="upload-btn"
              onClick={() => inputRef.current?.click()}
              disabled={uploading || !!busyFileId}
              type="button"
            >
              <Plus size={15} />
              {uploading ? "Đang tải lên…" : "Thêm tài liệu"}
              <span className="upload-hint">.md · .txt · .pdf</span>
            </button>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".md,.txt,.pdf"
            multiple
            hidden
            onChange={(e) => handleFiles(e.target.files)}
          />

          {actionError && <div className="error-banner small">{actionError}</div>}

          {/* File list */}
          <div className="block-label file-drawer-label">Tài liệu · {files.length}</div>
          <ul className="file-list file-drawer-list side-scroll">
            {files.map((f) => {
              const busy = busyFileId === f.file_id;
              return (
                <li key={f.file_id} className={`file-item status-${f.status}`} title={statusTitle(f)}>
                  <button type="button" className="file-main" onClick={() => onInspectFile?.(f)}>
                    <span className="file-icon" aria-label={f.status}>
                      {f.status === "ready" ? (
                        <Check size={13} />
                      ) : f.status === "failed" ? (
                        <AlertCircle size={13} />
                      ) : (
                        <Loader2 size={13} className="animate-spin" />
                      )}
                    </span>
                    <span className="file-name">{f.name}</span>
                    {f.status === "embedding" && (
                      <span className="file-meta">
                        {f.chunks_done}/{f.chunks_total}
                      </span>
                    )}
                    {f.status === "ready" && f.chunks_done > 0 && (
                      <span className="file-meta quiet">{f.chunks_done}</span>
                    )}
                  </button>
                  <div className="file-actions">
                    <button
                      type="button"
                      className="file-action"
                      title="Nhúng lại file này"
                      disabled={processing || busy}
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleReingestOne(f.file_id);
                      }}
                    >
                      {busy ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                    </button>
                    <button
                      type="button"
                      className="file-action danger"
                      title="Xóa khỏi index và đĩa"
                      disabled={processing || busy}
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleDeleteOne(f.file_id, f.name);
                      }}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </li>
              );
            })}
            {files.length === 0 && <li className="file-empty">Chưa có tài liệu</li>}
          </ul>
        </div>
      </aside>
    </>
  );
}
