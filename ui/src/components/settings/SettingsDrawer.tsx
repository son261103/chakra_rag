import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Plus,
  Radio,
  Settings,
  Trash2,
  Wrench,
  X,
  Zap,
} from "lucide-react";
import {
  activateIntegration,
  createIntegration,
  deleteIntegration,
  listIntegrations,
  testIntegration,
  updateIntegration,
} from "../../api/client";
import type { CreateIntegrationPayload, IntegrationEntry, UpdateIntegrationPayload } from "../../api/types";

interface Props {
  open: boolean;
  onClose: () => void;
  onChanged?: () => void;
}

const COMMON_BASE_URLS = [
  { label: "OpenAI", url: "https://api.openai.com/v1" },
  { label: "OpenRouter", url: "https://openrouter.ai/api/v1" },
  { label: "Vilao AI", url: "https://api.vilao.ai/v1" },
  { label: "Ollama (Local)", url: "http://localhost:11434/v1" },
];

const COMMON_MODELS = [
  "gpt-4o-mini",
  "gpt-4o",
  "llmx/partner/deepseek-v4-flash",
  "deepseek-chat",
  "qwen2.5:7b",
];

export default function SettingsDrawer({ open, onClose, onChanged }: Props) {
  const [integrations, setIntegrations] = useState<IntegrationEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Form state
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formName, setFormName] = useState("");
  const [formProvider, setFormProvider] = useState("openai");
  const [formBaseUrl, setFormBaseUrl] = useState("https://api.openai.com/v1");
  const [formModel, setFormModel] = useState("gpt-4o-mini");
  const [formApiKey, setFormApiKey] = useState("");
  const [formIsActive, setFormIsActive] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);

  // Test state
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const fetchIntegrations = useCallback(async () => {
    setLoading(true);
    setActionError(null);
    try {
      const list = await listIntegrations();
      setIntegrations(list);
    } catch (e) {
      setActionError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      void fetchIntegrations();
      setFormOpen(false);
      setEditingId(null);
      setTestResult(null);
    }
  }, [open, fetchIntegrations]);

  if (!open) return null;

  const activeIntegration = integrations.find((i) => i.is_active);

  const resetForm = () => {
    setEditingId(null);
    setFormName("");
    setFormProvider("openai");
    setFormBaseUrl("https://api.openai.com/v1");
    setFormModel("gpt-4o-mini");
    setFormApiKey("");
    setFormIsActive(false);
    setShowApiKey(false);
    setTestResult(null);
    setFormOpen(false);
  };

  const startAdd = () => {
    setEditingId(null);
    setFormName("");
    setFormProvider("openai");
    setFormBaseUrl("https://api.openai.com/v1");
    setFormModel("gpt-4o-mini");
    setFormApiKey("");
    setFormIsActive(integrations.length === 0);
    setShowApiKey(false);
    setTestResult(null);
    setFormOpen(true);
  };

  const startEdit = (item: IntegrationEntry) => {
    setEditingId(item.id);
    setFormName(item.name);
    setFormProvider(item.provider || "openai");
    setFormBaseUrl(item.base_url);
    setFormModel(item.model);
    setFormApiKey(""); // Để trống để giữ nguyên key cũ
    setFormIsActive(item.is_active);
    setShowApiKey(false);
    setTestResult(null);
    setFormOpen(true);
  };

  const handleActivate = async (id: string) => {
    setBusyId(id);
    setActionError(null);
    try {
      await activateIntegration(id);
      await fetchIntegrations();
      onChanged?.();
    } catch (e) {
      setActionError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!window.confirm(`Xóa cấu hình tích hợp «${name}»?`)) return;
    setBusyId(id);
    setActionError(null);
    try {
      await deleteIntegration(id);
      await fetchIntegrations();
      if (editingId === id) resetForm();
      onChanged?.();
    } catch (e) {
      setActionError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  const handleTestConnection = async () => {
    if (!formModel.trim()) {
      setTestResult({ ok: false, msg: "Vui lòng nhập Model trước khi kiểm tra." });
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const res = await testIntegration({
        model: formModel.trim(),
        base_url: formBaseUrl.trim() || "https://api.openai.com/v1",
        api_key: formApiKey.trim() || undefined,
        integration_id: editingId || undefined,
      });
      setTestResult({
        ok: true,
        msg: `Kết nối thành công (${res.latency_ms}ms)! Model phản hồi: "${res.response || "OK"}"`,
      });
    } catch (e) {
      setTestResult({ ok: false, msg: String(e).replace(/^Error:\s*/, "") });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formName.trim() || !formModel.trim()) {
      setActionError("Vui lòng điền Tên tích hợp và Model.");
      return;
    }

    setBusyId("form-saving");
    setActionError(null);
    try {
      if (editingId) {
        const payload: UpdateIntegrationPayload = {
          name: formName.trim(),
          provider: formProvider.trim(),
          base_url: formBaseUrl.trim(),
          model: formModel.trim(),
          is_active: formIsActive,
        };
        if (formApiKey.trim()) {
          payload.api_key = formApiKey.trim();
        }
        await updateIntegration(editingId, payload);
      } else {
        const payload: CreateIntegrationPayload = {
          name: formName.trim(),
          provider: formProvider.trim(),
          base_url: formBaseUrl.trim(),
          model: formModel.trim(),
          api_key: formApiKey.trim(),
          is_active: formIsActive,
        };
        await createIntegration(payload);
      }
      resetForm();
      await fetchIntegrations();
      onChanged?.();
    } catch (err) {
      setActionError(String(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer settings-drawer" role="dialog" aria-label="Cài đặt tích hợp LLM">
        {/* Header */}
        <div className="drawer-header">
          <div className="flex items-center gap-2.5">
            <span className="grid size-7 place-items-center rounded-lg bg-accent text-accent-contrast">
              <Settings size={15} />
            </span>
            <div>
              <h3 className="font-semibold text-text">Cài đặt tích hợp LLM</h3>
              <p className="text-[12px] text-muted">Điều chỉnh model, API key và endpoint OpenAI-compatible</p>
            </div>
          </div>
          <button type="button" className="drawer-close" onClick={onClose} aria-label="Đóng">
            <X size={15} />
          </button>
        </div>

        {/* Body */}
        <div className="drawer-body flex flex-col gap-4 overflow-y-auto p-5">
          {actionError && (
            <div className="flex items-start gap-2 rounded-lg border border-red/20 bg-red/10 p-3 text-[13px] text-red">
              <AlertCircle size={16} className="mt-0.5 shrink-0" />
              <div className="flex-1">{actionError}</div>
              <button
                type="button"
                className="text-red hover:opacity-80"
                onClick={() => setActionError(null)}
              >
                <X size={14} />
              </button>
            </div>
          )}

          {/* Active Integration Banner */}
          <div className="rounded-xl border border-accent/25 bg-accent/5 p-3.5 text-[13px]">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                Đang kích hoạt sử dụng
              </span>
              <span className="inline-flex items-center gap-1 rounded-full bg-green/15 px-2 py-0.5 text-[11px] font-medium text-green">
                <span className="size-1.5 rounded-full bg-green" />
                Live
              </span>
            </div>
            {activeIntegration ? (
              <div className="mt-2 flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <strong className="text-[14px] text-text">{activeIntegration.name}</strong>
                  <code className="rounded bg-bg-soft px-1.5 py-0.5 text-[12px] font-mono text-accent">
                    {activeIntegration.model}
                  </code>
                </div>
                <div className="flex flex-wrap items-center gap-x-3 text-[12px] text-muted">
                  <span>URL: {activeIntegration.base_url}</span>
                  <span>•</span>
                  <span>
                    API Key:{" "}
                    {activeIntegration.has_api_key
                      ? activeIntegration.masked_api_key
                      : "(Không cần key)"}
                  </span>
                </div>
              </div>
            ) : (
              <div className="mt-2 text-muted">
                Chưa chọn tích hợp nào — đang dùng fallback từ <code>.env</code>
              </div>
            )}
          </div>

          {/* Add / Edit Form (Toggleable) */}
          {formOpen ? (
            <form onSubmit={handleSave} className="flex flex-col gap-3 rounded-xl border border-border bg-bg-elevated p-4">
              <div className="flex items-center justify-between border-b border-border pb-2.5">
                <h4 className="text-[13.5px] font-semibold text-text">
                  {editingId ? "Chỉnh sửa tích hợp" : "Thêm tích hợp LLM mới"}
                </h4>
                <button
                  type="button"
                  onClick={resetForm}
                  className="text-[12px] text-muted hover:text-text"
                >
                  Đóng form
                </button>
              </div>

              {/* Tên tích hợp */}
              <div className="flex flex-col gap-1">
                <label className="text-[12px] font-medium text-muted">Tên tích hợp *</label>
                <input
                  type="text"
                  required
                  placeholder="Ví dụ: OpenAI GPT-4o-mini, Vilao AI..."
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className="rounded-lg border border-border bg-bg-card px-3 py-2 text-[13px] text-text placeholder:text-muted focus:border-accent"
                />
              </div>

              {/* Base URL */}
              <div className="flex flex-col gap-1">
                <label className="text-[12px] font-medium text-muted">Base URL (OpenAI-compatible) *</label>
                <input
                  type="url"
                  required
                  placeholder="https://api.openai.com/v1"
                  value={formBaseUrl}
                  onChange={(e) => setFormBaseUrl(e.target.value)}
                  className="rounded-lg border border-border bg-bg-card px-3 py-2 text-[13px] font-mono text-text placeholder:text-muted focus:border-accent"
                />
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {COMMON_BASE_URLS.map((u) => (
                    <button
                      key={u.url}
                      type="button"
                      onClick={() => setFormBaseUrl(u.url)}
                      className="rounded border border-border bg-bg-soft px-1.5 py-0.5 text-[11px] text-muted hover:border-accent hover:text-text"
                    >
                      {u.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Model */}
              <div className="flex flex-col gap-1">
                <label className="text-[12px] font-medium text-muted">Tên Model *</label>
                <input
                  type="text"
                  required
                  placeholder="gpt-4o-mini, deepseek-chat..."
                  value={formModel}
                  onChange={(e) => setFormModel(e.target.value)}
                  className="rounded-lg border border-border bg-bg-card px-3 py-2 text-[13px] font-mono text-text placeholder:text-muted focus:border-accent"
                />
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {COMMON_MODELS.map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setFormModel(m)}
                      className="rounded border border-border bg-bg-soft px-1.5 py-0.5 text-[11px] font-mono text-muted hover:border-accent hover:text-text"
                    >
                      {m}
                    </button>
                  ))}
                </div>
              </div>

              {/* API Key */}
              <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between">
                  <label className="text-[12px] font-medium text-muted">
                    API Key {editingId ? "(Để trống nếu không đổi)" : ""}
                  </label>
                  <span className="text-[11px] text-muted">Mã hóa DEK/KEK 🔒</span>
                </div>
                <div className="relative">
                  <input
                    type={showApiKey ? "text" : "password"}
                    placeholder={
                      editingId
                        ? "(Giữ nguyên API key hiện tại đã lưu)"
                        : "sk-..."
                    }
                    value={formApiKey}
                    onChange={(e) => setFormApiKey(e.target.value)}
                    className="w-full rounded-lg border border-border bg-bg-card py-2 pl-3 pr-9 text-[13px] font-mono text-text placeholder:text-muted focus:border-accent"
                  />
                  <button
                    type="button"
                    onClick={() => setShowApiKey((s) => !s)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-text"
                    title={showApiKey ? "Ẩn key" : "Hiện key"}
                  >
                    {showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
                <p className="text-[11px] text-muted">
                  Key được mã hóa an toàn trong database trước khi lưu, giải mã theo cơ chế Envelope Encryption bằng ENCRYPTION_KEY từ .env.
                </p>
              </div>

              {/* Checkbox kích hoạt ngay */}
              <label className="flex cursor-pointer items-center gap-2 pt-1 text-[13px] text-text">
                <input
                  type="checkbox"
                  checked={formIsActive}
                  onChange={(e) => setFormIsActive(e.target.checked)}
                  className="size-4 rounded border-border text-accent focus:ring-accent"
                />
                Đặt làm tích hợp mặc định ngay sau khi lưu
              </label>

              {/* Test result message */}
              {testResult && (
                <div
                  className={`flex items-start gap-2 rounded-lg border p-2.5 text-[12px] ${
                    testResult.ok
                      ? "border-green/25 bg-green/10 text-green"
                      : "border-red/25 bg-red/10 text-red"
                  }`}
                >
                  {testResult.ok ? (
                    <CheckCircle2 size={15} className="mt-0.5 shrink-0" />
                  ) : (
                    <AlertCircle size={15} className="mt-0.5 shrink-0" />
                  )}
                  <span className="flex-1 leading-snug">{testResult.msg}</span>
                </div>
              )}

              {/* Form buttons */}
              <div className="flex items-center justify-between gap-2 pt-2">
                <button
                  type="button"
                  onClick={handleTestConnection}
                  disabled={testing || !formModel.trim()}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-bg-card px-3 py-1.5 text-[12.5px] font-medium text-text hover:border-accent disabled:opacity-50"
                >
                  {testing ? (
                    <>
                      <Loader2 size={13} className="animate-spin" />
                      Đang kiểm tra...
                    </>
                  ) : (
                    <>
                      <Zap size={13} />
                      Kiểm tra kết nối
                    </>
                  )}
                </button>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={resetForm}
                    className="rounded-lg px-3 py-1.5 text-[12.5px] text-muted hover:text-text"
                  >
                    Hủy
                  </button>
                  <button
                    type="submit"
                    disabled={busyId === "form-saving"}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-4 py-1.5 text-[12.5px] font-medium text-accent-contrast transition hover:brightness-105 disabled:opacity-50"
                  >
                    {busyId === "form-saving" && <Loader2 size={13} className="animate-spin" />}
                    {editingId ? "Cập nhật" : "Lưu tích hợp"}
                  </button>
                </div>
              </div>
            </form>
          ) : (
            <button
              type="button"
              onClick={startAdd}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-border py-2.5 text-[13px] font-medium text-muted transition hover:border-accent hover:text-accent"
            >
              <Plus size={15} />
              Thêm cấu hình tích hợp mới
            </button>
          )}

          {/* Integrations Table / List */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between px-1">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                Danh sách tích hợp ({integrations.length})
              </span>
              {loading && <Loader2 size={13} className="animate-spin text-muted" />}
            </div>

            <div className="flex flex-col gap-2">
              {integrations.map((item) => {
                const isBusy = busyId === item.id;
                return (
                  <div
                    key={item.id}
                    className={`flex flex-col gap-2 rounded-xl border p-3.5 transition ${
                      item.is_active
                        ? "border-accent/40 bg-accent/5"
                        : "border-border bg-bg-card hover:border-border/80"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <button
                          type="button"
                          onClick={() => !item.is_active && handleActivate(item.id)}
                          disabled={item.is_active || isBusy}
                          className={`flex items-center gap-1 text-[12px] font-medium transition ${
                            item.is_active
                              ? "cursor-default text-green"
                              : "cursor-pointer text-muted hover:text-accent"
                          }`}
                          title={item.is_active ? "Đang sử dụng" : "Bấm để kích hoạt"}
                        >
                          {item.is_active ? (
                            <CheckCircle2 size={15} className="text-green shrink-0" />
                          ) : (
                            <Radio size={15} className="shrink-0" />
                          )}
                        </button>
                        <strong className="truncate text-[13.5px] text-text" title={item.name}>
                          {item.name}
                        </strong>
                      </div>

                      <div className="flex items-center gap-1 shrink-0">
                        {!item.is_active && (
                          <button
                            type="button"
                            onClick={() => handleActivate(item.id)}
                            disabled={isBusy}
                            className="rounded px-2 py-1 text-[11px] font-medium text-muted hover:bg-bg-soft hover:text-accent"
                            title="Đặt làm mặc định"
                          >
                            {isBusy ? <Loader2 size={12} className="animate-spin" /> : "Sử dụng"}
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => startEdit(item)}
                          className="rounded p-1 text-muted hover:bg-bg-soft hover:text-text"
                          title="Sửa cấu hình này"
                        >
                          <Wrench size={13} />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(item.id, item.name)}
                          disabled={isBusy}
                          className="rounded p-1 text-muted hover:bg-bg-soft hover:text-red"
                          title="Xóa cấu hình này"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 gap-1 text-[12px] text-muted">
                      <div className="flex items-center gap-1.5 font-mono">
                        <span className="text-[11px] uppercase tracking-wide text-muted">Model:</span>
                        <span className="rounded bg-bg-soft px-1.5 py-0.5 text-[11.5px] text-text">
                          {item.model}
                        </span>
                      </div>
                      <div className="truncate font-mono text-[11.5px]" title={item.base_url}>
                        <span className="text-[11px] uppercase tracking-wide text-muted">URL: </span>
                        {item.base_url}
                      </div>
                      <div className="flex items-center gap-1 font-mono text-[11.5px]">
                        <KeyRound size={12} className="text-muted shrink-0" />
                        <span>Key: </span>
                        <span>{item.has_api_key ? item.masked_api_key : "(Trống)"}</span>
                      </div>
                    </div>
                  </div>
                );
              })}

              {integrations.length === 0 && !loading && (
                <div className="rounded-xl border border-dashed border-border p-6 text-center text-[13px] text-muted">
                  Chưa có cấu hình nào. Bấm nút phía trên để thêm tích hợp mới.
                </div>
              )}
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
