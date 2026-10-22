"""Smoke test for pitch keypoints + homography.

Writes an overlay video with the projected pitch markings drawn on each frame,
projects the cached tracks from test_tracking.py onto the pitch, and plots the
players' movement on an mplsoccer pitch.

Usage:
    python scripts/test_homography.py
    python scripts/test_homography.py --stride 1 --max-frames 750
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")  # render to file, no window
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import supervision as sv  # noqa: E402
from mplsoccer import Pitch  # noqa: E402
from tqdm import tqdm  # noqa: E402

# Allow "python scripts/test_homography.py" from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.homography import (  # noqa: E402
    FrameHomography,
    HomographyEstimator,
    PitchKeypointDetector,
    homographies_to_dataframe,
    iter_homographies,
    project_tracks,
)
from src.tracker import load_tracks, save_tracks  # noqa: E402

LINE_COLOUR = (0, 255, 0)  # BGR
KEYPOINT_COLOUR = (255, 0, 255)
CLASS_COLOURS = {"goalkeeper": "#00BFFF", "player": "#FF1493", "referee": "#FFD700", "ball": "white"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", type=Path, default=config.DEFAULT_VIDEO)
    parser.add_argument("--weights", type=Path, default=config.PITCH_WEIGHTS)
    parser.add_argument("--stride", type=int, default=2, help="must match test_tracking.py")
    parser.add_argument("--max-frames", type=int, default=100, help="must match test_tracking.py")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR)
    return parser.parse_args()


def draw_overlay(frame_h: FrameHomography, estimator: HomographyEstimator) -> np.ndarray:
    """Draw the pitch markings as the homography sees them, plus the raw keypoints."""
    scene = frame_h.frame.copy()
    h = frame_h.homography
    if h is not None:
        for line in estimator.pitch.line_segments():
            pts = h.pitch_to_image(line).round().astype(np.int32)
            cv2.polylines(scene, [pts], isClosed=False, color=LINE_COLOUR, thickness=2)
    confident = frame_h.keypoints_conf >= estimator.keypoint_confidence
    for x, y in frame_h.keypoints_xy[confident].round().astype(int):
        cv2.circle(scene, (int(x), int(y)), 6, KEYPOINT_COLOUR, -1)

    if h is None:
        status = "no homography"
    else:
        status = f"inliers {h.n_inliers}/{h.n_keypoints}  err {h.reprojection_error:.2f} m"
        status += "  (reused)" if frame_h.reused else ""
    cv2.putText(scene, status, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    return scene


def plot_movement(tracks: pd.DataFrame, path: Path) -> None:
    """Draw each track's path on a pitch, with its last position marked."""
    pitch = Pitch(pitch_type="uefa", pitch_color="#1e4d2b", line_color="white")
    fig, ax = pitch.draw(figsize=(12, 8))
    for _, track in tracks[tracks["class_name"] != "ball"].groupby("tracker_id"):
        colour = CLASS_COLOURS[track["class_name"].mode().iat[0]]
        pitch.plot(track["pitch_x"], track["pitch_y"], ax=ax, color=colour, alpha=0.5, lw=1)
        last = track.iloc[-1]
        pitch.scatter(last["pitch_x"], last["pitch_y"], ax=ax, s=120, color=colour,
                      edgecolors="black", zorder=3)
        pitch.annotate(str(int(last["tracker_id"])), (last["pitch_x"], last["pitch_y"] + 1.5),
                       ax=ax, color="white", fontsize=8, ha="center")
    ball = tracks[tracks["class_name"] == "ball"]
    pitch.scatter(ball["pitch_x"], ball["pitch_y"], ax=ax, s=10, color="white", zorder=2)
    ax.set_title("Player movement (pitch coordinates, metres)", color="black")
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.video.stem
    overlay_path = args.output_dir / f"{stem}_pitch_overlay.mp4"
    homography_path = args.output_dir / f"{stem}_homography.parquet"
    tracks_path = args.output_dir / f"{stem}_tracks.parquet"
    pitch_tracks_path = args.output_dir / f"{stem}_tracks_pitch.parquet"
    plot_path = args.output_dir / f"{stem}_movement.png"

    detector = PitchKeypointDetector(args.weights)
    estimator = HomographyEstimator()
    source_info = sv.VideoInfo.from_video_path(str(args.video))
    overlay_info = sv.VideoInfo(
        width=source_info.width,
        height=source_info.height,
        fps=max(1, round(source_info.fps / args.stride)),
    )

    def draw_and_write(frames, sink: sv.VideoSink):
        for frame_h in frames:
            sink.write_frame(draw_overlay(frame_h, estimator))
            yield frame_h

    started = time.perf_counter()
    with sv.VideoSink(str(overlay_path), overlay_info) as sink:
        frames = iter_homographies(
            args.video, detector, estimator, stride=args.stride,
            max_frames=args.max_frames, batch_size=args.batch_size,
        )
        frames = tqdm(frames, desc="Homography", unit="frame", total=args.max_frames)
        homographies = homographies_to_dataframe(draw_and_write(frames, sink))
    elapsed = time.perf_counter() - started
    save_tracks(homographies, homography_path)

    # --- Homography summary --------------------------------------------------
    n = len(homographies)
    own = homographies["valid"] & ~homographies["reused"]
    print(f"\nProcessed {n} frames in {elapsed:.1f}s ({n / elapsed:.2f} fps)")
    print(f"Homography from own keypoints: {own.sum()}/{n} ({own.mean():.0%})")
    print(f"Reused previous homography:    {homographies['reused'].sum()}/{n}")
    print(f"No homography:                 {(~homographies['valid']).sum()}/{n}")
    print(f"Inliers per frame (mean):      {homographies.loc[own, 'n_inliers'].mean():.1f}")
    print(f"Reprojection error (mean):     {homographies['reprojection_error'].mean():.2f} m")
    print(f"Overlay: {overlay_path}")

    # --- Project cached tracks -----------------------------------------------
    if not tracks_path.exists():
        print(f"\nNo tracks at {tracks_path}; run scripts/test_tracking.py to project players.")
        return
    tracks = project_tracks(load_tracks(tracks_path), homographies)
    save_tracks(tracks, pitch_tracks_path)

    people = tracks[(tracks["class_name"] != "ball") & tracks["pitch_x"].notna()]
    margin = 2.0  # metres; players can legitimately stand just off the pitch
    inside = (
        people["pitch_x"].between(-margin, 105 + margin)
        & people["pitch_y"].between(-margin, 68 + margin)
    )
    print(f"\nProjected {tracks['pitch_x'].notna().sum()}/{len(tracks)} detections onto the pitch")
    print(f"People within pitch (+{margin:.0f} m margin): {inside.mean():.1%}")
    plot_movement(tracks.dropna(subset=["pitch_x"]), plot_path)
    print(f"Tracks:  {pitch_tracks_path}\nPlot:    {plot_path}")


if __name__ == "__main__":
    main()
