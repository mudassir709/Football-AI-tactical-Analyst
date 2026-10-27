// Every call to the backend goes through this file.
// Paths start with /api; in development Vite forwards them to the backend.
import type { AnalysisMode, Match, User } from "./types";

/** An error response from the API, carrying the server's message and status code. */
export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    credentials: "include", // send the login cookie
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(data.error ?? `Request failed (${response.status})`, response.status);
  }
  return data as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  me: () => request<{ user: User }>("/auth/me"),
  login: (email: string, password: string) =>
    post<{ user: User }>("/auth/login", { email, password }),
  register: (name: string, email: string, password: string) =>
    post<{ user: User }>("/auth/register", { name, email, password }),
  logout: () => post<void>("/auth/logout"),

  listMatches: () => request<{ matches: Match[] }>("/matches"),
  getMatch: (id: string) => request<{ match: Match }>(`/matches/${id}`),
  deleteMatch: (id: string) => request<void>(`/matches/${id}`, { method: "DELETE" }),
  getReport: (id: string) => request<{ report: string | null; enabled: boolean }>(`/matches/${id}/report`),
  generateReport: (id: string) => post<{ report: string; enabled: boolean }>(`/matches/${id}/report`),
  reanalyse: (id: string, mode?: AnalysisMode) =>
    post<{ match: Match }>(`/matches/${id}/reanalyse`, mode ? { mode } : {}),
  getResults: <T>(id: string) => request<T>(`/matches/${id}/results`),
  videoUrl: (id: string) => `/api/matches/${id}/video`,
};

/**
 * Upload a video with progress reporting. `fetch` cannot report upload
 * progress, so this uses the older XMLHttpRequest API, which can.
 */
export function uploadMatch(
  file: File,
  title: string,
  mode: AnalysisMode,
  onProgress: (fraction: number) => void,
): Promise<Match> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("title", title);
    form.append("mode", mode);
    form.append("video", file); // the file goes last so the fields arrive first

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/matches");
    xhr.withCredentials = true;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      const data = JSON.parse(xhr.responseText || "{}");
      if (xhr.status >= 200 && xhr.status < 300) resolve(data.match);
      else reject(new ApiError(data.error ?? `Upload failed (${xhr.status})`, xhr.status));
    };
    xhr.onerror = () => reject(new ApiError("Network error during upload", 0));
    xhr.send(form);
  });
}
