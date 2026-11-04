// Drawing the analysis layers on the video overlay canvas and on the 2D board.
// Both are plain <canvas> elements redrawn for every displayed video frame.
import { applyHomography, convexHull, fitContain, type Point } from "./geometry";
import type { FrameState, Timeline } from "./timeline";
import { ROLE, type AnalysisResults } from "./types";

export type HeatmapLayer = "off" | "0" | "1" | "ball";

export interface Layers {
  players: boolean;
  trails: boolean;
  shape: boolean;
  ball: boolean;
  heatmap: HeatmapLayer;
}

export const TRAIL_SECONDS = 4;
export const REFEREE_COLOUR = "#FACC15";
const UNASSIGNED_COLOUR = "#94A3B8";

// Colours of the "tactics board" theme (the same as in index.css).
const CHALK = "#e9ece4";
const AMBER = "#f2b33d";
const BOARD_GRASS = "#183024";
const BOARD_STRIPE = "#1c3829";
const DARK = "#13261c";

// On the 2D board the teams are drawn like on a coach's whiteboard:
// Team A as chalk circles (○), Team B as amber crosses (×).
export const BOARD_SYMBOL: Record<number, string> = { 0: "○", 1: "×" };

// Colour of a person on the video: their real kit colour, so the markers
// match the shirts you see; referees are always yellow.
export function personColour(results: AnalysisResults, team: number, role: number): string {
  if (role === ROLE.referee) return REFEREE_COLOUR;
  return results.teams.find((t) => t.id === team)?.colour ?? UNASSIGNED_COLOUR;
}

// Colour of a person on the 2D board: chalk for Team A, amber for Team B.
function boardColour(team: number, role: number): string {
  if (role === ROLE.referee) return REFEREE_COLOUR;
  return team === 0 ? CHALK : team === 1 ? AMBER : UNASSIGNED_COLOUR;
}

/** Heat colour from cool/transparent (0) to hot red (1). */
function heatColour(value: number): string {
  const hue = 60 * (1 - value); // yellow -> red
  return `hsla(${hue}, 100%, 50%, ${0.12 + 0.5 * value})`;
}

const withAlpha = (hex: string, alpha: number) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
};

/** Draw a polyline whose older segments fade out. */
function fadingPath(ctx: CanvasRenderingContext2D, points: Point[], colour: string, width: number) {
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  for (let i = 1; i < points.length; i++) {
    ctx.strokeStyle = withAlpha(colour, 0.15 + 0.75 * (i / points.length));
    ctx.beginPath();
    ctx.moveTo(...points[i - 1]);
    ctx.lineTo(...points[i]);
    ctx.stroke();
  }
}

function fillPolygon(ctx: CanvasRenderingContext2D, points: Point[]) {
  ctx.beginPath();
  points.forEach((p, i) => (i === 0 ? ctx.moveTo(...p) : ctx.lineTo(...p)));
  ctx.closePath();
}

/** Iterate over non-empty heatmap cells as pitch-space rectangles. */
function forEachHeatCell(
  results: AnalysisResults,
  grid: number[][],
  visit: (x0: number, y0: number, x1: number, y1: number, value: number) => void,
) {
  const max = Math.max(...grid.flat());
  if (max <= 0) return;
  const cellW = results.pitch.length / results.heatmapBins.x;
  const cellH = results.pitch.width / results.heatmapBins.y;
  grid.forEach((row, iy) =>
    row.forEach((share, ix) => {
      const value = share / max;
      if (value >= 0.04) visit(ix * cellW, iy * cellH, (ix + 1) * cellW, (iy + 1) * cellH, value);
    }),
  );
}

// ---------------------------------------------------------------------------
// Video overlay
// ---------------------------------------------------------------------------

export function drawVideoOverlay(
  ctx: CanvasRenderingContext2D,
  canvasW: number,
  canvasH: number,
  results: AnalysisResults,
  timeline: Timeline,
  state: FrameState,
  layers: Layers,
  selectedId: number | null,
) {
  ctx.clearRect(0, 0, canvasW, canvasH);
  const { scale, offsetX, offsetY } = fitContain(results.video.width, results.video.height, canvasW, canvasH);
  const toCanvas = ([x, y]: Point): Point => [offsetX + x * scale, offsetY + y * scale];
  const h = state.h;
  // Pitch (metres) -> canvas pixels through this frame's homography.
  const pitchToCanvas = (p: Point): Point | null => {
    const image = h ? applyHomography(h, p[0], p[1]) : null;
    return image ? toCanvas(image) : null;
  };
  const lineWidth = Math.max(1.5, 3 * scale);

  // 1. Heatmap painted onto the grass.
  if (layers.heatmap !== "off" && h) {
    forEachHeatCell(results, results.heatmaps[layers.heatmap] ?? [], (x0, y0, x1, y1, value) => {
      const corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map((c) => pitchToCanvas(c as Point));
      if (corners.some((c) => c === null)) return;
      fillPolygon(ctx, corners as Point[]);
      ctx.fillStyle = heatColour(value);
      ctx.fill();
    });
  }

  // 2. Team shape: the area enclosed by each team's outfield players.
  if (layers.shape) {
    for (const team of results.teams) {
      const feet = state.people.filter((p) => p.team === team.id && p.role === ROLE.player).map((p) => toCanvas(p.foot));
      if (feet.length < 3) continue;
      fillPolygon(ctx, convexHull(feet));
      ctx.fillStyle = withAlpha(team.colour, 0.12);
      ctx.fill();
      ctx.setLineDash([8, 6]);
      ctx.strokeStyle = withAlpha(team.colour, 0.8);
      ctx.lineWidth = lineWidth * 0.7;
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  // 3. Movement paths over the last few seconds, projected into this frame.
  if (layers.trails && h) {
    for (const person of state.people) {
      if (selectedId !== null && person.key !== selectedId) continue;
      const trail = timeline.trail(person.id, state.time, TRAIL_SECONDS);
      const points = trail.map(pitchToCanvas).filter((p): p is Point => p !== null);
      // End at the detected feet, not the smoothed pitch position, which lags
      // a few pixels behind during sprints; the path then always meets the marker.
      points.push(toCanvas(person.foot));
      const colour = personColour(results, person.team, person.role);
      fadingPath(ctx, points, colour, person.key === selectedId ? lineWidth * 1.6 : lineWidth);
    }
  }

  // 4. Player markers: ellipse at the feet plus ID label, like TV graphics.
  if (layers.players) {
    ctx.font = `600 ${Math.max(10, 13 * scale * 1.4)}px "IBM Plex Sans", system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const person of state.people) {
      const [fx, fy] = toCanvas(person.foot);
      const boxWidth = (person.box[2] - person.box[0]) * scale;
      const rx = Math.max(8, boxWidth * 0.65);
      const selected = person.key !== null && person.key === selectedId;
      const colour = personColour(results, person.team, person.role);

      ctx.beginPath();
      ctx.ellipse(fx, fy, rx, rx * 0.35, 0, -0.25 * Math.PI, 1.25 * Math.PI);
      ctx.strokeStyle = selected ? "#ffffff" : colour;
      ctx.lineWidth = selected ? lineWidth * 1.8 : lineWidth;
      ctx.stroke();

      // The label (LB, GK, REF...) in a small tag under the feet. Players
      // whose position is unknown only get the ellipse.
      const label = person.label;
      if (!label) continue;
      const textW = ctx.measureText(label).width + 8;
      const textH = Math.max(14, 18 * scale * 1.4);
      const ly = fy + rx * 0.35 + textH / 2 + 2;
      ctx.fillStyle = selected ? "#ffffff" : colour;
      ctx.beginPath();
      ctx.roundRect(fx - textW / 2, ly - textH / 2, textW, textH, 4);
      ctx.fill();
      ctx.fillStyle = DARK;
      ctx.fillText(label, fx, ly + 1);
    }
  }

  // 5. Ball: short trail plus a marker above it.
  if (layers.ball && state.ball) {
    if (h) {
      const trail = timeline.ballTrail(state.time, 1.5).map(pitchToCanvas).filter((p): p is Point => p !== null);
      if (state.ball.image) trail.push(toCanvas(state.ball.image));
      fadingPath(ctx, trail, "#ffffff", lineWidth * 0.8);
    }
    if (state.ball.image) {
      const [bx, by] = toCanvas(state.ball.image);
      const size = Math.max(7, 14 * scale * 1.4);
      ctx.beginPath();
      ctx.moveTo(bx, by - size * 0.9);
      ctx.lineTo(bx - size / 2, by - size * 1.8);
      ctx.lineTo(bx + size / 2, by - size * 1.8);
      ctx.closePath();
      ctx.fillStyle = "#ffffff";
      ctx.fill();
      ctx.strokeStyle = DARK;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  }
}

/** The person whose feet are nearest to a click (canvas pixels), if close enough. */
export function personAt(
  results: AnalysisResults,
  state: FrameState,
  canvasW: number,
  canvasH: number,
  clickX: number,
  clickY: number,
): number | null {
  const { scale, offsetX, offsetY } = fitContain(results.video.width, results.video.height, canvasW, canvasH);
  let best: number | null = null;
  let bestDistance = Infinity;
  for (const person of state.people) {
    const [x1, y1, x2, y2] = person.box;
    // Distance to the player's box (zero inside it), in canvas pixels.
    const dx = Math.max(offsetX + x1 * scale - clickX, 0, clickX - (offsetX + x2 * scale));
    const dy = Math.max(offsetY + y1 * scale - clickY, 0, clickY - (offsetY + y2 * scale));
    const distance = Math.hypot(dx, dy);
    if (person.key !== null && distance < bestDistance) {
      bestDistance = distance;
      best = person.key;
    }
  }
  return bestDistance <= 25 ? best : null;
}

// ---------------------------------------------------------------------------
// 2D tactical board
// ---------------------------------------------------------------------------

const BOARD_MARGIN = 3; // metres of grass drawn around the pitch

/** Map pitch metres to board pixels; y is flipped so the near touchline is at the bottom. */
export function boardTransform(results: AnalysisResults, canvasW: number, canvasH: number) {
  const { length, width } = results.pitch;
  const scale = Math.min(canvasW / (length + 2 * BOARD_MARGIN), canvasH / (width + 2 * BOARD_MARGIN));
  const offsetX = (canvasW - (length + 2 * BOARD_MARGIN) * scale) / 2;
  const offsetY = (canvasH - (width + 2 * BOARD_MARGIN) * scale) / 2;
  const toBoard = ([x, y]: Point): Point => [
    offsetX + (x + BOARD_MARGIN) * scale,
    offsetY + (width - y + BOARD_MARGIN) * scale,
  ];
  return { scale, toBoard };
}

// The pitch drawn like chalk on a dark green board: faint mowing stripes and
// dashed white lines.
function drawPitchMarkings(ctx: CanvasRenderingContext2D, results: AnalysisResults, canvasW: number, canvasH: number) {
  const { length: L, width: W } = results.pitch;
  const { scale, toBoard } = boardTransform(results, canvasW, canvasH);
  ctx.fillStyle = BOARD_GRASS;
  ctx.fillRect(0, 0, canvasW, canvasH);
  // Alternating mowing stripes.
  for (let i = 0; i < 10; i++) {
    if (i % 2) continue;
    const [x0, y0] = toBoard([(i * L) / 10, W]);
    const [x1, y1] = toBoard([((i + 1) * L) / 10, 0]);
    ctx.fillStyle = BOARD_STRIPE;
    ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
  }
  ctx.strokeStyle = withAlpha(CHALK, 0.7);
  ctx.lineWidth = Math.max(1, scale * 0.15);
  ctx.setLineDash([Math.max(3, scale * 1.2), Math.max(2, scale * 0.7)]); // dashes look like chalk
  const rect = (x0: number, y0: number, x1: number, y1: number) => {
    const [ax, ay] = toBoard([x0, y1]);
    const [bx, by] = toBoard([x1, y0]);
    ctx.strokeRect(ax, ay, bx - ax, by - ay);
  };
  rect(0, 0, L, W);
  const [mx0, my0] = toBoard([L / 2, 0]);
  const [mx1, my1] = toBoard([L / 2, W]);
  ctx.beginPath();
  ctx.moveTo(mx0, my0);
  ctx.lineTo(mx1, my1);
  ctx.stroke();
  const [cx, cy] = toBoard([L / 2, W / 2]);
  ctx.beginPath();
  ctx.arc(cx, cy, 9.15 * scale, 0, 2 * Math.PI);
  ctx.stroke();
  for (const [x0, x1] of [[0, 16.5], [L - 16.5, L]]) rect(x0, (W - 40.32) / 2, x1, (W + 40.32) / 2);
  for (const [x0, x1] of [[0, 5.5], [L - 5.5, L]]) rect(x0, (W - 18.32) / 2, x1, (W + 18.32) / 2);
  ctx.setLineDash([]); // solid lines again for everything drawn after this
}

export interface BoardOptions {
  heatmapGrid?: number[][]; // overrides layers.heatmap (player panel)
  staticPath?: Point[][]; // whole-clip path of one player or position, in pieces (player panel)
  showPeople?: boolean;
}

export function drawBoard(
  ctx: CanvasRenderingContext2D,
  canvasW: number,
  canvasH: number,
  results: AnalysisResults,
  timeline: Timeline,
  state: FrameState | null,
  layers: Layers,
  selectedId: number | null,
  options: BoardOptions = {},
) {
  drawPitchMarkings(ctx, results, canvasW, canvasH);
  const { scale, toBoard } = boardTransform(results, canvasW, canvasH);

  const grid = options.heatmapGrid ?? (layers.heatmap !== "off" ? results.heatmaps[layers.heatmap] : undefined);
  if (grid) {
    forEachHeatCell(results, grid, (x0, y0, x1, y1, value) => {
      const [ax, ay] = toBoard([x0, y1]);
      const [bx, by] = toBoard([x1, y0]);
      ctx.fillStyle = heatColour(value);
      ctx.fillRect(ax, ay, bx - ax, by - ay);
    });
  }

  if (options.staticPath) {
    ctx.strokeStyle = withAlpha(CHALK, 0.9);
    ctx.lineWidth = Math.max(1, scale * 0.25);
    for (const piece of options.staticPath) {
      ctx.beginPath();
      piece.map(toBoard).forEach((p, i) => (i === 0 ? ctx.moveTo(...p) : ctx.lineTo(...p)));
      ctx.stroke();
    }
  }

  if (!state || options.showPeople === false) return;
  const located = state.people.filter((p): p is typeof p & { pitch: Point } => p.pitch !== null);

  // Team shape: the area of each team's outfield players, faintly filled and
  // outlined with dashes in the team's board colour.
  if (layers.shape) {
    for (const team of results.teams) {
      const points = located.filter((p) => p.team === team.id && p.role === ROLE.player).map((p) => toBoard(p.pitch));
      if (points.length < 3) continue;
      const colour = boardColour(team.id, ROLE.player);
      fillPolygon(ctx, convexHull(points));
      ctx.fillStyle = withAlpha(colour, 0.1);
      ctx.fill();
      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = withAlpha(colour, 0.8);
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  if (layers.trails) {
    for (const person of located) {
      if (selectedId !== null && person.key !== selectedId) continue;
      const trail = timeline.trail(person.id, state.time, TRAIL_SECONDS).concat([person.pitch]);
      fadingPath(ctx, trail.map(toBoard), boardColour(person.team, person.role), Math.max(1.5, scale * 0.25));
    }
  }

  // People: ○ for Team A, × for Team B, a small square for referees. The
  // selected player gets an amber halo, and every player's number sits beside them.
  const size = Math.max(4, scale * 1.1);
  ctx.font = `500 ${Math.max(8, size * 1.05)}px "IBM Plex Mono", monospace`;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  for (const person of located) {
    const [x, y] = toBoard(person.pitch);
    const colour = boardColour(person.team, person.role);
    const selected = person.key !== null && person.key === selectedId;
    if (selected) {
      ctx.beginPath();
      ctx.arc(x, y, size * 2.1, 0, 2 * Math.PI);
      ctx.fillStyle = withAlpha(AMBER, 0.25);
      ctx.fill();
    }
    ctx.strokeStyle = colour;
    ctx.lineWidth = selected ? 2.6 : person.role === ROLE.goalkeeper ? 2.2 : 1.6;
    ctx.beginPath();
    if (person.role === ROLE.referee) {
      ctx.fillStyle = colour;
      ctx.fillRect(x - size * 0.5, y - size * 0.5, size, size);
    } else if (person.team === 1) {
      ctx.moveTo(x - size, y - size);
      ctx.lineTo(x + size, y + size);
      ctx.moveTo(x + size, y - size);
      ctx.lineTo(x - size, y + size);
      ctx.stroke();
    } else {
      ctx.arc(x, y, size, 0, 2 * Math.PI);
      ctx.stroke();
    }
    if (person.role !== ROLE.referee && person.label) {
      ctx.fillStyle = selected ? AMBER : withAlpha(CHALK, 0.75);
      ctx.fillText(person.label, x + size * 1.4, y - size * 0.9);
    }
  }

  // The ball: a small white dot with a dark edge.
  if (layers.ball && state.ball?.pitch) {
    const [x, y] = toBoard(state.ball.pitch);
    ctx.beginPath();
    ctx.arc(x, y, size * 0.6, 0, 2 * Math.PI);
    ctx.fillStyle = "#ffffff";
    ctx.fill();
    ctx.strokeStyle = DARK;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
}

/** The person nearest to a click on the board, if close enough. */
export function personOnBoard(
  results: AnalysisResults,
  state: FrameState,
  canvasW: number,
  canvasH: number,
  clickX: number,
  clickY: number,
): number | null {
  const { scale, toBoard } = boardTransform(results, canvasW, canvasH);
  let best: number | null = null;
  let bestDistance = Infinity;
  for (const person of state.people) {
    if (!person.pitch) continue;
    const [x, y] = toBoard(person.pitch);
    const distance = Math.hypot(x - clickX, y - clickY);
    if (person.key !== null && distance < bestDistance) {
      bestDistance = distance;
      best = person.key;
    }
  }
  return bestDistance <= Math.max(12, scale * 2.5) ? best : null;
}
