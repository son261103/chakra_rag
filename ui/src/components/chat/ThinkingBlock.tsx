import { useEffect, useState } from "react";

interface Props {
  text: string;
  /** true khi model đang suy luận (stream) — tự mở, hiện spinner. */
  active: boolean;
  /** Tổng thời gian suy luận (ms), hiện khi xong. */
  durationMs: number | null;
}

/** Khối "thinking" kiểu ChatGPT: collapsible, gõ dần khi stream,
 *  khi xong thu gọn thành "Đã suy luận trong Xs". */
export default function ThinkingBlock({ text, active, durationMs }: Props) {
  const [open, setOpen] = useState(active);

  // Đang stream thì luôn mở; khi xong tự thu gọn lại.
  useEffect(() => {
    if (active) setOpen(true);
    else setOpen(false);
  }, [active]);

  if (!text && !active) return null;

  const seconds = durationMs !== null ? Math.max(1, Math.round(durationMs / 1000)) : null;

  return (
    <div className={`thinking-block ${active ? "active" : ""}`}>
      <button className="thinking-header" onClick={() => setOpen((o) => !o)}>
        <span className={`thinking-chevron ${open ? "open" : ""}`}>▸</span>
        {active ? (
          <>
            <span className="thinking-spinner" />
            <span className="thinking-title">Đang suy luận…</span>
          </>
        ) : (
          <span className="thinking-title">
            💭 Đã suy luận{seconds !== null ? ` trong ${seconds}s` : ""}
          </span>
        )}
      </button>
      {open && <div className="thinking-text">{text}</div>}
    </div>
  );
}
