// LLM coaching report: turns the computed tactical statistics of a match into
// a short written report for a coach, using the Claude API.
//
// Only numbers computed by the AI worker are sent (formations, compactness,
// distances...), never the video. The prompt tells the model to stick to
// these numbers, because the analysis contains no events such as passes,
// shots or goals.
import { readFile } from "node:fs/promises";
import Anthropic from "@anthropic-ai/sdk";
import type { Match } from "./generated/prisma/client.ts";
import { absolutePath } from "./storage.ts";

const MODEL = "claude-opus-5-5";

/** True when an API key is configured; otherwise the feature is disabled. */
export const reportsEnabled = () => Boolean(process.env.ANTHROPIC_API_KEY);

// Reads ANTHROPIC_API_KEY from the environment (loaded from .env by config.ts).
const client = new Anthropic({ timeout: 120_000, maxRetries: 2 });

/** A report could not be produced; `status` is the HTTP status to answer with. */
export class ReportError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

const SYSTEM_PROMPT = `You are an experienced football (soccer) analyst writing for a team's coaching staff.
You receive statistics that a computer-vision system extracted from a short broadcast clip of a match.

Write a concise coaching report in Markdown (about 300-450 words) with these sections:
## Overview
## Team A
## Team B
## Shape over time
## Recommendations  (2-3 bullet points per team)
## Data limitations

Rules:
- Base every statement on the numbers provided. The data contains positions, formations, team shape
  and running distances only - no passes, shots, goals or ball possession. Never invent such events.
- Interpret the numbers tactically (e.g. a small area and a 5-man back line suggests a compact,
  defensive block; a large width suggests stretching the opponent).
- Refer to teams as "Team A" and "Team B" (with their kit colour) and to players as "Player #<id>".
- Mention that the clip is short and the broadcast camera may not show every player, so conclusions are tentative.`;

interface ResultsFile {
  video: { durationSeconds: number };
  teams: { id: number; colour: string; defends: string | null }[];
  players: { id: number; team: number; role: string; distanceM: number | null; maxSpeedKmh: number | null; secondsVisible: number | null }[];
  teamShape: { t: number; team: number; area: number | null; width: number | null; depth: number | null }[];
  formations: {
    windows: { team: number; start: number; end: number; formation: string | null; runnerUp: string | null; confidenceMargin: number | null }[];
    changes: { team: number; time: number; from: string; to: string }[];
  };
}

const teamName = (id: number) => (id === 0 ? "Team A" : "Team B");
const average = (values: (number | null)[]) => {
  const numbers = values.filter((v): v is number => v !== null);
  return numbers.length ? Math.round((numbers.reduce((a, b) => a + b, 0) / numbers.length) * 10) / 10 : null;
};

/** The compact, model-friendly summary of one match sent in the prompt. */
async function buildMatchData(match: Match) {
  if (!match.resultPath) throw new ReportError("Analysis has not finished yet", 409);
  const results = JSON.parse(await readFile(absolutePath(match.resultPath), "utf8")) as ResultsFile;
  const duration = results.video.durationSeconds;

  return {
    clipSeconds: duration,
    summary: match.summary,
    teams: results.teams.map((team) => {
      const shape = results.teamShape.filter((s) => s.team === team.id);
      // Team shape in the first, middle and last third of the clip.
      const thirds = [0, 1, 2].map((i) => {
        const part = shape.filter((s) => s.t >= (i * duration) / 3 && s.t < ((i + 1) * duration) / 3);
        return { from: Math.round((i * duration) / 3), to: Math.round(((i + 1) * duration) / 3), areaM2: average(part.map((s) => s.area)), widthM: average(part.map((s) => s.width)), depthM: average(part.map((s) => s.depth)) };
      });
      const runners = results.players
        .filter((p) => p.team === team.id && p.role === "player" && (p.secondsVisible ?? 0) >= duration / 3)
        .sort((a, b) => (b.distanceM ?? 0) - (a.distanceM ?? 0))
        .slice(0, 3)
        .map((p) => ({ player: p.id, distanceM: p.distanceM, topSpeedKmh: p.maxSpeedKmh }));
      return {
        team: teamName(team.id),
        kitColour: team.colour,
        defendsGoal: team.defends,
        formationTimeline: results.formations.windows
          .filter((w) => w.team === team.id)
          .map((w) => ({ from: w.start, to: w.end, formation: w.formation, nextBestFit: w.runnerUp })),
        shapeOverTime: thirds,
        topRunners: runners,
      };
    }),
    formationChanges: results.formations.changes.map((c) => ({ ...c, team: teamName(c.team) })),
  };
}

/** Generate a Markdown coaching report for a completed match. */
export async function generateCoachingReport(match: Match): Promise<string> {
  if (!reportsEnabled()) {
    throw new ReportError("Coaching reports are not configured (set ANTHROPIC_API_KEY)", 503);
  }
  const data = await buildMatchData(match);

  let response: Anthropic.Beta.BetaMessage;
  try {
    response = await client.beta.messages.create({
      model: MODEL,
      max_tokens: 16000,
      output_config: { effort: "medium" }, // a short report needs no deep reasoning
      // If a safety classifier declines, the API retries on a suitable model.
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      system: SYSTEM_PROMPT,
      messages: [
        {
          role: "user",
          content: `Match: "${match.title}"\n\nStatistics (JSON):\n${JSON.stringify(data, null, 2)}`,
        },
      ],
    });
  } catch (error) {
    // Most specific first; the SDK already retried 429/5xx/network errors twice.
    if (error instanceof Anthropic.AuthenticationError) {
      throw new ReportError("The Anthropic API key is invalid", 502);
    } else if (error instanceof Anthropic.RateLimitError) {
      throw new ReportError("The report service is busy; try again in a minute", 429);
    } else if (error instanceof Anthropic.APIConnectionError) {
      throw new ReportError("Could not reach the report service", 502);
    } else if (error instanceof Anthropic.APIError) {
      throw new ReportError(`Report service error (${error.status})`, 502);
    }
    throw error;
  }

  if (response.stop_reason === "refusal") {
    throw new ReportError("The report could not be generated for this match", 502);
  }
  const report = response.content
    .filter((block): block is Anthropic.Beta.BetaTextBlock => block.type === "text")
    .map((block) => block.text)
    .join("\n")
    .trim();
  if (!report) throw new ReportError("The report came back empty", 502);
  return report;
}
