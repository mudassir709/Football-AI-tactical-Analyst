// Account routes: /api/auth/register, /login, /logout, /me
import bcrypt from "bcryptjs";
import { Router } from "express";
import { z } from "zod";
import { AUTH_COOKIE, authCookieOptions, requireAuth, signToken } from "../auth.ts";
import { prisma } from "../db.ts";
import type { User } from "../generated/prisma/client.ts";

export const authRouter = Router();

const BCRYPT_ROUNDS = 12; // cost factor: higher = slower to brute-force

const Email = z.string().trim().toLowerCase().pipe(z.email());
const RegisterBody = z.object({
  email: Email,
  name: z.string().trim().min(1).max(80),
  password: z.string().min(8, "Password must be at least 8 characters").max(128),
});
const LoginBody = z.object({ email: Email, password: z.string().min(1) });

/** The user fields that are safe to send to the browser (never the hash). */
const publicUser = (user: User) => ({
  id: user.id,
  email: user.email,
  name: user.name,
  createdAt: user.createdAt,
});

authRouter.post("/register", async (req, res) => {
  const body = RegisterBody.parse(req.body);
  if (await prisma.user.findUnique({ where: { email: body.email } })) {
    res.status(409).json({ error: "An account with this email already exists" });
    return;
  }
  const user = await prisma.user.create({
    data: {
      email: body.email,
      name: body.name,
      passwordHash: await bcrypt.hash(body.password, BCRYPT_ROUNDS),
    },
  });
  res.cookie(AUTH_COOKIE, signToken(user.id), authCookieOptions);
  res.status(201).json({ user: publicUser(user) });
});

authRouter.post("/login", async (req, res) => {
  const body = LoginBody.parse(req.body);
  const user = await prisma.user.findUnique({ where: { email: body.email } });
  // Same message for "no such user" and "wrong password", so attackers
  // cannot use the login form to discover which emails are registered.
  if (!user || !(await bcrypt.compare(body.password, user.passwordHash))) {
    res.status(401).json({ error: "Invalid email or password" });
    return;
  }
  res.cookie(AUTH_COOKIE, signToken(user.id), authCookieOptions);
  res.json({ user: publicUser(user) });
});

authRouter.post("/logout", (_req, res) => {
  res.clearCookie(AUTH_COOKIE, { ...authCookieOptions, maxAge: undefined });
  res.status(204).end();
});

authRouter.get("/me", requireAuth, async (req, res) => {
  const user = await prisma.user.findUnique({ where: { id: req.userId } });
  if (!user) {
    res.clearCookie(AUTH_COOKIE, { ...authCookieOptions, maxAge: undefined });
    res.status(401).json({ error: "Account no longer exists" });
    return;
  }
  res.json({ user: publicUser(user) });
});
