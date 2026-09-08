import { useEffect, useRef, useState } from "react";
import { ArrowUp, Square } from "lucide-react";

interface Props {
  onAsk: (question: string) => void;
  onStop?: () => void;
  asking: boolean;
}

/** Ô nhập câu hỏi kiểu ChatGPT: bo tròn, nút gửi chuyển thành nút Dừng (Stop) khi đang chạy. */
export default function Composer({ onAsk, onStop, asking }: Props) {
  const [question, setQuestion] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`;
    }
  }, [question]);

  // Tự động focus vào ô input khi mở trang hoặc khi AI trả lời xong
  useEffect(() => {
    textareaRef.current?.focus();
  }, [asking]);

  const submit = () => {
    const q = question.trim();
    if (!q || asking) return;
    onAsk(q);
    setQuestion("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.focus();
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
              if (!asking) {
                submit();
              }
            }
          }}
          placeholder={
            asking
              ? "Chakra AI đang phản hồi… (bạn vẫn có thể nhập tiếp)"
              : "Nhập câu hỏi hoặc yêu cầu bất kỳ cho Chakra AI…"
          }
          rows={1}
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
            disabled={asking || !question.trim()}
            title="Gửi (Enter)"
          >
            <ArrowUp size={17} />
          </button>
        )}
      </div>
    </div>
  );
}
