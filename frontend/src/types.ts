// Shapes of the data the backend sends. Keeping them in one place lets
// TypeScript catch typos like `match.stauts` before the code ever runs.

export interface User {
  id: string;
  email: string;
  name: string;
  createdAt: string;
}

export type MatchStatus = "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED" | "CANCELLED";
export type AnalysisMode = "standard" | "quick";

export interface TeamSummary {
  id: number;
  colour: string;
  formation: string | null;
  playersVisible: number;
  avgCompactnessM2: number | null;
  avgWidthM: number | null;
  avgDepthM: number | null;
  distanceKm: number | null;
}

/** Headline numbers stored in the database when analysis completes. */
export interface MatchSummary {
  durationSeconds: number;
  framesAnalysed: number;
  processingSeconds: number;
  ballDetectionRate: number;
  teams: TeamSummary[];
  formationChanges: number;
  processedOn?: string; // e.g. "CPU" or "GPU (NVIDIA GeForce RTX 3090)"
}

export interface Match {
  id: string;
  title: string;
  status: MatchStatus;
  analysisMode: AnalysisMode;
  progress: number;
  stage: string | null;
  errorMessage: string | null;
  originalFilename: string;
  fileSizeBytes: number;
  summary: MatchSummary | null;
  hasReport: boolean;
  createdAt: string;
  completedAt: string | null;
}
