import { useState } from "react";

interface Props {
  onAsk: (question: string) => void;
  disabled: boolean;
  asking: boolean;
  ready: boolean;
}

/** Ô nhập câu hỏi kiểu ChatGPT: bo tròn, nút gửi tròn, hint trạng thái. */
export default function Composer({ onAsk, disabled, asking, ready }: Props) {
  const [question, setQuestion] = useState("");

  const submit = () => {
    const q = question.trim();
    if (!q || disabled) return;
    onAsk(q);
    setQuestion("");
  };

  return (
    <div className="composer-wrap">
      <div className="composer">
        <textarea
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
          className="send-btn"
          onClick={submit}
          disabled={disabled || !question.trim()}
          title="Gửi (Enter)"
        >
          ↑
        </button>
      </div>
      <div className="composer-hint">
        Câu trả lời luôn kèm trích dẫn nguồn · Enter để gửi, Shift+Enter xuống dòng
      </div>
    </div>
  );
}
