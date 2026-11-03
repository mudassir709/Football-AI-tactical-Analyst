// Tests for the Timeline, which answers "where is everyone at time t?" for the
// overlays, including the moments between two analysed frames.
import { describe, expect, it } from "vitest";
import { Timeline } from "./timeline";
import type { AnalysisResults, PersonRow, ResultFrame } from "./types";

// A tiny results file: 25 fps video, every 2nd frame analysed (0.08 s apart).
function results(frames: ResultFrame[]): AnalysisResults {
  return {
    version: 2,
    video: { fps: 25, width: 1920, height: 1080, totalFrames: 100, durationSeconds: 4, stride: 2 },
    pitch: { length: 105, width: 68 },
    teams: [],
    frames,
    players: [],
    teamShape: [],
    heatmaps: {},
    heatmapBins: { x: 21, y: 14 },
    formations: { windows: [], changes: [] },
    homography: { validShare: 1, meanReprojectionErrorM: 0 },
  };
}

// Player 7 of Team A with a box and a pitch position.
const player = (x: number, pitchX: number | null): PersonRow => [7, 0, 0, x, 100, x + 20, 160, pitchX, pitchX === null ? null : 30];

describe("Timeline.stateAt", () => {
  const timeline = new Timeline(results([
    { f: 0, t: 0, p: [player(100, 10)], b: [500, 300, 50, 34], h: [1, 0, 0, 0, 1, 0, 0, 0, 1] },
    { f: 2, t: 0.08, p: [player(140, 12)], b: [520, 300, null, null], h: [3, 0, 0, 0, 3, 0, 0, 0, 1] },
  ]));

  it("returns the analysed frame exactly at its time", () => {
    const state = timeline.stateAt(0);
    expect(state.people[0].box).toEqual([100, 100, 120, 160]);
    expect(state.people[0].pitch).toEqual([10, 30]);
  });

  it("glides halfway between two analysed frames", () => {
    const state = timeline.stateAt(0.04);
    expect(state.people[0].box[0]).toBeCloseTo(120);
    expect(state.people[0].pitch![0]).toBeCloseTo(11);
    // The foot point is the bottom middle of the box.
    expect(state.people[0].foot[0]).toBeCloseTo(130);
    expect(state.people[0].foot[1]).toBeCloseTo(160);
    // The camera matrix is blended too, so drawings follow the camera.
    expect(state.h![0]).toBeCloseTo(2);
  });

  it("keeps the ball's image position even when its pitch position is unknown next frame", () => {
    const ball = timeline.stateAt(0.04).ball!;
    expect(ball.image![0]).toBeCloseTo(510);
    expect(ball.pitch).toEqual([50, 34]); // nothing to blend with, so it stays put
  });

  it("is empty before the first analysed frame", () => {
    expect(timeline.stateAt(-1).people).toEqual([]);
  });
});

describe("gaps in the analysis", () => {
  // Two analysed frames one second apart, e.g. around a camera cut.
  const timeline = new Timeline(results([
    { f: 0, t: 0, p: [player(100, 10)], b: null },
    { f: 25, t: 1.0, p: [player(900, 60)], b: null },
  ]));

  it("never blends across a long gap (the player would fly across the screen)", () => {
    // Shortly after the first frame: shown where it was, not moved towards the next one.
    expect(timeline.stateAt(0.1).people[0].box[0]).toBe(100);
  });

  it("shows nothing in the middle of a long gap", () => {
    expect(timeline.stateAt(0.5).people).toEqual([]);
  });
});

describe("paths", () => {
  const timeline = new Timeline(results(
    [0, 1, 2, 3, 4].map((i) => ({ f: i * 2, t: i * 0.08, p: [player(100, i)], b: null })),
  ));

  it("trail returns the recent positions, oldest first", () => {
    expect(timeline.trail(7, 0.32, 0.17)).toEqual([[2, 30], [3, 30], [4, 30]]);
  });

  it("fullPath returns every position of the player", () => {
    expect(timeline.fullPath(7)).toHaveLength(5);
    expect(timeline.fullPath(99)).toEqual([]);
  });

  it("knows whether the results include camera matrices (needed for video paths)", () => {
    expect(timeline.hasPitchMatrices).toBe(false);
  });
});

describe("indexAt", () => {
  it("finds the last analysed frame at or before a time", () => {
    const timeline = new Timeline(results(
      [0, 0.08, 0.16, 0.24].map((t, i) => ({ f: i * 2, t, p: [], b: null })),
    ));
    expect(timeline.indexAt(0.1)).toBe(1);
    expect(timeline.indexAt(0.24)).toBe(3);
    expect(timeline.indexAt(5)).toBe(3);
    expect(timeline.indexAt(-0.1)).toBe(-1);
  });
});
