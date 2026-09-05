import { useState, type ReactNode } from "react";
import { ChevronRight, FileText, Library, Loader2, Search } from "lucide-react";
import type { ToolTraceEntry } from "../../api/types";

interface Props {
  index: number;
  trace: ToolTraceEntry;
  /** true khi tool đang chạy (chưa có kết quả). */
  running: boolean;
  onCitationClick: (chunkId: string) => void;
}

/** Đầu đề card theo loại tool (ChatGPT-style: "Đã tìm kiếm…"/"Đã đọc…"/"Đã liệt kê…"). */
function headerLabel(trace: ToolTraceEntry, running: boolean): string {
  if (trace.name === "read_chunk") return running ? "Đang đọc đoạn tài liệu…" : "Đã đọc đoạn tài liệu";
  if (trace.name === "list_documents") return running ? "Đang liệt kê tài liệu…" : "Đã liệt kê tài liệu";
  return running ? "Đang tìm kiếm tài liệu…" : "Đã tìm kiếm";
}

/** Nhãn inline sau đầu đề (query / chunk_id); list_documents không có. */
function inlineHeader(trace: ToolTraceEntry): { text: ReactNode; title: string } | null {
  if (trace.name === "read_chunk") {
    return trace.chunk_id ? { text: `"${trace.chunk_id}"`, title: trace.chunk_id } : null;
  }
  if (!trace.name || trace.name === "search_docs") {
    return {
      text: trace.query?.trim() ? (
        `"${trace.query.trim()}"`
      ) : (
        <span className="italic text-muted/70">Tra cứu tài liệu liên quan</span>
      ),
      title: trace.query || "Tra cứu tài liệu",
    };
  }
  return null;
}

/** Tóm tắt bên phải card: số kết quả / tên doc / số tài liệu. */
function summaryText(trace: ToolTraceEntry): string {
  if (trace.name === "read_chunk") return trace.found ? trace.doc : "Không tìm thấy";
  if (trace.name === "list_documents") return `${trace.n_docs} tài liệu`;
  return `${trace.n_results} kết quả`;
}

/** Một lần gọi tool kiểu ChatGPT: card bo tròn, đầu đề theo loại tool, kết quả expandable. */
export default function ToolCallBlock({ trace, running, onCitationClick }: Props) {
  const [open, setOpen] = useState(false);
  const Icon = trace.name === "read_chunk" ? FileText : trace.name === "list_documents" ? Library : Search;
  const inline = running ? null : inlineHeader(trace);

  return (
    <div className={`tool-block ${open ? "open" : ""} ${running ? "running" : ""}`}>
      <button
        type="button"
        className="tool-header"
        onClick={() => !running && setOpen((o) => !o)}
        disabled={running}
      >
        <ChevronRight size={13} className={`tool-chevron ${open ? "open" : ""}`} />
        <Icon size={13} className="text-accent shrink-0" />
        <span className="font-semibold text-text">{headerLabel(trace, running)}</span>
        {inline && (
          <span className="tool-query-inline" title={inline.title}>
            {inline.text}
          </span>
        )}
        {running ? (
          <Loader2 size={13} className="animate-spin text-accent shrink-0" />
        ) : (
          <span className="tool-summary">{summaryText(trace)}</span>
        )}
      </button>

      {!running && (
        <div className={`tool-body ${open ? "open" : ""}`}>
          <div className="tool-body-inner">
            <div className="tool-results">
              {(!trace.name || trace.name === "search_docs") && (
                <>
                  {trace.chunk_ids.filter(Boolean).map((cid) => (
                    <button
                      key={cid}
                      type="button"
                      className="tool-result-chip"
                      onClick={() => onCitationClick(cid!)}
                      title={`Xem đoạn: ${cid}`}
                    >
                      {cid}
                    </button>
                  ))}
                  {trace.n_results === 0 && (
                    <span className="tool-no-result">Không tìm thấy kết quả phù hợp</span>
                  )}
                </>
              )}
              {trace.name === "read_chunk" &&
                (trace.found ? (
                  <button
                    type="button"
                    className="tool-result-chip"
                    onClick={() => onCitationClick(trace.chunk_id)}
                    title={`Xem đoạn: ${trace.chunk_id}`}
                  >
                    {trace.chunk_id}
                  </button>
                ) : (
                  <span className="tool-no-result">Chunk không tồn tại hoặc đã bị xóa</span>
                ))}
              {trace.name === "list_documents" &&
                (trace.docs.length > 0 ? (
                  trace.docs.map((doc, i) => (
                    <span key={`${doc}-${i}`} className="tool-result-chip cursor-default">
                      {doc}
                    </span>
                  ))
                ) : (
                  <span className="tool-no-result">Hệ thống chưa có tài liệu nào</span>
                ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
