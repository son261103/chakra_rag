import { useEffect, useMemo, useState } from "react";
import { getFileChunks } from "../../api/client";
import type { ChunkDetail, FileChunksResponse, FileEntry } from "../../api/types";

interface Props {
  file: FileEntry | null;
  onClose: () => void;
}

const STATUS_LABEL: Record<FileEntry["status"], string> = {
  queued: "Chờ xử lý",
  parsing: "Đang đọc file",
  chunking: "Đang cắt đoạn",
  embedding: "Đang embedding",
  ready: "Sẵn sàng",
  failed: "Lỗi",
};

function preview(text: string, n = 160): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n)}…` : t;
}

/** Drawer phải: xem full text gốc + chunks đã ingest. */
export default function DocumentDrawer({ file, onClose }: Props) {
  const [data, setData] = useState<FileChunksResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<"full" | "chunks">("full");

  useEffect(() => {
    if (!file) {
      setData(null);
      setActiveId(null);
      setQuery("");
      setError(null);
      setTab("full");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    setActiveId(null);
    setQuery("");
    setTab("full");
    getFileChunks(file.file_id)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        if (res.chunks.length > 0) setActiveId(res.chunks[0].chunk_id);
        // Không có full text thì mở tab chunks
        if (!res.full_text) setTab("chunks");
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [file?.file_id]);

  const filtered = useMemo(() => {
    const chunks = data?.chunks ?? [];
    const q = query.trim().toLowerCase();
    if (!q) return chunks;
    return chunks.filter(
      (c) =>
        c.text.toLowerCase().includes(q) ||
        c.section.toLowerCase().includes(q) ||
        c.chunk_id.toLowerCase().includes(q)
    );
  }, [data, query]);

  const active: ChunkDetail | null = useMemo(() => {
    if (filtered.length === 0) return null;
    return filtered.find((c) => c.chunk_id === activeId) ?? filtered[0];
  }, [filtered, activeId]);

  if (!file) return null;

  const meta = data?.file ?? file;
  const fullText = data?.full_text ?? "";
  const fullChars = data?.full_text_chars ?? fullText.length;
  const chunkChars = data?.chunks.reduce((s, c) => s + c.text.length, 0) ?? 0;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer doc-drawer" role="dialog" aria-label="Chi tiết tài liệu">
        <div className="drawer-header">
          <div className="doc-drawer-heading">
            <span className="doc-drawer-kicker">Dữ liệu đã xử lý</span>
            <h3 title={meta.name}>{meta.name}</h3>
          </div>
          <button type="button" className="drawer-close" onClick={onClose} aria-label="Đóng">
            ✕
          </button>
        </div>

        <div className="doc-summary">
          <div className={`doc-pill status-${meta.status}`}>{STATUS_LABEL[meta.status]}</div>
          <div className="doc-stat">
            <span className="doc-stat-value">{data?.chunk_count ?? meta.chunks_done ?? 0}</span>
            <span className="doc-stat-label">chunks</span>
          </div>
          <div className="doc-stat">
            <span className="doc-stat-value">
              {fullChars > 0 ? `${(fullChars / 1000).toFixed(1)}k` : chunkChars > 0 ? `${(chunkChars / 1000).toFixed(1)}k` : "—"}
            </span>
            <span className="doc-stat-label">ký tự gốc</span>
          </div>
          <div className="doc-stat">
            <span className="doc-stat-value">{meta.source}</span>
            <span className="doc-stat-label">nguồn</span>
          </div>
        </div>

        <div className="doc-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            className={`doc-tab ${tab === "full" ? "active" : ""}`}
            aria-selected={tab === "full"}
            onClick={() => setTab("full")}
          >
            Toàn văn
            {fullChars > 0 && <span className="doc-tab-meta">{fullChars.toLocaleString()}</span>}
          </button>
          <button
            type="button"
            role="tab"
            className={`doc-tab ${tab === "chunks" ? "active" : ""}`}
            aria-selected={tab === "chunks"}
            onClick={() => setTab("chunks")}
          >
            Chunks
            <span className="doc-tab-meta">{data?.chunk_count ?? 0}</span>
          </button>
        </div>

        {meta.error && <div className="error-banner small doc-error">{meta.error}</div>}
        {error && <div className="error-banner small doc-error">{error}</div>}
        {data?.full_text_error && tab === "full" && (
          <div className="error-banner small doc-error">{data.full_text_error}</div>
        )}

        {loading && <div className="doc-loading">Đang tải dữ liệu…</div>}

        {!loading && data && tab === "full" && (
          <div className="doc-full-pane side-scroll">
            {fullText ? (
              <pre className="doc-full-text">{fullText}</pre>
            ) : (
              <div className="file-empty">
                Không đọc được toàn văn gốc. Mở tab Chunks hoặc nhúng lại file.
              </div>
            )}
          </div>
        )}

        {!loading && data && tab === "chunks" && (
          <div className="doc-body">
            <div className="doc-list-pane">
              <div className="doc-search-wrap">
                <input
                  className="doc-search"
                  type="search"
                  placeholder="Lọc chunk / mục / id…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
                <span className="doc-search-count">
                  {filtered.length}/{data.chunk_count}
                </span>
              </div>
              <ul className="doc-chunk-list side-scroll">
                {filtered.map((c, i) => (
                  <li key={c.chunk_id}>
                    <button
                      type="button"
                      className={`doc-chunk-item ${active?.chunk_id === c.chunk_id ? "active" : ""}`}
                      onClick={() => setActiveId(c.chunk_id)}
                    >
                      <div className="doc-chunk-top">
                        <span className="doc-chunk-idx">#{i + 1}</span>
                        <span className="doc-chunk-section" title={c.section}>
                          {c.section}
                        </span>
                        <span className="doc-chunk-len">{c.text.length}</span>
                      </div>
                      <p className="doc-chunk-preview">{preview(c.text)}</p>
                    </button>
                  </li>
                ))}
                {filtered.length === 0 && (
                  <li className="file-empty">
                    {data.chunk_count === 0
                      ? "Chưa có chunk — file lỗi hoặc chưa nhúng xong"
                      : "Không khớp bộ lọc"}
                  </li>
                )}
              </ul>
            </div>

            <div className="doc-detail-pane side-scroll">
              {active ? (
                <>
                  <div className="drawer-meta">
                    <div className="meta-row">
                      <span className="meta-label">Mục</span>
                      <span>{active.section}</span>
                    </div>
                    <div className="meta-row">
                      <span className="meta-label">Chunk ID</span>
                      <code>{active.chunk_id}</code>
                    </div>
                    <div className="meta-row">
                      <span className="meta-label">Vị trí</span>
                      <span>
                        ký tự {active.char_start}–{active.char_end} · {active.text.length} chars
                      </span>
                    </div>
                  </div>
                  <blockquote className="drawer-text">{active.text}</blockquote>
                </>
              ) : (
                <div className="file-empty">Chọn một chunk bên trái để xem nội dung</div>
              )}
            </div>
          </div>
        )}
      </aside>
    </>
  );
}
