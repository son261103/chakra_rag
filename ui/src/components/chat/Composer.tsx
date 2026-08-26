import { useEffect, useRef, useState } from "react";
import { ArrowUp } from "lucide-react";

interface Props {
  onAsk: (question: string) => void;
  disabled: boolean;
  asking: boolean;
  ready: boolean;
}

/** Ô nhập câu hỏi kiểu ChatGPT: bo tròn, nút gửi tròn, hint trạng thái. */
export default function Composer({ onAsk, disabled, asking, ready }: Props) {
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
    if (!q || disabled) return;
    onAsk(q);
    setQuestion("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  return (
    <div className="composer-wrap">
      <div className="composer">
        <textarea
          ref={textareaRef}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={
            !ready
              ? "Chờ index tài liệu sẵn sàng…"
              : asking
                ? "Đang tra cứu tài liệu…"
                : "Hỏi về tài liệu nội bộ…"
          }
          rows={1}
          disabled={disabled}
        />
        <button
          type="button"
          className="send-btn"
          onClick={submit}
          disabled={disabled || !question.trim()}
          title="Gửi (Enter)"
        >
          <ArrowUp size={17} />
        </button>
      </div>
    </div>
  );
}
