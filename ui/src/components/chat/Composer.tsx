import { useEffect, useRef, useState } from "react";
import { ArrowUp, Square } from "lucide-react";

interface Props {
  onAsk: (question: string) => void;
  onStop?: () => void;
  disabled: boolean;
  asking: boolean;
  ready: boolean;
}

/** Ô nhập câu hỏi kiểu ChatGPT: bo tròn, nút gửi chuyển thành nút Dừng (Stop) khi đang chạy. */
export default function Composer({ onAsk, onStop, disabled, asking, ready }: Props) {
  const [question, setQuestion] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`;
    }
  }, [question]);

  const submit = () => {
    const q = question.trim();
    if (!q || disabled || asking) return;
    onAsk(q);
    setQuestion("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  return (
    <div className="composer-wrap">
      <div className={`composer ${asking ? "is-asking" : ""}`}>
        <textarea
          ref={textareaRef}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (asking) {
                onStop?.();
              } else {
                submit();
              }
            }
          }}
          placeholder={
            !ready
              ? "Chờ index tài liệu sẵn sàng…"
              : asking
                ? "Chakra AI đang tra cứu & tạo câu trả lời…"
                : "Hỏi về tài liệu nội bộ…"
          }
          rows={1}
          disabled={disabled || asking}
        />
        {asking ? (
          <button
            type="button"
            className="send-btn running"
            onClick={onStop}
            title="Dừng phản hồi"
          >
            <span className="send-btn-spinner" />
            <Square size={11} className="send-btn-square" fill="currentColor" />
          </button>
        ) : (
          <button
            type="button"
            className={`send-btn ${question.trim() ? "has-text" : ""}`}
            onClick={submit}
            disabled={disabled || !question.trim()}
            title="Gửi (Enter)"
          >
            <ArrowUp size={17} />
          </button>
        )}
      </div>
    </div>
  );
}
