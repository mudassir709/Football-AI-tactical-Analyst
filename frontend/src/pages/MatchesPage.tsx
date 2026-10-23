// The user's matches, with progress bars that update live while analysing.
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { Button, buttonClasses, Card, ErrorMessage, ProgressBar, Spinner, StatusBadge } from "../components/ui";
import { formatBytes, formatDate } from "../format";
import type { Match } from "../types";
import { useMatchUpdates } from "../useMatchUpdates";

export function MatchesPage() {
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // useEffect runs code after the page appears; [] means "only once".
  useEffect(() => {
    api.listMatches()
      .then(({ matches }) => setMatches(matches))
      .catch((err: Error) => setError(err.message));
  }, []);

  // Replace the updated match in the list (or add it if it is new).
  useMatchUpdates((updated) =>
    setMatches((current) => {
      if (!current) return current;
      const exists = current.some((m) => m.id === updated.id);
      return exists ? current.map((m) => (m.id === updated.id ? updated : m)) : [updated, ...current];
    }),
  );

  const removeMatch = (id: string) => setMatches((current) => current?.filter((m) => m.id !== id) ?? null);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Matches</h1>
          <p className="text-sm text-slate-400">Uploaded footage and its tactical analysis.</p>
        </div>
        <Link to="/upload" className={buttonClasses()}>
          Upload a match
        </Link>
      </div>

      {error && <ErrorMessage>{error}</ErrorMessage>}
      {!matches && !error && <Spinner label="Loading matches" />}
      {matches?.length === 0 && (
        <Card className="py-12 text-center">
          <p className="text-slate-300">No matches yet.</p>
          <p className="mt-1 text-sm text-slate-500">Upload a broadcast clip to get started.</p>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {matches?.map((match) => (
          <MatchCard key={match.id} match={match} onDeleted={() => removeMatch(match.id)} />
        ))}
      </div>
    </div>
  );
}

function MatchCard({ match, onDeleted }: { match: Match; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const inProgress = match.status === "QUEUED" || match.status === "PROCESSING";

  async function handleDelete() {
    try {
      await api.deleteMatch(match.id);
      onDeleted();
    } catch (err) {
      setDeleteError((err as Error).message);
      setConfirming(false);
    }
  }

  return (
    <Card className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <Link to={`/matches/${match.id}`} className="min-w-0">
          <h2 className="truncate font-semibold hover:text-emerald-300">{match.title}</h2>
          <p className="text-xs text-slate-500">
            {formatDate(match.createdAt)} · {formatBytes(match.fileSizeBytes)}
            {match.analysisMode === "quick" && " · Quick mode"}
          </p>
        </Link>
        <StatusBadge status={match.status} />
      </div>

      {inProgress && <ProgressBar value={match.progress} label={match.stage} />}
      {match.status === "FAILED" && (
        <p className="text-sm text-red-300">{match.errorMessage ?? "Analysis failed"}</p>
      )}
      {match.status === "COMPLETED" && match.summary && (
        <div className="flex flex-wrap gap-2">
          {match.summary.teams.map((team) => (
            <span key={team.id} className="flex items-center gap-1.5 rounded-full bg-slate-800 px-2.5 py-1 text-xs">
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: team.colour }} />
              {team.formation ?? "No formation"}
            </span>
          ))}
        </div>
      )}
      {deleteError && <p className="text-xs text-red-300">{deleteError}</p>}

      <div className="mt-auto flex items-center gap-2">
        <Link to={`/matches/${match.id}`} className="text-sm font-medium text-emerald-400 hover:underline">
          {match.status === "COMPLETED" ? "Open analysis" : "View details"}
        </Link>
        <div className="ml-auto">
          {confirming ? (
            <span className="flex items-center gap-2 text-xs">
              Delete?
              <Button variant="danger" className="px-2 py-1 text-xs" onClick={handleDelete}>Yes</Button>
              <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setConfirming(false)}>No</Button>
            </span>
          ) : (
            <button
              className="text-xs text-slate-500 hover:text-red-300 disabled:opacity-40"
              onClick={() => setConfirming(true)}
              disabled={match.status === "PROCESSING"}
              title={match.status === "PROCESSING" ? "Cannot delete while analysing" : undefined}
            >
              Delete
            </button>
          )}
        </div>
      </div>
    </Card>
  );
}
