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

          {response.citations.length > 0 && (
            <SourcesBlock citations={response.citations} onCitationClick={onCitationClick} />
          )}

          <div className="message-meta">
            <span>
              {nTraces > 0 ? `Agent · ${nTraces} lượt tra cứu` : "Agent"}
              {response.latency_ms > 0 && ` · ${latencyDisplay}`}
            </span>

            {((response.low_confidence && nTraces > 0) ||
              response.unsupported_claims.length > 0 ||
              response.invalid_citations.length > 0) && (
              <div className="message-warnings">
                {response.low_confidence && nTraces > 0 && (
                  <span className="meta-warn-badge" title="Độ tin cậy truy xuất thấp">
                    <AlertTriangle size={11} /> Độ tin cậy thấp
                  </span>
                )}
                {response.unsupported_claims.length > 0 && (
                  <span
                    className="meta-warn-badge"
                    title={`${response.unsupported_claims.length} câu trong câu trả lời chưa được nguồn tài liệu đỡ`}
                  >
                    <AlertTriangle size={11} /> {response.unsupported_claims.length} câu chưa có nguồn
                  </span>
                )}
                {response.invalid_citations.length > 0 && (
                  <span
                    className="meta-error-badge"
                    title={`${response.invalid_citations.length} citation không hợp lệ`}
                  >
                    <XCircle size={11} /> {response.invalid_citations.length} citation lỗi
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

