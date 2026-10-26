"""Client for the remote GPU analysis service (see worker/gpu_server.py).

The queue worker calls ``run_remote_analysis`` instead of running the pipeline
itself. It uploads the video, relays progress while the GPU works, and
downloads the results JSON and playback video into local storage.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]

POLL_SECONDS = 2.0
MAX_CONSECUTIVE_POLL_ERRORS = 15  # ~30 s of network trouble before giving up
JOB_TIMEOUT_SECONDS = 2 * 60 * 60

# Share of the progress bar used by each phase.
UPLOAD_END, ANALYSIS_END = 5.0, 95.0


class RemoteAnalysisError(RuntimeError):
    """The remote service accepted the job but it failed or was lost."""


class RemoteUnavailable(RemoteAnalysisError):
    """The service could not be reached or refused the job; nothing ran remotely,
    so it is safe to analyse locally instead."""


def _download(client: httpx.Client, url: str, target: Path) -> None:
    """Stream a file to disk via a temporary name, so readers never see half a file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with tmp.open("wb") as out:
            for chunk in response.iter_bytes(1024 * 1024):
                out.write(chunk)
    tmp.replace(target)


def run_remote_analysis(
    base_url: str,
    token: str,
    video_path: Path,
    output_path: Path,
    playback_path: Path,
    progress: ProgressCallback,
    mode: str,
) -> dict[str, Any]:
    """Analyse ``video_path`` on the GPU service; returns the pipeline summary."""
    headers = {"Authorization": f"Bearer {token}"}
    timeout = httpx.Timeout(30.0, read=300.0, write=300.0)
    with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
        # 1. Upload. Any failure here means nothing ran remotely.
        try:
            device = client.get("/health").raise_for_status().json().get("device", "remote GPU")
            progress(0.0, f"Uploading video to {device}")
            with video_path.open("rb") as video:
                response = client.post(
                    "/jobs",
                    files={"file": (video_path.name, video, "video/mp4")},
                    data={"mode": mode},
                )
            response.raise_for_status()
            job_id = response.json()["id"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise RemoteUnavailable(f"GPU service unavailable: {exc}") from exc
        logger.info("Remote job %s started on %s", job_id, device)

        # 2. Relay progress until the job finishes.
        started, errors = time.monotonic(), 0
        while True:
            if time.monotonic() - started > JOB_TIMEOUT_SECONDS:
                raise RemoteAnalysisError("Remote analysis timed out")
            time.sleep(POLL_SECONDS)
            try:
                status = client.get(f"/jobs/{job_id}").raise_for_status().json()
                errors = 0
            except httpx.HTTPError as exc:
                errors += 1
                logger.warning("Polling remote job failed (%d/%d): %s", errors, MAX_CONSECUTIVE_POLL_ERRORS, exc)
                if errors >= MAX_CONSECUTIVE_POLL_ERRORS:
                    raise RemoteAnalysisError(f"Lost contact with the GPU service: {exc}") from exc
                continue
            scaled = UPLOAD_END + (ANALYSIS_END - UPLOAD_END) * status["percent"] / 100
            progress(scaled, f"{status['stage']} (on {device})")
            if status["status"] == "completed":
                break
            if status["status"] == "failed":
                raise RemoteAnalysisError(status.get("error") or "Remote analysis failed")

        # 3. Download the outputs, then free the remote disk space.
        progress(ANALYSIS_END, "Downloading results")
        _download(client, f"/jobs/{job_id}/results", output_path)
        _download(client, f"/jobs/{job_id}/playback", playback_path)
        try:
            client.delete(f"/jobs/{job_id}")
        except httpx.HTTPError:
            pass  # the service also purges old jobs on its own
        progress(100.0, "Done")
        return status["summary"]
