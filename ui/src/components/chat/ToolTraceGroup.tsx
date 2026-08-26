import { useState } from "react";
import { ChevronRight, Search } from "lucide-react";
import type { SearchTraceEntry } from "../../api/types";
import ToolCallBlock from "./ToolCallBlock";

interface ToolItem {
  trace: SearchTraceEntry;
  running?: boolean;
}

interface Props {
  tools: ToolItem[];
  onCitationClick: (chunkId: string) => void;
  /** true nếu đang trong quá trình streaming */
  streaming?: boolean;
}

/** Gom các lượt tra cứu tài liệu thành 1 khối collapsible gọn gàng, bấm để mở rộng chi tiết. */
export default function ToolTraceGroup({ tools, onCitationClick }: Props) {
  const [open, setOpen] = useState(false);

  if (tools.length === 0) return null;

  const anyRunning = tools.some((t) => t.running);
  const totalResults = tools.reduce((sum, t) => sum + (t.trace?.n_results || 0), 0);

  // Tìm query đầu tiên có nội dung để làm preview
  const firstQuery = tools.find((t) => t.trace?.query?.trim())?.trace?.query?.trim();

  return (
    <div className={`collapsible-info-block ${open ? "open" : ""} ${anyRunning ? "running" : ""}`}>
      <button
        type="button"
        className="collapsible-info-toggle"
        onClick={() => setOpen((o) => !o)}
        title={open ? "Thu gọn chi tiết tra cứu" : "Mở rộng xem chi tiết từng lượt tra cứu"}
      >
        <div className="collapsible-info-left">
          {anyRunning ? (
            <span className="tool-spinner" />
          ) : (
            <Search size={14} className="text-accent shrink-0" />
          )}
          <span className="collapsible-info-title">
            {anyRunning ? "Đang tra cứu tài liệu…" : "Đã tra cứu tài liệu"}
          </span>
          <span className="collapsible-info-badge">
            {tools.length} lượt{totalResults > 0 && ` · ${totalResults} kết quả`}
          </span>
          {!anyRunning && firstQuery && (
            <span className="collapsible-info-preview" title={firstQuery}>
              "{firstQuery}"{tools.length > 1 && ` +${tools.length - 1}`}
            </span>
          )}
        </div>

        <div className="collapsible-info-right">
          <span className="collapsible-info-hint">{open ? "Thu gọn" : "Chi tiết"}</span>
          <ChevronRight size={13} className={`collapsible-info-chevron ${open ? "open" : ""}`} />
        </div>
      </button>

      <div className={`collapsible-info-body ${open ? "open" : ""}`}>
        <div className="collapsible-info-inner">
          <div className="tools-list">
            {tools.map((item, i) => (
              <ToolCallBlock
                key={i}
                index={i + 1}
                trace={item.trace}
                running={!!item.running}
                onCitationClick={onCitationClick}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
