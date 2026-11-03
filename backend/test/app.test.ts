// Tests for the parts of the API that are not about users or matches:
// the health check, unknown addresses and the file storage safety checks.
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import request from "supertest";
import { describe, expect, it } from "vitest";
import { absolutePath, isVideoFile } from "../src/storage.ts";
import { app, fakeMp4 } from "./helpers.ts";

describe("health check", () => {
  it("reports that the database and the queue are reachable", async () => {
    const response = await request(app).get("/api/health").expect(200);
    expect(response.body).toMatchObject({ status: "ok", database: "up", redis: "up" });
    expect(typeof response.body.workers).toBe("number");
  });
});

it("answers unknown API addresses with 404 and a JSON error", async () => {
  const response = await request(app).get("/api/does-not-exist").expect(404);
  expect(response.body).toEqual({ error: "Not found" });
});

describe("file storage", () => {
  it("refuses paths that try to leave the storage folder", () => {
    expect(() => absolutePath("../../.env")).toThrow("Path outside storage");
    expect(() => absolutePath("videos/../../secret.txt")).toThrow("Path outside storage");
    expect(absolutePath("videos/a.mp4")).toMatch(/videos[\\/]a\.mp4$/);
  });

  // Write some bytes to a temporary file and ask whether it is a video.
  const folder = mkdtempSync(path.join(tmpdir(), "video-check-"));
  const check = (name: string, bytes: Buffer) => {
    const file = path.join(folder, name);
    writeFileSync(file, bytes);
    return isVideoFile(file);
  };

  it("recognises real video files by their first bytes", async () => {
    expect(await check("a.mp4", fakeMp4())).toBe(true);
    expect(await check("a.mkv", Buffer.from([0x1a, 0x45, 0xdf, 0xa3, 0, 0, 0, 0, 0, 0, 0, 0]))).toBe(true);
    expect(await check("a.avi", Buffer.from("RIFF\u0000\u0000\u0000\u0000AVI LIST", "binary"))).toBe(true);
  });

  it("rejects other files, whatever their name", async () => {
    expect(await check("fake.mp4", Buffer.from("plain text pretending to be a video"))).toBe(false);
    expect(await check("tiny.mp4", Buffer.from("abc"))).toBe(false);
  });
});
