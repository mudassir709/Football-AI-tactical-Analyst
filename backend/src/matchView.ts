// The shape of a match as sent to the browser. Internal file paths stay on
// the server; the browser fetches files through the API instead.
import type { Match } from "./generated/prisma/client.ts";

export function toPublicMatch(match: Match) {
  return {
    id: match.id,
    title: match.title,
    status: match.status,
    analysisMode: match.analysisMode,
    progress: match.progress,
    stage: match.stage,
    errorMessage: match.errorMessage,
    originalFilename: match.originalFilename,
    fileSizeBytes: match.fileSizeBytes,
    summary: match.summary,
    hasReport: match.report !== null,
    createdAt: match.createdAt,
    completedAt: match.completedAt,
  };
}

export type PublicMatch = ReturnType<typeof toPublicMatch>;
