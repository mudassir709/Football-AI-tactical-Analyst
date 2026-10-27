// Coordinate helpers shared by the video overlay and the 2D board.

export type Point = [number, number];

/**
 * Apply a 3x3 homography (row-major) to a point. Used to project pitch
 * positions in metres onto the current video frame. Returns null for points
 * that would land behind the camera.
 */
export function applyHomography(h: number[], x: number, y: number): Point | null {
  const w = h[6] * x + h[7] * y + h[8];
  if (w <= 1e-9) return null;
  return [(h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w];
}

/**
 * Blend two homographies; good for small camera moves. The worker stores them
 * with a consistent scale and sign, so plain element-wise blending works
 * (dividing by h[8] would explode when it is close to zero).
 */
export function lerpHomography(a: number[], b: number[], alpha: number): number[] {
  return a.map((value, i) => value + (b[i] - value) * alpha);
}

export const lerp = (a: number, b: number, alpha: number) => a + (b - a) * alpha;

/** Convex hull (Andrew's monotone chain), counter-clockwise. */
export function convexHull(points: Point[]): Point[] {
  if (points.length < 3) return points.slice();
  const sorted = points.slice().sort((p, q) => p[0] - q[0] || p[1] - q[1]);
  const cross = (o: Point, a: Point, b: Point) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: Point[] = [];
  for (const p of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper: Point[] = [];
  for (const p of sorted.reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  return lower.slice(0, -1).concat(upper.slice(0, -1));
}

/**
 * Where a video is actually drawn inside its element: videos keep their
 * aspect ratio, leaving black bars. Returns the scale and offset that map
 * source-video pixels to element pixels.
 */
export function fitContain(sourceW: number, sourceH: number, boxW: number, boxH: number) {
  const scale = Math.min(boxW / sourceW, boxH / sourceH);
  return {
    scale,
    offsetX: (boxW - sourceW * scale) / 2,
    offsetY: (boxH - sourceH * scale) / 2,
  };
}
