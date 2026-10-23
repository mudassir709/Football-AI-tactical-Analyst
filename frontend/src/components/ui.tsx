// Small reusable building blocks, so every page looks consistent.
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { MatchStatus } from "../types";

type ButtonVariant = "primary" | "secondary" | "danger";

const BUTTON_STYLES: Record<ButtonVariant, string> = {
  primary: "bg-emerald-500 text-slate-950 hover:bg-emerald-400",
  secondary: "bg-slate-800 text-slate-100 hover:bg-slate-700",
  danger: "bg-red-600 text-white hover:bg-red-500",
};

/** Button styling, also usable on links that should look like buttons. */
export const buttonClasses = (variant: ButtonVariant = "primary", className = "") =>
  `inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON_STYLES[variant]} ${className}`;

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button className={buttonClasses(variant, className)} {...props} />;
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-slate-800 bg-slate-900/70 p-5 ${className}`}>
      {children}
    </div>
  );
}

const STATUS_STYLES: Record<MatchStatus, { label: string; style: string }> = {
  QUEUED: { label: "Queued", style: "bg-slate-700 text-slate-200" },
  PROCESSING: { label: "Analysing", style: "bg-sky-500/20 text-sky-300" },
  COMPLETED: { label: "Ready", style: "bg-emerald-500/20 text-emerald-300" },
  FAILED: { label: "Failed", style: "bg-red-500/20 text-red-300" },
};

export function StatusBadge({ status }: { status: MatchStatus }) {
  const { label, style } = STATUS_STYLES[status];
  return <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${style}`}>{label}</span>;
}

export function ProgressBar({ value, label }: { value: number; label?: string | null }) {
  const percent = Math.max(0, Math.min(100, value));
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs text-slate-400">
        <span>{label ?? "Waiting for a worker"}</span>
        <span>{Math.round(percent)}%</span>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-slate-800"
        role="progressbar"
        aria-valuenow={Math.round(percent)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className="h-full rounded-full bg-emerald-400 transition-all duration-500" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

export function ErrorMessage({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200" role="alert">
      {children}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 text-slate-400" role="status">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-600 border-t-emerald-400" />
      {label}…
    </div>
  );
}

/** Label + big number, used for statistics. */
export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}
