// "Where is everyone at time t?"
//
// The worker only analyses every 2nd (standard) or 5th (quick) frame, but the
// video plays every frame. To keep markers gliding instead of jumping, the
// state between two analysed frames is linearly interpolated.
import { lerp, lerpHomography, type Point } from "./geometry";
import type { AnalysisResults, PersonRow, ResultFrame } from "./types";

export interface PersonState {
  id: number; // the track, used to draw smooth movement
  key: number | null; // what clicking this person selects: their position (v3+) or their track (older results)
  label: string; // shown next to the marker: "LB", "GK", "REF"... (or the track number in older results)
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

  /** From results v3 players are labelled by position instead of track number. */
  readonly usesPositions: boolean;
  private readonly positionLabels: Map<number, string>;

  constructor(results: AnalysisResults) {
    this.usesPositions = results.version >= 3;
    this.positionLabels = new Map(results.players.map((p) => [p.id, p.label ?? ""]));
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
      return { id: row[0], ...this.identify(row), team: row[1], role: row[2], box, foot: [(box[0] + box[2]) / 2, box[3]], pitch };
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

  /** What selecting this person selects, and the label shown next to them. */
  private identify(row: PersonRow): { key: number | null; label: string } {
    const role = row[2];
    if (!this.usesPositions) {
      // Older results: players are identified by their track number.
      return { key: row[0], label: role === 1 ? `GK ${row[0]}` : role === 2 ? "REF" : `${row[0]}` };
    }
    if (role === 2) return { key: null, label: "REF" };
    const position = row[9] ?? null;
    return { key: position, label: position === null ? "" : (this.positionLabels.get(position) ?? "") };
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

  /** The ball's pitch positions over the `seconds` before `time`, oldest first.
   *  The trail stops at the first frame without a ball: after a gap the ball may
   *  be somewhere else entirely, and a line across the pitch would be wrong. */
  ballTrail(time: number, seconds: number): Point[] {
    const points: Point[] = [];
    for (let k = this.indexAt(time); k >= 0 && this.frames[k].t >= time - seconds; k--) {
      const b = this.frames[k].b;
      if (!b || b[2] === null || b[3] === null) break;
      points.push([b[2], b[3]]);
    }
    return points.reverse();
  }

  /** Every pitch position of one selection (a position, or a track in older
   *  results) over the whole clip, for the player panel. The path is split into
   *  pieces wherever a different player takes over the position or the player
   *  is out of view, so no line jumps from one player to another. */
  fullPath(key: number): Point[][] {
    const pieces: Point[][] = [];
    let current: Point[] = [];
    let lastTrack: number | null = null;
    let lastTime = -Infinity;
    for (const frame of this.frames) {
      const row = frame.p.find((r) => (this.usesPositions ? (r[9] ?? null) === key && r[2] !== 2 : r[0] === key));
      if (!row || row[7] === null || row[8] === null) continue;
      if (row[0] !== lastTrack || frame.t - lastTime > this.maxGap) {
        if (current.length > 1) pieces.push(current);
        current = [];
      }
      current.push([row[7], row[8]]);
      lastTrack = row[0];
      lastTime = frame.t;
    }
    if (current.length > 1) pieces.push(current);
    return pieces;
  }

  /** Whether the results include per-frame pitch matrices (results v2+). */
  get hasPitchMatrices(): boolean {
    return this.frames.some((frame) => Array.isArray(frame.h));
  }
}
