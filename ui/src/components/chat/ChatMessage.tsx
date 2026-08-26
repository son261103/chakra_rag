import { AlertTriangle, Sparkles, XCircle } from "lucide-react";
import type { QAEntry } from "../../app/App";
import ThinkingBlock from "./ThinkingBlock";
import ToolTraceGroup from "./ToolTraceGroup";
import MarkdownAnswer from "./MarkdownAnswer";
import SourcesBlock from "./SourcesBlock";

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

  const latencyDisplay =
    response.latency_ms >= 1000
      ? `${(response.latency_ms / 1000).toFixed(1)}s`
      : `${response.latency_ms}ms`;

  const toolItems = response.search_trace.map((trace) => ({ trace, running: false }));

  return (
    <div className="message-pair">
      <div className="user-row">
        <div className="user-bubble">{question}</div>
      </div>

      <div className="assistant-row">
        <div className="assistant-header">
          <div className="avatar">
            <Sparkles size={13} />
          </div>
          <span className="assistant-name">Chakra AI</span>
          <span className="assistant-badge">
            {response.mode === "agent" ? "Agent" : "RAG"}
          </span>
        </div>

        <div className="assistant-content">
          {response.reasoning && (
            <ThinkingBlock text={response.reasoning} active={false} durationMs={response.latency_ms} />
          )}

          {toolItems.length > 0 && (
            <ToolTraceGroup tools={toolItems} onCitationClick={onCitationClick} />
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

          {response.citations.length > 0 && (
            <SourcesBlock citations={response.citations} onCitationClick={onCitationClick} />
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

