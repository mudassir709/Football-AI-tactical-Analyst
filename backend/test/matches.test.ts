// Tests for uploading and managing matches (/api/matches/...): which files are
// accepted, that the analysis job is queued, that an analysis can be
// cancelled, and that users can only ever see and change their own matches.
import { existsSync } from "node:fs";
import request from "supertest";
import { Job, Worker } from "bullmq";
import { Redis } from "ioredis";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { config } from "../src/config.ts";
import { prisma } from "../src/db.ts";
import { analysisQueue, cancelKey, cancelledState, QUEUE_NAME } from "../src/queue.ts";
import { absolutePath } from "../src/storage.ts";
import { app, fakeMp4, loggedInUser, resetData } from "./helpers.ts";

beforeEach(resetData);

/** Upload a fake video as the given user and return the new match. */
async function upload(agent: Awaited<ReturnType<typeof loggedInUser>>, mode = "quick") {
  const response = await agent
    .post("/api/matches")
    .field("title", "Test match")
    .field("mode", mode)
    .attach("video", fakeMp4(), { filename: "match.mp4", contentType: "video/mp4" })
    .expect(201);
  return response.body.match;
}

describe("uploading", () => {
  it("is only possible when logged in", async () => {
    await request(app).get("/api/matches").expect(401);
    await request(app)
      .post("/api/matches")
      .attach("video", fakeMp4(), { filename: "match.mp4", contentType: "video/mp4" })
      .expect(401);
  });

  it("stores the video, creates a queued match and puts a job in the queue", async () => {
    const agent = await loggedInUser();
    const match = await upload(agent);

    expect(match).toMatchObject({ title: "Test match", status: "QUEUED", analysisMode: "quick" });
    // The job's ID is the match ID, and it tells the worker which file to analyse.
    const job = await Job.fromId(analysisQueue, match.id);
    expect(job?.data).toMatchObject({ matchId: match.id, mode: "quick" });
    expect(existsSync(absolutePath(job!.data.videoPath))).toBe(true);
    // The browser must never see where files are stored on the server.
    expect(match.videoPath).toBeUndefined();
  });

  it("refuses a request without a file", async () => {
    const agent = await loggedInUser();
    const response = await agent.post("/api/matches").field("title", "No file").expect(400);
    expect(response.body.error).toContain("Upload a video file");
  });

  it("refuses files that are not videos by name and type", async () => {
    const agent = await loggedInUser();
    await agent
      .post("/api/matches")
      .attach("video", Buffer.from("hello"), { filename: "notes.txt", contentType: "text/plain" })
      .expect(400);
  });

  it("refuses a text file disguised as an .mp4 and deletes it again", async () => {
    const agent = await loggedInUser();
    const response = await agent
      .post("/api/matches")
      .attach("video", Buffer.from("this is not really a video"), { filename: "fake.mp4", contentType: "video/mp4" })
      .expect(400);
    expect(response.body.error).toBe("The file is not a valid video");
    expect(await prisma.match.count()).toBe(0);
  });

  it("refuses files over the size limit", async () => {
    const agent = await loggedInUser();
    const response = await agent
      .post("/api/matches")
      .attach("video", fakeMp4(2 * 1024 * 1024), { filename: "big.mp4", contentType: "video/mp4" })
      .expect(413); // the test limit is 1 MB
    expect(response.body.error).toBe("File is larger than 1 MB");
  });

  it("refuses an unknown analysis mode", async () => {
    const agent = await loggedInUser();
    await agent
      .post("/api/matches")
      .field("mode", "turbo")
      .attach("video", fakeMp4(), { filename: "match.mp4", contentType: "video/mp4" })
      .expect(400);
    expect(await prisma.match.count()).toBe(0);
  });
});

describe("other users' matches", () => {
  it("are invisible: every route answers 404, as if the match did not exist", async () => {
    const owner = await loggedInUser("owner@example.com");
    const stranger = await loggedInUser("stranger@example.com");
    const match = await upload(owner);

    await stranger.get(`/api/matches/${match.id}`).expect(404);
    await stranger.get(`/api/matches/${match.id}/video`).expect(404);
    await stranger.get(`/api/matches/${match.id}/results`).expect(404);
    await stranger.get(`/api/matches/${match.id}/report`).expect(404);
    await stranger.post(`/api/matches/${match.id}/reanalyse`).expect(404);
    await stranger.delete(`/api/matches/${match.id}`).expect(404);

    // ...and the stranger's own list is empty, while the owner still has the match.
    expect((await stranger.get("/api/matches").expect(200)).body.matches).toEqual([]);
    await owner.get(`/api/matches/${match.id}`).expect(200);
  });
});

describe("the rules while a match is being analysed", () => {
  it("results and reports are only available after the analysis", async () => {
    const agent = await loggedInUser();
    const match = await upload(agent);
    await agent.get(`/api/matches/${match.id}/results`).expect(409);
    await agent.post(`/api/matches/${match.id}/report`).expect(409);
  });

  it("a match cannot be queued twice", async () => {
    const agent = await loggedInUser();
    const match = await upload(agent);
    const response = await agent.post(`/api/matches/${match.id}/reanalyse`).expect(409);
    expect(response.body.error).toBe("This match is already being analysed");
  });

  it("a match cannot be deleted while the worker is analysing it", async () => {
    const agent = await loggedInUser();
    const match = await upload(agent);
    await prisma.match.update({ where: { id: match.id }, data: { status: "PROCESSING" } });
    await agent.delete(`/api/matches/${match.id}`).expect(409);
  });

  it("a finished match can be re-analysed in another mode", async () => {
    const agent = await loggedInUser();
    const match = await upload(agent, "quick");
    await prisma.match.update({ where: { id: match.id }, data: { status: "COMPLETED" } });
    const response = await agent.post(`/api/matches/${match.id}/reanalyse`).send({ mode: "standard" }).expect(200);
    expect(response.body.match).toMatchObject({ status: "QUEUED", analysisMode: "standard" });
  });
});

describe("deleting", () => {
  it("removes the match, its waiting job and its video file", async () => {
    const agent = await loggedInUser();
    const match = await upload(agent);
    const videoPath = (await Job.fromId(analysisQueue, match.id))!.data.videoPath;

    await agent.delete(`/api/matches/${match.id}`).expect(204);

    await agent.get(`/api/matches/${match.id}`).expect(404);
    expect(await Job.fromId(analysisQueue, match.id)).toBeUndefined();
    expect(existsSync(absolutePath(videoPath))).toBe(false);
  });
});

describe("coaching report", () => {
  it("tells the dashboard when no AI service is configured", async () => {
    const agent = await loggedInUser();
    const match = await upload(agent);
    const response = await agent.get(`/api/matches/${match.id}/report`).expect(200);
    expect(response.body).toEqual({ report: null, enabled: false });
  });
});

describe("cancelling", () => {
  it("a queued analysis is cancelled at once and its job leaves the queue", async () => {
    const agent = await loggedInUser();
    const match = await upload(agent);

    const response = await agent.post(`/api/matches/${match.id}/cancel`).expect(200);
    expect(response.body.match).toMatchObject({ status: "CANCELLED", stage: "Cancelled" });
    expect(await Job.fromId(analysisQueue, match.id)).toBeUndefined();
    // It can be started again later.
    await agent.post(`/api/matches/${match.id}/reanalyse`).expect(200);
  });

  it("a running analysis gets a stop note for the worker", async () => {
    const agent = await loggedInUser();
    const match = await upload(agent);
    // Play the worker: take the job and keep it "running" until the test ends.
    let finish = () => {};
    const worker = new Worker(QUEUE_NAME, () => new Promise<void>((resolve) => (finish = resolve)), {
      connection: new Redis(config.redisUrl, { maxRetriesPerRequest: null }),
    });
    await vi.waitFor(async () => expect(await (await Job.fromId(analysisQueue, match.id))!.isActive()).toBe(true));
    await prisma.match.update({ where: { id: match.id }, data: { status: "PROCESSING" } });

    const response = await agent.post(`/api/matches/${match.id}/cancel`).expect(200);
    expect(response.body.match).toMatchObject({ status: "PROCESSING", stage: "Cancelling…" });
    const redis = new Redis(config.redisUrl);
    expect(await redis.get(cancelKey(match.id))).toBe("1"); // the note the Python worker looks for

    finish();
    await worker.close();
    redis.disconnect();
  });

  it("is refused when nothing is being analysed, and invisible to other users", async () => {
    const owner = await loggedInUser("owner@example.com");
    const stranger = await loggedInUser("stranger@example.com");
    const match = await upload(owner);
    await stranger.post(`/api/matches/${match.id}/cancel`).expect(404);

    await prisma.match.update({ where: { id: match.id }, data: { status: "COMPLETED" } });
    const response = await owner.post(`/api/matches/${match.id}/cancel`).expect(409);
    expect(response.body.error).toBe("This match is not being analysed");
  });

  it("a cancelled re-analysis goes back to the earlier results", () => {
    expect(cancelledState({ resultPath: "results/abc.json" })).toMatchObject({ status: "COMPLETED" });
    expect(cancelledState({ resultPath: null })).toMatchObject({ status: "CANCELLED" });
  });
});
