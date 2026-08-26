import { useState } from "react";
import { ChevronRight, FileText } from "lucide-react";
import type { Citation } from "../../api/types";
import SourceCard from "../sources/SourceCard";

interface Props {
  citations: Citation[];
  onCitationClick: (chunkId: string) => void;
}

/** Khối nguồn trích dẫn: mặc định thu gọn 1 thanh ngang tinh tế, bấm để mở lưới chi tiết. */
export default function SourcesBlock({ citations, onCitationClick }: Props) {
  const [open, setOpen] = useState(false);

  if (citations.length === 0) return null;

  return (
    <div className={`collapsible-info-block ${open ? "open" : ""}`}>
      <button
        type="button"
        className="collapsible-info-toggle"
        onClick={() => setOpen((o) => !o)}
        title={open ? "Thu gọn danh sách nguồn trích dẫn" : "Mở rộng xem chi tiết các đoạn trích dẫn"}
      >
        <div className="collapsible-info-left">
          <FileText size={14} className="text-accent shrink-0" />
          <span className="collapsible-info-title">Nguồn trích dẫn</span>
          <span className="collapsible-info-badge">{citations.length} nguồn</span>
        </div>

        <div className="collapsible-info-right">
          <span className="collapsible-info-hint">{open ? "Thu gọn" : "Chi tiết"}</span>
          <ChevronRight size={13} className={`collapsible-info-chevron ${open ? "open" : ""}`} />
        </div>
      </button>

      <div className={`collapsible-info-body ${open ? "open" : ""}`}>
        <div className="collapsible-info-inner">
          <div className="sources-grid">
            {citations.map((c, i) => (
              <SourceCard
                key={c.chunk_id}
                index={i + 1}
                citation={c}
                onClick={() => onCitationClick(c.chunk_id)}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
