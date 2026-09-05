import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ReactNode } from "react";

interface Props {
  text: string;
  /** map chunk_id → số thứ tự hiển thị [1], [2]…; rỗng khi đang stream */
  citationIndex?: Map<string, number>;
  invalidIds?: string[];
  onCitationClick?: (chunkId: string) => void;
  /** true khi answer đang gõ dần — hiện con trỏ nhấp nháy cuối block */
  streaming?: boolean;
}

/** Match [chunk_id] — có thể chứa nhiều id phân tách bởi "," / ";" (vd: [a#s#0, b#s#1]). */
const CITE_RE = /\[([\p{L}\p{N}_#.\-]+(?:\s*[,;]\s*[\p{L}\p{N}_#.\-]+)*)\]/gu;

/** Render answer markdown (GFM) + biến [chunk_id] thành chip bấm được.
 *  Chip luôn hiển thị SỐ THỨ TỰ ngắn (không in chuỗi id dài): khi có
 *  citationIndex (tin đã chốt) thì số theo danh sách citations; khi chưa
 *  (đang stream) đánh số theo thứ tự xuất hiện trong answer. */
export default function MarkdownAnswer({
  text,
  citationIndex = new Map(),
  invalidIds = [],
  onCitationClick,
  streaming = false,
}: Props) {
  // Số fallback cho id chưa nằm trong citationIndex: đánh theo vị trí xuất hiện.
  const seenOrder = new Map<string, number>();
  const autoRe = new RegExp(CITE_RE.source, CITE_RE.flags);
  let m: RegExpExecArray | null;
  let next = 1;
  while ((m = autoRe.exec(text)) !== null) {
    for (const id of m[1].split(/[\s,;]+/).filter(Boolean)) {
      if (!seenOrder.has(id)) {
        seenOrder.set(id, next);
        next += 1;
      }
    }
  }
  const autoIndex = new Map<string, number>();
  for (const [id, num] of seenOrder) {
    if (!citationIndex.has(id)) autoIndex.set(id, num);
  }

  const inject = (children: ReactNode) =>
    injectCitations(children, citationIndex, autoIndex, invalidIds, onCitationClick);
  const components: Components = {
    p: ({ children }) => <p>{inject(children)}</p>,
    li: ({ children }) => <li>{inject(children)}</li>,
    strong: ({ children }) => <strong>{inject(children)}</strong>,
    em: ({ children }) => <em>{inject(children)}</em>,
    td: ({ children }) => <td>{inject(children)}</td>,
    th: ({ children }) => <th>{inject(children)}</th>,
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noreferrer noopener">
        {children}
      </a>
    ),
  };

  return (
    <div className={`answer-text${streaming ? " is-streaming" : ""}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
      {streaming && <span className="stream-cursor" />}
    </div>
  );
}

/** Duyệt cây children của markdown, thay text chứa [id] bằng chip citation. */
function injectCitations(
  children: ReactNode,
  citationIndex: Map<string, number>,
  autoIndex: Map<string, number>,
  invalidIds: string[],
  onCitationClick?: (chunkId: string) => void
): ReactNode {
  return walk(children, citationIndex, autoIndex, invalidIds, onCitationClick);
}

function walk(
  node: ReactNode,
  citationIndex: Map<string, number>,
  autoIndex: Map<string, number>,
  invalidIds: string[],
  onCitationClick?: (chunkId: string) => void
): ReactNode {
  if (node == null || typeof node === "boolean") return node;
  if (typeof node === "string" || typeof node === "number") {
    return splitCitations(String(node), citationIndex, autoIndex, invalidIds, onCitationClick);
  }
  if (Array.isArray(node)) {
    return node.map((child, i) => (
      <span key={i}>{walk(child, citationIndex, autoIndex, invalidIds, onCitationClick)}</span>
    ));
  }
  // Element React — giữ nguyên, không đụng children lồng sâu ngoài các tag đã custom
  return node;
}

function splitCitations(
  text: string,
  citationIndex: Map<string, number>,
  autoIndex: Map<string, number>,
  invalidIds: string[],
  onCitationClick?: (chunkId: string) => void
): ReactNode {
  const parts: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  const re = new RegExp(CITE_RE.source, CITE_RE.flags);
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    // Một cặp [] có thể chứa nhiều id → mỗi id một chip riêng
    const ids = match[1].split(/[\s,;]+/).filter(Boolean);
    const chipMatch = match;
    ids.forEach((id, i) => {
      const invalid = invalidIds.includes(id);
      // Luôn có số: citationIndex (tin đã chốt) → autoIndex (thứ tự xuất hiện,
      // đang stream) — không bao giờ in chuỗi id dài ra UI.
      const num = citationIndex.get(id) ?? autoIndex.get(id)!;
      const clickable = citationIndex.has(id) && onCitationClick != null;
      if (clickable) {
        parts.push(
          <button
            key={`${chipMatch.index}-${id}-${i}`}
            type="button"
            className="cite-chip"
            onClick={() => onCitationClick(id)}
            title={`Xem nguồn [${num}]: ${id}`}
          >
            [{num}]
          </button>
        );
      } else {
        parts.push(
          <span
            key={`${chipMatch.index}-${id}-${i}`}
            className={`cite-chip ${invalid ? "invalid" : "unknown"}`}
            title={invalid ? "Citation không hợp lệ" : `Nguồn: ${id}`}
          >
            [{num}]
          </span>
        );
      }
    });
    last = match.index + match[0].length;

    // Chuẩn hóa: loại bỏ khoảng trắng vô duyên giữa citation chip và dấu câu (vd: "[1] ." -> "[1].")
    const remaining = text.slice(last);
    const punctMatch = remaining.match(/^(\s+)([.,;:!?])/);
    if (punctMatch) {
      last += punctMatch[1].length;
    }
  }
  if (last < text.length) parts.push(text.slice(last));
  if (parts.length === 0) return text;
  if (parts.length === 1) return parts[0];
  return parts;
}
