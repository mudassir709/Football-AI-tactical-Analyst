// Match routes (all require login):
//   POST   /api/matches              upload a video -> creates a match + queues analysis
//   GET    /api/matches              list the user's matches
//   GET    /api/matches/:id          one match
//   GET    /api/matches/:id/video    stream the video (supports seeking)
//   GET    /api/matches/:id/results  full analysis JSON (tracks, heatmaps, formations...)
//   POST   /api/matches/:id/reanalyse  queue the analysis again (optionally another mode)
//   DELETE /api/matches/:id          delete a match and its files
import { randomUUID } from "node:crypto";
import path from "node:path";
import { Router, type Request, type Response } from "express";
import multer from "multer";
import { z } from "zod";
import { requireAuth } from "../auth.ts";
import { config } from "../config.ts";
import { prisma } from "../db.ts";
import { toPublicMatch } from "../matchView.ts";
import { ANALYSIS_MODES, enqueueAnalysis, removeQueuedJob, type AnalysisMode } from "../queue.ts";
import { VIDEO_DIR, absolutePath, isVideoFile, removeFile } from "../storage.ts";

export const matchesRouter = Router();
matchesRouter.use(requireAuth);

const ALLOWED_EXTENSIONS = new Set([".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"]);

// Multer handles "multipart/form-data" uploads and streams the file to disk,
// so even large videos never have to fit in memory.
const upload = multer({
  storage: multer.diskStorage({
    destination: path.join(config.storageDir, VIDEO_DIR),
    // Never trust the user's filename on disk: use a random one.
    filename: (_req, file, cb) =>
      cb(null, `${randomUUID()}${path.extname(file.originalname).toLowerCase()}`),
  }),
  limits: { fileSize: config.maxUploadBytes, files: 1 },
  fileFilter: (_req, file, cb) => {
    const extension = path.extname(file.originalname).toLowerCase();
    cb(null, ALLOWED_EXTENSIONS.has(extension) && file.mimetype.startsWith("video/"));
  },
});

const UploadBody = z.object({
  title: z.string().trim().max(120).optional(),
  // "quick" analyses fewer frames at lower resolution: much faster, less precise.
  mode: z.enum(ANALYSIS_MODES).default("standard"),
});

/** Load a match owned by the logged-in user, or answer 404 and return null. */
async function findOwnMatch(req: Request, res: Response) {
  const match = await prisma.match.findFirst({
    where: { id: String(req.params.id), userId: req.userId },
  });
  // 404 (not 403) for other users' matches, so their IDs cannot be probed.
  if (!match) res.status(404).json({ error: "Match not found" });
  return match;
}

matchesRouter.post("/", upload.single("video"), async (req, res) => {
  const file = req.file;
  if (!file) {
    res.status(400).json({ error: `Upload a video file (${[...ALLOWED_EXTENSIONS].join(", ")})` });
    return;
  }
  const videoPath = `${VIDEO_DIR}/${file.filename}`;
  if (!(await isVideoFile(file.path))) {
    await removeFile(videoPath);
    res.status(400).json({ error: "The file is not a valid video" });
    return;
  }

  const parsedBody = UploadBody.safeParse(req.body);
  if (!parsedBody.success) {
    await removeFile(videoPath);
    throw parsedBody.error;
  }
  const { title, mode } = parsedBody.data;
  let match = await prisma.match.create({
    data: {
      title: title || path.parse(file.originalname).name,
      analysisMode: mode,
      originalFilename: file.originalname,
      fileSizeBytes: file.size,
      videoPath,
      userId: req.userId!,
    },
  });

  try {
    await enqueueAnalysis({ matchId: match.id, videoPath, mode });
  } catch (error) {
    match = await prisma.match.update({
      where: { id: match.id },
      data: { status: "FAILED", errorMessage: "Could not queue the analysis job" },
    });
    console.error("Failed to queue analysis:", error);
  }
  res.status(201).json({ match: toPublicMatch(match) });
});

matchesRouter.get("/", async (req, res) => {
  const matches = await prisma.match.findMany({
    where: { userId: req.userId },
    orderBy: { createdAt: "desc" },
  });
  res.json({ matches: matches.map(toPublicMatch) });
});

matchesRouter.get("/:id", async (req, res) => {
  const match = await findOwnMatch(req, res);
  if (match) res.json({ match: toPublicMatch(match) });
});

matchesRouter.get("/:id/video", async (req, res) => {
  const match = await findOwnMatch(req, res);
  // Prefer the worker's H.264 copy: the original may use a codec browsers
  // cannot play. sendFile handles HTTP Range requests, which the browser's
  // video player uses to seek without downloading the whole file.
  if (match) res.sendFile(absolutePath(match.playbackPath ?? match.videoPath));
});

matchesRouter.get("/:id/results", async (req, res) => {
  const match = await findOwnMatch(req, res);
  if (!match) return;
  if (!match.resultPath) {
    res.status(409).json({ error: "Analysis has not finished yet" });
    return;
  }
  res.sendFile(absolutePath(match.resultPath));
});

// Run the analysis again on the stored video, e.g. after a pipeline upgrade
// or in a different mode. The previous results stay until the new ones are ready.
const ReanalyseBody = z.object({ mode: z.enum(ANALYSIS_MODES).optional() });

matchesRouter.post("/:id/reanalyse", async (req, res) => {
  const match = await findOwnMatch(req, res);
  if (!match) return;
  if (match.status === "QUEUED" || match.status === "PROCESSING") {
    res.status(409).json({ error: "This match is already being analysed" });
    return;
  }
  const { mode = match.analysisMode as AnalysisMode } = ReanalyseBody.parse(req.body ?? {});
  await enqueueAnalysis({ matchId: match.id, videoPath: match.videoPath, mode });
  const updated = await prisma.match.update({
    where: { id: match.id },
    data: { status: "QUEUED", analysisMode: mode, progress: 0, stage: null, errorMessage: null },
  });
  res.json({ match: toPublicMatch(updated) });
});

matchesRouter.delete("/:id", async (req, res) => {
  const match = await findOwnMatch(req, res);
  if (!match) return;
  if (match.status === "PROCESSING") {
    res.status(409).json({ error: "This match is being analysed; delete it when it finishes" });
    return;
  }
  await removeQueuedJob(match.id);
  await prisma.match.delete({ where: { id: match.id } });
  await Promise.all([
    removeFile(match.videoPath),
    removeFile(match.playbackPath),
    removeFile(match.resultPath),
  ]);
  res.status(204).end();
});
