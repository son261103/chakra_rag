import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Plus,
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

  const [detailItem, setDetailItem] = useState<IntegrationEntry | null>(null);
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
      setDetailItem(null);
    }
  }, [open, fetchIntegrations]);

  useEffect(() => {
    if (!detailItem) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDetailItem(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [detailItem]);

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
      setDetailItem((prev) => (prev && prev.id === id ? { ...prev, is_active: true } : prev));
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
      if (detailItem?.id === id) setDetailItem(null);
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
            <h3 className="font-semibold text-text">Cài đặt tích hợp LLM</h3>
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
              className="drawer-action-btn"
            >
              <Plus size={15} />
              <span>Thêm cấu hình tích hợp mới</span>
            </button>
          )}

          {/* Integrations Table / List */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between px-1 pt-1 text-muted">
              <span className="block-label p-0">Danh sách tích hợp · {integrations.length}</span>
              {loading && <Loader2 size={13} className="animate-spin text-muted" />}
            </div>

            <div className="flex flex-col gap-2">
              {integrations.map((item) => {
                const isBusy = busyId === item.id;
                return (
                  <div
                    key={item.id}
                    className={`group relative flex flex-col gap-2 rounded-xl border p-3 transition-all ${
                      item.is_active
                        ? "border-accent/40 bg-accent/[0.04]"
                        : "border-border bg-bg-card hover:border-border/90 hover:bg-bg-elevated/30"
                    }`}
                  >
                    {/* Hàng 1: Trạng thái active + Tên + Badge/Nút kích hoạt + Action buttons */}
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <span
                          className={`size-2 shrink-0 rounded-full transition-all ${
                            item.is_active
                              ? "bg-green shadow-[0_0_6px_rgba(34,197,94,0.7)]"
                              : "bg-muted/30"
                          }`}
                          title={item.is_active ? "Đang kích hoạt" : "Chưa kích hoạt"}
                        />
                        <strong
                          className="truncate text-[13.5px] font-semibold text-text"
                          title={item.name}
                        >
                          {item.name}
                        </strong>
                        {item.is_active && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-green/15 border border-green/20 px-2 py-0.2 text-[10.5px] font-medium text-green">
                            Đang dùng
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-1 shrink-0">
                        {!item.is_active && (
                          <button
                            type="button"
                            onClick={() => handleActivate(item.id)}
                            disabled={isBusy}
                            className="rounded-md border border-border/80 bg-bg-elevated px-2 py-0.5 text-[11px] font-medium text-muted transition hover:border-accent hover:text-accent hover:bg-accent/5 disabled:opacity-50"
                            title="Kích hoạt cấu hình này"
                          >
                            {isBusy ? <Loader2 size={12} className="animate-spin" /> : "Kích hoạt"}
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => setDetailItem(item)}
                          className="rounded p-1 text-muted transition hover:bg-bg-soft hover:text-text"
                          title="Xem chi tiết"
                          aria-label="Xem chi tiết"
                        >
                          <Eye size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => startEdit(item)}
                          className="rounded p-1 text-muted transition hover:bg-bg-soft hover:text-text"
                          title="Sửa cấu hình"
                          aria-label="Sửa cấu hình"
                        >
                          <Wrench size={13} />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(item.id, item.name)}
                          disabled={isBusy}
                          className="rounded p-1 text-muted transition hover:bg-bg-soft hover:text-red disabled:opacity-50"
                          title="Xóa cấu hình"
                          aria-label="Xóa cấu hình"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </div>

                    {/* Hàng 2: Model pill + Base URL */}
                    <div className="flex items-center gap-2 pl-4 text-[12px] text-muted">
                      <code
                        className="rounded bg-bg-soft px-1.5 py-0.5 text-[11px] font-mono text-accent truncate max-w-[180px]"
                        title={item.model}
                      >
                        {item.model}
                      </code>
                      <span className="text-muted/40">•</span>
                      <span
                        className="truncate font-mono text-[11.5px] text-muted/90"
                        title={item.base_url}
                      >
                        {item.base_url.replace(/^https?:\/\//, "")}
                      </span>
                    </div>
                  </div>
                );
              })}

              {integrations.length === 0 && !loading && (
                <div className="flex flex-col items-center justify-center gap-1.5 rounded-xl border border-dashed border-border py-8 text-center text-muted">
                  <div className="text-[13px] font-medium text-text">Chưa có cấu hình nào</div>
                  <div className="text-[11.5px] text-muted">
                    Bấm &quot;Thêm cấu hình tích hợp mới&quot; để thiết lập LLM
                  </div>
                </div>
              )}

              {integrations.length > 0 && !activeIntegration && (
                <div className="rounded-lg bg-bg-soft/60 px-3 py-2 text-[11.5px] text-muted">
                  Chưa kích hoạt cấu hình nào — hệ thống đang dùng model mặc định từ <code>.env</code>.
                </div>
              )}
            </div>
          </div>
        </div>
      </aside>

      {/* Detail Modal Popup */}
      {detailItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-[2px]">
          <div
            className="fixed inset-0"
            onClick={() => setDetailItem(null)}
            aria-hidden="true"
          />
          <div
            className="relative z-10 w-full max-w-[460px] rounded-2xl border border-border bg-bg-card shadow-2xl p-5 flex flex-col gap-4"
            role="dialog"
            aria-label="Chi tiết tích hợp LLM"
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-border/70 pb-3">
              <div className="flex items-center gap-2.5">
                <span className="grid size-7 place-items-center rounded-lg bg-accent text-accent-contrast">
                  <Eye size={15} />
                </span>
                <div>
                  <h4 className="text-[14px] font-semibold text-text">Chi tiết tích hợp</h4>
                  <p className="text-[11.5px] text-muted truncate max-w-[280px]">{detailItem.name}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setDetailItem(null)}
                className="drawer-close"
                aria-label="Đóng"
              >
                <X size={15} />
              </button>
            </div>

            {/* Content Details */}
            <div className="flex flex-col gap-2.5 text-[12.5px]">
              <div className="flex items-center justify-between rounded-lg bg-bg-elevated/60 px-3 py-2">
                <span className="text-muted">Trạng thái</span>
                {detailItem.is_active ? (
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-green/15 border border-green/20 px-2.5 py-0.5 text-[11px] font-medium text-green">
                    <span className="size-1.5 rounded-full bg-green animate-pulse" />
                    Đang kích hoạt
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded-full bg-bg-soft px-2.5 py-0.5 text-[11px] font-medium text-muted">
                    Chưa kích hoạt
                  </span>
                )}
              </div>

              <div className="flex flex-col gap-1 rounded-lg bg-bg-elevated/60 px-3 py-2">
                <span className="text-[11px] font-medium uppercase tracking-wider text-muted">Tên tích hợp</span>
                <span className="font-medium text-text">{detailItem.name}</span>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div className="flex flex-col gap-1 rounded-lg bg-bg-elevated/60 px-3 py-2">
                  <span className="text-[11px] font-medium uppercase tracking-wider text-muted">Provider</span>
                  <span className="font-mono text-text capitalize text-[12px]">{detailItem.provider || "openai"}</span>
                </div>
                <div className="flex flex-col gap-1 rounded-lg bg-bg-elevated/60 px-3 py-2">
                  <span className="text-[11px] font-medium uppercase tracking-wider text-muted">Model</span>
                  <code className="font-mono text-accent truncate text-[12px]" title={detailItem.model}>
                    {detailItem.model}
                  </code>
                </div>
              </div>

              <div className="flex flex-col gap-1 rounded-lg bg-bg-elevated/60 px-3 py-2">
                <span className="text-[11px] font-medium uppercase tracking-wider text-muted">Endpoint (Base URL)</span>
                <span className="font-mono text-text break-all text-[12px]">{detailItem.base_url}</span>
              </div>

              <div className="flex flex-col gap-1 rounded-lg bg-bg-elevated/60 px-3 py-2">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-medium uppercase tracking-wider text-muted">API Key</span>
                  <span className="text-[11px] text-muted">
                    {detailItem.has_api_key ? "Đã lưu (mã hóa)" : "Không cần key"}
                  </span>
                </div>
                <div className="flex items-center gap-2 font-mono text-[12px] text-text">
                  <KeyRound size={13} className="text-muted shrink-0" />
                  <span className="truncate">{detailItem.has_api_key ? detailItem.masked_api_key : "(Trống)"}</span>
                </div>
              </div>

              {(detailItem.created_at || detailItem.updated_at) && (
                <div className="flex items-center justify-between px-1 text-[11px] text-muted">
                  {detailItem.created_at && (
                    <span>Tạo: {new Date(detailItem.created_at).toLocaleDateString("vi-VN")}</span>
                  )}
                  {detailItem.updated_at && (
                    <span>Cập nhật: {new Date(detailItem.updated_at).toLocaleDateString("vi-VN")}</span>
                  )}
                </div>
              )}
            </div>

            {/* Footer Buttons */}
            <div className="flex items-center justify-end gap-2 border-t border-border/70 pt-3">
              {!detailItem.is_active && (
                <button
                  type="button"
                  onClick={async () => {
                    await handleActivate(detailItem.id);
                    setDetailItem((prev) => (prev ? { ...prev, is_active: true } : null));
                  }}
                  disabled={busyId === detailItem.id}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-[12px] font-medium text-accent-contrast transition hover:brightness-105 disabled:opacity-50"
                >
                  {busyId === detailItem.id ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <CheckCircle2 size={13} />
                  )}
                  Kích hoạt cấu hình này
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  const item = detailItem;
                  setDetailItem(null);
                  startEdit(item);
                }}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-bg-elevated px-3 py-1.5 text-[12px] font-medium text-text transition hover:bg-bg-soft"
              >
                <Wrench size={13} />
                Chỉnh sửa
              </button>
              <button
                type="button"
                onClick={() => setDetailItem(null)}
                className="rounded-lg px-3 py-1.5 text-[12px] font-medium text-muted hover:text-text transition"
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
