import { useState } from "react";
import { Brain, ChevronRight, Loader2 } from "lucide-react";

interface Props {
  text: string;
  /** true khi model đang suy luận (stream) — tự mở, hiện spinner. */
  active: boolean;
  /** Tổng thời gian suy luận (ms), hiện khi xong. */
  durationMs: number | null;
}

/** Khối suy luận: cấu trúc đồng bộ 100% với ToolTraceGroup và SourcesBlock. */
export default function ThinkingBlock({ text, active, durationMs }: Props) {
  // Mặc định luôn đóng gọn 1 dòng — không tự bung ra làm giật/nhảy giao diện
  const [open, setOpen] = useState(false);

  if (!text && !active) return null;

  const seconds = durationMs !== null ? Math.max(1, Math.round(durationMs / 1000)) : null;

  return (
    <div className={`collapsible-info-block ${open ? "open" : ""} ${active ? "active" : ""}`}>
      <button
        type="button"
        className="collapsible-info-toggle"
        onClick={() => setOpen((o) => !o)}
        title={open ? "Thu gọn quá trình suy luận" : "Mở rộng xem nội dung suy luận"}
      >
        <div className="collapsible-info-left">
          {active ? (
            <Loader2 size={14} className="animate-spin text-accent shrink-0" />
          ) : (
            <Brain size={14} className="text-accent shrink-0" />
          )}
          <span className="collapsible-info-title">
            {active ? "Đang suy luận…" : "Đã suy luận"}
          </span>
          {seconds !== null && !active && (
            <span className="collapsible-info-badge">{seconds}s</span>
          )}
        </div>

        <div className="collapsible-info-right">
          <span className="collapsible-info-hint">{open ? "Thu gọn" : "Chi tiết"}</span>
          <ChevronRight size={13} className={`collapsible-info-chevron ${open ? "open" : ""}`} />
        </div>
      </button>

      <div className={`collapsible-info-body ${open ? "open" : ""}`}>
        <div className="collapsible-info-inner">
          <div className="thinking-text side-scroll">{text}</div>
        </div>
      </div>
    </div>
  );
}
