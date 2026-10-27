// AI coaching report: a written interpretation of the match statistics,
// generated on demand by a large language model (Claude) via the backend.
import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import { api } from "../api";
import { Button, Card, ErrorMessage, Spinner } from "./ui";

export function CoachingReport({ matchId, completedAt }: { matchId: string; completedAt: string | null }) {
  const [report, setReport] = useState<string | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reload when the match is re-analysed (completedAt changes).
  useEffect(() => {
    let active = true;
    api.getReport(matchId)
      .then((data) => {
        if (!active) return;
        setReport(data.report);
        setEnabled(data.enabled);
      })
      .catch((err: Error) => active && setError(err.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [matchId, completedAt]);

  async function generate() {
    setGenerating(true);
    setError(null);
    try {
      setReport((await api.generateReport(matchId)).report);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setGenerating(false);
    }
  }

  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h2 className="font-semibold">AI coaching report</h2>
          <p className="text-xs text-slate-500">Written by Claude from the computed statistics; no video is sent.</p>
        </div>
        {enabled && !loading && (
          <Button variant={report ? "secondary" : "primary"} className="ml-auto" onClick={generate} disabled={generating}>
            {generating ? "Writing report…" : report ? "Regenerate" : "Generate report"}
          </Button>
        )}
      </div>

      {loading && <Spinner label="Loading report" />}
      {!loading && !enabled && (
        <p className="text-sm text-slate-400">
          Coaching reports are not configured on this server (an Anthropic API key is needed).
        </p>
      )}
      {error && <ErrorMessage>{error}</ErrorMessage>}
      {generating && <Spinner label="Analysing the statistics (about 10-30 seconds)" />}
      {report && !generating && (
        <div className="report max-w-none text-sm leading-relaxed text-slate-200">
          <Markdown>{report}</Markdown>
        </div>
      )}
      {enabled && !loading && !report && !generating && !error && (
        <p className="text-sm text-slate-400">
          Generate a short written analysis of both teams' shape, formations and work rate, with recommendations.
        </p>
      )}
    </Card>
  );
}
