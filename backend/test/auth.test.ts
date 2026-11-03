// Tests for creating accounts, logging in and out (/api/auth/...).
import request from "supertest";
import { beforeEach, describe, expect, it } from "vitest";
import { prisma } from "../src/db.ts";
import { app, loggedInUser, resetData } from "./helpers.ts";

beforeEach(resetData);

describe("registration", () => {
  it("creates the account, logs the user in and never returns the password", async () => {
    const response = await request(app)
      .post("/api/auth/register")
      .send({ name: "Ana", email: "Ana@Example.com", password: "longenough1" })
      .expect(201);

    expect(response.body.user).toMatchObject({ name: "Ana", email: "ana@example.com" });
    expect(JSON.stringify(response.body)).not.toContain("passwordHash");
    // The login cookie must be HTTP-only, so page scripts cannot steal it.
    expect(response.headers["set-cookie"][0]).toMatch(/^token=.+HttpOnly/);
  });

  it("stores a bcrypt hash, not the password itself", async () => {
    await loggedInUser("hash@example.com");
    const user = await prisma.user.findUniqueOrThrow({ where: { email: "hash@example.com" } });
    expect(user.passwordHash).not.toBe("longenough1");
    expect(user.passwordHash).toMatch(/^\$2[aby]\$12\$/); // bcrypt, cost factor 12
  });

  it("refuses an e-mail address that is already registered, ignoring upper/lower case", async () => {
    await loggedInUser("taken@example.com");
    const response = await request(app)
      .post("/api/auth/register")
      .send({ name: "Copy", email: "TAKEN@example.com", password: "longenough1" })
      .expect(409);
    expect(response.body.error).toBe("An account with this email already exists");
  });

  it.each([
    ["a short password", { name: "X", email: "x@example.com", password: "short" }, "password"],
    ["an invalid e-mail", { name: "X", email: "not-an-email", password: "longenough1" }, "email"],
    ["a missing name", { email: "x@example.com", password: "longenough1" }, "name"],
  ])("refuses %s with a message naming the field", async (_case, body, field) => {
    const response = await request(app).post("/api/auth/register").send(body).expect(400);
    expect(response.body.error).toContain(field);
  });
});

describe("login and logout", () => {
  beforeEach(async () => {
    await loggedInUser("player@example.com");
  });

  it("logs in with the right password", async () => {
    const response = await request(app)
      .post("/api/auth/login")
      .send({ email: "player@example.com", password: "longenough1" })
      .expect(200);
    expect(response.body.user.email).toBe("player@example.com");
  });

  it("gives the same answer for a wrong password and an unknown e-mail", async () => {
    // Same message in both cases, so nobody can find out which e-mails exist.
    const wrongPassword = await request(app)
      .post("/api/auth/login")
      .send({ email: "player@example.com", password: "wrong-password" })
      .expect(401);
    const unknownEmail = await request(app)
      .post("/api/auth/login")
      .send({ email: "nobody@example.com", password: "longenough1" })
      .expect(401);
    expect(wrongPassword.body).toEqual(unknownEmail.body);
  });

  it("knows who is logged in until they log out", async () => {
    const agent = request.agent(app);
    await agent.post("/api/auth/login").send({ email: "player@example.com", password: "longenough1" });
    await agent.get("/api/auth/me").expect(200);
    await agent.post("/api/auth/logout").expect(204);
    await agent.get("/api/auth/me").expect(401);
  });

  it("rejects a forged login cookie", async () => {
    await request(app).get("/api/auth/me").set("Cookie", "token=not-a-real-token").expect(401);
  });
});
