// Runs before every test file, before the app's code is loaded, so the app
// reads the test settings instead of the real ones.
import { afterAll } from "vitest";
import { testEnv } from "./env.ts";

Object.assign(process.env, testEnv());

// After each test file, close the database and Redis connections the app
// opened; otherwise the test run would never finish.
afterAll(async () => {
  const { prisma } = await import("../src/db.ts");
  const { closeQueue } = await import("../src/queue.ts");
  await Promise.all([prisma.$disconnect(), closeQueue()]);
});
