import { useState } from "react";
import type { SearchTraceEntry } from "../../api/types";

interface Props {
  index: number;
  trace: SearchTraceEntry;
  /** true khi tool đang chạy (chưa có kết quả). */
  running: boolean;
  onCitationClick: (chunkId: string) => void;
}

/** Một lần gọi tool kiểu Claude: header "Đã dùng search_docs" + query,
 *  bấm mở xem kết quả (các chunk tìm được). */
export default function ToolCallBlock({ index, trace, running, onCitationClick }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div className={`tool-block ${running ? "running" : ""}`}>
      <button className="tool-header" onClick={() => setOpen((o) => !o)} disabled={running}>
        <span className={`tool-chevron ${open ? "open" : ""}`}>▸</span>
        <span className="tool-icon">🔍</span>
        <span className="tool-title">
          {running ? "Đang gọi" : "Đã gọi"} <code>search_docs</code> lần {index}
        </span>
        {running ? (
          <span className="tool-spinner" />
        ) : (
          <span className="tool-summary">
            {trace.n_results} kết quả · điểm cao nhất {trace.max_score.toFixed(2)}
          </span>
        )}
      </button>

      {!running && (
        <>
          <div className="tool-query">"{trace.query}"</div>
          {open && (
            <div className="tool-results">
              {trace.chunk_ids.filter(Boolean).map((cid) => (
                <button key={cid} className="tool-result-chip" onClick={() => onCitationClick(cid!)}>
                  {cid}
                </button>
              ))}
              {trace.n_results === 0 && <span className="tool-no-result">Không tìm thấy kết quả nào</span>}
            </div>
          )}
        </>
      )}
    </div>
  );
}
