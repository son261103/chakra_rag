import { useEffect, useState } from "react";
import { getChunk } from "../../api/client";
import type { ChunkDetail } from "../../api/types";

interface Props {
  chunkId: string | null;
  onClose: () => void;
}

/** Drawer trượt từ phải: hiển thị đoạn tài liệu gốc của citation. */
export default function SourceDrawer({ chunkId, onClose }: Props) {
  const [chunk, setChunk] = useState<ChunkDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!chunkId) {
      setChunk(null);
      return;
    }
    setError(null);
    getChunk(chunkId)
      .then(setChunk)
      .catch((e) => setError(String(e)));
  }, [chunkId]);

  if (!chunkId) return null;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer">
        <div className="drawer-header">
          <h3>Nguồn trích dẫn</h3>
          <button className="drawer-close" onClick={onClose}>✕</button>
        </div>

        {error && <div className="error-banner">{error}</div>}

        {chunk && (
          <div className="drawer-body">
            <div className="drawer-meta">
              <div className="meta-row">
                <span className="meta-label">File</span>
                <span>{chunk.doc}</span>
              </div>
              <div className="meta-row">
                <span className="meta-label">Mục</span>
                <span>{chunk.section}</span>
              </div>
              <div className="meta-row">
                <span className="meta-label">Chunk ID</span>
                <code>{chunk.chunk_id}</code>
              </div>
              <div className="meta-row">
                <span className="meta-label">Vị trí</span>
                <span>ký tự {chunk.char_start}–{chunk.char_end}</span>
              </div>
            </div>
            <blockquote className="drawer-text">{chunk.text}</blockquote>
          </div>
        )}
      </aside>
    </>
  );
}
