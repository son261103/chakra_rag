import { AlertCircle, X } from "lucide-react";
import { formatErrorMessage } from "../../exceptions";

interface Props {
  error: string | null;
  onDismiss?: () => void;
  className?: string;
}
export default function ErrorBanner({ error, onDismiss, className = "" }: Props) {
  if (!error) return null;
  const message = formatErrorMessage(error);

  return (
    <div
      className={`flex items-center gap-2 rounded-xl border border-red-200 dark:border-red/35 bg-bg-card px-3 py-2 text-[12.5px] text-text shadow-xs ${className}`}
      role="alert"
    >
      <div className="flex size-5 shrink-0 items-center justify-center rounded-md bg-red-100 dark:bg-red-500/20 text-red-600 dark:text-red-400">
        <AlertCircle size={12} />
      </div>
      <span className="flex-1 truncate font-medium text-red-700 dark:text-red-400">
        {message}
      </span>
      {onDismiss && (
        <button
          type="button"
          className="flex size-5 shrink-0 items-center justify-center rounded-md text-muted hover:bg-bg-elevated hover:text-text transition-colors cursor-pointer"
          onClick={onDismiss}
          aria-label="Đóng thông báo lỗi"
        >
          <X size={12} />
        </button>
      )}
    </div>
  );
}
