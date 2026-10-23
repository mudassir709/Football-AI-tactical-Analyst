// File storage for uploaded videos and analysis results.
//
// The database only stores *relative* paths such as "videos/abc.mp4"; each
// service joins them with its own STORAGE_DIR. That way the API and the worker
// can see the same files even when they are mounted at different locations
// (e.g. inside Docker containers).
import { mkdirSync } from "node:fs";
import { open, rm } from "node:fs/promises";
import path from "node:path";
import { config } from "./config.ts";

export const VIDEO_DIR = "videos";
export const RESULTS_DIR = "results";

for (const dir of [VIDEO_DIR, RESULTS_DIR]) {
  mkdirSync(path.join(config.storageDir, dir), { recursive: true });
}

/** Absolute path for a path stored in the database. */
export function absolutePath(relativePath: string): string {
  const resolved = path.resolve(config.storageDir, relativePath);
  // Refuse anything that escapes the storage folder (e.g. "../../.env").
  if (!resolved.startsWith(config.storageDir + path.sep)) {
    throw new Error(`Path outside storage: ${relativePath}`);
  }
  return resolved;
}

/** Delete a stored file, ignoring files that are already gone. */
export async function removeFile(relativePath: string | null): Promise<void> {
  if (relativePath) await rm(absolutePath(relativePath), { force: true });
}

/**
 * Check a file's first bytes ("magic numbers") to confirm it really is a video.
 * The browser-provided MIME type and file extension can be faked; the file
 * contents cannot (without breaking the video).
 */
export async function isVideoFile(absPath: string): Promise<boolean> {
  const handle = await open(absPath, "r");
  try {
    const header = Buffer.alloc(12);
    const { bytesRead } = await handle.read(header, 0, 12, 0);
    if (bytesRead < 12) return false;
    const ascii = (start: number, end: number) => header.toString("ascii", start, end);
    return (
      ascii(4, 8) === "ftyp" || // MP4 / MOV / M4V
      header.readUInt32BE(0) === 0x1a45dfa3 || // Matroska / WebM
      (ascii(0, 4) === "RIFF" && ascii(8, 12) === "AVI ") // AVI
    );
  } finally {
    await handle.close();
  }
}
