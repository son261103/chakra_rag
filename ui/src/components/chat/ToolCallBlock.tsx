import { useState } from "react";
import { ChevronRight, Search } from "lucide-react";
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
    <div className={`tool-block ${running ? "running" : ""}`}>
      <button className="tool-header" onClick={() => setOpen((o) => !o)} disabled={running}>
        <ChevronRight size={14} className={`tool-chevron ${open ? "open" : ""}`} />
        <Search size={14} className="tool-icon" />
        <span className="tool-title">
          {running ? "Đang tìm kiếm…" : "Đã tìm kiếm"}
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
          <span className="tool-spinner" />
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
