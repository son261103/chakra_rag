import { Sparkles } from "lucide-react";
import type { SearchTraceEntry } from "../../api/types";
import ThinkingBlock from "./ThinkingBlock";
import ToolCallBlock from "./ToolCallBlock";
import MarkdownAnswer from "./MarkdownAnswer";

/** Trạng thái tin nhắn đang stream, do App.tsx cập nhật theo từng SSE event. */
export interface StreamingState {
  question: string;
  reasoning: string;
  thinkingActive: boolean;
  thinkingDurationMs: number | null;
  toolCalls: { trace: SearchTraceEntry; running: boolean }[];
  answer: string;
  error: string | null;
}

interface Props {
  state: StreamingState;
}

/** Tin nhắn đang chạy: thinking gõ dần, tool calls chạy trực tiếp, answer gõ dần. */
export default function StreamingMessage({ state }: Props) {
  const { question, reasoning, thinkingActive, thinkingDurationMs, toolCalls, answer, error } = state;

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
          {(reasoning || thinkingActive) && (
            <ThinkingBlock text={reasoning} active={thinkingActive} durationMs={thinkingDurationMs} />
          )}

          {toolCalls.length > 0 && (
            <div className="tool-trace-group">
              {toolCalls.map((tc, i) => (
                <ToolCallBlock
                  key={i}
                  index={i + 1}
                  trace={tc.trace}
                  running={tc.running}
                  onCitationClick={() => {}}
                />
              ))}
            </div>
          )}

          {answer && <MarkdownAnswer text={answer} streaming />}

          {error && <div className="error-banner small">{error}</div>}

          {!reasoning && !thinkingActive && toolCalls.length === 0 && !answer && !error && (
            <div className="thinking-dots">
              <span /> <span /> <span />
              <span className="thinking-label">Đang kết nối…</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
