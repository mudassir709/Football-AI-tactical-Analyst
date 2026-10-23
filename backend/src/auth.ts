// Login tokens and the "must be logged in" middleware.
//
// After login the server gives the browser a signed token (a JWT) in an
// HTTP-only cookie: the browser sends it back automatically on every request,
// but page scripts cannot read it, which protects it from cross-site-scripting
// attacks. The signature lets the server trust the user ID inside without a
// database lookup.
import type { CookieOptions, NextFunction, Request, Response } from "express";
import jwt from "jsonwebtoken";
import { config } from "./config.ts";

export const AUTH_COOKIE = "token";
const TOKEN_LIFETIME_SECONDS = 7 * 24 * 60 * 60; // 7 days

// Make `req.userId` known to TypeScript on every Express request.
declare global {
  namespace Express {
    interface Request {
      userId?: string;
    }
  }
}

export const authCookieOptions: CookieOptions = {
  httpOnly: true,
  sameSite: "lax",
  secure: config.isProduction, // HTTPS-only in production
  maxAge: TOKEN_LIFETIME_SECONDS * 1000,
  path: "/",
};

export function signToken(userId: string): string {
  return jwt.sign({ sub: userId }, config.jwtSecret, { expiresIn: TOKEN_LIFETIME_SECONDS });
}

/** Return the user ID inside a valid token, or null if it is missing/invalid/expired. */
export function verifyToken(token: string | undefined): string | null {
  if (!token) return null;
  try {
    const payload = jwt.verify(token, config.jwtSecret);
    return typeof payload === "object" && typeof payload.sub === "string" ? payload.sub : null;
  } catch {
    return null;
  }
}

/** Reject the request with 401 unless it carries a valid login cookie. */
export function requireAuth(req: Request, res: Response, next: NextFunction): void {
  const userId = verifyToken(req.cookies?.[AUTH_COOKIE]);
  if (!userId) {
    res.status(401).json({ error: "Not logged in" });
    return;
  }
  req.userId = userId;
  next();
}
