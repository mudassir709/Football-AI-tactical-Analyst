// Tests for the geometry helpers used to draw the overlays.
import { describe, expect, it } from "vitest";
import { applyHomography, convexHull, fitContain, lerpHomography } from "./geometry";

describe("applyHomography", () => {
  it("leaves points unchanged with the identity matrix", () => {
    expect(applyHomography([1, 0, 0, 0, 1, 0, 0, 0, 1], 52.5, 34)).toEqual([52.5, 34]);
  });

  it("applies scaling and moving like a camera would", () => {
    // Pitch metres -> pixels: 10 px per metre, pitch corner at (100, 50).
    const h = [10, 0, 100, 0, 10, 50, 0, 0, 1];
    expect(applyHomography(h, 0, 0)).toEqual([100, 50]);
    expect(applyHomography(h, 105, 68)).toEqual([1150, 730]);
  });

  it("divides by w, which is what makes far things look smaller", () => {
    // w = 2 for this point, so the result is halved.
    expect(applyHomography([1, 0, 0, 0, 1, 0, 0, 0, 2], 10, 20)).toEqual([5, 10]);
  });

  it("returns null for points behind the camera (w <= 0)", () => {
    expect(applyHomography([1, 0, 0, 0, 1, 0, 0, 0, -1], 10, 20)).toBeNull();
    expect(applyHomography([1, 0, 0, 0, 1, 0, 0, 0, 0], 10, 20)).toBeNull();
  });
});

describe("lerpHomography", () => {
  it("blends two matrices number by number", () => {
    const a = [0, 0, 0, 0, 0, 0, 0, 0, 1];
    const b = [2, 4, 6, 8, 10, 12, 0, 0, 1];
    expect(lerpHomography(a, b, 0.5)).toEqual([1, 2, 3, 4, 5, 6, 0, 0, 1]);
    expect(lerpHomography(a, b, 0)).toEqual(a);
    expect(lerpHomography(a, b, 1)).toEqual(b);
  });
});

describe("convexHull", () => {
  it("keeps only the outer points (the team shape outline)", () => {
    const corners: [number, number][] = [[0, 0], [10, 0], [10, 10], [0, 10]];
    const hull = convexHull([...corners, [5, 5], [3, 7]]); // two players inside
    expect(hull).toHaveLength(4);
    expect(hull).toEqual(expect.arrayContaining(corners));
  });

  it("drops points that lie on a straight edge", () => {
    expect(convexHull([[0, 0], [5, 0], [10, 0], [5, 8]])).toHaveLength(3);
  });

  it("returns fewer than three points unchanged (no area to draw)", () => {
    expect(convexHull([[1, 2], [3, 4]])).toEqual([[1, 2], [3, 4]]);
  });
});

describe("fitContain", () => {
  it("fits a wide video into a taller box with bars above and below", () => {
    expect(fitContain(1920, 1080, 960, 600)).toEqual({ scale: 0.5, offsetX: 0, offsetY: 30 });
  });

  it("fits a video into a wider box with bars on the sides", () => {
    expect(fitContain(1920, 1080, 1200, 540)).toEqual({ scale: 0.5, offsetX: 120, offsetY: 0 });
  });
});
