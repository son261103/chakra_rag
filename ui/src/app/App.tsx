import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Code2,
  Compass,
  Cpu,
  Lightbulb,
  Sparkles,
  Terminal,
} from "lucide-react";
import {
  askStream,
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
} from "../api/client";
import type { AskResponse, ConversationSummary, FileEntry, StreamEvent, ToolTraceEntry } from "../api/types";
import { useIngestStatus } from "../hooks/useIngestStatus";
import Sidebar from "../components/sidebar/Sidebar";
import ChatMessage from "../components/chat/ChatMessage";
import StreamingMessage, { type StreamingState } from "../components/chat/StreamingMessage";
import Composer from "../components/chat/Composer";
import SourceDrawer from "../components/sources/SourceDrawer";
import DocumentDrawer from "../components/sources/DocumentDrawer";
import FileDrawer from "../components/files/FileDrawer";
import SettingsDrawer from "../components/settings/SettingsDrawer";

export interface QAEntry {
  question: string;
  response: AskResponse;
}

interface SuggestionItem {
  category: string;
  icon: typeof Sparkles;
  question: string;
}

/** Gợi ý khám phá và tương tác cùng Chakra AI. */
const SUGGESTIONS: SuggestionItem[] = [
  {
    category: "Lập trình thông minh",
    icon: Code2,
    question: "Viết giúp tôi một đoạn script Python tự động hóa tác vụ hàng ngày kèm giải thích",
  },
  {
    category: "Khám phá AI & RAG",
    icon: Sparkles,
    question: "AI Agent và RAG hoạt động phối hợp với nhau như thế nào trong thực tế?",
  },
  {
    category: "Ý tưởng sáng tạo",
    icon: Lightbulb,
    question: "Gợi ý 5 ý tưởng dự án công nghệ thú vị có thể tự xây dựng vào cuối tuần",
  },
  {
    category: "Tối ưu hóa hệ thống",
    icon: Cpu,
    question: "Làm sao để thiết kế hệ thống xử lý dữ liệu nhanh, mượt và ít tốn tài nguyên?",
  },
  {
    category: "Góc học hỏi vui vẻ",
    icon: Compass,
    question: "Giải thích một khái niệm công nghệ phức tạp theo cách dễ hiểu và hài hước nhất",
  },
  {
    category: "Kỹ thuật chuyên sâu",
    icon: Terminal,
    question: "Tóm tắt các công nghệ và dự án nổi bật mà tôi có thể tham khảo trong hệ thống",
  },
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

/** Placeholder trace khi tool vừa được gọi (chưa có kết quả) — shape theo loại tool. */
function emptyToolEntry(name: string): ToolTraceEntry {
  switch (name) {
    case "read_chunk":
      return { name: "read_chunk", chunk_id: "", doc: "", section: "", found: false };
    case "list_documents":
      return { name: "list_documents", n_docs: 0, docs: [] };
    default:
      return { name: "search_docs", query: "", n_results: 0, chunk_ids: [], max_score: 0 };
  }
}

/** Đổi tool_call event thành entry trace (bỏ type/index điều khiển). */
function toolEntryFromEvent(ev: Extract<StreamEvent, { type: "tool_call" }>): ToolTraceEntry {
  const { type: _type, index: _index, ...entry } = ev;
  return entry as ToolTraceEntry;
}

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
  const [settingsDrawerOpen, setSettingsDrawerOpen] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
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
                      toolCalls: [...s.toolCalls, { trace: emptyToolEntry(ev.name), running: true }],
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
                  calls[idx] = { trace: toolEntryFromEvent(ev), running: false };
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
              // Event cuối: payload đã verify → đưa vào streaming để nhả mượt nốt chữ rồi chuyển lịch sử
              const { type: _t, ...response } = ev;
              if (activeIdRef.current === conversationId) {
                setStreaming((s) =>
                  s
                    ? {
                        ...s,
                        answer: response.answer,
                        finalResponse: response,
                      }
                    : null
                );
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
      if (s && !s.error && !s.finalResponse) {
        return { ...s, error: "Mất kết nối — chưa nhận được câu trả lời hoàn chỉnh." };
      }
      return s;
    });
    setAsking(false);
  };

  // Tự động cuộn đáy thông minh: không dùng behavior smooth liên tục để tránh giật/nhảy khung hình
  useEffect(() => {
    const el = chatScrollRef.current;
    if (!el) return;

    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;

    // Chỉ tự cuộn nếu người dùng đang ở gần đáy (< 180px)
    if (distanceFromBottom < 180) {
      if (streaming) {
        // Trong khi stream: gán trực tiếp scrollTop để giao diện tĩnh lặng, không rung giật
        el.scrollTop = el.scrollHeight;
      } else {
        // Khi tin nhắn đã chốt hoặc đổi câu hỏi: cuộn mượt
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      }
    }
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
        onOpenSettings={() => setSettingsDrawerOpen(true)}
      />

      <main className="chat-area">
        <div ref={chatScrollRef} className="chat-scroll side-scroll">
          {history.length === 0 && !asking && (
            <div className="empty-state">
              {/* Logo & Headline */}
              <div className="empty-hero">
                <div className="empty-logo">
                  <Sparkles size={22} />
                </div>
                <h2>Tôi có thể giúp gì cho bạn?</h2>
              </div>

              {/* Suggestions grid */}
              <div className="suggestions">
                {SUGGESTIONS.map((s) => {
                  const Icon = s.icon;
                  return (
                    <button
                      key={s.question}
                      className="suggestion-chip"
                      onClick={() => handleAsk(s.question)}
                      disabled={!ready}
                      type="button"
                    >
                      <div className="suggestion-chip-header">
                        <div className="suggestion-chip-tag">
                          <span className="suggestion-chip-icon">
                            <Icon size={12} />
                          </span>
                          <span className="suggestion-chip-category">{s.category}</span>
                        </div>
                        <ArrowUpRight size={13} className="suggestion-chip-arrow" />
                      </div>
                      <p className="suggestion-chip-text">{s.question}</p>
                    </button>
                  );
                })}
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

          {streaming && (
            <StreamingMessage
              state={streaming}
              onComplete={(response) => {
                if (activeIdRef.current === response.conversation_id || !response.conversation_id) {
                  setHistory((h) => [...h, { question: streaming.question, response }]);
                  setStreaming(null);
                }
              }}
            />
          )}

          {error && <div className="error-banner">{error}</div>}
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
      <SettingsDrawer
        open={settingsDrawerOpen}
        onClose={() => setSettingsDrawerOpen(false)}
      />
    </div>
  );
}
