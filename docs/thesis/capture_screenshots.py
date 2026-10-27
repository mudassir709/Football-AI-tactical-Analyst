"""Capture the dashboard screenshots used in the thesis documentation.

Drives Microsoft Edge (Playwright) through the running platform at
http://localhost:8080 with the demo account. It also creates the states the
user guide explains: an upload in progress, a rejected file and a failed
analysis.

    python capture_screenshots.py <dir with short.mp4, empty_pitch.mp4, not_a_video.mp4>
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = "http://localhost:8080"
EMAIL, PASSWORD = "demo@example.com", "supersecret1"
OUT = Path(__file__).parent / "screenshots"
FILES = Path(sys.argv[1])
SECTIONS = set((sys.argv[2] if len(sys.argv) > 2 else "public,upload,analysis,failure").split(","))
SHOWCASE_TITLE = "Bundesliga clip 1 (sample)"


def shot(page: Page, name: str, locator=None, full_page: bool = False) -> None:
    page.wait_for_timeout(400)  # let canvases and transitions settle
    target = OUT / f"{name}.png"
    if locator is not None:
        locator.screenshot(path=target)
    else:
        page.screenshot(path=target, full_page=full_page)
    print("saved", target.name)


def api(page: Page, path: str):
    return page.evaluate(f"fetch('/api{path}').then(r => r.json())")


def wait_for(page: Page, match_id: str, done, timeout: float = 900):
    deadline = time.time() + timeout
    while time.time() < deadline:
        match = api(page, f"/matches/{match_id}")["match"]
        if done(match):
            return match
        page.wait_for_timeout(2000)
    raise TimeoutError(match_id)


def upload(page: Page, file: Path, title: str, mode: str) -> str:
    page.goto(f"{BASE}/upload")
    page.set_input_files("input[type=file]", str(file))
    page.fill("input[placeholder^='e.g.']", title)
    page.click(f"label:has(input[value={mode}])")
    return file.name


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


def upload_pages(page: Page) -> None:
    # Replace the old smoke-test match with a properly named demo clip.
    for match in api(page, "/matches")["matches"]:
        if match["title"].startswith("Docker test"):
            page.evaluate(f"fetch('/api/matches/{match['id']}', {{method: 'DELETE'}})")
    page.goto(f"{BASE}/")
    page.wait_for_selector(f"text={SHOWCASE_TITLE}")
    shot(page, "04_matches")

    page.goto(f"{BASE}/upload")
    shot(page, "05_upload_empty")
    upload(page, FILES / "not_a_video.mp4", "Not a video", "quick")
    page.click("button[type=submit]")
    page.wait_for_selector("text=The file is not a valid video")
    shot(page, "06_upload_invalid_file")

    upload(page, FILES / "short.mp4", "Short demo clip", "quick")
    shot(page, "07_upload_ready")
    page.click("button[type=submit]")
    page.wait_for_url(f"{BASE}/matches/*")
    short_id = page.url.rsplit("/", 1)[1]
    wait_for(page, short_id, lambda m: m["status"] == "PROCESSING" and m["progress"] >= 20)
    shot(page, "08_match_in_progress")
    page.goto(f"{BASE}/")
    page.wait_for_selector("text=Short demo clip")
    shot(page, "09_matches_live_progress")


def analysis_pages(page: Page) -> None:
    showcase = next(m for m in api(page, "/matches")["matches"] if m["title"] == SHOWCASE_TITLE)
    page.goto(f"{BASE}/matches/{showcase['id']}")
    page.wait_for_function("document.querySelector('video')?.readyState >= 2", timeout=60000)
    page.evaluate("""() => new Promise(done => {
        const v = document.querySelector('video');
        v.addEventListener('seeked', done, {once: true});
        v.currentTime = 8;
    })""")
    shot(page, "10_match_page")
    video_card = page.locator("video >> xpath=../..")
    shot(page, "11_overlay_players_paths", video_card)

    page.click("button:has-text('Team shape')")
    shot(page, "12_overlay_team_shape", video_card)
    page.click("button:has-text('Team shape')")
    heatmap_select = page.locator("label:has-text('Heatmap') select")
    heatmap_select.select_option("0")
    shot(page, "13_overlay_heatmap_team_a", video_card)
    heatmap_select.select_option("ball")
    shot(page, "14_overlay_heatmap_ball", video_card)
    heatmap_select.select_option("off")
    shot(page, "15_layer_controls", page.locator("span:text-is('Layers') >> xpath=.."))

    # Click the largest (closest) outfield player of Team A on the overlay.
    results = api(page, f"/matches/{showcase['id']}/results")
    now = page.evaluate("document.querySelector('video').currentTime")
    frame = min(results["frames"], key=lambda f: abs(f["t"] - now))
    person = max((r for r in frame["p"] if r[1] == 0 and r[2] == 0), key=lambda r: r[6] - r[4])
    box = page.locator("canvas[aria-label^='Tactical overlay']").bounding_box()
    scale = box["width"] / results["video"]["width"]
    page.mouse.click(box["x"] + (person[3] + person[5]) / 2 * scale,
                     box["y"] + (person[4] + person[6]) / 2 * scale)
    page.wait_for_selector("text=Top speed")
    shot(page, "16_player_selected")
    shot(page, "17_board_and_player_panel",
         page.locator("canvas[aria-label^='2D tactical board'] >> xpath=../.."))

    summary = page.locator("text=Clip length >> xpath=ancestor::div[contains(@class,'space-y-4')][1]")
    summary.scroll_into_view_if_needed()
    shot(page, "18_summary", summary)
    report = page.locator("h2:has-text('AI coaching report') >> xpath=../../..")
    report.scroll_into_view_if_needed()
    shot(page, "19_coaching_report", report)


def failure_pages(page: Page) -> None:
    for match in api(page, "/matches")["matches"]:  # the worker runs one job at a time
        if match["status"] in ("QUEUED", "PROCESSING"):
            wait_for(page, match["id"], lambda m: m["status"] in ("COMPLETED", "FAILED"))
    upload(page, FILES / "empty_pitch.mp4", "Clip without players", "quick")
    page.click("button[type=submit]")
    page.wait_for_url(f"{BASE}/matches/*")
    failed_id = page.url.rsplit("/", 1)[1]
    wait_for(page, failed_id, lambda m: m["status"] == "FAILED")
    page.reload()
    page.wait_for_selector("text=Analysis failed")
    shot(page, "20_match_failed")
    page.goto(f"{BASE}/")
    card = page.locator("h2:has-text('Clip without players') >> xpath=ancestor::div[contains(@class,'flex-col')][1]")
    card.locator("button:has-text('Delete')").click()
    shot(page, "21_matches_failed_and_delete_confirm")
    card.locator("button:has-text('Yes')").click()
    page.wait_for_selector("text=Clip without players", state="detached")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        if "public" in SECTIONS:
            public_pages(page)
        log_in(page)
        if "upload" in SECTIONS:
            upload_pages(page)
        if "analysis" in SECTIONS:
            analysis_pages(page)
        if "failure" in SECTIONS:
            failure_pages(page)
        browser.close()


if __name__ == "__main__":
    main()
