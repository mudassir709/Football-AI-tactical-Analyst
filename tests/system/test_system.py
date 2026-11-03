"""System tests: the whole running platform, tested from the outside.

These tests talk to Tactical Eye only through its public doors, like a browser
does: HTTP requests to nginx and the Socket.IO WebSocket. Nothing inside the
services is mocked, so a passing run means the frontend server, API, database,
queue and AI worker really work together.

Run against a running platform (default http://localhost:8080):

    pip install -r tests/system/requirements.txt
    python -m pytest tests/system -v

Settings (environment variables):
    TACTICAL_EYE_URL   address of the platform (default http://localhost:8080)
    SYSTEM_TEST_CLIP   a short football clip for the full-analysis test
                       (default tests/system/data/short_clip.mp4; skipped if missing)
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest
import socketio

BASE_URL = os.environ.get("TACTICAL_EYE_URL", "http://localhost:8080")
REPO = Path(__file__).resolve().parents[2]
CLIP = Path(os.environ.get("SYSTEM_TEST_CLIP", REPO / "tests" / "system" / "data" / "short_clip.mp4"))
# Analysing a 3-second clip on a CPU takes 1-3 minutes; allow plenty of time.
ANALYSIS_TIMEOUT_S = 15 * 60


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def new_user() -> httpx.Client:
    """Register a fresh user and return a client that keeps their login cookie."""
    client = httpx.Client(base_url=BASE_URL, timeout=60)
    email = f"systemtest-{uuid.uuid4().hex[:10]}@example.com"
    response = client.post("/api/auth/register", json={"name": "System Test", "email": email, "password": "longenough1"})
    assert response.status_code == 201, response.text
    return client


def upload(client: httpx.Client, path: Path, mode: str = "quick", title: str = "System test") -> dict:
    with path.open("rb") as file:
        response = client.post(
            "/api/matches",
            data={"title": title, "mode": mode},
            files={"video": (path.name, file, "video/mp4")},
        )
    assert response.status_code == 201, response.text
    return response.json()["match"]


def wait_for(client: httpx.Client, match_id: str, statuses: set[str]) -> dict:
    """Ask for the match every 2 seconds until it reaches one of ``statuses``."""
    deadline = time.time() + ANALYSIS_TIMEOUT_S
    while time.time() < deadline:
        match = client.get(f"/api/matches/{match_id}").json()["match"]
        if match["status"] in statuses:
            return match
        time.sleep(2)
    pytest.fail(f"match {match_id} did not reach {statuses} in time")


@pytest.fixture(scope="session")
def player_less_clip(tmp_path_factory) -> Path:
    """A real 2-second video that shows only green grass, so no players."""
    path = tmp_path_factory.mktemp("clips") / "empty_pitch.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (640, 360))
    for _ in range(50):
        writer.write(np.full((360, 640, 3), (40, 120, 40), np.uint8))
    writer.release()
    return path


# --------------------------------------------------------------------------
# The platform is up
# --------------------------------------------------------------------------

def test_health_check_reports_all_parts_up():
    body = httpx.get(f"{BASE_URL}/api/health", timeout=30).json()
    assert body["status"] == "ok" and body["database"] == "up" and body["redis"] == "up"
    assert body["workers"] >= 1, "no AI worker is connected to the queue"


def test_deep_links_load_the_dashboard():
    # nginx must answer any page address with the React app, not a 404.
    response = httpx.get(f"{BASE_URL}/matches/some-id", timeout=30)
    assert response.status_code == 200 and '<div id="root">' in response.text


def test_unknown_api_address_gives_a_json_404():
    response = httpx.get(f"{BASE_URL}/api/nothing-here", timeout=30)
    assert response.status_code == 404 and response.json() == {"error": "Not found"}


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------

def test_matches_need_a_login():
    assert httpx.get(f"{BASE_URL}/api/matches", timeout=30).status_code == 401


@pytest.mark.parametrize("body, field", [
    ({"name": "X", "email": "x@example.com", "password": "short"}, "password"),
    ({"name": "X", "email": "not-an-email", "password": "longenough1"}, "email"),
])
def test_invalid_registrations_are_refused(body, field):
    response = httpx.post(f"{BASE_URL}/api/auth/register", json=body, timeout=30)
    assert response.status_code == 400 and field in response.json()["error"]


def test_login_logout_cycle():
    email = f"systemtest-{uuid.uuid4().hex[:10]}@example.com"
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        client.post("/api/auth/register", json={"name": "A", "email": email, "password": "longenough1"})
        client.post("/api/auth/logout")
        assert client.get("/api/auth/me").status_code == 401
        wrong = client.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
        assert wrong.status_code == 401 and wrong.json()["error"] == "Invalid email or password"
        assert client.post("/api/auth/login", json={"email": email, "password": "longenough1"}).status_code == 200
        assert client.get("/api/auth/me").json()["user"]["email"] == email
        # Registering the same address again (in capitals) is refused.
        again = client.post("/api/auth/register", json={"name": "B", "email": email.upper(), "password": "longenough1"})
        assert again.status_code == 409


# --------------------------------------------------------------------------
# Uploads that must be refused
# --------------------------------------------------------------------------

def test_non_videos_are_refused(tmp_path):
    client = new_user()
    text = tmp_path / "notes.txt"
    text.write_text("hello")
    disguised = tmp_path / "fake.mp4"
    disguised.write_text("plain text pretending to be a video")

    with text.open("rb") as f:
        assert client.post("/api/matches", files={"video": ("notes.txt", f, "text/plain")}).status_code == 400
    with disguised.open("rb") as f:
        response = client.post("/api/matches", files={"video": ("fake.mp4", f, "video/mp4")})
    assert response.status_code == 400 and response.json()["error"] == "The file is not a valid video"
    assert client.post("/api/matches", data={"title": "no file"}).status_code == 400
    assert client.get("/api/matches").json()["matches"] == []


# --------------------------------------------------------------------------
# A failing analysis
# --------------------------------------------------------------------------

def test_a_video_without_players_fails_with_a_clear_reason(player_less_clip):
    client = new_user()
    match = upload(client, player_less_clip, title="No players")
    # The worker tries twice (one retry after 10 s) before giving up.
    failed = wait_for(client, match["id"], {"FAILED", "COMPLETED"})
    assert failed["status"] == "FAILED"
    assert failed["errorMessage"] == "No players were detected in this video"
    assert client.delete(f"/api/matches/{match['id']}").status_code == 204


# --------------------------------------------------------------------------
# A full analysis, followed live over the WebSocket
# --------------------------------------------------------------------------

@pytest.mark.skipif(not CLIP.exists(), reason=f"test clip not found: {CLIP}")
def test_full_analysis_with_live_updates_and_ownership():
    owner = new_user()
    stranger = new_user()

    # Listen to the owner's live updates, the same way the dashboard does.
    updates: list[dict] = []
    live = socketio.Client()
    live.on("match:updated", updates.append)
    cookie = "; ".join(f"{name}={value}" for name, value in owner.cookies.items())
    live.connect(BASE_URL, headers={"Cookie": cookie}, transports=["websocket"])

    try:
        match = upload(owner, CLIP, mode="quick", title="Full analysis")
        match_id = match["id"]
        assert match["status"] == "QUEUED"

        # While it is queued or running, these requests must be refused.
        assert owner.post(f"/api/matches/{match_id}/reanalyse").status_code == 409
        assert owner.get(f"/api/matches/{match_id}/results").status_code == 409

        # Another user cannot see or touch the match.
        assert stranger.get(f"/api/matches/{match_id}").status_code == 404
        assert stranger.delete(f"/api/matches/{match_id}").status_code == 404
        assert stranger.get("/api/matches").json()["matches"] == []

        done = wait_for(owner, match_id, {"COMPLETED", "FAILED"})
    finally:
        live.disconnect()

    assert done["status"] == "COMPLETED", done["errorMessage"]

    # The progress reached the browser live: several updates, going up to 100 %.
    progress = [u["progress"] for u in updates if u["id"] == match_id]
    assert len(progress) >= 5, f"only {len(progress)} live updates received"
    assert progress == sorted(progress) and progress[-1] == 100

    # Headline numbers for both teams were stored.
    summary = done["summary"]
    assert len(summary["teams"]) == 2 and summary["framesAnalysed"] > 0

    # The full results file has the parts the dashboard draws.
    results = owner.get(f"/api/matches/{match_id}/results").json()
    assert results["version"] == 2 and len(results["frames"]) == summary["framesAnalysed"]
    assert {"players", "teamShape", "heatmaps", "formations"} <= results.keys()

    # The video can be streamed in pieces (needed for seeking in the player).
    piece = owner.get(f"/api/matches/{match_id}/video", headers={"Range": "bytes=0-999"})
    assert piece.status_code == 206 and len(piece.content) == 1000

    # Re-analysis is allowed now, and deleting removes the match for good.
    assert owner.post(f"/api/matches/{match_id}/reanalyse").json()["match"]["status"] == "QUEUED"
    wait_for(owner, match_id, {"COMPLETED", "FAILED"})
    assert owner.delete(f"/api/matches/{match_id}").status_code == 204
    assert owner.get(f"/api/matches/{match_id}").status_code == 404
