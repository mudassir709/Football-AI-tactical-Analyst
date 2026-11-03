"""GPU analysis service: runs the analysis pipeline on a (cloud) GPU machine.

The queue worker on the main machine uploads a video here, polls progress, and
downloads the results; see src/remote.py. The service never touches the
platform's database, queue or file storage, so it can run anywhere with only
an HTTPS address and a shared secret token.

Run (on the GPU machine, from the worker/ folder):
    GPU_SERVER_TOKEN=<secret> DEVICE=cuda:0 python gpu_server.py

Endpoints (all except /health need "Authorization: Bearer <token>"):
    GET    /health                 device information
    POST   /jobs                   create a job (form fields: mode, filename) -> {"id": ...}
    PUT    /jobs/{id}/video        add the next piece of the video (?offset=<bytes so far>)
    POST   /jobs/{id}/start        the whole video has arrived: start the analysis
    GET    /jobs/{id}              status, progress and summary
    GET    /jobs/{id}/results      results JSON (when completed)
    GET    /jobs/{id}/playback     browser-playable H.264 video (when completed)
    DELETE /jobs/{id}              delete the job's files
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import FileResponse

from src import config
from src.pipeline import _pitch_detector, _player_detector, describe_device, run_analysis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("gpu_server")

TOKEN = config.GPU_SERVER_TOKEN
if len(TOKEN) < 16:
    raise SystemExit("Set GPU_SERVER_TOKEN to a secret of at least 16 characters")

WORK_DIR = Path(os.environ.get("GPU_WORK_DIR", Path(tempfile.gettempdir()) / "tactical-gpu"))
WORK_DIR.mkdir(parents=True, exist_ok=True)
JOB_TTL_SECONDS = 2 * 60 * 60  # forget finished jobs that were never collected
UPLOAD_TTL_SECONDS = 6 * 60 * 60  # and uploads that were never finished
MAX_CHUNK_BYTES = 100 * 1024 * 1024  # the worker sends 50 MB pieces
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}


@dataclass
class JobState:
    id: str
    mode: str
    folder: Path
    video: Path
    status: str = "uploading"  # uploading -> queued -> running -> completed | failed
    percent: float = 0.0
    stage: str = "Waiting for the GPU"
    error: str | None = None
    summary: dict[str, Any] | None = None
    finished_at: float | None = None
    created_at: float = 0.0

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "status": self.status, "percent": round(self.percent, 1),
            "stage": self.stage, "error": self.error, "summary": self.summary,
        }


jobs: dict[str, JobState] = {}
jobs_lock = threading.Lock()
# One job at a time: a single pipeline run already saturates the GPU.
executor = ThreadPoolExecutor(max_workers=1)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Load both models before the first job, so it does not pay the start-up cost.
    _player_detector()
    _pitch_detector()
    logger.info("Models loaded on %s", describe_device())
    yield
    executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Tactical Eye GPU analysis service", lifespan=lifespan)


def require_token(authorization: str = Header(default="")) -> None:
    """Reject requests without the shared secret (constant-time comparison)."""
    supplied = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(supplied, TOKEN):
        raise HTTPException(status_code=401, detail="Invalid or missing token")


def get_job(job_id: str) -> JobState:
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    return job


def purge_old_jobs() -> None:
    """Delete jobs finished long ago whose files were never collected, and
    uploads that stopped half-way."""
    now = time.time()
    with jobs_lock:
        stale = [
            j for j in jobs.values()
            if (j.finished_at and j.finished_at < now - JOB_TTL_SECONDS)
            or (j.status == "uploading" and j.created_at < now - UPLOAD_TTL_SECONDS)
        ]
        for job in stale:
            jobs.pop(job.id, None)
    for job in stale:
        shutil.rmtree(job.folder, ignore_errors=True)


def run_job(job: JobState, video: Path) -> None:
    def on_progress(percent: float, stage: str) -> None:
        job.percent, job.stage = percent, stage

    job.status = "running"
    try:
        job.summary = run_analysis(
            video, job.folder / "results.json", job.folder / "playback.mp4", on_progress, job.mode
        )
        job.status, job.percent, job.stage = "completed", 100.0, "Done"
    except Exception as exc:  # report any failure to the client instead of crashing
        logger.exception("Job %s failed", job.id)
        job.status, job.stage, job.error = "failed", "Failed", f"{type(exc).__name__}: {exc}"
    finally:
        job.finished_at = time.time()
        video.unlink(missing_ok=True)  # the input is no longer needed


@app.get("/health")
def health() -> dict[str, Any]:
    with jobs_lock:
        active = sum(j.status in ("uploading", "queued", "running") for j in jobs.values())
    return {"status": "ok", "device": describe_device(), "activeJobs": active}


@app.post("/jobs", dependencies=[Depends(require_token)])
def create_job(mode: str = Form(config.DEFAULT_ANALYSIS_MODE), filename: str = Form(...)) -> dict[str, str]:
    """Step 1: create an empty job. The video follows in pieces (upload_chunk)."""
    if mode not in config.ANALYSIS_MODES:
        raise HTTPException(status_code=400, detail=f"Unknown mode {mode!r}")
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported video type")
    purge_old_jobs()

    job_id = uuid.uuid4().hex
    folder = WORK_DIR / job_id
    folder.mkdir()
    video = folder / f"input{extension}"
    video.touch()  # empty for now
    job = JobState(id=job_id, mode=mode, folder=folder, video=video, created_at=time.time())
    with jobs_lock:
        jobs[job_id] = job
    return {"id": job_id}


@app.put("/jobs/{job_id}/video", dependencies=[Depends(require_token)])
async def upload_chunk(job_id: str, offset: int, request: Request) -> dict[str, int]:
    """Step 2: add one piece of the video to the end of the file.

    ``offset`` is how many bytes the worker had sent before this piece. If it
    doesn't match the file, the piece is either a repeat of the last one (its
    answer got lost and the worker tried again), which we ignore, or
    something went wrong.
    """
    job = get_job(job_id)
    if job.status != "uploading":
        raise HTTPException(status_code=409, detail="The upload is already finished")
    chunk = await request.body()
    if len(chunk) > MAX_CHUNK_BYTES:
        raise HTTPException(status_code=413, detail="Piece too large")
    size = job.video.stat().st_size
    if offset == size:
        with job.video.open("ab") as out:
            out.write(chunk)
    elif offset + len(chunk) != size:  # not a repeat of the last piece either
        raise HTTPException(status_code=409, detail=f"Expected offset {size}, got {offset}")
    return {"size": job.video.stat().st_size}


@app.post("/jobs/{job_id}/start", dependencies=[Depends(require_token)])
def start_job(job_id: str) -> dict[str, str]:
    """Step 3: the whole video has arrived, so queue the analysis."""
    job = get_job(job_id)
    if job.status != "uploading":
        raise HTTPException(status_code=409, detail="The job has already started")
    if job.video.stat().st_size == 0:
        raise HTTPException(status_code=400, detail="No video was uploaded")
    job.status, job.stage = "queued", "Waiting for the GPU"
    executor.submit(run_job, job, job.video)
    logger.info("Job %s queued (%s mode, %.1f MB)", job.id, job.mode, job.video.stat().st_size / 1e6)
    return {"id": job.id}


@app.get("/jobs/{job_id}", dependencies=[Depends(require_token)])
def job_status(job_id: str) -> dict[str, Any]:
    return get_job(job_id).public()


def finished_file(job_id: str, name: str, media_type: str) -> FileResponse:
    job = get_job(job_id)
    if job.status != "completed":
        raise HTTPException(status_code=409, detail="Job has not completed")
    return FileResponse(job.folder / name, media_type=media_type)


@app.get("/jobs/{job_id}/results", dependencies=[Depends(require_token)])
def job_results(job_id: str) -> FileResponse:
    return finished_file(job_id, "results.json", "application/json")


@app.get("/jobs/{job_id}/playback", dependencies=[Depends(require_token)])
def job_playback(job_id: str) -> FileResponse:
    return finished_file(job_id, "playback.mp4", "video/mp4")


@app.delete("/jobs/{job_id}", dependencies=[Depends(require_token)], status_code=204)
def delete_job(job_id: str) -> None:
    job = get_job(job_id)
    if job.status in ("queued", "running"):
        raise HTTPException(status_code=409, detail="Job is still running")
    with jobs_lock:
        jobs.pop(job_id, None)
    shutil.rmtree(job.folder, ignore_errors=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
