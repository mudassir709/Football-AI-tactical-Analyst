"""Smoke test for detection + tracking.

Writes an annotated preview video and a parquet file of tracks, then prints
throughput and tracking statistics.

Usage:
    python scripts/test_tracking.py
    python scripts/test_tracking.py --stride 1 --max-frames 750 --imgsz 960
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import supervision as sv
from tqdm import tqdm

# Allow "python scripts/test_tracking.py" from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.detector import FootballDetector  # noqa: E402
from src.tracker import frame_tracks_to_dataframe, iter_tracks, save_tracks  # noqa: E402

# Colours indexed by canonical class ID: ball, goalkeeper, player, referee.
CLASS_PALETTE = sv.ColorPalette.from_hex(["#FFD700", "#00BFFF", "#FF1493", "#FFD700"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", type=Path, default=config.DEFAULT_VIDEO)
    parser.add_argument("--weights", type=Path, default=config.DEFAULT_WEIGHTS)
    parser.add_argument("--stride", type=int, default=2, help="process every Nth frame")
    parser.add_argument("--max-frames", type=int, default=100, help="frames to process")
    parser.add_argument("--imgsz", type=int, default=config.DEFAULT_IMGSZ)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    preview_path = args.output_dir / f"{args.video.stem}_tracked.mp4"
    tracks_path = args.output_dir / f"{args.video.stem}_tracks.parquet"

    detector = FootballDetector(args.weights, imgsz=args.imgsz)
    source_info = sv.VideoInfo.from_video_path(str(args.video))
    # The preview plays back at real speed even when frames are skipped.
    preview_info = sv.VideoInfo(
        width=source_info.width,
        height=source_info.height,
        fps=max(1, round(source_info.fps / args.stride)),
    )

    ellipse = sv.EllipseAnnotator(color=CLASS_PALETTE, thickness=2)
    label = sv.LabelAnnotator(
        color=CLASS_PALETTE, text_color=sv.Color.BLACK,
        text_position=sv.Position.BOTTOM_CENTER, text_scale=0.5,
    )
    ball_marker = sv.TriangleAnnotator(color=CLASS_PALETTE, base=20, height=17, outline_thickness=1)

    def annotate_and_write(frames, sink: sv.VideoSink):
        """Draw each frame into the preview, then pass it on unchanged."""
        for frame_tracks in frames:
            scene = frame_tracks.frame.copy()
            labels = [f"#{tid}" for tid in frame_tracks.people.tracker_id]
            scene = ellipse.annotate(scene, frame_tracks.people)
            scene = label.annotate(scene, frame_tracks.people, labels=labels)
            scene = ball_marker.annotate(scene, frame_tracks.ball)
            sink.write_frame(scene)
            yield frame_tracks

    started = time.perf_counter()
    with sv.VideoSink(str(preview_path), preview_info) as sink:
        frames = iter_tracks(
            args.video, detector, stride=args.stride,
            max_frames=args.max_frames, batch_size=args.batch_size,
        )
        frames = tqdm(frames, desc="Tracking", unit="frame", total=args.max_frames)
        tracks = frame_tracks_to_dataframe(annotate_and_write(frames, sink))
    elapsed = time.perf_counter() - started
    save_tracks(tracks, tracks_path)

    # --- Summary -------------------------------------------------------------
    n_frames = tracks["frame_idx"].nunique()
    people = tracks[tracks["class_name"] != "ball"]
    ball_frames = tracks.loc[tracks["class_name"] == "ball", "frame_idx"].nunique()
    print(f"\nProcessed {n_frames} frames in {elapsed:.1f}s ({n_frames / elapsed:.2f} fps)")
    print(f"Ball detected in {ball_frames}/{n_frames} frames ({ball_frames / max(n_frames, 1):.0%})")
    print(f"People per frame (mean): {people.groupby('frame_idx').size().mean():.1f}")
    print(f"Unique track IDs: {people['tracker_id'].nunique()}")
    print("Track IDs by majority class:")
    majority = people.groupby("tracker_id")["class_name"].agg(lambda s: s.mode().iat[0])
    print(majority.value_counts().to_string())
    print(f"\nPreview: {preview_path}\nTracks:  {tracks_path}")


if __name__ == "__main__":
    main()
