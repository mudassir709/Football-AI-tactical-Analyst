// One match: live progress while analysing, then the interactive analysis.
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import type { AnalysisResults } from "../analysis/types";
import { api } from "../api";
import { VideoAnalysis } from "../components/VideoAnalysis";
import { Button, Card, ErrorMessage, ProgressBar, Spinner, Stat, StatusBadge } from "../components/ui";
import { formatDate, formatDuration, formatPercent } from "../format";
import type { Match, TeamSummary } from "../types";
import { useMatchUpdates } from "../useMatchUpdates";

export function MatchPage() {
  const { id } = useParams<{ id: string }>();
  const [match, setMatch] = useState<Match | null>(null);
  // Results are stored with the completion time they belong to, so results
  // from before a re-analysis are never shown with the new match data.
  const [loaded, setLoaded] = useState<{ completedAt: string; results: AnalysisResults } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reanalysing, setReanalysing] = useState(false);

  useEffect(() => {
    if (!id) return;
    api.getMatch(id)
      .then(({ match }) => setMatch(match))
      .catch((err: Error) => setError(err.message));
  }, [id]);

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

  if (error) return <ErrorMessage>{error}</ErrorMessage>;
  if (!match) return <Spinner label="Loading match" />;
  const busy = match.status === "QUEUED" || match.status === "PROCESSING";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link to="/" className="text-sm text-slate-400 hover:text-white">← All matches</Link>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold">{match.title}</h1>
            <StatusBadge status={match.status} />
          </div>
          <p className="text-sm text-slate-500">
            Uploaded {formatDate(match.createdAt)} · {match.analysisMode === "quick" ? "Quick" : "Standard"} analysis
          </p>
        </div>
        {!busy && (
          <Button variant="secondary" onClick={reanalyse} disabled={reanalysing}>
            {reanalysing ? "Queuing…" : "Re-analyse"}
          </Button>
        )}
      </div>

      {busy && (
        <Card className="space-y-3">
          <h2 className="font-semibold">Analysis in progress</h2>
          <ProgressBar value={match.progress} label={match.stage} />
          <p className="text-xs text-slate-500">
            This page updates live. You can leave it; the analysis keeps running on the server.
          </p>
        </Card>
      )}

      {match.status === "FAILED" && (
        <ErrorMessage>Analysis failed: {match.errorMessage ?? "unknown error"}</ErrorMessage>
      )}

      {match.status === "COMPLETED" && (
        <>
          {results ? (
            <VideoAnalysis videoUrl={api.videoUrl(match.id)} results={results} />
          ) : (
            <Spinner label="Loading analysis" />
          )}
          {match.summary && <SummaryPanel match={match} />}
        </>
      )}
    </div>
  );
}

function SummaryPanel({ match }: { match: Match }) {
  const summary = match.summary!;
  return (
    <div className="space-y-4">
      <Card className="grid grid-cols-2 gap-6 md:grid-cols-4">
        <Stat label="Clip length" value={formatDuration(summary.durationSeconds)} />
        <Stat label="Frames analysed" value={summary.framesAnalysed} />
        <Stat label="Ball detected" value={formatPercent(summary.ballDetectionRate)} hint="of analysed frames" />
        <Stat
          label="Processing time"
          value={formatDuration(summary.processingSeconds)}
          hint={summary.processedOn ? `on ${summary.processedOn}` : undefined}
        />
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        {summary.teams.map((team) => (
          <TeamCard key={team.id} team={team} />
        ))}
      </div>
    </div>
  );
}

function TeamCard({ team }: { team: TeamSummary }) {
  return (
    <Card>
      <div className="mb-4 flex items-center gap-2">
        <span className="h-4 w-4 rounded-full ring-2 ring-slate-700" style={{ backgroundColor: team.colour }} />
        <h3 className="font-semibold">Team {team.id === 0 ? "A" : "B"}</h3>
        <span className="ml-auto rounded-full bg-slate-800 px-2.5 py-0.5 text-sm font-semibold">
          {team.formation ?? "—"}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Stat label="Compactness" value={team.avgCompactnessM2 !== null ? `${team.avgCompactnessM2} m²` : "—"} hint="area covered by outfield players" />
        <Stat label="Distance covered" value={team.distanceKm !== null ? `${team.distanceKm} km` : "—"} hint="all outfield players" />
        <Stat label="Width" value={team.avgWidthM !== null ? `${team.avgWidthM} m` : "—"} />
        <Stat label="Depth" value={team.avgDepthM !== null ? `${team.avgDepthM} m` : "—"} />
      </div>
    </Card>
  );
}
