// Tests for the AI coaching report data: kit colours must reach the language
// model as names ("white") and players as positions ("LB (left back)"), never
// as colour codes or track numbers. No model is called here.
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { colourName } from "../src/colours.ts";
import { config } from "../src/config.ts";
import type { Match } from "../src/generated/prisma/client.ts";
import { buildMatchData } from "../src/report.ts";

describe("colourName", () => {
  // Kit colours measured on the real test videos, and what a person would call them.
  it.each([
    ["#C7C9AA", "white"], // Real Madrid, first half (white looks cream on video)
    ["#D2E1E6", "white"], // a white kit in shade
    ["#4F4F42", "dark grey"], // a dark kit with hardly any colour
    ["#4E525D", "navy"], // PSG's dark blue
    ["#A27051", "orange"], // Barcelona's orange away kit
    ["#B66D5C", "red"],
    ["#B1F699", "light green"],
    ["#111111", "black"],
  ])("%s is %s", (hex, name) => {
    expect(colourName(hex)).toBe(name);
  });
});

describe("buildMatchData", () => {
  // A tiny results file in the newer format, where "players" are positions.
  const results = {
    video: { durationSeconds: 60 },
    teams: [
      { id: 0, colour: "#C7C9AA", defends: "left" },
      { id: 1, colour: "#4E525D", defends: "right" },
    ],
    players: [
      { id: 0, label: "LB", team: 0, role: "player", distanceM: 450, maxSpeedKmh: 31, secondsVisible: 55 },
      { id: 1, label: "ST", team: 1, role: "player", distanceM: 500, maxSpeedKmh: 33, secondsVisible: 50 },
    ],
    teamShape: [],
    formations: { windows: [], changes: [] },
  };

  it("names kit colours and positions instead of codes and numbers", async () => {
    await mkdir(path.join(config.storageDir, "results"), { recursive: true });
    await writeFile(path.join(config.storageDir, "results", "report-test.json"), JSON.stringify(results));
    const match = {
      resultPath: "results/report-test.json",
      summary: { teams: [{ id: 0, colour: "#C7C9AA" }, { id: 1, colour: "#4E525D" }] },
    } as unknown as Match;

    const data = await buildMatchData(match);
    const text = JSON.stringify(data);

    expect(data.teams.map((t) => t.kitColour)).toEqual(["white", "navy"]);
    expect(data.teams[0].topRunners[0]).toMatchObject({ position: "LB (left back)" });
    expect(text).not.toMatch(/#[0-9A-F]{6}/i); // no colour codes anywhere
    expect(text).not.toContain("Player #"); // no track numbers
  });
});
