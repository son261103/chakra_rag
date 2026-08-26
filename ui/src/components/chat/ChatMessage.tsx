import { AlertTriangle, FileText, Search, Sparkles, XCircle } from "lucide-react";
import type { QAEntry } from "../../app/App";
import ThinkingBlock from "./ThinkingBlock";
import MarkdownAnswer from "./MarkdownAnswer";

interface Props {
  entry: QAEntry;
  /** true khi tin nhắn này đang được chọn để hiện trace bên panel phải. */
  selected: boolean;
  onCitationClick: (chunkId: string) => void;
  /** Mở panel phải xem lượt tra cứu + nguồn của tin nhắn này. */
  onOpenTrace: () => void;
}

/** Một cặp hỏi–trả lời đã hoàn tất. Tool call + nguồn đã chuyển sang panel phải. */
export default function ChatMessage({ entry, selected, onCitationClick, onOpenTrace }: Props) {
  const { question, response } = entry;
  const citationIndex = new Map<string, number>();
  response.citations.forEach((c, i) => citationIndex.set(c.chunk_id, i + 1));

  const nTraces = response.search_trace.length;
  const nSources = response.citations.length;
  const hasTrace = nTraces > 0 || nSources > 0;

  return (
    <div className="message-pair">
      <div className="user-row">
        <div className="user-bubble">{question}</div>
      </div>

      <div className="assistant-row">
        <div className="avatar">
          <Sparkles size={15} />
        </div>
        <div className="assistant-content">
          {response.reasoning && (
            <ThinkingBlock text={response.reasoning} active={false} durationMs={response.latency_ms} />
          )}

          <MarkdownAnswer
            text={response.answer}
            citationIndex={citationIndex}
            invalidIds={response.invalid_citations}
            onCitationClick={onCitationClick}
          />

          {/* low_confidence chỉ có nghĩa khi đã gọi search_docs — chào hỏi không cảnh báo */}
          {((response.low_confidence && response.search_trace.length > 0) ||
            response.unsupported_claims.length > 0 ||
            response.invalid_citations.length > 0) && (
            <div className="warnings">
              {response.low_confidence && response.search_trace.length > 0 && (
                <span className="badge warn">
                  <AlertTriangle size={12} /> Độ tin cậy truy xuất thấp
                </span>
              )}
              {response.unsupported_claims.length > 0 && (
                <span className="badge warn">
                  <AlertTriangle size={12} /> {response.unsupported_claims.length} câu chưa được nguồn đỡ
                </span>
              )}
              {response.invalid_citations.length > 0 && (
                <span className="badge error">
                  <XCircle size={12} /> {response.invalid_citations.length} citation không hợp lệ
                </span>
              )}
            </div>
          )}

          <div className="message-meta">
            <span>
              {response.mode === "agent"
                ? nTraces > 0
                  ? `Agent · ${nTraces} lượt tra cứu`
                  : "Agent"
                : "Retrieve trực tiếp"}
              {response.latency_ms > 0 &&
                ` · ${response.latency_ms >= 1000 ? `${(response.latency_ms / 1000).toFixed(1)}s` : `${response.latency_ms}ms`}`}
            </span>
            {hasTrace && (
              <button
                type="button"
                className={`trace-chip ${selected ? "active" : ""}`}
                onClick={onOpenTrace}
                title="Xem chi tiết lượt tra cứu và nguồn"
              >
                <Search size={12} />
                <span>{nTraces} lượt</span>
                <span>·</span>
                <FileText size={12} />
                <span>{nSources} nguồn</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
