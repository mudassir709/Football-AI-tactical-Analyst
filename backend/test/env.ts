// Settings for the automated tests. The tests must never touch the real data:
//   - they use their own database: the normal one with "_test" added to its name
//   - they use Redis database 1, so the real AI worker (which listens on
//     database 0) never picks up the test uploads
//   - uploaded files go to a temporary folder
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const envFile = path.resolve(import.meta.dirname, "../../.env");

export function testEnv(): Record<string, string> {
  // Locally the database address comes from .env; in CI it is already set.
  if (!process.env.DATABASE_URL && existsSync(envFile)) process.loadEnvFile(envFile);
  const database = new URL(process.env.DATABASE_URL ?? "postgresql://tactical:tactical@localhost:5432/tactical_analyst");
  database.pathname = `${database.pathname}_test`;

  const redis = new URL(process.env.REDIS_URL ?? "redis://localhost:6379");
  redis.pathname = "/1";

  return {
    DATABASE_URL: database.toString(),
    REDIS_URL: redis.toString(),
    STORAGE_DIR: path.join(tmpdir(), "tactical-eye-test-storage"),
    JWT_SECRET: "test-secret-that-is-at-least-32-characters-long",
    MAX_UPLOAD_MB: "1", // small limit, so the "file too large" test is quick
    NODE_ENV: "test",
    // No AI report settings: reports count as "not configured" in the tests.
    AZURE_OPENAI_ENDPOINT: "",
    AZURE_OPENAI_API_KEY: "",
    AZURE_OPENAI_DEPLOYMENT: "",
  };
}
