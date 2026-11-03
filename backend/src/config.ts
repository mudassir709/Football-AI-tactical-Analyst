// Loads and validates all settings once at startup, so a missing or malformed
// value stops the server immediately with a clear message instead of failing
// later in the middle of a request.
import { existsSync } from "node:fs";
import path from "node:path";
import { z } from "zod";

const REPO_ROOT = path.resolve(import.meta.dirname, "../..");

// Locally, settings live in the shared .env at the repository root.
// In Docker they arrive as real environment variables instead.
const envFile = path.join(REPO_ROOT, ".env");
if (existsSync(envFile)) process.loadEnvFile(envFile);

const EnvSchema = z.object({
  DATABASE_URL: z.string().min(1),
  REDIS_URL: z.string().default("redis://localhost:6379"),
  API_PORT: z.coerce.number().int().default(4000),
  JWT_SECRET: z.string().min(32, "JWT_SECRET must be at least 32 characters"),
  STORAGE_DIR: z.string().default("./storage"),
  FRONTEND_URL: z.string().default("http://localhost:5173"),
  // 1 GB: enough for a full half of a match (about 45 minutes).
  MAX_UPLOAD_MB: z.coerce.number().positive().default(1024),
  NODE_ENV: z.string().default("development"),
  // Send the login cookie over HTTPS only. Defaults to on in production; set
  // "false" when serving production builds over plain HTTP (e.g. a local demo).
  COOKIE_SECURE: z.enum(["true", "false"]).optional(),
});

const parsed = EnvSchema.safeParse(process.env);
if (!parsed.success) {
  console.error("Invalid configuration:\n" + z.prettifyError(parsed.error));
  process.exit(1);
}
const env = parsed.data;

export const config = {
  databaseUrl: env.DATABASE_URL,
  redisUrl: env.REDIS_URL,
  port: env.API_PORT,
  jwtSecret: env.JWT_SECRET,
  // Relative paths are resolved from the repository root, so the API and the
  // Python worker agree on where files live.
  storageDir: path.resolve(REPO_ROOT, env.STORAGE_DIR),
  frontendUrl: env.FRONTEND_URL,
  maxUploadBytes: env.MAX_UPLOAD_MB * 1024 * 1024,
  isProduction: env.NODE_ENV === "production",
  cookieSecure: env.COOKIE_SECURE ? env.COOKIE_SECURE === "true" : env.NODE_ENV === "production",
};
