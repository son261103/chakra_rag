import type { QAEntry } from "../../app/App";
import type { Citation } from "../../api/types";
import ThinkingBlock from "./ThinkingBlock";
import ToolCallBlock from "./ToolCallBlock";
import MarkdownAnswer from "./MarkdownAnswer";

interface Props {
  entry: QAEntry;
  onCitationClick: (chunkId: string) => void;
}

/** Một cặp hỏi–trả lời đã hoàn tất: user bubble phải, assistant block trái. */
export default function ChatMessage({ entry, onCitationClick }: Props) {
  const { question, response } = entry;
  const citationIndex = new Map<string, number>();
  response.citations.forEach((c, i) => citationIndex.set(c.chunk_id, i + 1));

  return (
    <div className="message-pair">
      <div className="user-row">
        <div className="user-bubble">{question}</div>
      </div>

      <div className="assistant-row">
        <div className="avatar">✦</div>
        <div className="assistant-content">
          {response.reasoning && (
            <ThinkingBlock
              text={response.reasoning}
              active={false}
              durationMs={response.latency_ms}
            />
          )}

          {response.search_trace.map((t, i) => (
            <ToolCallBlock
              key={i}
              index={i + 1}
              trace={t}
              running={false}
              onCitationClick={onCitationClick}
            />
          ))}

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
                <span className="badge warn">⚠️ Độ tin cậy truy xuất thấp</span>
              )}
              {response.unsupported_claims.length > 0 && (
                <span className="badge warn">
                  ⚠️ {response.unsupported_claims.length} câu chưa được nguồn đỡ
                </span>
              )}
              {response.invalid_citations.length > 0 && (
                <span className="badge error">
                  ✗ {response.invalid_citations.length} citation không hợp lệ
                </span>
              )}
            </div>
          )}

          {response.citations.length > 0 && (
            <div className="sources-list">
              <div className="sources-title">Nguồn trích dẫn</div>
              {response.citations.map((c, i) => (
                <SourceCard key={c.chunk_id} index={i + 1} citation={c} onClick={() => onCitationClick(c.chunk_id)} />
              ))}
            </div>
          )}

          <div className="message-meta">
            {response.mode === "agent"
              ? `Agent · ${response.search_trace.length} lượt tra cứu`
              : "Retrieve trực tiếp"}{" "}
            · {response.latency_ms}ms
          </div>
        </div>
      </div>
    </div>
  );
}

function SourceCard({ index, citation, onClick }: { index: number; citation: Citation; onClick: () => void }) {
  return (
    <button className="source-card" onClick={onClick} title="Xem đoạn tài liệu gốc">
      <span className="source-num">{index}</span>
      <span className="source-body">
        <span className="source-doc">{citation.doc}</span>
        <span className="source-section">{citation.section}</span>
        <span className="source-snippet">{citation.text.slice(0, 120)}{citation.text.length > 120 ? "…" : ""}</span>
      </span>
    </button>
  );
}
