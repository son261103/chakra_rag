import { toastStore, type ToastType } from "../components/toast/toast";
import { formatErrorMessage } from "./format";

export interface NotifyOptions {
  duration?: number;
  action?: {
    label: string;
    onClick: () => void;
  };
}

/**
 * Dispatcher tập trung cho phản hồi UI (Error, Warning, Success, Info).
 * Tự động format các lỗi thô thành thông báo tiếng Việt ngắn gọn, chuẩn 1 dòng.
 */
export const notify = {
  error(errOrTitle: unknown, contextOrOptions?: string | NotifyOptions): string {
    let title: string;
    let options: NotifyOptions | undefined;

    if (typeof contextOrOptions === "string") {
      title = formatErrorMessage(errOrTitle, contextOrOptions);
    } else {
      title = formatErrorMessage(errOrTitle);
      options = contextOrOptions;
    }

    return toastStore.show({
      type: "error",
      title,
      duration: options?.duration,
      action: options?.action,
    });
  },

  warning(title: string, options?: NotifyOptions): string {
    return toastStore.show({
      type: "warning",
      title,
      duration: options?.duration,
      action: options?.action,
    });
  },

  success(title: string, options?: NotifyOptions): string {
    return toastStore.show({
      type: "success",
      title,
      duration: options?.duration,
      action: options?.action,
    });
  },

  info(title: string, options?: NotifyOptions): string {
    return toastStore.show({
      type: "info",
      title,
      duration: options?.duration,
      action: options?.action,
    });
  },

  dismiss(id?: string): void {
    toastStore.dismiss(id);
  },
};

export type { ToastType };
