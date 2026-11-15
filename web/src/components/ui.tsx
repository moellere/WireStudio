import { createContext, useContext, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { ReactNode, ButtonHTMLAttributes, InputHTMLAttributes, SelectHTMLAttributes } from "react";
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

// The one control size for dense panels: 26px tall, 12px text. Width comes from the caller.
const CONTROL =
  "h-[26px] min-w-0 rounded-md border border-line bg-surface-1 px-2 text-xs text-ink transition-colors " +
  "placeholder:text-ink-ghost focus:border-accent-500/60 focus:outline-none disabled:opacity-40";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  compact?: boolean;
  mono?: boolean;
}

export function Input({ compact = false, mono = false, className, ...rest }: InputProps) {
  const base = compact
    ? `${CONTROL} ${className ?? "w-full"}`
    : `w-full rounded-md border border-line bg-surface-1 px-2.5 py-1.5 text-sm text-ink placeholder:text-ink-ghost transition-colors focus:border-accent-500/60 focus:outline-none ${className ?? ""}`;
  return <input className={`${base} ${mono ? "font-mono" : ""}`} {...rest} />;
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  mono?: boolean;
}

export function Select({ mono = false, className = "w-full", ...rest }: SelectProps) {
  return <select className={`${CONTROL} ${mono ? "font-mono" : ""} ${className}`} {...rest} />;
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
  /** Actions, right-aligned in the footer. */
  footer?: ReactNode;
  /** Status text, left of the actions. */
  footerNote?: ReactNode;
  /** Controls beside the close button, e.g. import and export. */
  headerActions?: ReactNode;
  maxWidth?: string;
}

const FooterSlot = createContext<HTMLElement | null>(null);

function FooterContent({ note, children }: { note?: ReactNode; children?: ReactNode }) {
  return (
    <>
      <div className="min-w-0 text-xs text-ink-dim">{note}</div>
      <div className="flex shrink-0 items-center gap-2">{children}</div>
    </>
  );
}

/** Fills the enclosing Dialog's footer from a child that owns the action's state. */
export function DialogFooter({ note, children }: { note?: ReactNode; children?: ReactNode }) {
  const slot = useContext(FooterSlot);
  return slot ? createPortal(<FooterContent note={note}>{children}</FooterContent>, slot) : null;
}

export function Dialog({
  title, subtitle, onClose, children, footer, footerNote, headerActions, maxWidth = "max-w-xl",
}: DialogProps) {
  const [footerSlot, setFooterSlot] = useState<HTMLElement | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

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
          <div className="flex shrink-0 items-center gap-1">
            {headerActions}
            <button
              onClick={onClose}
              aria-label="Close"
              className="-m-1 rounded-md p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <FooterSlot.Provider value={footerSlot}>{children}</FooterSlot.Provider>
        </div>
        <div
          ref={setFooterSlot}
          className="flex items-center justify-between gap-4 border-t border-line bg-surface-0/50 px-5 py-3 empty:hidden"
        >
          {(footer || footerNote) && <FooterContent note={footerNote}>{footer}</FooterContent>}
        </div>
      </div>
    </div>
  );
}

interface TabsProps<T extends string> {
  label: string;
  tabs: { id: T; label: ReactNode }[];
  value: T;
  onChange: (id: T) => void;
  className?: string;
}

export function Tabs<T extends string>({ label, tabs, value, onChange, className = "" }: TabsProps<T>) {
  return (
    <div role="tablist" aria-label={label} className={`flex border-b border-line text-xs ${className}`}>
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={`px-3 py-2 font-medium transition-colors ${
            value === t.id
              ? "border-b-2 border-accent-500 text-ink"
              : "border-b-2 border-transparent text-ink-faint hover:text-ink-dim"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-ink-faint">{title}</h3>
      <div>{children}</div>
    </section>
  );
}

export function KeyValueRow({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-xs">
      <span className="text-ink-faint">{k}</span>
      <span className="font-mono text-ink">{v}</span>
    </div>
  );
}

interface ListRowProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  active?: boolean;
}

export function ListRow({ active = false, className = "w-full", ...rest }: ListRowProps) {
  return (
    <button
      className={`rounded-md px-3 py-2 text-left transition-all ${
        active
          ? "bg-accent-500/5 text-ink ring-1 ring-inset ring-accent-500/50"
          : "bg-surface-2/40 hover:bg-surface-2"
      } ${className}`}
      {...rest}
    />
  );
}

type ChipVariant = "category" | "mcu" | "source" | "state";

const CHIP_VARIANT: Record<ChipVariant, string> = {
  category: "rounded-md bg-surface-2 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-ink-dim",
  mcu: "rounded-md bg-surface-2 px-1.5 py-0.5 font-mono font-medium text-ink-dim",
  source:
    "rounded bg-accent-500/10 px-1 py-0.5 text-[9px] font-medium uppercase tracking-wider text-accent-200 " +
    "ring-1 ring-accent-500/30",
  state: "whitespace-nowrap rounded-md bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-400 ring-1 ring-amber-500/30",
};

export function Chip({ variant, className = "", children }: { variant: ChipVariant; className?: string; children: ReactNode }) {
  return <span className={`${CHIP_VARIANT[variant]} ${className}`}>{children}</span>;
}

export function Code({ children }: { children: ReactNode }) {
  return <code className="rounded-md bg-surface-2 px-1 font-mono">{children}</code>;
}

type NoticeTone = "rose" | "amber";

const NOTICE_TONE: Record<NoticeTone, string> = {
  rose: "border-rose-500/40 bg-rose-500/10 text-rose-200",
  amber: "border-amber-500/40 bg-amber-500/10 text-amber-100",
};

export function Notice({
  tone, title, className = "text-xs", children,
}: { tone: NoticeTone; title: string; className?: string; children: ReactNode }) {
  return (
    <div className={`rounded-md border p-3 ${NOTICE_TONE[tone]} ${className}`}>
      <div className="font-semibold">{title}</div>
      {children}
    </div>
  );
}

export type PinTagTone = "amber" | "rose" | "emerald" | "accent";

const PIN_TAG_TONE: Record<PinTagTone, string> = {
  amber: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  rose: "border-rose-500/30 bg-rose-500/10 text-rose-200",
  emerald: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  accent: "border-accent-500/30 bg-accent-500/10 text-accent-200",
};

export function PinTag({ tone, children }: { tone: PinTagTone; children: ReactNode }) {
  return (
    <span className={`rounded-md border px-1 text-[10px] uppercase tracking-wider ${PIN_TAG_TONE[tone]}`}>
      {children}
    </span>
  );
}

export type Severity = "error" | "warn" | "info";

const SEVERITY_TONE: Record<Severity, string> = {
  error: "border-rose-500/40 bg-rose-500/10 text-rose-200",
  warn: "border-amber-500/40 bg-amber-500/10 text-amber-100",
  info: "border-accent-500/40 bg-accent-500/5 text-accent-200",
};

export function CompatibilityRow({
  severity, code, where, children,
}: { severity: Severity; code: string; where: string; children: ReactNode }) {
  return (
    <li className={`rounded-md border px-2 py-1.5 text-xs ${SEVERITY_TONE[severity]}`}>
      <div className="flex items-baseline justify-between gap-2 font-mono">
        <span>[{severity}] {code}</span>
        <span className="text-[11px] opacity-80">{where}</span>
      </div>
      <div className="mt-1">{children}</div>
    </li>
  );
}
