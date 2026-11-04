// The page of one match (/matches/:id). What it shows depends on the status:
//   - Queued / Analysing: a progress bar that updates live
//   - Failed: the reason
//   - Cancelled: a note, and the Re-analyse button to start again
//   - Ready: the video analysis, with the summary and the AI report in tabs
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import type { AnalysisResults } from "../analysis/types";
import { api } from "../api";
import { CoachingReport } from "../components/CoachingReport";
import { VideoAnalysis } from "../components/VideoAnalysis";
import { Button, ErrorMessage, ProgressBar, Spinner, Stat, StatusBadge } from "../components/ui";
import { formatDate, formatDuration, formatPercent } from "../format";
import type { Match, TeamSummary } from "../types";
import { useMatchUpdates } from "../useMatchUpdates";

export function MatchPage() {
  // The match ID comes from the address bar.
  const { id } = useParams<{ id: string }>();
  const [match, setMatch] = useState<Match | null>(null);
  // Results are stored with the completion time they belong to, so results
  // from before a re-analysis are never shown with the new match data.
  const [loaded, setLoaded] = useState<{ completedAt: string; results: AnalysisResults } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reanalysing, setReanalysing] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  // Load the match when the page opens (or when we move to another match).
  useEffect(() => {
    if (!id) return;
    api.getMatch(id)
      .then(({ match }) => setMatch(match))
      .catch((err: Error) => setError(err.message));
  }, [id]);

  // Live updates: the server sends updates for all of this user's matches,
  // so only keep the ones for the match on this page.
  useMatchUpdates((updated) => {
    if (updated.id === id) setMatch(updated);
  });

  // Download the full results once the analysis is complete (and again after
  // a re-analysis, which changes completedAt).
  const completedAt = match?.status === "COMPLETED" ? match.completedAt : null;
  useEffect(() => {
    if (!id || !completedAt) return;
    api.getResults<AnalysisResults>(id)
      .then((results) => setLoaded({ completedAt, results }))
      .catch((err: Error) => setError(err.message));
  }, [id, completedAt]);
  const results = loaded && loaded.completedAt === completedAt ? loaded.results : null;

  // "Re-analyse" button: put the match back in the queue. The server answers
  // with the match in its new Queued state, so the progress bar appears.
  async function reanalyse() {
    if (!match) return;
    setReanalysing(true);
    try {
      setMatch((await api.reanalyse(match.id)).match);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setReanalysing(false);
    }
  }

  // "Cancel" button: after a confirmation, ask the server to stop the
  // analysis. A queued one stops at once; a running one shows "Cancelling…"
  // until the worker has stopped (a few seconds), then the page updates live.
  async function cancel() {
    if (!match) return;
    if (!window.confirm("Cancel this analysis? You can start it again later with Re-analyse.")) return;
    setCancelling(true);
    try {
      setMatch((await api.cancelAnalysis(match.id)).match);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCancelling(false);
    }
  }

  if (error) return <ErrorMessage>{error}</ErrorMessage>;
  if (!match) return <Spinner label="Loading match" />;
  // "busy" = waiting in the queue or being analysed right now.
  const busy = match.status === "QUEUED" || match.status === "PROCESSING";

  // One line of details under the title, e.g.
  // "uploaded 27 Oct · standard analysis · processed on GPU (NVIDIA L4) in 39 s".
  const details = [
    `uploaded ${formatDate(match.createdAt)}`,
    `${match.analysisMode} analysis`,
    match.summary &&
      `processed${match.summary.processedOn ? ` on ${match.summary.processedOn}` : ""} in ${formatDuration(match.summary.processingSeconds)}`,
  ].filter(Boolean).join(" · ");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link to="/" className="font-mono text-xs text-dim hover:text-chalk">← all matches</Link>
          <div className="mt-2 flex flex-wrap items-baseline gap-4">
            <h1 className="text-3xl font-semibold">{match.title}</h1>
            <StatusBadge status={match.status} />
          </div>
          <p className="mt-1 font-mono text-xs text-dim">{details}</p>
        </div>
        {!busy && (
          <Button variant="secondary" onClick={reanalyse} disabled={reanalysing}>
            {reanalysing ? "Queuing…" : "Re-analyse"}
          </Button>
        )}
      </div>

      {busy && (
        <div className="space-y-4 border border-dashed border-line bg-pitch-2 p-6">
          <p className="font-hand text-2xl text-accent">Analysing the match…</p>
          <ProgressBar value={match.progress} label={match.stage} />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-dim">
              This page updates live. You can leave it; the analysis keeps running on the server.
            </p>
            <Button variant="danger" onClick={cancel} disabled={cancelling || match.stage === "Cancelling…"}>
              {cancelling || match.stage === "Cancelling…" ? "Cancelling…" : "Cancel analysis"}
            </Button>
          </div>
        </div>
      )}

      {match.status === "FAILED" && (
        <ErrorMessage>Analysis failed: {match.errorMessage ?? "unknown error"}</ErrorMessage>
      )}

      {match.status === "CANCELLED" && (
        <p className="border border-dashed border-line p-6 text-sm text-dim">
          The analysis was cancelled. Press <span className="text-chalk">Re-analyse</span> to start it again.
        </p>
      )}

      {/* The finished analysis. The summary and the AI report are handed to
          VideoAnalysis, which shows them in tabs under the video. */}
      {match.status === "COMPLETED" &&
        (results ? (
          <VideoAnalysis
            videoUrl={api.videoUrl(match.id)}
            results={results}
            summary={match.summary ? <SummaryPanel match={match} /> : null}
            report={<CoachingReport matchId={match.id} completedAt={match.completedAt} />}
          />
        ) : (
          <Spinner label="Loading analysis" />
        ))}
    </div>
  );
}

// The "Summary" tab: the two teams side by side, then facts about the clip.
// These numbers come from the small summary saved in the database.
function SummaryPanel({ match }: { match: Match }) {
  const summary = match.summary!;
  const [teamA, teamB] = summary.teams;
  // Show a number with its unit, or "—" when it wasn't measured.
  const value = (v: number | null | undefined, unit = "") => (v === null || v === undefined ? "—" : `${v}${unit}`);
  // Each row compares one measurement for Team A and Team B.
  const rows: [string, (t: TeamSummary) => string, string?][] = [
    ["Formation", (t) => t.formation ?? "—", "most common in the clip"],
    ["Compactness", (t) => value(t.avgCompactnessM2, " m²"), "area covered by outfield players"],
    ["Width", (t) => value(t.avgWidthM, " m")],
    ["Depth", (t) => value(t.avgDepthM, " m")],
    ["Distance covered", (t) => value(t.distanceKm, " km"), "all outfield players"],
  ];

  return (
    <div className="space-y-8">
      {teamA && teamB && (
        <table className="w-full max-w-3xl text-sm">
          <thead>
            <tr className="border-b border-line text-left">
              <th className="py-2 font-normal text-dim" />
              {[teamA, teamB].map((team) => (
                <th key={team.id} className="py-2 font-medium">
                  <span className="mr-2 inline-block h-3 w-1.5 align-middle" style={{ backgroundColor: team.colour }} />
                  Team {team.id === 0 ? "A ○" : "B ×"}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, get, hint]) => (
              <tr key={label} className="border-b border-dashed border-line">
                <td className="py-3 pr-4 text-dim">
                  {label}
                  {hint && <span className="block font-mono text-[11px] text-dim/70">{hint}</span>}
                </td>
                <td className="py-3 font-mono text-lg">{get(teamA)}</td>
                <td className="py-3 font-mono text-lg">{get(teamB)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
        <Stat label="Clip length" value={formatDuration(summary.durationSeconds)} />
        <Stat label="Frames analysed" value={summary.framesAnalysed} />
        <Stat label="Ball detected" value={formatPercent(summary.ballDetectionRate)} hint="of analysed frames" />
        <Stat label="Formation changes" value={summary.formationChanges} hint="both teams" />
      </div>
    </div>
  );
}
