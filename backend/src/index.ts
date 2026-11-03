// Entry point: starts the HTTP API and the WebSocket server on one port.
//
// WebSockets keep a connection open to each logged-in browser, so the server
// can *push* progress updates the moment the worker reports them, instead of
// the browser asking "is it done yet?" over and over.
import { createServer } from "node:http";
import { Server } from "socket.io";
import { createApp } from "./app.ts";
import { AUTH_COOKIE, verifyToken } from "./auth.ts";
import { config } from "./config.ts";
import { prisma } from "./db.ts";
import { toPublicMatch } from "./matchView.ts";
import { closeQueue, startQueueEventListener } from "./queue.ts";

const app = createApp();
const server = createServer(app);
const io = new Server(server, {
  cors: { origin: config.frontendUrl, credentials: true },
});

/** Read the login token out of a raw "Cookie" header ("a=1; token=xyz"). */
function tokenFromCookieHeader(header: string | undefined): string | undefined {
  for (const part of header?.split(";") ?? []) {
    const [name, ...value] = part.trim().split("=");
    if (name === AUTH_COOKIE) return decodeURIComponent(value.join("="));
  }
  return undefined;
}

// Only logged-in users may connect; each joins a private "room" so they only
// ever receive updates about their own matches.
io.use((socket, next) => {
  const userId = verifyToken(tokenFromCookieHeader(socket.handshake.headers.cookie));
  if (!userId) return next(new Error("Not logged in"));
  socket.data.userId = userId;
  next();
});
io.on("connection", (socket) => {
  void socket.join(`user:${socket.data.userId}`);
});

const queueEvents = startQueueEventListener((match) => {
  io.to(`user:${match.userId}`).emit("match:updated", toPublicMatch(match));
});

server.listen(config.port, () => {
  console.log(`API listening on http://localhost:${config.port}`);
  console.log(`Storage directory: ${config.storageDir}`);
});

// Close connections cleanly on Ctrl+C or when Docker stops the container.
async function shutdown(signal: string) {
  console.log(`${signal} received, shutting down`);
  io.close();
  server.close();
  await Promise.allSettled([queueEvents.close(), closeQueue(), prisma.$disconnect()]);
  process.exit(0);
}
process.on("SIGINT", () => void shutdown("SIGINT"));
process.on("SIGTERM", () => void shutdown("SIGTERM"));
