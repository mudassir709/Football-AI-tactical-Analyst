// Runs once before all tests: creates the test database (if needed) and brings
// its tables up to date by applying the same migrations as production.
import { execSync } from "node:child_process";
import path from "node:path";
import { testEnv } from "./env.ts";

export default function setup() {
  execSync("npx prisma migrate deploy", {
    cwd: path.resolve(import.meta.dirname, ".."),
    env: { ...process.env, ...testEnv() },
    stdio: "inherit",
  });
}
