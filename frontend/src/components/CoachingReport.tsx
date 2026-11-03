// The "AI coaching report" card at the bottom of a match page.
// The report itself is written by a language model on Azure OpenAI. The
// browser never talks to Azure directly: it asks our backend, which sends
// only the match statistics to Azure and saves the report it gets back.
import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import { api } from "../api";
import { Button, ErrorMessage, Spinner } from "./ui";

export function CoachingReport({ matchId, completedAt }: { matchId: string; completedAt: string | null }) {
  // report: the saved report text (Markdown), or null if there isn't one yet.
  // enabled: false when the server has no Azure settings, so we hide the button.
  // loading: fetching the saved report; generating: waiting for a new one.
  const [report, setReport] = useState<string | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load the saved report when the card appears, and again after a
  // re-analysis (completedAt changes). "active" makes sure an answer that
  // arrives after the user has left the page is simply ignored.
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

  // "Generate report" / "Regenerate": ask the backend for a new report.
  // This takes 10-30 seconds, so a spinner is shown in the meantime.
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

  // Shown inside the "AI coaching report" tab, so it needs no card of its own.
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <p className="max-w-xl text-xs text-dim">
          Written by an AI language model (Azure OpenAI) from the computed statistics; no video is sent.
        </p>
        {enabled && !loading && (
          <Button variant={report ? "secondary" : "primary"} className="ml-auto" onClick={generate} disabled={generating}>
            {generating ? "Writing report…" : report ? "Regenerate" : "Generate report"}
          </Button>
        )}
      </div>

      {loading && <Spinner label="Loading report" />}
      {!loading && !enabled && (
        <p className="text-sm text-dim">
          Coaching reports are not configured on this server (Azure OpenAI settings are needed).
        </p>
      )}
      {error && <ErrorMessage>{error}</ErrorMessage>}
      {generating && <Spinner label="Analysing the statistics (about 10-30 seconds)" />}
      {/* The report comes as Markdown (headings, bullet points), turned into HTML here. */}
      {report && !generating && (
        <div className="report max-w-3xl text-sm leading-relaxed text-chalk/90">
          <Markdown>{report}</Markdown>
        </div>
      )}
      {enabled && !loading && !report && !generating && !error && (
        <p className="font-hand text-xl text-accent">
          Generate a short written analysis of both teams' shape, formations and work rate, with recommendations.
        </p>
      )}
    </div>
  );
}
