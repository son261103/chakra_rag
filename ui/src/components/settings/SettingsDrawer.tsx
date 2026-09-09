/**
 * Drawer Cài đặt Model & API Key — shell với 2 tab:
 * - "Tích hợp LLM": các model chat (agent trả lời).
 * - "Tích hợp Embedding": model nhúng vector (API + chiều vector).
 * Nội dung list + modal dùng chung `IntegrationPanel`.
 */
import { useState } from "react";
import { Settings, X } from "lucide-react";
import IntegrationPanel, { type IntegrationKind } from "./IntegrationPanel";

interface Props {
  open: boolean;
  onClose: () => void;
  onChanged?: () => void;
}

export default function SettingsDrawer({ open, onClose, onChanged }: Props) {
  const [tab, setTab] = useState<IntegrationKind>("llm");

  if (!open) return null;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer settings-drawer" role="dialog" aria-label="Cài đặt Model & API Key">
        {/* Header */}
        <div className="drawer-header">
          <div className="flex items-center gap-2.5">
            <span className="grid size-7 place-items-center rounded-lg bg-accent text-accent-contrast">
              <Settings size={15} />
            </span>
            <h3 className="font-semibold text-text">Cài đặt Model &amp; API Key</h3>
          </div>
          <button type="button" className="drawer-close" onClick={onClose} aria-label="Đóng">
            <X size={15} />
          </button>
        </div>

        {/* Tabs: LLM | Embedding */}
        <div className="px-5 pt-4">
          <div className="flex gap-1 rounded-xl bg-bg-elevated p-1" role="tablist">
            {(["llm", "embedding"] as const).map((k) => (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={tab === k}
                onClick={() => setTab(k)}
                className={`flex-1 cursor-pointer rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition ${
                  tab === k
                    ? "bg-bg-card text-text shadow-sm"
                    : "text-muted hover:text-text"
                }`}
              >
                {k === "llm" ? "Tích hợp LLM" : "Tích hợp Embedding"}
              </button>
            ))}
          </div>
        </div>

        {/* Body */}
        <div className="drawer-body flex flex-col gap-4 overflow-y-auto p-5">
          <IntegrationPanel key={tab} kind={tab} onChanged={onChanged} />
        </div>
      </aside>
    </>
  );
}
