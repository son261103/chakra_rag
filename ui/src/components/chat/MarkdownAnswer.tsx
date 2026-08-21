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

const CITE_RE = /\[([\p{L}\p{N}_#.\-]+)\]/gu;

/** Render answer markdown (GFM) + biến [chunk_id] thành chip bấm được. */
export default function MarkdownAnswer({
  text,
  citationIndex = new Map(),
  invalidIds = [],
  onCitationClick,
  streaming = false,
}: Props) {
  const components: Components = {
    p: ({ children }) => <p>{injectCitations(children, citationIndex, invalidIds, onCitationClick)}</p>,
    li: ({ children }) => <li>{injectCitations(children, citationIndex, invalidIds, onCitationClick)}</li>,
    strong: ({ children }) => (
      <strong>{injectCitations(children, citationIndex, invalidIds, onCitationClick)}</strong>
    ),
    em: ({ children }) => <em>{injectCitations(children, citationIndex, invalidIds, onCitationClick)}</em>,
    td: ({ children }) => <td>{injectCitations(children, citationIndex, invalidIds, onCitationClick)}</td>,
    th: ({ children }) => <th>{injectCitations(children, citationIndex, invalidIds, onCitationClick)}</th>,
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
  invalidIds: string[],
  onCitationClick?: (chunkId: string) => void
): ReactNode {
  return walk(children, citationIndex, invalidIds, onCitationClick);
}

function walk(
  node: ReactNode,
  citationIndex: Map<string, number>,
  invalidIds: string[],
  onCitationClick?: (chunkId: string) => void
): ReactNode {
  if (node == null || typeof node === "boolean") return node;
  if (typeof node === "string" || typeof node === "number") {
    return splitCitations(String(node), citationIndex, invalidIds, onCitationClick);
  }
  if (Array.isArray(node)) {
    return node.map((child, i) => (
      <span key={i}>{walk(child, citationIndex, invalidIds, onCitationClick)}</span>
    ));
  }
  // Element React — giữ nguyên, không đụng children lồng sâu ngoài các tag đã custom
  return node;
}

function splitCitations(
  text: string,
  citationIndex: Map<string, number>,
  invalidIds: string[],
  onCitationClick?: (chunkId: string) => void
): ReactNode {
  const parts: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  const re = new RegExp(CITE_RE.source, CITE_RE.flags);
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const id = match[1];
    const num = citationIndex.get(id);
    const invalid = invalidIds.includes(id);
    if (num != null && onCitationClick) {
      parts.push(
        <button
          key={`${match.index}-${id}`}
          type="button"
          className="cite-chip"
          onClick={() => onCitationClick(id)}
          title={id}
        >
          [{num}]
        </button>
      );
    } else if (num != null) {
      parts.push(
        <span key={`${match.index}-${id}`} className="cite-chip unknown" title={id}>
          [{num}]
        </span>
      );
    } else {
      parts.push(
        <span
          key={`${match.index}-${id}`}
          className={`cite-chip ${invalid ? "invalid" : "unknown"}`}
          title={invalid ? "Citation không hợp lệ" : id}
        >
          [{id}]
        </span>
      );
    }
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  if (parts.length === 0) return text;
  if (parts.length === 1) return parts[0];
  return parts;
}
