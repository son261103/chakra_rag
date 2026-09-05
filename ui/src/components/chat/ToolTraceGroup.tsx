import { useState } from "react";
import { ChevronRight, Loader2, Search } from "lucide-react";
import type { ToolTraceEntry } from "../../api/types";
import ToolCallBlock from "./ToolCallBlock";

interface ToolItem {
  trace: ToolTraceEntry;
  running?: boolean;
}

interface Props {
  tools: ToolItem[];
  onCitationClick: (chunkId: string) => void;
  /** true nếu đang trong quá trình streaming */
  streaming?: boolean;
}

/** Số kết quả tóm tắt: chỉ search có n_results, read/list trả 0 để không đếm chung. */
function nResultsOf(trace: ToolTraceEntry): number {
  if (trace.name === "read_chunk" || trace.name === "list_documents") return 0;
  return trace.n_results ?? 0;
}

export default function ToolTraceGroup({ tools, onCitationClick, streaming = false }: Props) {
  const [open, setOpen] = useState(false);

  if (tools.length === 0) return null;

  // Khi đang streaming câu hỏi và các tool chưa chốt xong: giữ trạng thái loading liên tục,
  // không bật-tắt spinner giật cục giữa các lượt gọi tool
  const anyRunning = streaming || tools.some((t) => t.running);
  const totalResults = tools.reduce((sum, t) => sum + nResultsOf(t.trace), 0);

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
            <Loader2 size={14} className="animate-spin text-accent shrink-0" />
          ) : (
            <Search size={14} className="text-accent shrink-0" />
          )}
          <span className="collapsible-info-title">
            {anyRunning ? "Đang tra cứu tài liệu…" : "Đã tra cứu tài liệu"}
          </span>
          <span className="collapsible-info-badge">
            {tools.length} lượt{totalResults > 0 && ` · ${totalResults} kết quả`}
          </span>
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
