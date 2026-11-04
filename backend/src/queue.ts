// The job queue between this API and the Python AI worker (BullMQ on Redis).
//
//   API  --add job-->  Redis "match-analysis" queue  --picks job-->  Python worker
//   API  <--events (active / progress / completed / failed)--  Redis  <--  worker
//
// The job ID is the match ID, so every event maps straight to a database row.
import { Job, Queue, QueueEvents } from "bullmq";
import { Redis } from "ioredis";
import { config } from "./config.ts";
import { prisma } from "./db.ts";
import type { Match } from "./generated/prisma/client.ts";

export const QUEUE_NAME = "match-analysis"; // must match the worker's queue name

/** What the worker needs to know about a job. */
export const ANALYSIS_MODES = ["standard", "quick"] as const;
export type AnalysisMode = (typeof ANALYSIS_MODES)[number];

export interface AnalysisJobData {
  matchId: string;
  videoPath: string; // relative to STORAGE_DIR
  mode: AnalysisMode;
}

/** What the worker returns when a job succeeds, or { cancelled: true } when
 *  the user stopped it (see requestCancel). */
interface AnalysisJobResult {
  cancelled?: boolean;
  resultPath: string; // relative to STORAGE_DIR
  playbackPath: string; // browser-playable copy, relative to STORAGE_DIR
  summary: Record<string, unknown>;
}

/** Redis key the worker checks to see if the user asked to stop a running job.
 *  The worker uses the same name (worker/worker.py). */
export const cancelKey = (matchId: string) => `tactical-eye:cancel:${matchId}`;

/** Progress payload the worker sends with job.updateProgress(). */
interface ProgressData {
  percent: number;
  stage: string;
}

// BullMQ requires maxRetriesPerRequest: null so blocking Redis commands never time out.
const redisConnection = () => new Redis(config.redisUrl, { maxRetriesPerRequest: null });

export const analysisQueue = new Queue<AnalysisJobData>(QUEUE_NAME, {
  connection: redisConnection(),
  defaultJobOptions: {
    attempts: 2, // retry once if the worker crashes or errors
    backoff: { type: "fixed", delay: 10_000 },
    removeOnComplete: 500, // keep recent history for monitoring
    removeOnFail: 500,
  },
});

// Separate lightweight connection used only by the health check.
const healthConnection = redisConnection();
export const pingRedis = () => healthConnection.ping();

/** Close this module's Redis connections (on shutdown, and after the tests). */
export async function closeQueue(): Promise<void> {
  await analysisQueue.close();
  healthConnection.disconnect();
}

/**
 * Number of workers connected to the queue. BullMQ's own getWorkersCount()
 * only recognises Node workers (it expects a base64 queue name in the Redis
 * client name); the Python worker uses the plain name, so accept both.
 */
export async function countWorkers(): Promise<number> {
  const clients = (await healthConnection.client("LIST")) as string;
  const prefixes = [
    `bull:${QUEUE_NAME}:w:`,
    `bull:${Buffer.from(QUEUE_NAME).toString("base64")}:w:`,
  ];
  const names = clients
    .split("\n")
    .map((line) => /(?:^| )name=(\S+)/.exec(line)?.[1])
    .filter((name): name is string => !!name && prefixes.some((p) => name.startsWith(p)));
  return new Set(names).size; // each worker opens several connections with one name
}

export async function enqueueAnalysis(data: AnalysisJobData): Promise<void> {
  // BullMQ silently ignores a job whose ID already exists, and finished jobs
  // are kept for history; remove the old one so re-analysis really runs.
  const previous = await Job.fromId(analysisQueue, data.matchId);
  if (previous && !(await previous.isActive())) await previous.remove();
  // A cancel note left over from an earlier run must not stop this new one.
  await healthConnection.del(cancelKey(data.matchId));
  await analysisQueue.add("analyse", data, { jobId: data.matchId });
}

/** Remove a job that has not started yet (e.g. when its match is deleted).
 *  Returns true if a waiting job was removed. */
export async function removeQueuedJob(matchId: string): Promise<boolean> {
  const job = await Job.fromId(analysisQueue, matchId);
  if (job && ((await job.isWaiting()) || (await job.isDelayed()))) {
    await job.remove();
    return true;
  }
  return false;
}

/**
 * Stop a match's analysis. A job still waiting in the queue is simply removed
 * ("removed"; the same when there is no job left at all). A running one can't be pulled away from the worker, so we
 * leave a note in Redis that the worker checks every few seconds; it then
 * stops and reports back ("stopping"). The note expires after a day in case
 * no worker ever picks it up.
 */
export async function requestCancel(matchId: string): Promise<"removed" | "stopping"> {
  if (await removeQueuedJob(matchId)) return "removed";
  const job = await Job.fromId(analysisQueue, matchId);
  // No job at all (e.g. lost after a crash): nothing is running, so it's cancelled now.
  if (!job || !(await job.isActive())) return "removed";
  await healthConnection.set(cancelKey(matchId), "1", "EX", 24 * 60 * 60);
  return "stopping";
}

/**
 * The database fields for a match whose analysis was stopped. If an earlier
 * analysis had finished, its results are still on disk (new results only
 * replace them at the very end), so the match simply goes back to showing
 * them. Otherwise it is marked as cancelled.
 */
export function cancelledState(match: Pick<Match, "resultPath">) {
  return match.resultPath
    ? { status: "COMPLETED" as const, progress: 100, stage: "Re-analysis cancelled" }
    : { status: "CANCELLED" as const, progress: 0, stage: "Cancelled" };
}

/**
 * Listen to worker events, keep the database in sync, and call `onUpdate`
 * with every changed match so it can be pushed to the user's browser.
 */
export function startQueueEventListener(onUpdate: (match: Match) => void): QueueEvents {
  const events = new QueueEvents(QUEUE_NAME, { connection: redisConnection() });

  // Events often arrive in bursts. Each match's updates are chained so they are
  // written and pushed in arrival order; otherwise a slower database write
  // could finish last and make the progress bar jump backwards.
  const chains = new Map<string, Promise<void>>();
  const update = (matchId: string, data: Parameters<typeof prisma.match.update>[0]["data"]) => {
    const next = (chains.get(matchId) ?? Promise.resolve()).then(async () => {
      // Updates for matches deleted in the meantime are simply dropped.
      const match = await prisma.match.update({ where: { id: matchId }, data }).catch(() => null);
      if (match) onUpdate(match);
    });
    chains.set(matchId, next);
    void next.finally(() => {
      if (chains.get(matchId) === next) chains.delete(matchId);
    });
    return next;
  };

  events.on("active", ({ jobId }) => {
    void update(jobId, { status: "PROCESSING", stage: "Starting", errorMessage: null });
  });

  events.on("progress", ({ jobId, data }) => {
    const progress = data as ProgressData;
    if (typeof progress?.percent !== "number") return;
    void update(jobId, {
      status: "PROCESSING",
      progress: Math.round(progress.percent),
      stage: progress.stage,
    });
  });

  events.on("completed", async ({ jobId, returnvalue }) => {
    // The return value arrives JSON-encoded when it comes from the Python worker.
    const result = (typeof returnvalue === "string" ? JSON.parse(returnvalue) : returnvalue) as AnalysisJobResult;
    if (result?.cancelled) {
      // The worker stopped because the user asked it to.
      const match = await prisma.match.findUnique({ where: { id: jobId } });
      if (match) void update(jobId, cancelledState(match));
      return;
    }
    void update(jobId, {
      status: "COMPLETED",
      progress: 100,
      stage: "Done",
      resultPath: result.resultPath,
      playbackPath: result.playbackPath,
      summary: result.summary as object,
      completedAt: new Date(),
    });
  });

  events.on("failed", async ({ jobId, failedReason }) => {
    // A failed attempt is retried while attempts remain; only the last one is final.
    const job = await Job.fromId(analysisQueue, jobId);
    const willRetry = job !== undefined && job.attemptsMade < (job.opts.attempts ?? 1);
    await update(jobId, willRetry
      ? { status: "QUEUED", stage: "Retrying after an error", errorMessage: failedReason }
      : { status: "FAILED", stage: "Failed", errorMessage: failedReason });
  });

  events.on("error", (error) => console.error("Queue event listener error:", error.message));
  return events;
}
