// Shared helpers for the API tests.
import request from "supertest";
import { createApp } from "../src/app.ts";
import { prisma } from "../src/db.ts";
import { analysisQueue } from "../src/queue.ts";

export const app = createApp();

/** Empty the test database and the test queue, so every test starts clean. */
export async function resetData(): Promise<void> {
  await prisma.$executeRawUnsafe('TRUNCATE "Match", "User" CASCADE');
  await analysisQueue.obliterate({ force: true });
}

/**
 * Register a new user and return a supertest "agent". An agent works like a
 * browser: it keeps the login cookie and sends it with every later request.
 */
export async function loggedInUser(email = "coach@example.com") {
  const agent = request.agent(app);
  await agent
    .post("/api/auth/register")
    .send({ name: "Test Coach", email, password: "longenough1" })
    .expect(201);
  return agent;
}

/**
 * The smallest file that passes the server's video check: the first 12 bytes
 * of an MP4 file ("....ftypisom"), followed by some padding.
 */
export function fakeMp4(sizeBytes = 2048): Buffer {
  const file = Buffer.alloc(sizeBytes);
  file.write("\u0000\u0000\u0000\u0018ftypisom", 0, "binary");
  return file;
}
