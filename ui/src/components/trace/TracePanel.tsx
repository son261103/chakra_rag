import { FileText, PanelRightClose, Search } from "lucide-react";
import type { Citation, SearchTraceEntry } from "../../api/types";
import ToolCallBlock from "../chat/ToolCallBlock";
import SourceCard from "../sources/SourceCard";

/** Dữ liệu trace của một tin nhắn (hoặc của tin đang stream) để hiện bên panel phải. */
export interface PanelTrace {
  question: string;
  traces: { trace: SearchTraceEntry; running: boolean }[];
  citations: Citation[];
  /** true khi đang stream — chỉ có tool call, chưa có citations. */
  live: boolean;
}

interface Props {
  open: boolean;
  onClose: () => void;
  data: PanelTrace | null;
  onCitationClick: (chunkId: string) => void;
}

/** Panel phải hiển thị toàn bộ lượt tra cứu + nguồn trích dẫn, giúp chat gọn gàng. */
export default function TracePanel({ open, onClose, data, onCitationClick }: Props) {
  if (!open) return null;

  const hasContent = !!data && (data.traces.length > 0 || data.citations.length > 0);

  return (
    <aside className="trace-panel">
      <div className="trace-panel-header">
        <div className="trace-panel-title">
          <Search size={15} />
          <span>Chi tiết tra cứu</span>
        </div>
        <button className="drawer-close" onClick={onClose} title="Đóng panel">
          <PanelRightClose size={16} />
        </button>
      </div>

      <div className="trace-panel-body side-scroll">
        {!data && <div className="trace-empty">Chi tiết tra cứu sẽ hiện ở đây.</div>}

        {data && (
          <>
            <div className="trace-question" title={data.question}>
              {data.question}
            </div>

            {data.traces.length > 0 && (
              <div className="trace-section">
                <div className="trace-section-title">Lượt tra cứu</div>
                {data.traces.map((tc, i) => (
                  <ToolCallBlock
                    key={i}
                    index={i + 1}
                    trace={tc.trace}
                    running={tc.running}
                    onCitationClick={onCitationClick}
                  />
                ))}
              </div>
            )}

            {data.citations.length > 0 && (
              <div className="trace-section">
                <div className="trace-section-title">
                  <FileText size={12} /> Nguồn trích dẫn
                </div>
                <div className="sources-list">
                  {data.citations.map((c, i) => (
                    <SourceCard
                      key={c.chunk_id}
                      index={i + 1}
                      citation={c}
                      onClick={() => onCitationClick(c.chunk_id)}
                    />
                  ))}
                </div>
              </div>
            )}

            {!hasContent && !data.live && (
              <div className="trace-empty">Câu trả lời này không tra cứu tài liệu.</div>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
