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
  const [isDragging, setIsDragging] = useState(false);

  const processing = progress?.status === "processing";
  const totalChunks =
    progress?.chunks_total && progress.chunks_total > 0
      ? progress.chunks_total
      : files.reduce((acc, f) => acc + (f.chunks_done || 0), 0);
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

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!uploading && !busyFileId) {
      setIsDragging(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (uploading || busyFileId) return;
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      void handleFiles(e.dataTransfer.files);
    }
  };

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer file-drawer" role="dialog" aria-label="Quản lý tài liệu">
        <div className="drawer-header">
          <div className="flex items-center gap-2">
            <h3>Tài liệu</h3>
            {files.length > 0 && (
              <span className="rounded-full border border-border/60 bg-bg-elevated px-2 py-0.5 font-mono text-[11px] text-muted">
                {files.length}
              </span>
            )}
          </div>
          <button type="button" className="drawer-close" onClick={onClose} aria-label="Đóng">
            <X size={15} />
          </button>
        </div>

        <div className="drawer-body file-drawer-body">
          {/* Tiến trình xử lý (chỉ hiện khi đang embedding / indexing) */}
          {processing && progress && (
            <div className="rounded-xl border border-amber/30 bg-amber/5 p-3 text-xs">
              <div className="flex items-center justify-between font-medium">
                <span className="flex items-center gap-1.5 text-amber">
                  <Loader2 size={13} className="animate-spin" />
                  Đang xử lý tài liệu…
                </span>
                <span className="font-mono text-[11px] text-muted">
                  {progress.chunks_done}/{progress.chunks_total} chunks ({progress.percent}%)
                </span>
              </div>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-bg-elevated">
                <div
                  className="h-full bg-amber transition-all duration-300 ease-out"
                  style={{ width: `${progress.percent}%` }}
                />
              </div>
            </div>
          )}

          {/* Upload */}
          <div className="knowledge-actions">
            <button
              className={`upload-btn ${isDragging ? "border-accent bg-accent/10" : ""}`}
              onClick={() => inputRef.current?.click()}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              disabled={uploading || !!busyFileId}
              type="button"
            >
              {uploading ? (
                <Loader2 size={15} className="animate-spin text-accent" />
              ) : (
                <Plus size={15} />
              )}
              <span>{uploading ? "Đang tải lên…" : "Thêm tài liệu"}</span>
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

          {/* Danh sách tài liệu */}
          <div className="flex items-center justify-between px-1 pt-1 text-muted">
            <span className="block-label p-0">Tài liệu · {files.length}</span>
            {totalChunks > 0 && (
              <span className="font-mono text-[11px] text-muted/80">
                {totalChunks} chunks
              </span>
            )}
          </div>
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
                      <span className="file-meta quiet">{f.chunks_done} chunks</span>
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
            {files.length === 0 && (
              <li className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-8 text-center text-muted">
                <div className="text-[13px] font-medium text-text">Chưa có tài liệu</div>
                <div className="text-[11.5px] text-muted">
                  Bấm &quot;Thêm tài liệu&quot; hoặc kéo thả file vào đây để bắt đầu
                </div>
              </li>
            )}
          </ul>
        </div>
      </aside>
    </>
  );
}
