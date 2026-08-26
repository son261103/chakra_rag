import { Sparkles } from "lucide-react";
import type { AskResponse, SearchTraceEntry } from "../../api/types";
import ThinkingBlock from "./ThinkingBlock";
import ToolTraceGroup from "./ToolTraceGroup";
import MarkdownAnswer from "./MarkdownAnswer";
import { useSmoothText } from "../../hooks/useSmoothText";

/** Trạng thái tin nhắn đang stream, do App.tsx cập nhật theo từng SSE event. */
export interface StreamingState {
  question: string;
  reasoning: string;
  thinkingActive: boolean;
  thinkingDurationMs: number | null;
  toolCalls: { trace: SearchTraceEntry; running: boolean }[];
  answer: string;
  error: string | null;
  /** Payload hoàn chỉnh khi nhận event "done" */
  finalResponse?: AskResponse | null;
}

interface Props {
  state: StreamingState;
  onComplete?: (response: AskResponse) => void;
}

/** Tin nhắn đang chạy: thinking gõ dần, tool calls chạy trực tiếp, answer nhả chữ mượt mà như ChatGPT. */
export default function StreamingMessage({ state, onComplete }: Props) {
  const { question, reasoning, thinkingActive, thinkingDurationMs, toolCalls, answer, error, finalResponse } = state;

  const smoothAnswer = useSmoothText(answer, {
    isComplete: !!finalResponse,
    onComplete: () => {
      if (finalResponse) {
        onComplete?.(finalResponse);
      }
    },
  });

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
          {(reasoning || thinkingActive) && (
            <ThinkingBlock text={reasoning} active={thinkingActive} durationMs={thinkingDurationMs} />
          )}

          {toolCalls.length > 0 && (
            <ToolTraceGroup
              tools={toolCalls}
              onCitationClick={() => {}}
              streaming={!answer && !finalResponse}
            />
          )}

          {smoothAnswer && <MarkdownAnswer text={smoothAnswer} streaming />}

          {error && <div className="error-banner small">{error}</div>}

          {!reasoning && !thinkingActive && toolCalls.length === 0 && !smoothAnswer && !error && (
            <div className="collapsible-info-block running">
              <div className="collapsible-info-toggle cursor-default">
                <div className="collapsible-info-left">
                  <span className="tool-spinner" />
                  <span className="collapsible-info-title">Đang xử lý…</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
