// "Where is everyone at time t?"
//
// The worker only analyses every 2nd (standard) or 5th (quick) frame, but the
// video plays every frame. To keep markers gliding instead of jumping, the
// state between two analysed frames is linearly interpolated.
import { lerp, lerpHomography, type Point } from "./geometry";
import type { AnalysisResults, PersonRow, ResultFrame } from "./types";

export interface PersonState {
  id: number;
  team: number;
  role: number; // see ROLE
  box: [number, number, number, number]; // x1, y1, x2, y2 in source-video pixels
  foot: Point; // bottom-centre of the box, in source-video pixels
  pitch: Point | null; // metres
}

export interface FrameState {
  time: number;
  people: PersonState[];
  ball: { image: Point | null; pitch: Point | null } | null;
  h: number[] | null; // pitch -> image for this moment
}

const EMPTY = (time: number): FrameState => ({ time, people: [], ball: null, h: null });

export class Timeline {
  readonly frames: ResultFrame[];
  private readonly byId: Map<number, PersonRow>[];
  /** Never interpolate across gaps longer than this (seconds), e.g. camera cuts. */
  private readonly maxGap: number;

  constructor(results: AnalysisResults) {
    this.frames = results.frames.slice().sort((a, b) => a.t - b.t);
    this.byId = this.frames.map((frame) => new Map(frame.p.map((row) => [row[0], row])));
    this.maxGap = (3 * results.video.stride) / results.video.fps + 1e-6;
  }

  /** Index of the last analysed frame at or before `time` (binary search), or -1. */
  indexAt(time: number): number {
    let lo = 0;
    let hi = this.frames.length - 1;
    let found = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (this.frames[mid].t <= time) {
        found = mid;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    return found;
  }

  stateAt(time: number): FrameState {
    const i = this.indexAt(time);
    if (i < 0 || time - this.frames[i].t > this.maxGap) return EMPTY(time);

    const a = this.frames[i];
    const b = this.frames[i + 1];
    const canBlend = b !== undefined && b.t - a.t <= this.maxGap;
    const alpha = canBlend ? Math.min(1, Math.max(0, (time - a.t) / (b.t - a.t))) : 0;
    const next = canBlend ? this.byId[i + 1] : undefined;

    const people = a.p.map((row): PersonState => {
      const other = next?.get(row[0]);
      const at = (k: 3 | 4 | 5 | 6) => (other ? lerp(row[k], other[k], alpha) : row[k]); // box columns
      const box: PersonState["box"] = [at(3), at(4), at(5), at(6)];
      let pitch: Point | null = null;
      if (row[7] !== null && row[8] !== null) {
        pitch = other && other[7] !== null && other[8] !== null
          ? [lerp(row[7], other[7], alpha), lerp(row[8], other[8], alpha)]
          : [row[7], row[8]];
      }
      return { id: row[0], team: row[1], role: row[2], box, foot: [(box[0] + box[2]) / 2, box[3]], pitch };
    });

    let h = a.h ?? null;
    if (h && canBlend && b.h) h = lerpHomography(h, b.h, alpha);

    let ball: FrameState["ball"] = null;
    if (a.b) {
      const [x, y, px, py] = a.b;
      const nb = canBlend ? b.b : null;
      const mix = (p: number | null, q: number | null | undefined) =>
        p === null ? null : q === null || q === undefined ? p : lerp(p, q, alpha);
      const ix = mix(x, nb?.[0]), iy = mix(y, nb?.[1]), qx = mix(px, nb?.[2]), qy = mix(py, nb?.[3]);
      ball = {
        image: ix !== null && iy !== null ? [ix, iy] : null,
        pitch: qx !== null && qy !== null ? [qx, qy] : null,
      };
    }
    return { time, people, ball, h };
  }

  /** A person's pitch positions over the `seconds` before `time`, oldest first. */
  trail(id: number, time: number, seconds: number): Point[] {
    const points: Point[] = [];
    for (let k = this.indexAt(time); k >= 0 && this.frames[k].t >= time - seconds; k--) {
      const row = this.byId[k].get(id);
      if (row && row[7] !== null && row[8] !== null) points.push([row[7], row[8]]);
    }
    return points.reverse();
  }

  /** The ball's pitch positions over the `seconds` before `time`, oldest first. */
  ballTrail(time: number, seconds: number): Point[] {
    const points: Point[] = [];
    for (let k = this.indexAt(time); k >= 0 && this.frames[k].t >= time - seconds; k--) {
      const b = this.frames[k].b;
      if (b && b[2] !== null && b[3] !== null) points.push([b[2], b[3]]);
    }
    return points.reverse();
  }

  /** Every pitch position of one person in the whole clip (for the player panel). */
  fullPath(id: number): Point[] {
    const points: Point[] = [];
    this.byId.forEach((rows) => {
      const row = rows.get(id);
      if (row && row[7] !== null && row[8] !== null) points.push([row[7], row[8]]);
    });
    return points;
  }

  /** Whether the results include per-frame pitch matrices (results v2+). */
  get hasPitchMatrices(): boolean {
    return this.frames.some((frame) => Array.isArray(frame.h));
  }
}
