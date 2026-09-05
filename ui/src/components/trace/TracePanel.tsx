import { FileText, MessageSquare, PanelRightClose, Search } from "lucide-react";
import type { Citation, ToolTraceEntry } from "../../api/types";
import ToolCallBlock from "../chat/ToolCallBlock";
import SourceCard from "../sources/SourceCard";

/** Dữ liệu trace của một tin nhắn (hoặc của tin đang stream) để hiện bên panel phải. */
export interface PanelTrace {
  question: string;
  traces: { trace: ToolTraceEntry; running: boolean }[];
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
          {data?.live && <span className="trace-live-badge">Live</span>}
        </div>
        <button className="drawer-close" onClick={onClose} title="Đóng panel">
          <PanelRightClose size={16} />
        </button>
      </div>

      <div className="trace-panel-body side-scroll">
        {!data && <div className="trace-empty">Chi tiết tra cứu sẽ hiện ở đây.</div>}

        {data && (
          <>
            <div className="trace-context-card">
              <div className="trace-context-kicker">
                <MessageSquare size={12} />
                <span>Câu hỏi đang xem</span>
              </div>
              <div className="trace-context-question" title={data.question}>
                {data.question}
              </div>
            </div>

            {data.traces.length > 0 && (
              <div className="trace-section">
                <div className="trace-section-title">
                  <span className="flex items-center gap-1.5">
                    <Search size={12} /> Lượt tra cứu
                  </span>
                  <span className="trace-count-badge">{data.traces.length}</span>
                </div>
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
                  <span className="flex items-center gap-1.5">
                    <FileText size={12} /> Nguồn trích dẫn
                  </span>
                  <span className="trace-count-badge">{data.citations.length}</span>
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

