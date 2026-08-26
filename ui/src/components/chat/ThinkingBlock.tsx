import { useEffect, useState } from "react";
import { Brain, ChevronRight } from "lucide-react";

interface Props {
  text: string;
  /** true khi model đang suy luận (stream) — tự mở, hiện spinner. */
  active: boolean;
  /** Tổng thời gian suy luận (ms), hiện khi xong. */
  durationMs: number | null;
}

/** Khối "thinking" kiểu ChatGPT: card bo tròn, collapsible mượt. */
export default function ThinkingBlock({ text, active, durationMs }: Props) {
  const [open, setOpen] = useState(active);

  useEffect(() => {
    if (active) setOpen(true);
    else setOpen(false);
  }, [active]);

  if (!text && !active) return null;

  const seconds = durationMs !== null ? Math.max(1, Math.round(durationMs / 1000)) : null;

  return (
    <div className={`thinking-block ${active ? "active" : ""}`}>
      <button className="thinking-header" onClick={() => setOpen((o) => !o)}>
        <ChevronRight size={14} className={`thinking-chevron ${open ? "open" : ""}`} />
        {active ? (
          <>
            <span className="thinking-spinner" />
            <span className="thinking-title">Đang suy luận…</span>
          </>
        ) : (
          <>
            <Brain size={14} className="thinking-icon" />
            <span className="thinking-title">
              Đã suy luận{seconds !== null ? ` trong ${seconds}s` : ""}
            </span>
          </>
        )}
      </button>
      <div className={`thinking-body ${open ? "open" : ""}`}>
        <div className="thinking-body-inner">
          <div className="thinking-text">{text}</div>
        </div>
      </div>
    </div>
  );
}
