import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Info,
  Loader2,
  RotateCw,
  X,
} from "lucide-react";
import { toastStore, type ToastItem, type ToastType } from "./toast";

export type ConnectionStatus = "connected" | "connecting" | "reconnecting";

interface ToastContainerProps {
  connectionStatus?: ConnectionStatus;
  onRetryConnection?: () => void;
}

export default function ToastContainer({
  connectionStatus = "connected",
  onRetryConnection,
}: ToastContainerProps) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  // Trạng thái hiển thị banner Dynamic Island khi kết nối thay đổi
  const [showRestoredIsland, setShowRestoredIsland] = useState(false);
  const prevStatusRef = useRef<ConnectionStatus>(connectionStatus);
  const restoredTimerRef = useRef<any>(null);

  useEffect(() => {
    return toastStore.subscribe(setToasts);
  }, []);

  // Khi chuyển từ "reconnecting" -> "connected", hiện pill "Đã kết nối lại" trong 2.5s rồi tự ẩn mượt mà
  useEffect(() => {
    if (prevStatusRef.current === "reconnecting" && connectionStatus === "connected") {
      setShowRestoredIsland(true);
      if (restoredTimerRef.current) clearTimeout(restoredTimerRef.current);
      restoredTimerRef.current = setTimeout(() => {
        setShowRestoredIsland(false);
      }, 2600);
    } else if (connectionStatus === "reconnecting") {
      setShowRestoredIsland(false);
      if (restoredTimerRef.current) clearTimeout(restoredTimerRef.current);
    }
    prevStatusRef.current = connectionStatus;
  }, [connectionStatus]);

  const isReconnecting = connectionStatus === "reconnecting";
  const showConnectionIsland = isReconnecting || showRestoredIsland;

  return (
    <div
      className="absolute top-3 sm:top-4 left-1/2 -translate-x-1/2 z-[100] pointer-events-none flex flex-col items-center gap-1.5 w-max max-w-[calc(100vw-2rem)] px-4"
      aria-live="polite"
    >
      {/* 1. Trạng thái kết nối server */}
      {showConnectionIsland && (
        <div
          className={`pointer-events-auto flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium backdrop-blur-md transition-all duration-200 border shadow-[0_2px_10px_rgba(0,0,0,0.05)] dark:shadow-[0_8px_20px_rgba(0,0,0,0.4)] ${
            isReconnecting
              ? "bg-bg-card border-amber-300/80 dark:border-amber-500/30 text-text animate-dynamic-island-down"
              : "bg-bg-card border-emerald-300/80 dark:border-accent/40 text-text animate-dynamic-island-pulse"
          }`}
          role="status"
        >
          {isReconnecting ? (
            <>
              <Loader2 size={12} className="animate-spin text-amber-600 dark:text-amber-400 shrink-0" />
              <span className="text-[12px] font-medium text-text">
                Đang kết nối lại…
              </span>
              {onRetryConnection && (
                <button
                  type="button"
                  onClick={onRetryConnection}
                  title="Thử lại ngay"
                  aria-label="Thử lại kết nối"
                  className="ml-0.5 flex size-5 cursor-pointer items-center justify-center rounded-full bg-amber-100 hover:bg-amber-200 dark:bg-amber-500/20 dark:hover:bg-amber-500/30 text-amber-800 dark:text-amber-200 transition-colors"
                >
                  <RotateCw size={10} />
                </button>
              )}
            </>
          ) : (
            <>
              <CheckCircle2 size={12} className="text-emerald-600 dark:text-accent shrink-0" />
              <span className="text-[12px] font-medium text-text">Đã kết nối lại</span>
            </>
          )}
        </div>
      )}

      {/* 2. Danh sách Toasts */}
      {toasts.map((toast) => (
        <ToastCard key={toast.id} toast={toast} />
      ))}
    </div>
  );
}

function ToastCard({ toast }: { toast: ToastItem }) {
  const [isHovered, setIsHovered] = useState(false);

  const handleMouseEnter = () => {
    setIsHovered(true);
    toastStore.pauseTimer(toast.id);
  };

  const handleMouseLeave = () => {
    setIsHovered(false);
    toastStore.resumeTimer(toast.id, 2500);
  };

  const config = TOAST_CONFIG[toast.type];
  const Icon = config.icon;

  return (
    <div
      className={`pointer-events-auto flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium backdrop-blur-md transition-all duration-200 border bg-bg-card shadow-[0_2px_10px_rgba(0,0,0,0.05)] dark:shadow-[0_8px_20px_rgba(0,0,0,0.4)] ${
        toast.isLeaving ? "animate-dynamic-island-up" : "animate-dynamic-island-down"
      } ${isHovered ? "brightness-105" : ""} ${config.borderClass}`}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      role="alert"
    >
      <Icon size={12} className={`shrink-0 ${config.iconClass}`} />

      <span
        className="text-[12px] font-medium text-text truncate max-w-[280px] sm:max-w-[340px]"
        title={toast.description ? `${toast.title}\n${toast.description}` : toast.title}
      >
        {toast.title}
      </span>

      {toast.count > 1 && (
        <span className="rounded-full bg-bg-elevated px-1.5 py-0.2 text-[10px] font-mono font-bold text-muted border border-border/80 shrink-0">
          ×{toast.count}
        </span>
      )}

      {toast.action && (
        <button
          type="button"
          onClick={() => {
            toast.action?.onClick();
            toastStore.dismiss(toast.id);
          }}
          className="cursor-pointer rounded-full bg-accent px-2 py-0.5 text-[10.5px] font-semibold text-accent-contrast hover:bg-accent-hover transition-colors shrink-0"
        >
          {toast.action.label}
        </button>
      )}

      <button
        type="button"
        onClick={() => toastStore.dismiss(toast.id)}
        className="flex size-5 shrink-0 items-center justify-center rounded-full text-muted hover:bg-bg-elevated hover:text-text transition-colors cursor-pointer ml-0.5"
        aria-label="Đóng thông báo"
      >
        <X size={11} />
      </button>
    </div>
  );
}

const TOAST_CONFIG: Record<
  ToastType,
  {
    icon: typeof AlertCircle;
    borderClass: string;
    iconClass: string;
  }
> = {
  error: {
    icon: AlertCircle,
    borderClass: "border-red-300/80 dark:border-red/40",
    iconClass: "text-red-600 dark:text-red-400",
  },
  warning: {
    icon: AlertTriangle,
    borderClass: "border-amber-300/80 dark:border-amber/40",
    iconClass: "text-amber-600 dark:text-amber-400",
  },
  success: {
    icon: CheckCircle2,
    borderClass: "border-emerald-300/80 dark:border-accent/40",
    iconClass: "text-emerald-600 dark:text-accent",
  },
  info: {
    icon: Info,
    borderClass: "border-border",
    iconClass: "text-muted",
  },
};
