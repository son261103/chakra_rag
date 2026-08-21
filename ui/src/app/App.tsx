import { useEffect, useRef, useState } from "react";
import { askStream } from "../api/client";
import type { AskResponse } from "../api/types";
import { useIngestStatus } from "../hooks/useIngestStatus";
import Sidebar from "../components/sidebar/Sidebar";
import ChatMessage from "../components/chat/ChatMessage";
import StreamingMessage, { type StreamingState } from "../components/chat/StreamingMessage";
import Composer from "../components/chat/Composer";
import SourceDrawer from "../components/sources/SourceDrawer";

export interface QAEntry {
  question: string;
  response: AskResponse;
}

const SUGGESTIONS = [
  "Nhân viên chính thức được nghỉ phép bao nhiêu ngày mỗi năm?",
  "Mức hoàn phí đào tạo tối đa cho nhân viên dưới 2 năm là bao nhiêu?",
  "Pull request cần ít nhất bao nhiêu approval trước khi merge?",
  "Công ty có chính sách hỗ trợ mua laptop cá nhân không?",
];

const EMPTY_STREAM = (question: string): StreamingState => ({
  question,
  reasoning: "",
  thinkingActive: false,
  thinkingDurationMs: null,
  toolCalls: [],
  answer: "",
  error: null,
});

export default function App() {
  const { files, progress, ready, error: ingestError, refresh } = useIngestStatus();
  const [history, setHistory] = useState<QAEntry[]>([]);
  const [streaming, setStreaming] = useState<StreamingState | null>(null);
  // Trạng thái "đang hỏi" tách riêng khỏi streaming: khi stream lỗi (provider
  // 502/503, mất kết nối) streaming vẫn giữ để hiện lỗi trong tin nhắn, nhưng
  // asking phải được giải phóng để người dùng hỏi tiếp được ngay.
  const [asking, setAsking] = useState(false);
  const [selectedChunkId, setSelectedChunkId] = useState<string | null>(null);
  const [askError, setAskError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Thời điểm bắt đầu suy luận — để tính "Đã suy luận trong Xs".
  const thinkStartRef = useRef<number | null>(null);

  const handleAsk = async (question: string) => {
    if (asking) return;
    setAskError(null);
    thinkStartRef.current = null;
    setStreaming(EMPTY_STREAM(question));
    setAsking(true);

    const endThinking = () => {
      setStreaming((s) => {
        if (!s || !s.thinkingActive) return s;
        const dur = thinkStartRef.current !== null ? Date.now() - thinkStartRef.current : null;
        return { ...s, thinkingActive: false, thinkingDurationMs: dur };
      });
    };

    try {
      await askStream(question, (ev) => {
        switch (ev.type) {
          case "thinking":
            setStreaming((s) => {
              if (!s) return s;
              if (thinkStartRef.current === null) thinkStartRef.current = Date.now();
              return { ...s, reasoning: s.reasoning + ev.delta, thinkingActive: true };
            });
            break;
          case "tool_start":
            endThinking();
            setStreaming((s) =>
              s
                ? {
                    ...s,
                    toolCalls: [
                      ...s.toolCalls,
                      { trace: { query: "", n_results: 0, chunk_ids: [], max_score: 0 }, running: true },
                    ],
                  }
                : s
            );
            break;
          case "tool_call":
            setStreaming((s) => {
              if (!s) return s;
              const calls = [...s.toolCalls];
              const idx = Math.min(ev.index - 1, calls.length - 1);
              if (idx >= 0) {
                calls[idx] = {
                  trace: {
                    query: ev.query,
                    n_results: ev.n_results,
                    chunk_ids: ev.chunk_ids,
                    max_score: ev.max_score,
                  },
                  running: false,
                };
              }
              return { ...s, toolCalls: calls };
            });
            break;
          case "answer":
            endThinking();
            setStreaming((s) => (s ? { ...s, answer: s.answer + ev.delta } : s));
            break;
          case "answer_clear":
            // Backend phát hiện phần answer vừa stream chỉ là lời dẫn trung gian
            // trước một tool_call → xóa để câu trả lời cuối không bị dính rác.
            setStreaming((s) => (s ? { ...s, answer: "" } : s));
            break;
          case "error":
            endThinking();
            setStreaming((s) => (s ? { ...s, error: ev.message } : s));
            // Stream đã chết — giải phóng asking để hỏi tiếp được ngay.
            setAsking(false);
            break;
          case "done": {
            // Event cuối: payload đã verify → chuyển vào lịch sử.
            const { type: _t, ...response } = ev;
            setHistory((h) => [...h, { question, response }]);
            setStreaming(null);
            setAsking(false);
            break;
          }
        }
      });
    } catch (e) {
      setStreaming(null);
      setAskError(String(e));
      setAsking(false);
    }
    // Nếu stream kết thúc mà chưa có event "done" (mất kết nối giữa chừng)
    setStreaming((s) => {
      if (s && !s.error) return { ...s, error: "Mất kết nối — chưa nhận được câu trả lời hoàn chỉnh." };
      return s;
    });
    setAsking(false);
  };

  // Tin nhắn mới / streaming thay đổi thì cuộn xuống đáy.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [history.length, streaming]);

  const error = ingestError ?? askError;

  return (
    <div className="layout">
      <Sidebar files={files} progress={progress} onUploaded={refresh} />

      <main className="chat-area">
        <div className="chat-scroll">
          {history.length === 0 && !asking && (
            <div className="empty-state">
              <div className="empty-logo">✦</div>
              <h2>Tôi có thể giúp gì?</h2>
              <p>Hỏi bất cứ điều gì về tài liệu nội bộ — tôi sẽ tra cứu và trích dẫn nguồn.</p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="suggestion-chip" onClick={() => handleAsk(s)} disabled={!ready}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {history.map((entry, i) => (
            <ChatMessage key={i} entry={entry} onCitationClick={setSelectedChunkId} />
          ))}

          {streaming && <StreamingMessage state={streaming} />}

          {error && <div className="error-banner">{error}</div>}
          <div ref={bottomRef} />
        </div>

        <Composer onAsk={handleAsk} disabled={!ready || asking} asking={asking} ready={ready} />
      </main>

      <SourceDrawer chunkId={selectedChunkId} onClose={() => setSelectedChunkId(null)} />
    </div>
  );
}
