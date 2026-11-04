"""Stopping an analysis that the user cancelled.

The API leaves a note in Redis when the user presses Cancel (see
backend/src/queue.ts, requestCancel). The worker checks for it every few
seconds; the next time the analysis reports progress, it raises
AnalysisCancelled, which stops the work wherever it is.
"""


class AnalysisCancelled(Exception):
    """Raised inside an analysis when the user asked to stop it."""


def cancel_key(match_id: str) -> str:
    """The Redis key of the note; the API uses the same name."""
    return f"tactical-eye:cancel:{match_id}"
