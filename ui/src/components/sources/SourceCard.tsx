import { FileText } from "lucide-react";
import type { Citation } from "../../api/types";

interface Props {
  index: number;
  citation: Citation;
  onClick: () => void;
}

/** Chuẩn hóa tên file cho gọn gàng, dễ nhìn trên card. */
function cleanDocName(doc: string): string {
  // Thay nhiều dấu gạch dưới liên tiếp thành gạch ngang mềm
  return doc.replace(/_{2,}/g, " — ").replace(/_/g, " ");
}

/** Làm sạch markdown rác (##, **, newlines) trong snippet xem trước. */
function cleanSnippet(text: string): string {
  return text
    .replace(/^#+\s*/gm, "") // xóa markdown headers #, ##
    .replace(/\*{1,2}([^*]+)\*{1,2}/g, "$1") // xóa bold / italic markdown
    .replace(/\s+/g, " ") // gom khoảng trắng & xuống dòng
    .trim();
}

/** Một nguồn trích dẫn — card thông tin tài liệu chuẩn chỉnh, dễ đọc. */
export default function SourceCard({ index, citation, onClick }: Props) {
  const docDisplayName = cleanDocName(citation.doc);
  const snippet = cleanSnippet(citation.text);

  return (
    <button
      className="source-card"
      onClick={onClick}
      title={`Xem chi tiết đoạn trích: ${citation.doc}`}
      type="button"
    >
      <div className="source-card-header">
        <span className="source-num">{index}</span>
        <span className="source-doc-name" title={citation.doc}>
          <FileText size={13} className="source-doc-icon" />
          <span className="truncate">{docDisplayName}</span>
        </span>
        {citation.section && (
          <span className="source-section-pill" title={citation.section}>
            {citation.section}
          </span>
        )}
      </div>

      <p className="source-snippet">{snippet}</p>
    </button>
  );
}

