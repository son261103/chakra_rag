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

export default function SettingsDrawer({ open, onClose, onChanged }: Props) {
  const [integrations, setIntegrations] = useState<IntegrationEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [detailItem, setDetailItem] = useState<IntegrationEntry | null>(null);
  const [modalMode, setModalMode] = useState<"view" | "edit" | "create" | null>(null);
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

  const closeModal = useCallback(() => {
    setModalMode(null);
    setDetailItem(null);
    setTestResult(null);
    setTesting(false);
    setActionError(null);
  }, []);

  useEffect(() => {
    if (open) {
      void fetchIntegrations();
      closeModal();
    } else {
      closeModal();
    }
  }, [open, fetchIntegrations, closeModal]);

  useEffect(() => {
    if (!modalMode) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeModal();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [modalMode, closeModal]);

  if (!open) return null;

  const activeIntegration = integrations.find((i) => i.is_active);

  const openViewModal = (item: IntegrationEntry) => {
    setDetailItem(item);
    setModalMode("view");
    setActionError(null);
    setTestResult(null);
  };

  const openEditModal = (item: IntegrationEntry) => {
    setDetailItem(item);
    setEditingId(item.id);
    setFormName(item.name);
    setFormProvider(item.provider || "openai");
    setFormBaseUrl(item.base_url);
    setFormModel(item.model);
    setFormApiKey("");
    setFormIsActive(item.is_active);
    setShowApiKey(false);
    setTestResult(null);
    setActionError(null);
    setModalMode("edit");
  };

  const openCreateModal = () => {
    setDetailItem(null);
    setEditingId(null);
    setFormName("");
    setFormProvider("openai");
    setFormBaseUrl("https://api.openai.com/v1");
    setFormModel("gpt-4o-mini");
    setFormApiKey("");
    setFormIsActive(integrations.length === 0);
    setShowApiKey(false);
    setTestResult(null);
    setActionError(null);
    setModalMode("create");
  };

  const handleActivate = async (id: string) => {
    setBusyId(id);
    setActionError(null);
    try {
      await activateIntegration(id);
      const updatedList = await listIntegrations();
      setIntegrations(updatedList);
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
      if (detailItem?.id === id) closeModal();
      await fetchIntegrations();
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
        const updatedList = await listIntegrations();
        setIntegrations(updatedList);
        const updatedItem = updatedList.find((x) => x.id === editingId) || null;
        setDetailItem(updatedItem);
        setModalMode(updatedItem ? "view" : null);
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
        const updatedList = await listIntegrations();
        setIntegrations(updatedList);
        closeModal();
      }
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

          {/* Add integration button */}
          <button
            type="button"
            onClick={openCreateModal}
            className="drawer-action-btn"
          >
            <Plus size={15} />
            <span>Thêm cấu hình tích hợp mới</span>
          </button>

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
                    className={`group relative flex flex-col gap-1.5 rounded-xl border p-3 transition-all ${
                      item.is_active
                        ? "border-border/80 bg-bg-card/90"
                        : "border-border/50 bg-bg-card/40 hover:border-border/80 hover:bg-bg-card/70"
                    }`}
                  >
                    {/* Hàng 1: Trạng thái active (chấm tròn) + Tên + Action buttons */}
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (!item.is_active) handleActivate(item.id);
                          }}
                          disabled={item.is_active || isBusy}
                          className="p-1 -m-1 cursor-pointer rounded-full transition-transform hover:scale-125 disabled:cursor-default"
                          title={item.is_active ? "Đang kích hoạt" : "Bấm để kích hoạt"}
                        >
                          {isBusy ? (
                            <Loader2 size={10} className="animate-spin text-accent" />
                          ) : (
                            <span
                              className={`block size-2 rounded-full transition-all ${
                                item.is_active
                                  ? "bg-green shadow-[0_0_6px_rgba(34,197,94,0.7)]"
                                  : "bg-muted/40 hover:bg-muted"
                              }`}
                            />
                          )}
                        </button>
                        <span
                          className="truncate text-[13.5px] font-medium text-text cursor-pointer hover:text-accent transition-colors"
                          onClick={() => openViewModal(item)}
                          title={item.name}
                        >
                          {item.name}
                        </span>
                      </div>

                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          type="button"
                          onClick={() => openViewModal(item)}
                          className="rounded-lg p-1.5 text-muted transition hover:bg-bg-soft hover:text-text"
                          title="Xem & chỉnh sửa chi tiết"
                          aria-label="Xem & chỉnh sửa chi tiết"
                        >
                          <Eye size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(item.id, item.name)}
                          disabled={isBusy}
                          className="rounded-lg p-1.5 text-muted transition hover:bg-bg-soft hover:text-red disabled:opacity-50"
                          title="Xóa cấu hình"
                          aria-label="Xóa cấu hình"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>

                    {/* Hàng 2: Model - căn thẳng hàng với chữ tên */}
                    <div
                      className="flex items-center pl-[18px] text-[11.5px] text-muted cursor-pointer"
                      onClick={() => openViewModal(item)}
                      title="Bấm để xem chi tiết"
                    >
                      <span className="truncate font-mono text-muted/75">{item.model}</span>
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

      {/* Modal Popup (Chi tiết / Chỉnh sửa / Thêm mới) */}
      {modalMode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/60 backdrop-blur-[3px] animate-in fade-in duration-150">
          <div
            className="fixed inset-0"
            onClick={closeModal}
            aria-hidden="true"
          />
          <div
            className="relative z-10 w-full max-w-[580px] rounded-2xl border border-border bg-bg-card shadow-2xl overflow-hidden flex flex-col max-h-[90vh]"
            role="dialog"
            aria-label="Cấu hình tích hợp LLM"
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-border/70 p-5 shrink-0">
              <div className="flex items-center gap-3 min-w-0">
                <span className="grid size-9 place-items-center rounded-xl bg-accent text-accent-contrast shrink-0">
                  {modalMode === "view" ? (
                    <Eye size={17} />
                  ) : modalMode === "edit" ? (
                    <Wrench size={17} />
                  ) : (
                    <Plus size={17} />
                  )}
                </span>
                <div className="min-w-0">
                  <h4 className="text-[15px] font-semibold text-text truncate">
                    {modalMode === "view"
                      ? "Chi tiết cấu hình tích hợp"
                      : modalMode === "edit"
                        ? "Chỉnh sửa cấu hình tích hợp"
                        : "Thêm cấu hình tích hợp mới"}
                  </h4>
                  <p className="text-[12px] text-muted truncate">
                    {modalMode === "view"
                      ? detailItem?.name || "Thông tin kết nối LLM"
                      : modalMode === "edit"
                        ? `Đang sửa: ${detailItem?.name || ""}`
                        : "Kết nối model qua endpoint chuẩn OpenAI-compatible"}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={closeModal}
                className="drawer-close"
                aria-label="Đóng"
              >
                <X size={16} />
              </button>
            </div>

            {/* Modal Error Banner if any */}
            {actionError && (
              <div className="mx-5 mt-4 flex items-start gap-2 rounded-xl border border-red/25 bg-red/10 p-3 text-[12.5px] text-red shrink-0">
                <AlertCircle size={15} className="mt-0.5 shrink-0" />
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

            {/* Modal Body */}
            <div className="p-5 sm:p-6 overflow-y-auto flex-1 flex flex-col gap-4">
              {modalMode === "view" && detailItem ? (
                /* ================= VIEW MODE ================= */
                <div className="flex flex-col gap-3 text-[13px]">
                  {/* Trạng thái */}
                  <div className="flex items-center justify-between rounded-xl bg-bg-elevated/60 border border-border/60 px-3.5 py-2.5">
                    <span className="text-muted font-medium">Trạng thái sử dụng</span>
                    {detailItem.is_active ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-green/15 border border-green/30 px-3 py-0.5 text-[11.5px] font-semibold text-green">
                        <span className="size-2 rounded-full bg-green shadow-[0_0_6px_rgba(34,197,94,0.7)]" />
                        Đang kích hoạt
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-bg-soft border border-border/80 px-3 py-0.5 text-[11.5px] font-medium text-muted">
                        Chưa kích hoạt
                      </span>
                    )}
                  </div>

                  {/* Tên & Provider */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div className="flex flex-col gap-1 rounded-xl bg-bg-elevated/50 border border-border/60 p-3">
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                        Tên cấu hình
                      </span>
                      <span className="font-semibold text-text text-[13.5px] truncate">
                        {detailItem.name}
                      </span>
                    </div>
                    <div className="flex flex-col gap-1 rounded-xl bg-bg-elevated/50 border border-border/60 p-3">
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                        Nhà cung cấp (Provider)
                      </span>
                      <span className="font-mono text-text capitalize text-[13px]">
                        {detailItem.provider || "openai"}
                      </span>
                    </div>
                  </div>

                  {/* Model */}
                  <div className="flex flex-col gap-1.5 rounded-xl bg-bg-elevated/50 border border-border/60 p-3">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                      Tên Model
                    </span>
                    <code className="font-mono text-accent text-[13px] break-all select-all font-medium">
                      {detailItem.model}
                    </code>
                  </div>

                  {/* Base URL */}
                  <div className="flex flex-col gap-1.5 rounded-xl bg-bg-elevated/50 border border-border/60 p-3">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                      Endpoint (Base URL)
                    </span>
                    <span className="font-mono text-text break-all text-[12.5px] select-all">
                      {detailItem.base_url}
                    </span>
                  </div>

                  {/* API Key */}
                  <div className="flex flex-col gap-1.5 rounded-xl bg-bg-elevated/50 border border-border/60 p-3">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                      API Key
                    </span>
                    <div className="flex items-center gap-2 font-mono text-[12.5px] text-text">
                      <KeyRound size={14} className="text-muted shrink-0" />
                      <span className="truncate">
                        {detailItem.has_api_key ? detailItem.masked_api_key : "(Trống)"}
                      </span>
                    </div>
                  </div>

                  {/* Ngày tạo / cập nhật */}
                  {(detailItem.created_at || detailItem.updated_at) && (
                    <div className="flex items-center justify-between px-1 text-[11.5px] text-muted pt-1">
                      {detailItem.created_at && (
                        <span>Tạo: {new Date(detailItem.created_at).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })}</span>
                      )}
                      {detailItem.updated_at && (
                        <span>Cập nhật: {new Date(detailItem.updated_at).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })}</span>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                /* ================= EDIT / CREATE FORM ================= */
                <form id="integration-modal-form" onSubmit={handleSave} className="flex flex-col gap-4">
                  {/* Tên tích hợp */}
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[12px] font-semibold text-muted">Tên tích hợp *</label>
                    <input
                      type="text"
                      required
                      placeholder="Ví dụ: Vilao AI, OpenAI GPT-4o-mini..."
                      value={formName}
                      onChange={(e) => setFormName(e.target.value)}
                      className="rounded-xl border border-border bg-bg-card px-3.5 py-2.5 text-[13px] text-text placeholder:text-muted focus:border-accent"
                    />
                  </div>

                  {/* Base URL */}
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[12px] font-semibold text-muted">
                      Base URL (OpenAI-compatible) *
                    </label>
                    <input
                      type="url"
                      required
                      placeholder="https://api.openai.com/v1"
                      value={formBaseUrl}
                      onChange={(e) => setFormBaseUrl(e.target.value)}
                      className="rounded-xl border border-border bg-bg-card px-3.5 py-2.5 font-mono text-[12.5px] text-text placeholder:text-muted focus:border-accent"
                    />
                  </div>

                  {/* Model */}
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[12px] font-semibold text-muted">Tên Model *</label>
                    <input
                      type="text"
                      required
                      placeholder="gpt-4o-mini hoặc llmx/partner/deepseek-v4-flash"
                      value={formModel}
                      onChange={(e) => setFormModel(e.target.value)}
                      className="rounded-xl border border-border bg-bg-card px-3.5 py-2.5 font-mono text-[12.5px] text-text placeholder:text-muted focus:border-accent"
                    />
                   </div>

                  {/* API Key */}
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[12px] font-semibold text-muted">API Key</label>
                    <div className="relative">
                      <input
                        type={showApiKey ? "text" : "password"}
                        placeholder={modalMode === "edit" ? "••••••••••••••••" : "sk-..."}
                        value={formApiKey}
                        onChange={(e) => setFormApiKey(e.target.value)}
                        className="w-full rounded-xl border border-border bg-bg-card px-3.5 py-2.5 pr-10 font-mono text-[12.5px] text-text placeholder:text-muted focus:border-accent"
                      />
                      <button
                        type="button"
                        onClick={() => setShowApiKey((v) => !v)}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-text p-1"
                        tabIndex={-1}
                        title={showApiKey ? "Ẩn key" : "Hiện key"}
                      >
                        {showApiKey ? <EyeOff size={15} /> : <Eye size={15} />}
                      </button>
                    </div>
                  </div>

                  {/* Default integration toggle */}
                  <div
                    className="flex items-center justify-between rounded-xl border border-border bg-bg-card px-3.5 py-2.5 cursor-pointer select-none transition hover:border-border/90 hover:bg-bg-elevated/40"
                    onClick={() => setFormIsActive(!formIsActive)}
                    role="switch"
                    aria-checked={formIsActive}
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === " " || e.key === "Enter") {
                        e.preventDefault();
                        setFormIsActive(!formIsActive);
                      }
                    }}
                  >
                    <div className="flex flex-col gap-0.5">
                      <span className="text-[13px] font-medium text-text">Đặt làm mặc định</span>
                      <span className="text-[11.5px] text-muted">Tự động kích hoạt ngay sau khi lưu</span>
                    </div>
                    <div
                      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-200 ease-in-out ${
                        formIsActive ? "bg-accent" : "bg-bg-elevated border border-border/80"
                      }`}
                    >
                      <span
                        className={`inline-block size-3.5 transform rounded-full shadow-xs transition duration-200 ease-in-out ${
                          formIsActive ? "translate-x-4 bg-accent-contrast" : "translate-x-0.5 bg-muted/70"
                        }`}
                      />
                    </div>
                  </div>

                   {/* Test result status */}
                   {testResult && (
                     <div
                       className={`rounded-xl border p-3 text-[12px] flex items-start gap-2 ${
                         testResult.ok
                           ? "border-green/30 bg-green/10 text-green"
                           : "border-red/30 bg-red/10 text-red"
                       }`}
                     >
                       <AlertCircle size={15} className="mt-0.5 shrink-0" />
                       <div className="flex-1">{testResult.msg}</div>
                     </div>
                   )}
                 </form>
               )}
             </div>

             {/* Modal Footer Buttons */}
             <div className="p-4 sm:p-5 border-t border-border/70 bg-bg-card/95 flex items-center justify-between gap-2 shrink-0">
               {modalMode === "view" ? (
                 <>
                   <div>
                     {!detailItem?.is_active && (
                       <button
                         type="button"
                         onClick={() => detailItem && handleActivate(detailItem.id)}
                         disabled={busyId === detailItem?.id}
                         className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-3.5 py-2 text-[12.5px] font-medium text-accent-contrast transition hover:brightness-105 disabled:opacity-50"
                       >
                         {busyId === detailItem?.id ? (
                           <Loader2 size={13} className="animate-spin" />
                         ) : (
                           <CheckCircle2 size={14} />
                         )}
                         Kích hoạt cấu hình này
                       </button>
                     )}
                   </div>
                   <div className="flex items-center gap-2">
                     <button
                       type="button"
                       onClick={() => detailItem && openEditModal(detailItem)}
                       className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-bg-elevated px-4 py-2 text-[12.5px] font-medium text-text transition hover:bg-bg-soft"
                     >
                       <Wrench size={13} />
                       Chỉnh sửa
                     </button>
                     <button
                       type="button"
                       onClick={closeModal}
                       className="rounded-xl px-4 py-2 text-[12.5px] font-medium text-muted hover:text-text transition"
                     >
                       Đóng
                     </button>
                   </div>
                 </>
               ) : (
                 <>
                   <button
                     type="button"
                     onClick={handleTestConnection}
                     disabled={testing}
                     className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-bg-elevated px-3.5 py-2 text-[12px] font-medium text-text transition hover:bg-bg-soft disabled:opacity-50"
                   >
                     {testing ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
                     Kiểm tra kết nối
                   </button>
                   <div className="flex items-center gap-2">
                     <button
                       type="button"
                       onClick={() => {
                         if (modalMode === "edit" && detailItem) {
                           setModalMode("view");
                         } else {
                           closeModal();
                         }
                       }}
                       className="rounded-xl px-4 py-2 text-[12.5px] font-medium text-muted hover:text-text transition"
                     >
                       Hủy
                     </button>
                     <button
                       type="submit"
                       form="integration-modal-form"
                       disabled={busyId === "form-saving"}
                       className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-4 py-2 text-[12.5px] font-medium text-accent-contrast transition hover:brightness-105 disabled:opacity-50"
                     >
                       {busyId === "form-saving" && <Loader2 size={13} className="animate-spin" />}
                       {modalMode === "edit" ? "Lưu thay đổi" : "Thêm cấu hình"}
                     </button>
                   </div>
                 </>
               )}
             </div>
           </div>
         </div>
       )}
    </>
  );
}
