import { useState } from "react";
import { ChevronRight, Loader2, Search } from "lucide-react";
import type { SearchTraceEntry } from "../../api/types";

interface Props {
  index: number;
  trace: SearchTraceEntry;
  /** true khi tool đang chạy (chưa có kết quả). */
  running: boolean;
  onCitationClick: (chunkId: string) => void;
}

/** Một lần gọi tool kiểu ChatGPT: card bo tròn, query inline, kết quả expandable. */
export default function ToolCallBlock({ trace, running, onCitationClick }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div className={`tool-block ${open ? "open" : ""} ${running ? "running" : ""}`}>
      <button
        type="button"
        className="tool-header"
        onClick={() => !running && setOpen((o) => !o)}
        disabled={running}
      >
        <ChevronRight size={13} className={`tool-chevron ${open ? "open" : ""}`} />
        <Search size={13} className="text-accent shrink-0" />
        <span className="font-semibold text-text">
          {running ? "Đang tìm kiếm tài liệu…" : "Đã tìm kiếm"}
        </span>
        {!running && (
          <span className="tool-query-inline" title={trace.query || "Tra cứu tài liệu"}>
            {trace.query?.trim() ? (
              `"${trace.query.trim()}"`
            ) : (
              <span className="italic text-muted/70">Tra cứu tài liệu liên quan</span>
            )}
          </span>
        )}
        {running ? (
          <Loader2 size={13} className="animate-spin text-accent shrink-0" />
        ) : (
          <span className="tool-summary">
            {trace.n_results} kết quả
          </span>
        )}
      </button>

      {!running && (
        <div className={`tool-body ${open ? "open" : ""}`}>
          <div className="tool-body-inner">
            <div className="tool-results">
              {trace.chunk_ids.filter(Boolean).map((cid) => (
                <button
                  key={cid}
                  type="button"
                  className="tool-result-chip"
                  onClick={() => onCitationClick(cid!)}
                  title={`Xem đoạn: ${cid}`}
                >
                  {cid}
                </button>
              ))}
              {trace.n_results === 0 && (
                <span className="tool-no-result">Không tìm thấy kết quả phù hợp</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
