// Small helpers that turn raw numbers into readable text.

// File size in KB, MB or GB, e.g. 19882918 -> "19.0 MB".
export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

// A length of time, e.g. 95 -> "1 min 35 s", 39 -> "39 s".
export function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return minutes > 0 ? `${minutes} min ${rest} s` : `${rest} s`;
}

// A date in the user's own language and time zone, e.g. "27 Oct, 10:55".
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// A fraction as a percentage, e.g. 0.636 -> "64%".
export const formatPercent = (fraction: number) => `${Math.round(fraction * 100)}%`;
