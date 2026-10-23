// Builds the Express application: middleware, routes and error handling.
import cookieParser from "cookie-parser";
import cors from "cors";
import express, { type NextFunction, type Request, type Response } from "express";
import multer from "multer";
import { ZodError, z } from "zod";
import { config } from "./config.ts";
import { prisma } from "./db.ts";
import { analysisQueue, countWorkers, pingRedis } from "./queue.ts";
import { authRouter } from "./routes/auth.ts";
import { matchesRouter } from "./routes/matches.ts";

export function createApp() {
  const app = express();

  // Let the React app (a different origin in development) call this API
  // and send its login cookie along.
  app.use(cors({ origin: config.frontendUrl, credentials: true }));
  app.use(express.json({ limit: "1mb" }));
  app.use(cookieParser());

  app.use("/api/auth", authRouter);
  app.use("/api/matches", matchesRouter);

  // Health check for monitoring and Docker: are the database and queue reachable?
  app.get("/api/health", async (_req, res) => {
    try {
      await prisma.$queryRaw`SELECT 1`;
      await pingRedis();
      const [jobs, workers] = await Promise.all([
        analysisQueue.getJobCounts("waiting", "active", "completed", "failed", "delayed"),
        countWorkers(),
      ]);
      res.json({ status: "ok", database: "up", redis: "up", workers, jobs });
    } catch (error) {
      res.status(503).json({ status: "error", message: (error as Error).message });
    }
  });

  app.use("/api", (_req, res) => {
    res.status(404).json({ error: "Not found" });
  });

  // Central error handler: Express 5 forwards errors thrown in async routes here.
  app.use((error: unknown, _req: Request, res: Response, _next: NextFunction) => {
    if (error instanceof ZodError) {
      res.status(400).json({ error: z.prettifyError(error) });
    } else if (error instanceof multer.MulterError) {
      const tooLarge = error.code === "LIMIT_FILE_SIZE";
      res.status(tooLarge ? 413 : 400).json({
        error: tooLarge ? `File is larger than ${config.maxUploadBytes / 1024 / 1024} MB` : error.message,
      });
    } else {
      console.error(error);
      res.status(500).json({ error: "Internal server error" });
    }
  });

  return app;
}
