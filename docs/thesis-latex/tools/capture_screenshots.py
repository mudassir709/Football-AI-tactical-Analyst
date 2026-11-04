"""Capture the dashboard screenshots for the LaTeX thesis (screenshots/*.png).

Drives Microsoft Edge (Playwright) through the running platform at
http://localhost:8080 with the demo account, at twice the normal pixel density
so the images stay sharp in print. It also creates the states the user guide
explains: an upload in progress, a cancelled analysis, a rejected file and a
failed analysis.

Run from the repository root while the platform is running:
    python docs/thesis-latex/tools/capture_screenshots.py [sections]
sections: any of public,upload,analysis,failure (default: all)
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import Page, sync_playwright

BASE = "http://localhost:8080"
EMAIL, PASSWORD = "demo@example.com", "supersecret1"
REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent.parent / "screenshots"
SECTIONS = set((sys.argv[1] if len(sys.argv) > 1 else "public,upload,analysis,failure").split(","))
SHOWCASE_TITLE = "Real Madrid vs Barcelona - First Half"
SHOWCASE_TIME = 1200  # 20:00, an open-play moment with every layer visible


def shot(page: Page, name: str, locator=None) -> None:
    page.wait_for_timeout(500)  # let canvases and transitions settle
    target = OUT / f"{name}.png"
    if locator is not None:
        locator.screenshot(path=target)
    else:
        page.screenshot(path=target)
    print("saved", target.name)


def api(page: Page, path: str):
    return page.evaluate(f"fetch('/api{path}').then(r => r.json())")


def wait_for(page: Page, match_id: str, done, timeout: float = 900):
    deadline = time.time() + timeout
    while time.time() < deadline:
        match = api(page, f"/matches/{match_id}")["match"]
        if done(match):
            return match
        page.wait_for_timeout(1000)
    raise TimeoutError(match_id)


def test_files() -> dict[str, Path]:
    """A fake video (text with an .mp4 name) and a real video of plain grass."""
    folder = Path(tempfile.mkdtemp(prefix="tactical-eye-shots-"))
    (folder / "not_a_video.mp4").write_text("This is a text file, not a video.\n")
    grass = folder / "empty_pitch.mp4"
    writer = cv2.VideoWriter(str(grass), cv2.VideoWriter_fourcc(*"mp4v"), 25, (640, 360))
    for _ in range(50):
        writer.write(np.full((360, 640, 3), (60, 140, 70), np.uint8))
    writer.release()
    return {"fake": folder / "not_a_video.mp4", "grass": grass, "short": REPO / "worker" / "data" / "short.mp4"}


def choose_upload(page: Page, file: Path, title: str, mode: str) -> None:
    page.goto(f"{BASE}/upload")
    page.set_input_files("input[type=file]", str(file))
    page.fill("input[aria-label=Title]", title)
    page.click(f"label:has(input[value={mode}])")


def public_pages(page: Page) -> None:
    page.goto(f"{BASE}/login")
    shot(page, "01_login")
    page.fill("input[type=email]", EMAIL)
    page.fill("input[type=password]", "wrong-password")
    page.click("button[type=submit]")
    page.wait_for_selector("text=Invalid email or password")
    shot(page, "02_login_error")
    page.goto(f"{BASE}/register")
    shot(page, "03_register")


def log_in(page: Page) -> None:
    page.goto(f"{BASE}/login")
    page.fill("input[type=email]", EMAIL)
    page.fill("input[type=password]", PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_url(f"{BASE}/")


def upload_pages(page: Page, files: dict[str, Path]) -> None:
    page.goto(f"{BASE}/")
    page.wait_for_selector(f"text={SHOWCASE_TITLE}")
    shot(page, "04_matches")

    page.goto(f"{BASE}/upload")
    shot(page, "05_upload_empty")
    choose_upload(page, files["fake"], "Not a video", "quick")
    page.click("button[type=submit]")
    page.wait_for_selector("text=The file is not a valid video")
    shot(page, "06_upload_invalid_file")

    choose_upload(page, files["short"], "Short demo clip", "quick")
    shot(page, "07_upload_ready")
    page.click("button[type=submit]")
    page.wait_for_url(f"{BASE}/matches/*")
    short_id = page.url.rsplit("/", 1)[1]
    wait_for(page, short_id, lambda m: m["status"] == "PROCESSING" and m["progress"] >= 10)
    shot(page, "08_match_in_progress")
    page.goto(f"{BASE}/")
    page.wait_for_selector("text=Short demo clip")
    shot(page, "09_matches_live_progress")

    # Cancel the running analysis from its page.
    page.goto(f"{BASE}/matches/{short_id}")
    page.once("dialog", lambda dialog: dialog.accept())
    page.click("text=Cancel analysis")
    page.wait_for_selector("text=The analysis was cancelled", timeout=120000)
    shot(page, "10_match_cancelled")
    page.evaluate(f"fetch('/api/matches/{short_id}', {{method: 'DELETE'}})")


def analysis_pages(page: Page) -> None:
    showcase = next(m for m in api(page, "/matches")["matches"] if m["title"] == SHOWCASE_TITLE)
    page.goto(f"{BASE}/matches/{showcase['id']}")
    # The page header sticks to the top while scrolling and would cover the
    # top of element screenshots further down the page.
    page.add_style_tag(content="header { position: static !important; }")
    page.wait_for_function("document.querySelector('video')?.readyState >= 2", timeout=120000)
    page.evaluate(f"""() => new Promise(done => {{
        const v = document.querySelector('video');
        v.addEventListener('seeked', done, {{once: true}});
        v.currentTime = {SHOWCASE_TIME};
    }})""")
    shot(page, "11_match_page")
    video_card = page.locator("video >> xpath=../..")
    shot(page, "12_overlay_players_paths", video_card)

    page.click("button:has-text('team shape')")
    shot(page, "13_overlay_team_shape", video_card)
    page.click("button:has-text('team shape')")
    heatmap = page.locator("select").nth(1)  # the first menu is the playback speed
    heatmap.select_option("0")
    shot(page, "14_overlay_heatmap_team_a", video_card)
    heatmap.select_option("ball")
    shot(page, "15_overlay_heatmap_ball", video_card)
    heatmap.select_option("off")
    shot(page, "16_layer_controls", page.locator("button:has-text('movement paths') >> xpath=.."))

    # Click the largest labelled outfield player of Team A on the video.
    results = api(page, f"/matches/{showcase['id']}/results")
    now = page.evaluate("document.querySelector('video').currentTime")
    frame = min(results["frames"], key=lambda f: abs(f["t"] - now))
    person = max((r for r in frame["p"] if r[1] == 0 and r[2] == 0 and len(r) > 9 and r[9] is not None),
                 key=lambda r: r[6] - r[4])
    box = page.locator("canvas[aria-label^='Tactical overlay']").bounding_box()
    scale = box["width"] / results["video"]["width"]
    page.mouse.click(box["x"] + (person[3] + person[5]) / 2 * scale, box["y"] + (person[4] + person[6]) / 2 * scale)
    page.wait_for_selector("text=Top speed")
    shot(page, "17_player_selected")
    shot(page, "18_board_and_formations", page.locator("canvas[aria-label^='2D tactical board'] >> xpath=.."))
    panel = page.locator("[role=tabpanel]")
    panel.scroll_into_view_if_needed()
    shot(page, "19_player_panel", panel)

    page.click("[role=tab]:has-text('Summary')")
    shot(page, "20_summary", panel)
    page.click("[role=tab]:has-text('AI coaching report')")
    page.wait_for_selector(".report h2", timeout=60000)
    shot(page, "21_coaching_report", page.locator(".report"))

    page.evaluate("window.scrollTo(0, 0)")
    page.click("button[aria-label='Full screen']")
    page.wait_for_timeout(1500)
    shot(page, "22_full_screen")
    page.evaluate("document.exitFullscreen()")


def failure_pages(page: Page, files: dict[str, Path]) -> None:
    for match in api(page, "/matches")["matches"]:  # the worker runs one job at a time
        if match["status"] in ("QUEUED", "PROCESSING"):
            wait_for(page, match["id"], lambda m: m["status"] not in ("QUEUED", "PROCESSING"))
    choose_upload(page, files["grass"], "Clip without players", "quick")
    page.click("button[type=submit]")
    page.wait_for_url(f"{BASE}/matches/*")
    failed_id = page.url.rsplit("/", 1)[1]
    wait_for(page, failed_id, lambda m: m["status"] == "FAILED")
    page.reload()
    page.wait_for_selector("text=Analysis failed")
    shot(page, "23_match_failed")
    page.goto(f"{BASE}/")
    row = page.locator("a:has-text('Clip without players') >> xpath=..")
    row.locator("button:has-text('Delete')").click()
    shot(page, "24_matches_failed_and_delete_confirm")
    row.locator("button:has-text('Yes')").click()
    page.wait_for_selector("text=Clip without players", state="detached")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    files = test_files()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        if "public" in SECTIONS:
            public_pages(page)
        log_in(page)
        if "upload" in SECTIONS:
            upload_pages(page, files)
        if "analysis" in SECTIONS:
            analysis_pages(page)
        if "failure" in SECTIONS:
            failure_pages(page, files)
        browser.close()


if __name__ == "__main__":
    main()
