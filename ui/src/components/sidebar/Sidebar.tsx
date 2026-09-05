import { FileText, Plus, Settings, Sparkles, Trash2 } from "lucide-react";
import type { ConversationSummary } from "../../api/types";
import ThemeToggle from "../theme/ThemeToggle";

interface Props {
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  onNewChat: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onOpenFiles: () => void;
  onOpenSettings: () => void;
}

/** Sidebar: brand → chat mới → tài liệu → hội thoại → footer. */
export default function Sidebar({
  conversations,
  activeConversationId,
  onNewChat,
  onSelectConversation,
  onDeleteConversation,
  onOpenFiles,
  onOpenSettings,
}: Props) {
  return (
    <aside className="sidebar">
      <div className="sidebar-top">
        <div className="sidebar-brand">
          <span className="brand-logo">
            <Sparkles size={15} />
          </span>
          <span className="brand-name">Chakra RAG</span>
          <ThemeToggle />
          <button
            type="button"
            className="settings-icon-btn"
            onClick={onOpenSettings}
            title="Cài đặt Model & API Key"
            aria-label="Cài đặt LLM"
          >
            <Settings size={15} />
          </button>
        </div>

        <button className="new-chat-btn" onClick={onNewChat} type="button">
          <Plus size={15} />
          Chat mới
        </button>

        <button className="files-btn" onClick={onOpenFiles} type="button">
          <FileText size={15} />
          Tài liệu
        </button>
      </div>

      <section className="panel chat-panel">
        <div className="block-label">Hội thoại · {conversations.length}</div>
        <ul className="chat-list side-scroll">
          {conversations.map((c) => (
            <li
              key={c.id}
              className={`chat-item ${c.id === activeConversationId ? "active" : ""}`}
            >
              <button
                type="button"
                className="chat-item-main"
                onClick={() => onSelectConversation(c.id)}
                title={c.title}
              >
                <span className="chat-item-title">{c.title}</span>
              </button>
              <button
                type="button"
                className="chat-item-delete"
                title="Xóa hội thoại"
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteConversation(c.id);
                }}
              >
                <Trash2 size={13} />
              </button>
            </li>
          ))}
          {conversations.length === 0 && (
            <li className="file-empty">Chưa có hội thoại — bấm Chat mới</li>
          )}
        </ul>
      </section>
    </aside>
  );
}
