export type ToastType = "error" | "warning" | "success" | "info";

export interface ToastOptions {
  id?: string;
  type?: ToastType;
  title: string;
  description?: string;
  duration?: number; // ms, default 4500 (0 = persistent)
  action?: {
    label: string;
    onClick: () => void;
  };
}

export interface ToastItem extends Required<Omit<ToastOptions, "action">> {
  action?: {
    label: string;
    onClick: () => void;
  };
  createdAt: number;
  count: number; // For deduplication multiplier (e.g. ×2)
  isLeaving?: boolean;
}

type ToastListener = (toasts: ToastItem[]) => void;

class ToastStore {
  private toasts: ToastItem[] = [];
  private autoDismissTimers: Map<string, any> = new Map();
  private listeners: Set<ToastListener> = new Set();
  subscribe(listener: ToastListener): () => void {
    this.listeners.add(listener);
    listener(this.toasts);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify() {
    for (const listener of this.listeners) {
      listener([...this.toasts]);
    }
  }

  show(options: ToastOptions): string {
    const id = options.id || `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const duration = options.duration ?? (options.type === "error" ? 5000 : 4000);
    const type = options.type || "info";

    // Deduplication: nếu cùng title và type trong vòng 4s, tăng count thay vì spam toast mới
    const existingIndex = this.toasts.findIndex(
      (t) => !t.isLeaving && t.title === options.title && t.type === type
    );

    if (existingIndex >= 0) {
      const existing = this.toasts[existingIndex];
      const updated: ToastItem = {
        ...existing,
        description: options.description ?? existing.description,
        count: existing.count + 1,
        createdAt: Date.now(),
      };
      this.toasts[existingIndex] = updated;

      // Reset timer
      this.clearTimer(existing.id);
      if (duration > 0) {
        this.startTimer(existing.id, duration);
      }

      this.notify();
      return existing.id;
    }

    const newToast: ToastItem = {
      id,
      type,
      title: options.title,
      description: options.description || "",
      duration,
      action: options.action,
      createdAt: Date.now(),
      count: 1,
    };

    // Giữ tối đa 4 toasts đồng thời để giao diện luôn thanh thoát như iOS
    if (this.toasts.length >= 4) {
      const oldest = this.toasts[0];
      this.dismiss(oldest.id);
    }

    this.toasts.push(newToast);

    if (duration > 0) {
      this.startTimer(id, duration);
    }

    this.notify();
    return id;
  }

  dismiss(id?: string) {
    if (!id) {
      // Dismiss all
      for (const t of this.toasts) {
        this.clearTimer(t.id);
      }
      this.toasts = [];
      this.notify();
      return;
    }

    const index = this.toasts.findIndex((t) => t.id === id);
    if (index === -1) return;

    this.clearTimer(id);

    // Đánh dấu isLeaving để chạy animation trượt lên trước khi gỡ hoàn toàn
    this.toasts[index] = { ...this.toasts[index], isLeaving: true };
    this.notify();

    setTimeout(() => {
      this.toasts = this.toasts.filter((t) => t.id !== id);
      this.notify();
    }, 280);
  }

  pauseTimer(id: string) {
    this.clearTimer(id);
  }

  resumeTimer(id: string, remainingTime = 2500) {
    const toast = this.toasts.find((t) => t.id === id);
    if (!toast || toast.duration === 0 || toast.isLeaving) return;
    this.clearTimer(id);
    this.startTimer(id, remainingTime);
  }

  private startTimer(id: string, ms: number) {
    this.clearTimer(id);
    const timer = setTimeout(() => {
      this.dismiss(id);
    }, ms);
    this.autoDismissTimers.set(id, timer);
  }

  private clearTimer(id: string) {
    const timer = this.autoDismissTimers.get(id);
    if (timer) {
      clearTimeout(timer);
      this.autoDismissTimers.delete(id);
    }
  }
}

export const toastStore = new ToastStore();

export function toast(options: ToastOptions): string {
  return toastStore.show(options);
}

toast.error = (title: string, options?: Omit<ToastOptions, "title" | "type"> | string) => {
  if (typeof options === "string") {
    return toastStore.show({ title, description: options, type: "error" });
  }
  return toastStore.show({ ...options, title, type: "error" });
};

toast.warning = (title: string, options?: Omit<ToastOptions, "title" | "type"> | string) => {
  if (typeof options === "string") {
    return toastStore.show({ title, description: options, type: "warning" });
  }
  return toastStore.show({ ...options, title, type: "warning" });
};

toast.success = (title: string, options?: Omit<ToastOptions, "title" | "type"> | string) => {
  if (typeof options === "string") {
    return toastStore.show({ title, description: options, type: "success" });
  }
  return toastStore.show({ ...options, title, type: "success" });
};

toast.info = (title: string, options?: Omit<ToastOptions, "title" | "type"> | string) => {
  if (typeof options === "string") {
    return toastStore.show({ title, description: options, type: "info" });
  }
  return toastStore.show({ ...options, title, type: "info" });
};

toast.dismiss = (id?: string) => {
  toastStore.dismiss(id);
};
