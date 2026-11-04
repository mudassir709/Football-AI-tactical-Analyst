// Small building blocks used all over the dashboard (buttons, cards, the
// status label, progress bar, error box, spinner...). Keeping them in one
// place means every page looks the same, and a style change happens once.
// The colours (pitch, chalk, accent...) are defined in index.css.
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { MatchStatus } from "../types";

// Three kinds of button: amber for the main action, a dashed chalk outline for
// other actions, and red text for deleting.
type ButtonVariant = "primary" | "secondary" | "danger";

const BUTTON_STYLES: Record<ButtonVariant, string> = {
  primary: "bg-accent text-pitch font-semibold hover:brightness-110",
  secondary: "border border-dashed border-chalk/70 text-chalk hover:bg-pitch-3",
  danger: "border border-danger/60 text-danger hover:bg-danger/10",
};

/** Button styling, also usable on links that should look like buttons. */
export const buttonClasses = (variant: ButtonVariant = "primary", className = "") =>
  `inline-flex items-center justify-center gap-2 rounded px-4 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON_STYLES[variant]} ${className}`;

// A normal <button> with our styling; any other button props are passed through.
export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button className={buttonClasses(variant, className)} {...props} />;
}

// A panel with a thin chalk border, slightly lighter than the background.
export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`border border-line bg-pitch-2 p-5 ${className}`}>{children}</div>;
}

// Small grey capital letters above a section, e.g. "TACTICAL BOARD".
export function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="font-mono text-xs font-medium tracking-[0.14em] text-dim uppercase">{children}</h2>;
}

// How each match status is shown: a short handwritten note in its own colour
// (the database says "PROCESSING", the user sees "analysing…", and so on).
const STATUS_STYLES: Record<MatchStatus, { label: string; style: string }> = {
  QUEUED: { label: "queued…", style: "text-dim" },
  PROCESSING: { label: "analysing…", style: "text-accent" },
  COMPLETED: { label: "ready ✓", style: "text-chalk" },
  FAILED: { label: "failed ✗", style: "text-danger" },
  CANCELLED: { label: "cancelled –", style: "text-dim" },
};

export function StatusBadge({ status }: { status: MatchStatus }) {
  const { label, style } = STATUS_STYLES[status];
  return <span className={`inline-block -rotate-2 font-hand text-lg leading-none ${style}`}>{label}</span>;
}

// A thin progress line with the current step on the left and the percentage
// on the right. The value is kept between 0 and 100 just in case.
export function ProgressBar({ value, label }: { value: number; label?: string | null }) {
  const percent = Math.max(0, Math.min(100, value));
  return (
    <div>
      <div className="mb-2 flex justify-between font-mono text-xs text-dim">
        <span>{label ?? "waiting for a worker"}</span>
        <span>{Math.round(percent)}%</span>
      </div>
      <div
        className="relative h-0.5 bg-line"
        role="progressbar"
        aria-valuenow={Math.round(percent)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className="h-full bg-accent transition-all duration-500" style={{ width: `${percent}%` }} />
        {/* The dot at the end of the line, like the seek bar of the video. */}
        <div
          className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent transition-all duration-500"
          style={{ left: `${percent}%` }}
        />
      </div>
    </div>
  );
}

// Box for error messages. role="alert" makes screen readers read it out.
export function ErrorMessage({ children }: { children: ReactNode }) {
  return (
    <div className="border-l-2 border-danger bg-danger/10 px-4 py-3 text-sm text-red-200" role="alert">
      {children}
    </div>
  );
}

// A small spinning circle with a text, shown while waiting for the server.
export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 font-mono text-sm text-dim" role="status">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-accent" />
      {label}…
    </div>
  );
}

/** A label with a big number under it, used for statistics. */
export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div>
      <div className="text-xs text-dim">{label}</div>
      <div className="mt-1 font-mono text-2xl font-medium tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 font-mono text-[11px] text-dim">{hint}</div>}
    </div>
  );
}

// The style of text boxes, shared by the login and upload forms.
export const inputClasses =
  "w-full rounded border border-line bg-pitch px-3 py-2 text-sm text-chalk outline-none placeholder:text-dim/60 focus:border-accent";
