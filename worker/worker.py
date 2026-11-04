"""AI worker: takes match-analysis jobs from the Redis queue and runs the pipeline.

Run from the worker/ folder:
    python worker.py

The worker processes one job at a time (the models already use every CPU
core). Progress is reported through BullMQ, which the API forwards to the
user's browser over WebSockets. If the worker crashes mid-job, BullMQ notices
the job's lock has expired and hands it to a worker again.

If GPU_SERVER_URL is set, the heavy analysis is offloaded to the remote GPU
analysis service (gpu_server.py); when that service cannot be reached, the
job is analysed locally instead.

The user can cancel a running analysis: the API leaves a note in Redis, the
worker notices it within a few seconds, stops the analysis (also on the GPU)
and reports the job as cancelled (see src/cancel.py).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import sys
import threading
from pathlib import Path
from typing import Any

from bullmq import Job, Worker
from redis.asyncio import Redis

from src import config
from src.cancel import AnalysisCancelled, cancel_key
from src.pipeline import run_analysis
from src.remote import RemoteUnavailable, run_remote_analysis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("worker")


def storage_path(relative: str) -> Path:
    """Resolve a storage-relative path, refusing anything outside STORAGE_DIR."""
    path = (config.STORAGE_DIR / relative).resolve()
    if not path.is_relative_to(config.STORAGE_DIR):
        raise ValueError(f"Path outside storage: {relative}")
    return path


async def process(job: Job, token: str) -> dict[str, Any]:
    """Run one job, logging failures (BullMQ only stores them on the job)."""
    try:
        return await analyse(job)
    except Exception as exc:
        logger.exception("Job %s failed", job.data.get("matchId"))
        if job.attemptsMade + 1 < job.opts.get("attempts", 1):
            # Tell the dashboard a retry follows, instead of a stale stage.
            await job.updateProgress({"percent": 0, "stage": f"Error, retrying: {exc}"})
        raise


async def analyse(job: Job) -> dict[str, Any]:
    """Analyse one uploaded match; the return value is sent back to the API."""
    match_id: str = job.data["matchId"]
    video = storage_path(job.data["videoPath"])
    mode: str = job.data.get("mode", config.DEFAULT_ANALYSIS_MODE)
    result_relative = f"results/{match_id}.json"
    playback_relative = f"videos/{match_id}_web.mp4"
    logger.info("Job %s: analysing %s (%s mode)", match_id, video.name, mode)

    loop = asyncio.get_running_loop()
    # Set when the user presses Cancel (watch_for_cancel below checks Redis).
    stop = threading.Event()

    def on_progress(percent: float, stage: str) -> None:
        # Called from the analysis thread. The analysis reports progress all
        # the time, so this is also where a cancelled analysis stops.
        if stop.is_set():
            raise AnalysisCancelled()
        # Hand the update to the event loop.
        asyncio.run_coroutine_threadsafe(
            job.updateProgress({"percent": round(percent, 1), "stage": stage}), loop
        )

    outputs = (storage_path(result_relative), storage_path(playback_relative))
    had_results = outputs[0].exists()  # from an earlier analysis of this match
    watcher = asyncio.create_task(watch_for_cancel(match_id, stop))
    # Both paths are slow, synchronous code. Running them in a thread keeps the
    # event loop free to renew the job's lock while the analysis runs.
    summary = None
    try:
        if config.GPU_SERVER_URL:
            try:
                summary = await asyncio.to_thread(
                    run_remote_analysis, config.GPU_SERVER_URL, config.GPU_SERVER_TOKEN,
                    video, *outputs, on_progress, mode, stop.is_set,
                )
            except RemoteUnavailable as exc:
                # Nothing ran remotely, so analysing here instead is safe.
                logger.warning("Job %s: %s; analysing locally instead", match_id, exc)
        if summary is None:
            summary = await asyncio.to_thread(run_analysis, video, *outputs, on_progress, mode)
    except AnalysisCancelled:
        logger.info("Job %s: cancelled by the user", match_id)
        if not had_results:
            outputs[1].unlink(missing_ok=True)  # the half-finished playback copy
        return {"cancelled": True}
    finally:
        watcher.cancel()

    logger.info("Job %s: done in %.0f s on %s", match_id, summary["processingSeconds"], summary.get("processedOn"))
    return {"resultPath": result_relative, "playbackPath": playback_relative, "summary": summary}


async def watch_for_cancel(match_id: str, stop: threading.Event) -> None:
    """Check Redis every 2 seconds for the user's cancel note (see src/cancel.py)."""
    redis = Redis.from_url(config.REDIS_URL)
    try:
        while not stop.is_set():
            if await redis.getdel(cancel_key(match_id)):
                stop.set()
            await asyncio.sleep(2)
    finally:
        await redis.aclose()


async def main() -> None:
    worker = Worker(
        config.QUEUE_NAME,
        process,
        {
            "connection": config.REDIS_URL,
            "concurrency": 1,
            # Unique per process so the API's health check can count workers.
            "name": f"python-ai-worker-{socket.gethostname()}-{os.getpid()}",
            # Analysis can be slow on CPU; a longer lock tolerates brief stalls.
            "lockDuration": 120_000,
        },
    )
    logger.info("Worker listening on queue '%s' (storage: %s)", config.QUEUE_NAME, config.STORAGE_DIR)

    stop = asyncio.Event()
    if sys.platform != "win32":  # Windows has no loop signal handlers; Ctrl+C raises instead
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        logger.info("Shutting down worker")
        await worker.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
