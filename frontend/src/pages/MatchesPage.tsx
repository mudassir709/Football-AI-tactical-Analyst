// The home page: the user's matches as a list, newest first, one row each.
// Matches that are still being analysed show a progress bar that moves on
// its own, because the server pushes every change over the WebSocket.
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { Button, buttonClasses, ErrorMessage, ProgressBar, SectionTitle, Spinner, StatusBadge } from "../components/ui";
import { formatBytes, formatDate } from "../format";
import type { Match } from "../types";
import { useMatchUpdates } from "../useMatchUpdates";

export function MatchesPage() {
  // null means "still loading"; an empty list means the user has no matches yet.
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // useEffect runs code after the page appears; [] means "only once".
  useEffect(() => {
    api.listMatches()
      .then(({ matches }) => setMatches(matches))
      .catch((err: Error) => setError(err.message));
  }, []);

  // A live update arrived from the server: swap the old version of that match
  // for the new one, or put it at the top if it's a match we haven't seen yet.
  useMatchUpdates((updated) =>
    setMatches((current) => {
      if (!current) return current;
      const exists = current.some((m) => m.id === updated.id);
      return exists ? current.map((m) => (m.id === updated.id ? updated : m)) : [updated, ...current];
    }),
  );

  // After a delete, take the card out of the list without reloading everything.
  const removeMatch = (id: string) => setMatches((current) => current?.filter((m) => m.id !== id) ?? null);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Matches</h1>
          <p className="mt-1 font-mono text-sm text-dim">
            {matches ? `${matches.length} uploaded · newest first` : "uploaded footage and its tactical analysis"}
          </p>
        </div>
        <Link to="/upload" className={buttonClasses()}>
          + Upload a match
        </Link>
      </div>

      {/* Show an error, a loading spinner, the "no matches yet" note, or the list. */}
      {error && <ErrorMessage>{error}</ErrorMessage>}
      {!matches && !error && <Spinner label="Loading matches" />}
      {matches?.length === 0 && (
        <div className="border border-dashed border-line px-6 py-16 text-center">
          <p className="font-hand text-3xl text-accent">No matches yet.</p>
          <p className="mt-2 text-sm text-dim">Upload a broadcast clip to get started.</p>
        </div>
      )}

      {matches && matches.length > 0 && (
        <div className="border border-line bg-pitch-2">
          {/* Column titles, only on wide screens. */}
          <div className="hidden grid-cols-[minmax(0,2fr)_minmax(0,1.3fr)_minmax(0,1fr)_auto] gap-6 border-b border-line px-5 py-3 md:grid">
            <SectionTitle>Match</SectionTitle>
            <SectionTitle>Formations</SectionTitle>
            <SectionTitle>Status</SectionTitle>
            <span className="w-32" />
          </div>
          {matches.map((match) => (
            <MatchRow key={match.id} match={match} onDeleted={() => removeMatch(match.id)} />
          ))}
        </div>
      )}
    </div>
  );
}

// One row of the list: title and details, the two teams' formations (or a
// progress bar / the error), the status, and the actions on the right.
function MatchRow({ match, onDeleted }: { match: Match; onDeleted: () => void }) {
  // confirming = the "Delete? Yes / No" question is showing.
  const [confirming, setConfirming] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const inProgress = match.status === "QUEUED" || match.status === "PROCESSING";

  // The user clicked "Yes". If the server refuses (e.g. the analysis has just
  // started), show its reason on the card instead.
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
    <div className="grid gap-3 border-b border-dashed border-line px-5 py-4 last:border-b-0 md:grid-cols-[minmax(0,2fr)_minmax(0,1.3fr)_minmax(0,1fr)_auto] md:items-center md:gap-6">
      {/* Title and details. */}
      <Link to={`/matches/${match.id}`} className="group min-w-0">
        <h2 className="truncate font-medium group-hover:text-accent">{match.title}</h2>
        <p className="font-mono text-xs text-dim">
          {formatDate(match.createdAt)} · {formatBytes(match.fileSizeBytes)}
          {match.analysisMode === "quick" && " · quick"}
        </p>
      </Link>

      {/* Middle column: formations when finished, otherwise progress or the error. */}
      <div className="min-w-0">
        {inProgress && <ProgressBar value={match.progress} label={match.stage} />}
        {match.status === "FAILED" && (
          <p className="text-sm text-danger">{match.errorMessage ?? "Analysis failed"}</p>
        )}
        {match.status === "COMPLETED" && match.summary && (
          <div className="flex items-center gap-3 font-mono text-sm">
            {match.summary.teams.map((team, i) => (
              <span key={team.id} className="flex items-center gap-2">
                {i > 0 && <span className="text-dim">vs</span>}
                <span className="h-3 w-1.5" style={{ backgroundColor: team.colour }} />
                {team.formation ?? "—"}
              </span>
            ))}
          </div>
        )}
      </div>

      <div>
        <StatusBadge status={match.status} />
      </div>

      {/* Actions. Deleting takes two clicks: "Delete", then "Yes". It is greyed out
          while the match is being analysed, because the server would refuse anyway. */}
      <div className="flex w-full items-center justify-end gap-3 md:w-auto">
        {deleteError && <span className="text-xs text-danger">{deleteError}</span>}
        {confirming ? (
          <span className="flex items-center gap-2 text-xs text-dim">
            Delete?
            <Button variant="danger" className="px-2 py-1 text-xs" onClick={handleDelete}>Yes</Button>
            <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setConfirming(false)}>No</Button>
          </span>
        ) : (
          <>
            <button
              className="text-xs text-dim hover:text-danger disabled:opacity-40"
              onClick={() => setConfirming(true)}
              disabled={match.status === "PROCESSING"}
              title={match.status === "PROCESSING" ? "Cannot delete while analysing" : undefined}
            >
              Delete
            </button>
            <Link to={`/matches/${match.id}`} className={buttonClasses("secondary", "w-32 px-3 py-1.5 text-xs")}>
              {match.status === "COMPLETED" ? "Open analysis →" : "View details →"}
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
