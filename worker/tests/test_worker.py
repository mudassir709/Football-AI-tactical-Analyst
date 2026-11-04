"""The queue worker (worker.py): a job handed out twice is only analysed once."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # worker.py lives next to tests/
import worker  # noqa: E402


class FakeJob:
    """Just enough of a BullMQ job for worker.analyse."""

    def __init__(self, timestamp: int):
        self.id = "match1"
        self.timestamp = timestamp  # when the job was created
        self.data = {"matchId": "match1", "videoPath": "videos/match1.mp4", "mode": "quick"}

    async def updateProgress(self, progress):  # noqa: N802 (BullMQ's name)
        pass


def test_a_job_handed_out_again_after_sleep_is_not_analysed_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(worker.config, "STORAGE_DIR", tmp_path)
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "match1.mp4").write_bytes(b"video")
    runs = []

    def pretend_analysis(video, results, playback, progress, mode):
        # Stands in for the real (slow) pipeline: writes the two outputs.
        runs.append(1)
        results.parent.mkdir(parents=True, exist_ok=True)
        results.write_text("{}")
        playback.write_bytes(b"web video")
        return {"processingSeconds": 1.0, "processedOn": "CPU", "framesAnalysed": len(runs)}

    async def no_cancel_watch(match_id, stop):
        await asyncio.sleep(3600)

    monkeypatch.setattr(worker, "run_analysis", pretend_analysis)
    monkeypatch.setattr(worker, "watch_for_cancel", no_cancel_watch)
    monkeypatch.setattr(worker.config, "GPU_SERVER_URL", "")

    first = asyncio.run(worker.analyse(FakeJob(timestamp=1000)))
    # The laptop slept; the queue hands out the very same job again.
    again = asyncio.run(worker.analyse(FakeJob(timestamp=1000)))
    assert len(runs) == 1 and again == first

    # A real re-analysis is a new job (new creation time), so it does run.
    asyncio.run(worker.analyse(FakeJob(timestamp=2000)))
    assert len(runs) == 2
