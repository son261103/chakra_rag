import { useCallback, useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import {
  askStream,
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
} from "../api/client";
import type { AskResponse, ConversationSummary, FileEntry } from "../api/types";
import { useIngestStatus } from "../hooks/useIngestStatus";
import Sidebar from "../components/sidebar/Sidebar";
import ChatMessage from "../components/chat/ChatMessage";
import StreamingMessage, { type StreamingState } from "../components/chat/StreamingMessage";
import Composer from "../components/chat/Composer";
import SourceDrawer from "../components/sources/SourceDrawer";
import DocumentDrawer from "../components/sources/DocumentDrawer";
import FileDrawer from "../components/files/FileDrawer";

export interface QAEntry {
  question: string;
  response: AskResponse;
}

/** Câu hỏi gợi ý theo hướng “bán mình” cho nhà tuyển dụng — bám CV Phạm Lê Sơn. */
const SUGGESTIONS = [
  "Điểm mạnh nổi bật nhất của ứng viên Phạm Lê Sơn khi apply Backend / AI Engineer là gì?",
  "Kỹ năng LLM, RAG, GraphRAG và AI agent trong CV có thể pitch thế nào cho nhà tuyển dụng?",
  "Kinh nghiệm tại RedAI (multi-provider AI, BullMQ, FastAPI) chứng minh năng lực production ra sao?",
  "So với JD Junior AI / Backend, phần nào trong CV Sơn match mạnh và nên nhấn trong phỏng vấn?",
  "Dự án GraphRAG custom và agent orchestration harness có gì khác biệt, vì sao đáng chú ý?",
  "Học vấn + intern Java (Spring Boot) bổ trợ thế nào cho hướng Backend/AI Engineer của Sơn?",
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

function messagesToHistory(
  messages: { role: string; content: string; payload?: AskResponse | null }[]
): QAEntry[] {
  const entries: QAEntry[] = [];
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i];
    if (m.role !== "user") continue;
    const next = messages[i + 1];
    if (next?.role === "assistant") {
      const response: AskResponse =
        next.payload ??
        ({
          question: m.content,
          answer: next.content,
          mode: "agent",
          citations: [],
          invalid_citations: [],
          unsupported_claims: [],
          search_trace: [],
          reasoning: "",
          low_confidence: false,
          latency_ms: 0,
        } satisfies AskResponse);
      entries.push({ question: m.content, response: { ...response, question: m.content } });
    }
  }
  return entries;
}

export default function App() {
  const { files, progress, ready, error: ingestError, refresh } = useIngestStatus();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [history, setHistory] = useState<QAEntry[]>([]);
  const [streaming, setStreaming] = useState<StreamingState | null>(null);
  // Trạng thái "đang hỏi" tách riêng khỏi streaming: khi stream lỗi (provider
  // 502/503, mất kết nối) streaming vẫn giữ để hiện lỗi trong tin nhắn, nhưng
  // asking phải được giải phóng để người dùng hỏi tiếp được ngay.
  const [asking, setAsking] = useState(false);
  const [selectedChunkId, setSelectedChunkId] = useState<string | null>(null);
  const [inspectFile, setInspectFile] = useState<FileEntry | null>(null);
  const [fileDrawerOpen, setFileDrawerOpen] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Thời điểm bắt đầu suy luận — để tính "Đã suy luận trong Xs".
  const thinkStartRef = useRef<number | null>(null);
  const activeIdRef = useRef<string | null>(null);
  activeIdRef.current = activeConversationId;
  const abortRef = useRef<AbortController | null>(null);

  const refreshConversations = useCallback(async () => {
    try {
      const list = await listConversations();
      setConversations(list);
      return list;
    } catch (e) {
      setAskError(String(e));
      return [] as ConversationSummary[];
    }
  }, []);

  const loadConversation = useCallback(async (id: string) => {
    const detail = await getConversation(id);
    setActiveConversationId(id);
    setHistory(messagesToHistory(detail.messages));
    setStreaming(null);
    setAskError(null);
  }, []);

  // Mount: load danh sách hội thoại; nếu có thì mở cái mới nhất.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const list = await refreshConversations();
      if (cancelled) return;
      if (list.length > 0) {
        try {
          await loadConversation(list[0].id);
        } catch (e) {
          if (!cancelled) setAskError(String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshConversations, loadConversation]);

  const ensureConversation = async (): Promise<string> => {
    if (activeConversationId) return activeConversationId;
    const conv = await createConversation();
    setActiveConversationId(conv.id);
    setConversations((prev) => [conv, ...prev.filter((c) => c.id !== conv.id)]);
    return conv.id;
  };

  const handleNewChat = async () => {
    if (asking) return;
    try {
      const conv = await createConversation();
      setActiveConversationId(conv.id);
      setHistory([]);
      setStreaming(null);
      setAskError(null);
      setConversations((prev) => [conv, ...prev.filter((c) => c.id !== conv.id)]);
    } catch (e) {
      setAskError(String(e));
    }
  };

  const handleSelectConversation = async (id: string) => {
    if (asking || id === activeConversationId) return;
    try {
      await loadConversation(id);
    } catch (e) {
      setAskError(String(e));
    }
  };

  const handleDeleteConversation = async (id: string) => {
    if (asking) return;
    try {
      await deleteConversation(id);
      const remaining = conversations.filter((c) => c.id !== id);
      setConversations(remaining);
      if (activeConversationId === id) {
        if (remaining.length > 0) {
          await loadConversation(remaining[0].id);
        } else {
          setActiveConversationId(null);
          setHistory([]);
          setStreaming(null);
        }
      }
    } catch (e) {
      setAskError(String(e));
    }
  };

  const handleStop = () => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
      setAsking(false);
      setStreaming((s) => (s ? { ...s, thinkingActive: false } : null));
    }
  };

  const handleAsk = async (question: string) => {
    if (asking) return;
    setAskError(null);
    thinkStartRef.current = null;
    setStreaming(EMPTY_STREAM(question));
    setAsking(true);

    const abortController = new AbortController();
    abortRef.current = abortController;

    let conversationId: string;
    try {
      conversationId = await ensureConversation();
    } catch (e) {
      setStreaming(null);
      setAskError(String(e));
      setAsking(false);
      abortRef.current = null;
      return;
    }

    const endThinking = () => {
      setStreaming((s) => {
        if (!s || !s.thinkingActive) return s;
        const dur = thinkStartRef.current !== null ? Date.now() - thinkStartRef.current : null;
        return { ...s, thinkingActive: false, thinkingDurationMs: dur };
      });
    };

    try {
      await askStream(
        question,
        (ev) => {
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
              // Chỉ append nếu user vẫn đang xem đúng conversation này.
              if (activeIdRef.current === conversationId) {
                setHistory((h) => [...h, { question, response }]);
                setStreaming(null);
              }
              setAsking(false);
              void refreshConversations();
              break;
            }
          }
        },
        { conversationId, signal: abortController.signal }
      );
    } catch (e) {
      if (abortController.signal.aborted) {
        setAsking(false);
        abortRef.current = null;
        return;
      }
      setStreaming(null);
      setAskError(String(e));
      setAsking(false);
    } finally {
      abortRef.current = null;
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
      <Sidebar
        conversations={conversations}
        activeConversationId={activeConversationId}
        onNewChat={handleNewChat}
        onSelectConversation={handleSelectConversation}
        onDeleteConversation={handleDeleteConversation}
        onOpenFiles={() => setFileDrawerOpen(true)}
      />

      <main className="chat-area">
        <div className="chat-scroll side-scroll">
          {history.length === 0 && !asking && (
            <div className="empty-state">
              <div className="empty-logo">
                <Sparkles size={24} />
              </div>
              <h2>Tôi có thể giúp gì?</h2>
              <p>
                Upload CV (PDF) rồi hỏi để luyện pitch với nhà tuyển dụng — tôi tra cứu tài liệu và
                trích dẫn nguồn.
              </p>
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
            <ChatMessage
              key={`${entry.question}-${i}`}
              entry={entry}
              onCitationClick={(id) => {
                setInspectFile(null);
                setSelectedChunkId(id);
              }}
            />
          ))}

          {streaming && <StreamingMessage state={streaming} />}

          {error && <div className="error-banner">{error}</div>}
          <div ref={bottomRef} />
        </div>

        <Composer
          onAsk={handleAsk}
          onStop={handleStop}
          disabled={!ready}
          asking={asking}
          ready={ready}
        />
      </main>

      <SourceDrawer chunkId={selectedChunkId} onClose={() => setSelectedChunkId(null)} />
      <DocumentDrawer file={inspectFile} onClose={() => setInspectFile(null)} />
      <FileDrawer
        open={fileDrawerOpen}
        onClose={() => setFileDrawerOpen(false)}
        files={files}
        progress={progress}
        onUploaded={refresh}
        onInspectFile={(f) => {
          setFileDrawerOpen(false);
          setSelectedChunkId(null);
          setInspectFile(f);
        }}
      />
    </div>
  );
}
