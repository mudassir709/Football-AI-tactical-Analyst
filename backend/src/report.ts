// LLM coaching report: turns the computed tactical statistics of a match into
// a short written report for a coach, using a model deployed on Azure OpenAI.
//
// Only numbers computed by the AI worker are sent (formations, compactness,
// distances...), never the video. The prompt tells the model to stick to
// these numbers, because the analysis contains no events such as passes,
// shots or goals.
import { readFile } from "node:fs/promises";
import OpenAI, { AzureOpenAI } from "openai";
import { colourName } from "./colours.ts";
import type { Match } from "./generated/prisma/client.ts";
import { absolutePath } from "./storage.ts";

// Settings from the Azure portal (loaded from .env by config.ts):
// the resource endpoint, its key, and the name given to the model deployment.
const endpoint = process.env.AZURE_OPENAI_ENDPOINT;
const apiKey = process.env.AZURE_OPENAI_API_KEY;
const deployment = process.env.AZURE_OPENAI_DEPLOYMENT;
const apiVersion = process.env.AZURE_OPENAI_API_VERSION || "2025-04-01-preview";

/** True when Azure OpenAI is configured; otherwise the feature is disabled. */
export const reportsEnabled = () => Boolean(endpoint && apiKey && deployment);

const client = reportsEnabled()
  ? new AzureOpenAI({ endpoint, apiKey, deployment, apiVersion, timeout: 120_000, maxRetries: 2 })
  : null;

/** A report could not be produced; `status` is the HTTP status to answer with. */
export class ReportError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

const SYSTEM_PROMPT = `You are an experienced football (soccer) analyst writing for a team's coaching staff.
You receive statistics that a computer-vision system extracted from a broadcast video of a match
(anything from a short clip to a full half; see clipSeconds).

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
- Refer to teams as "Team A" and "Team B" together with their kit colour name, e.g. "Team A (white)".
  Never write colour codes such as "#C7C9AA".
- Refer to players by their position, e.g. "Team A's left back (LB)". Never write player numbers
  such as "Player #17". Position statistics cover whoever played that position: one broadcast camera
  cannot follow the same player all match.
- Mention that the broadcast camera does not show every player all the time, so conclusions are tentative
  (and, for a short clip, based on only a few seconds of play).`;

interface ResultsFile {
  video: { durationSeconds: number };
  teams: { id: number; colour: string; defends: string | null }[];
  // From results v3 each entry is a position of a team ("LB"), before that a single player track.
  players: { id: number; label?: string; team: number; role: string; distanceM: number | null; maxSpeedKmh: number | null; secondsVisible: number | null }[];
  teamShape: { t: number; team: number; area: number | null; width: number | null; depth: number | null }[];
  formations: {
    windows: { team: number; start: number; end: number; formation: string | null; runnerUp: string | null; confidenceMargin: number | null }[];
    changes: { team: number; time: number; from: string; to: string }[];
  };
}

const teamName = (id: number) => (id === 0 ? "Team A" : "Team B");

// Full names of the position labels the worker uses (worker/src/positions.py).
const POSITION_NAMES: Record<string, string> = {
  GK: "goalkeeper", LB: "left back", LCB: "left centre-back", CB: "centre-back", RCB: "right centre-back",
  RB: "right back", LWB: "left wing-back", RWB: "right wing-back", LDM: "left defensive midfielder",
  DM: "defensive midfielder", RDM: "right defensive midfielder", LM: "left midfielder",
  LCM: "left central midfielder", CM: "central midfielder", RCM: "right central midfielder",
  RM: "right midfielder", LAM: "left attacking midfielder", AM: "attacking midfielder",
  RAM: "right attacking midfielder", LW: "left winger", ST: "striker", RW: "right winger",
  LS: "left striker", RS: "right striker",
};
/** "LB (left back)", or just the label if it is unusual. */
const positionName = (label: string) => (POSITION_NAMES[label] ? `${label} (${POSITION_NAMES[label]})` : label);
const average = (values: (number | null)[]) => {
  const numbers = values.filter((v): v is number => v !== null);
  return numbers.length ? Math.round((numbers.reduce((a, b) => a + b, 0) / numbers.length) * 10) / 10 : null;
};

/** The compact, model-friendly summary of one match sent in the prompt.
 *  Exported for the tests. */
export async function buildMatchData(match: Match) {
  if (!match.resultPath) throw new ReportError("Analysis has not finished yet", 409);
  const results = JSON.parse(await readFile(absolutePath(match.resultPath), "utf8")) as ResultsFile;
  const duration = results.video.durationSeconds;

  // The stored summary also holds the kit colours as codes: swap them for names.
  const summary = match.summary as { teams?: { colour?: string }[] } | null;
  const namedSummary = summary && {
    ...summary,
    teams: summary.teams?.map(({ colour, ...team }) => ({ ...team, kitColour: colour ? colourName(colour) : null })),
  };

  return {
    clipSeconds: duration,
    summary: namedSummary,
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
        // Newer results: positions ("LB (left back)"); older ones only have track numbers.
        .map((p) => ({
          ...(p.label ? { position: positionName(p.label) } : { player: `Player #${p.id}` }),
          distanceM: p.distanceM,
          topSpeedKmh: p.maxSpeedKmh,
        }));
      return {
        team: teamName(team.id),
        kitColour: colourName(team.colour),
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
  if (!client || !deployment) {
    throw new ReportError(
      "Coaching reports are not configured (set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT)",
      503,
    );
  }
  const data = await buildMatchData(match);

  let response: OpenAI.Chat.ChatCompletion;
  try {
    response = await client.chat.completions.create({
      model: deployment, // on Azure the deployment name selects the model
      // Generous limit: reasoning models (e.g. o-series, GPT-5) also spend
      // tokens on hidden reasoning before writing the report.
      max_completion_tokens: 8000,
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: `Match: "${match.title}"\n\nStatistics (JSON):\n${JSON.stringify(data, null, 2)}` },
      ],
    });
  } catch (error) {
    // Most specific first; the SDK already retried 429/5xx/network errors twice.
    if (error instanceof OpenAI.AuthenticationError) {
      throw new ReportError("The Azure OpenAI key is invalid", 502);
    } else if (error instanceof OpenAI.NotFoundError) {
      throw new ReportError("Azure OpenAI deployment not found (check AZURE_OPENAI_DEPLOYMENT and the endpoint)", 502);
    } else if (error instanceof OpenAI.RateLimitError) {
      throw new ReportError("The report service is busy; try again in a minute", 429);
    } else if (error instanceof OpenAI.APIConnectionError) {
      throw new ReportError("Could not reach the report service", 502);
    } else if (error instanceof OpenAI.APIError) {
      throw new ReportError(`Report service error (${error.status}): ${error.message}`, 502);
    }
    throw error;
  }

  const choice = response.choices[0];
  if (choice?.finish_reason === "content_filter") {
    throw new ReportError("The report was blocked by the Azure content filter", 502);
  }
  const report = choice?.message.content?.trim();
  if (!report) {
    throw new ReportError(
      choice?.finish_reason === "length" ? "The report was cut off (token limit reached)" : "The report came back empty",
      502,
    );
  }
  return report;
}
