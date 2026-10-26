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
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import sys
from pathlib import Path
from typing import Any

from bullmq import Job, Worker

from src import config
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
    """Analyse one uploaded match; the return value is sent back to the API."""
    match_id: str = job.data["matchId"]
    video = storage_path(job.data["videoPath"])
    mode: str = job.data.get("mode", config.DEFAULT_ANALYSIS_MODE)
    result_relative = f"results/{match_id}.json"
    playback_relative = f"videos/{match_id}_web.mp4"
    logger.info("Job %s: analysing %s (%s mode)", match_id, video.name, mode)

    loop = asyncio.get_running_loop()

    def on_progress(percent: float, stage: str) -> None:
        # Called from the analysis thread; hand the update to the event loop.
        asyncio.run_coroutine_threadsafe(
            job.updateProgress({"percent": round(percent, 1), "stage": stage}), loop
        )

    outputs = (storage_path(result_relative), storage_path(playback_relative))
    # Both paths are slow, synchronous code. Running them in a thread keeps the
    # event loop free to renew the job's lock while the analysis runs.
    summary = None
    if config.GPU_SERVER_URL:
        try:
            summary = await asyncio.to_thread(
                run_remote_analysis, config.GPU_SERVER_URL, config.GPU_SERVER_TOKEN,
                video, *outputs, on_progress, mode,
            )
        except RemoteUnavailable as exc:
            # Nothing ran remotely, so analysing here instead is safe.
            logger.warning("Job %s: %s; analysing locally instead", match_id, exc)
    if summary is None:
        summary = await asyncio.to_thread(run_analysis, video, *outputs, on_progress, mode)

    logger.info("Job %s: done in %.0f s on %s", match_id, summary["processingSeconds"], summary.get("processedOn"))
    return {"resultPath": result_relative, "playbackPath": playback_relative, "summary": summary}


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
