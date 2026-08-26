import type { Citation } from "../../api/types";

interface Props {
  index: number;
  citation: Citation;
  onClick: () => void;
}

/** Một nguồn trích dẫn — click để mở SourceDrawer xem đoạn tài liệu gốc. */
export default function SourceCard({ index, citation, onClick }: Props) {
  return (
    <button className="source-card" onClick={onClick} title="Xem đoạn tài liệu gốc">
      <span className="source-num">{index}</span>
      <span className="source-body">
        <span className="source-doc">{citation.doc}</span>
        <span className="source-section">{citation.section}</span>
        <span className="source-snippet">
          {citation.text.slice(0, 120)}
          {citation.text.length > 120 ? "…" : ""}
        </span>
      </span>
    </button>
  );
}
