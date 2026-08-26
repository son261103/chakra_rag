import { AlertTriangle, Sparkles, XCircle } from "lucide-react";
import type { QAEntry } from "../../app/App";
import ThinkingBlock from "./ThinkingBlock";
import ToolCallBlock from "./ToolCallBlock";
import MarkdownAnswer from "./MarkdownAnswer";
import SourceCard from "../sources/SourceCard";

interface Props {
  entry: QAEntry;
  onCitationClick: (chunkId: string) => void;
}

/** Một cặp hỏi–trả lời hoàn chỉnh: Tool call + trích dẫn nằm trực tiếp trong tin nhắn. */
export default function ChatMessage({ entry, onCitationClick }: Props) {
  const { question, response } = entry;
  const citationIndex = new Map<string, number>();
  response.citations.forEach((c, i) => citationIndex.set(c.chunk_id, i + 1));

  const nTraces = response.search_trace.length;
  const nSources = response.citations.length;

  const latencyDisplay =
    response.latency_ms >= 1000
      ? `${(response.latency_ms / 1000).toFixed(1)}s`
      : `${response.latency_ms}ms`;

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

          {response.search_trace.length > 0 && (
            <div className="tool-trace-group">
              {response.search_trace.map((t, i) => (
                <ToolCallBlock
                  key={i}
                  index={i + 1}
                  trace={t}
                  running={false}
                  onCitationClick={onCitationClick}
                />
              ))}
            </div>
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

          {nSources > 0 && (
            <div className="sources-container">
              <div className="sources-title">
                Nguồn trích dẫn ({nSources})
              </div>
              <div className="sources-grid">
                {response.citations.map((c, i) => (
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

          <div className="message-meta">
            <span>
              {response.mode === "agent"
                ? nTraces > 0
                  ? `Agent · ${nTraces} lượt tra cứu`
                  : "Agent"
                : "Retrieve trực tiếp"}
              {response.latency_ms > 0 && ` · ${latencyDisplay}`}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

