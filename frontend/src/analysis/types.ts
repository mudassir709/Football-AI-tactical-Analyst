// Shape of the analysis results file written by the Python worker
// (see worker/src/pipeline.py, `_build_results`).

/** [id, team, role, x1, y1, x2, y2, pitchX, pitchY, position]; image coords in source-video pixels.
 *  id is the track; position (results v3+) is the entry in `players` this person counts towards. */
export type PersonRow = [number, number, number, number, number, number, number, number | null, number | null, (number | null)?];
/** [x, y, pitchX, pitchY] */
export type BallRow = [number | null, number | null, number | null, number | null];

export interface ResultFrame {
  f: number; // frame index in the source video
  t: number; // seconds
  p: PersonRow[];
  b: BallRow | null;
  h?: number[] | null; // pitch (m) -> image (px) 3x3 matrix, row-major (results v2+)
}

/** One player track (results v1-v2) or, from v3, one position of a team (e.g. Team A's LB). */
export interface PlayerResult {
  id: number;
  label?: string; // the position, e.g. "LB" (results v3+)
  team: number;
  role: "player" | "goalkeeper" | "referee";
  secondsVisible: number | null;
  distanceM: number | null;
  avgSpeedKmh: number | null;
  maxSpeedKmh: number | null;
  heatmap: number[][];
}

export interface FormationWindow {
  team: number;
  start: number;
  end: number;
  formation: string | null;
  bestMatch: string | null;
  runnerUp: string | null;
  cost: number | null;
  confidenceMargin: number | null;
  players: number;
}

export interface TeamShapeRow {
  t: number;
  team: number;
  n: number;
  area: number | null;
  width: number | null;
  depth: number | null;
  cx: number | null;
  cy: number | null;
}

export interface AnalysisResults {
  version: number;
  video: { fps: number; width: number; height: number; totalFrames: number; durationSeconds: number; stride: number; mode?: string };
  pitch: { length: number; width: number };
  teams: { id: number; colour: string; defends: "left" | "right" | null }[];
  frames: ResultFrame[];
  players: PlayerResult[];
  teamShape: TeamShapeRow[];
  heatmaps: Record<string, number[][]>; // "0", "1", "ball"
  heatmapBins: { x: number; y: number };
  formations: { windows: FormationWindow[]; changes: { team: number; time: number; from: string; to: string }[] };
  homography: { validShare: number; meanReprojectionErrorM: number };
}

export const ROLE = { player: 0, goalkeeper: 1, referee: 2 } as const;
