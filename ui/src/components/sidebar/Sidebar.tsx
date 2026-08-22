import { useRef, useState } from "react";
import { deleteFile, reingestFile, uploadFile } from "../../api/client";
import type { ConversationSummary, FileEntry, IngestProgress } from "../../api/types";

interface Props {
  files: FileEntry[];
  progress: IngestProgress | null;
  onUploaded: () => void;
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  onNewChat: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
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

/** Sidebar: brand → chat mới → panel kiến thức → hội thoại → footer. */
export default function Sidebar({
  files,
  progress,
  onUploaded,
  conversations,
  activeConversationId,
  onNewChat,
  onSelectConversation,
  onDeleteConversation,
  onInspectFile,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [busyFileId, setBusyFileId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const ready = progress?.status === "ready" || progress?.status === "partial";
  const processing = progress?.status === "processing";

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
    <aside className="sidebar">
      <div className="sidebar-top">
        <div className="sidebar-brand">
          <span className="brand-logo">✦</span>
          <span className="brand-name">Chakra RAG</span>
        </div>

        <button className="new-chat-btn" onClick={onNewChat} type="button">
          <span className="btn-plus" aria-hidden>
            +
          </span>
          Chat mới
        </button>
      </div>

      <section className="panel knowledge-panel">
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

        <div className="knowledge-actions">
          <button
            className="upload-btn"
            onClick={() => inputRef.current?.click()}
            disabled={uploading || !!busyFileId}
            type="button"
          >
            <span className="btn-plus" aria-hidden>
              +
            </span>
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

        <div className="panel-split" />

        <div className="block-label">Tài liệu · {files.length}</div>
        <ul className="file-list side-scroll">
          {files.map((f) => {
            const busy = busyFileId === f.file_id;
            return (
              <li key={f.file_id} className={`file-item status-${f.status}`} title={statusTitle(f)}>
                <button
                  type="button"
                  className="file-main"
                  onClick={() => onInspectFile?.(f)}
                >
                  <span className="file-icon" aria-label={f.status}>
                    {f.status === "ready" ? "✓" : f.status === "failed" ? "!" : "···"}
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
                    {busy ? "…" : "↻"}
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
                    ×
                  </button>
                </div>
              </li>
            );
          })}
          {files.length === 0 && <li className="file-empty">Chưa có tài liệu</li>}
        </ul>
      </section>

      <section className="panel chat-panel">
        <div className="block-label">Hội thoại · {conversations.length}</div>
        <ul className="chat-list side-scroll">
          {conversations.map((c) => (
            <li
              key={c.id}
              className={`chat-item ${c.id === activeConversationId ? "active" : ""}`}
            >
              <button
                type="button"
                className="chat-item-main"
                onClick={() => onSelectConversation(c.id)}
                title={c.title}
              >
                <span className="chat-item-title">{c.title}</span>
              </button>
              <button
                type="button"
                className="chat-item-delete"
                title="Xóa hội thoại"
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteConversation(c.id);
                }}
              >
                ×
              </button>
            </li>
          ))}
          {conversations.length === 0 && (
            <li className="file-empty">Chưa có hội thoại — bấm Chat mới</li>
          )}
        </ul>
      </section>

      <div className="sidebar-footer">sqlite-vec · FTS5 · LangGraph agent</div>
    </aside>
  );
}
