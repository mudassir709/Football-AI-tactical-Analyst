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

from src.cancel import AnalysisCancelled

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]

POLL_SECONDS = 2.0
MAX_CONSECUTIVE_POLL_ERRORS = 15  # ~30 s of network trouble before giving up
JOB_TIMEOUT_SECONDS = 4 * 60 * 60  # a full half takes about an hour on a GPU
# The video is uploaded in pieces of this size. Proxies in front of cloud GPU
# machines (like RunPod's) refuse very large single requests.
CHUNK_BYTES = 50 * 1024 * 1024
CHUNK_ATTEMPTS = 3  # retry a piece this many times if the network hiccups

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


def _upload_in_chunks(
    client: httpx.Client, job_id: str, video_path: Path, on_progress: Callable[[float], None],
    should_stop: Callable[[], bool] = lambda: False,
) -> None:
    """Send the video in 50 MB pieces. Each piece says where in the file it
    starts (offset), so a piece that is sent twice is not added twice."""
    size = video_path.stat().st_size
    offset = 0
    with video_path.open("rb") as video:
        while chunk := video.read(CHUNK_BYTES):
            if should_stop():  # the user cancelled during the upload
                client.delete(f"/jobs/{job_id}")
                raise AnalysisCancelled()
            for attempt in range(1, CHUNK_ATTEMPTS + 1):
                try:
                    client.put(
                        f"/jobs/{job_id}/video", params={"offset": offset}, content=chunk
                    ).raise_for_status()
                    break
                except httpx.TransportError:  # network trouble: wait a bit and try again
                    if attempt == CHUNK_ATTEMPTS:
                        raise
                    time.sleep(2 * attempt)
            offset += len(chunk)
            on_progress(offset / max(size, 1))


def run_remote_analysis(
    base_url: str,
    token: str,
    video_path: Path,
    output_path: Path,
    playback_path: Path,
    progress: ProgressCallback,
    mode: str,
    should_stop: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    """Analyse ``video_path`` on the GPU service; returns the pipeline summary.

    ``should_stop`` returns True once the user has cancelled; the GPU service
    is then told to stop too, and AnalysisCancelled is raised.
    """
    headers = {"Authorization": f"Bearer {token}"}
    timeout = httpx.Timeout(30.0, read=300.0, write=300.0)
    with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
        # 1. Upload. Any failure here means nothing ran remotely.
        try:
            device = client.get("/health").raise_for_status().json().get("device", "remote GPU")
            progress(0.0, f"Uploading video to {device}")
            # Create the job, send the video piece by piece, then start it.
            job_id = client.post(
                "/jobs", data={"mode": mode, "filename": video_path.name}
            ).raise_for_status().json()["id"]
            _upload_in_chunks(client, job_id, video_path, lambda share: progress(
                UPLOAD_END * share, f"Uploading video to {device}"), should_stop)
            client.post(f"/jobs/{job_id}/start").raise_for_status()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise RemoteUnavailable(f"GPU service unavailable: {exc}") from exc
        logger.info("Remote job %s started on %s", job_id, device)

        # 2. Relay progress until the job finishes.
        started, errors = time.monotonic(), 0
        while True:
            if time.monotonic() - started > JOB_TIMEOUT_SECONDS:
                raise RemoteAnalysisError("Remote analysis timed out")
            time.sleep(POLL_SECONDS)
            if should_stop():
                # Ask the GPU service to stop; it frees the GPU for the next job.
                try:
                    client.post(f"/jobs/{job_id}/cancel")
                except httpx.HTTPError:
                    pass  # it also forgets unfinished jobs on its own
                raise AnalysisCancelled()
            try:
                status = client.get(f"/jobs/{job_id}").raise_for_status().json()
                errors = 0
            except httpx.HTTPError as exc:
                errors += 1
                logger.warning("Polling remote job failed (%d/%d): %s", errors, MAX_CONSECUTIVE_POLL_ERRORS, exc)
                if errors >= MAX_CONSECUTIVE_POLL_ERRORS:
                    raise RemoteAnalysisError(f"Lost contact with the GPU service: {exc}") from exc
                continue
            if status["status"] == "failed":
                raise RemoteAnalysisError(status.get("error") or "Remote analysis failed")
            if status["status"] == "cancelled":
                raise AnalysisCancelled()
            scaled = UPLOAD_END + (ANALYSIS_END - UPLOAD_END) * status["percent"] / 100
            progress(scaled, f"{status['stage']} (on {device})")
            if status["status"] == "completed":
                break

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
