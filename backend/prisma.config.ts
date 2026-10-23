// Prisma CLI configuration (used by `prisma migrate`, `prisma generate`, ...).
import { existsSync } from "node:fs";
import { defineConfig } from "prisma/config";

// Locally, settings live in the shared .env at the repository root.
// In Docker they arrive as real environment variables instead.
if (existsSync("../.env")) process.loadEnvFile("../.env");

export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: {
    path: "prisma/migrations",
  },
  datasource: {
    url: process.env["DATABASE_URL"],
  },
});
