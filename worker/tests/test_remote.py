"""The GPU client (src/remote.py) against a pretend GPU service."""

import httpx
import pytest

from src import remote
from src.cancel import AnalysisCancelled


def fake_gpu_service(calls: list[str]):
    """A pretend GPU service that accepts the upload and then keeps "running"."""
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/health":
            return httpx.Response(200, json={"device": "GPU (test)"})
        if request.method == "POST" and request.url.path == "/jobs":
            return httpx.Response(200, json={"id": "job1"})
        if request.method == "GET" and request.url.path == "/jobs/job1":
            return httpx.Response(200, json={"status": "running", "percent": 40, "stage": "Detecting"})
        return httpx.Response(200, json={})
    return httpx.MockTransport(handle)


def test_cancelling_tells_the_gpu_service_to_stop(tmp_path, monkeypatch):
    calls: list[str] = []
    transport = fake_gpu_service(calls)
    # Every client the GPU code creates talks to the pretend service.
    real_client = httpx.Client
    monkeypatch.setattr(remote.httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs))
    monkeypatch.setattr(remote, "POLL_SECONDS", 0)
    video = tmp_path / "match.mp4"
    video.write_bytes(b"x" * 1000)

    # The user presses Cancel after the second status check.
    status_checks = []
    def should_stop() -> bool:
        status_checks.append(1)
        return len(status_checks) > 2

    with pytest.raises(AnalysisCancelled):
        remote.run_remote_analysis(
            "http://gpu", "token", video, tmp_path / "r.json", tmp_path / "p.mp4",
            lambda percent, stage: None, "quick", should_stop,
        )
    assert "POST /jobs/job1/cancel" in calls  # the GPU was told to stop
    assert not any(call.endswith("/results") for call in calls)  # nothing downloaded
