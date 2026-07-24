import type { ReactNode, ButtonHTMLAttributes, InputHTMLAttributes } from "react";
import { X } from "lucide-react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "agent";

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-accent-600 text-accent-50 shadow-pop enabled:hover:bg-accent-500 " +
    "disabled:opacity-40",
  secondary:
    "bg-surface-2 text-ink ring-1 ring-inset ring-line enabled:hover:bg-surface-3 " +
    "enabled:hover:ring-line-strong disabled:opacity-40",
  ghost:
    "text-ink-dim enabled:hover:bg-surface-2 enabled:hover:text-ink disabled:opacity-40",
  danger:
    "bg-rose-500/15 text-rose-200 ring-1 ring-inset ring-rose-500/40 " +
    "enabled:hover:bg-rose-500/25 disabled:opacity-40",
  agent:
    "text-agent-300 enabled:hover:bg-agent-500/10 enabled:hover:text-agent-300 disabled:opacity-40",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md";
}

export function Button({ variant = "secondary", size = "md", className = "", ...rest }: ButtonProps) {
  const sizeCls = size === "sm" ? "gap-1 px-2 py-1 text-[11px]" : "gap-1.5 px-3 py-1.5 text-xs";
  return (
    <button
      className={`inline-flex items-center justify-center rounded-md font-medium transition-colors ${sizeCls} ${BUTTON_VARIANT[variant]} ${className}`}
      {...rest}
    />
  );
}

export function Input({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`w-full rounded-md border border-line bg-surface-1 px-2.5 py-1.5 text-sm text-ink placeholder:text-ink-ghost transition-colors focus:border-accent-500/60 focus:outline-none ${className}`}
      {...rest}
    />
  );
}

export function FieldLabel({ children }: { children: ReactNode }) {
  return (
    <label className="block text-[11px] font-medium uppercase tracking-wider text-ink-faint">
      {children}
    </label>
  );
}

interface DialogProps {
  title: string;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  maxWidth?: string;
}

export function Dialog({ title, subtitle, onClose, children, footer, maxWidth = "max-w-xl" }: DialogProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex animate-overlay-in items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label={title}
        className={`m-4 flex max-h-[85vh] w-full ${maxWidth} animate-dialog-in flex-col overflow-hidden rounded-xl bg-surface-1 shadow-panel`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-ink">{title}</div>
            {subtitle && <div className="mt-0.5 text-xs text-ink-faint">{subtitle}</div>}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="-m-1 rounded-md p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-line bg-surface-0/50 px-5 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
