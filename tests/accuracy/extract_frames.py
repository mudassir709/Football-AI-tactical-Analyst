"""Pick frames from the test clips for manual annotation.

For each analysed clip, a few frames spread over the clip are saved as JPEG
images, together with frames.json, which lists them. Only frames that the
pipeline actually analysed (and that have a camera matrix) are picked, so every
annotation can be compared with the AI's output for exactly that frame.

    python tests/accuracy/extract_frames.py
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2

HERE = Path(__file__).parent
REPO = HERE.parents[1]
FRAMES_DIR = HERE / "frames"
PER_CLIP = 4  # frames per clip; 5 clips x 4 = 20 frames to annotate

# Test clip -> its analysis results (match ID in storage/results).
CLIPS = {
    "sample": "cmw1hnfoj000130rve1d3g2s7",
    "08fd33_0": "cmw1hnfxm000230rvzjwi8jlh",
    "121364_0": "cmw1hng61000330rvlu25c485",
    "2e57b9_0": "cmw1hngfd000430rvsi9fr1eh",
    "573e61_0": "cmw1hngo5000530rvrknmt5li",
}


def pick_frames(results: dict) -> list[int]:
    """Analysed frames at 15 %, 40 %, 65 % and 90 % of the clip."""
    usable = [f["f"] for f in results["frames"] if f.get("h")]
    return [usable[round(share * (len(usable) - 1))] for share in (0.15, 0.40, 0.65, 0.90)][:PER_CLIP]


def main() -> None:
    FRAMES_DIR.mkdir(exist_ok=True)
    manifest = []
    for clip, match_id in CLIPS.items():
        results = json.loads((REPO / "storage" / "results" / f"{match_id}.json").read_text(encoding="utf-8"))
        wanted = set(pick_frames(results))
        # Read the video from the start instead of jumping, so the frame numbers
        # are exactly the ones the pipeline used.
        video = cv2.VideoCapture(str(REPO / "worker" / "data" / f"{clip}.mp4"))
        index = 0
        while wanted:
            ok, image = video.read()
            if not ok:
                break
            if index in wanted:
                name = f"{clip}_{index:04d}.jpg"
                cv2.imwrite(str(FRAMES_DIR / name), image, [cv2.IMWRITE_JPEG_QUALITY, 92])
                manifest.append({"clip": clip, "matchId": match_id, "frame": index, "file": name,
                                 "width": image.shape[1], "height": image.shape[0]})
                wanted.discard(index)
            index += 1
        video.release()
    (FRAMES_DIR / "frames.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    # Also as a script, so the annotation page can load it when opened from disk.
    (FRAMES_DIR / "frames.js").write_text(f"window.FRAMES = {json.dumps(manifest)};\n", encoding="utf-8")
    print(f"saved {len(manifest)} frames to {FRAMES_DIR}")


if __name__ == "__main__":
    main()
