"""Smoke test for jersey-colour team assignment.

Uses the cached pitch tracks from test_homography.py (no detection is re-run),
writes a preview video with players coloured by team, a pitch plot of team
positions, and prints clustering statistics.

Usage:
    python scripts/test_teams.py
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # render to file, no window
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import supervision as sv  # noqa: E402
from mplsoccer import Pitch  # noqa: E402

# Allow "python scripts/test_teams.py" from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.clustering import (  # noqa: E402
    TeamAssignment,
    add_team_column,
    assign_teams,
    extract_jersey_features,
)
from src.tracker import load_tracks, save_tracks  # noqa: E402

REFEREE_HEX = "#FFD700"
BALL_HEX = "#FFFFFF"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", type=Path, default=config.DEFAULT_VIDEO)
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR)
    return parser.parse_args()


def write_team_video(
    video_path: Path, tracks: pd.DataFrame, assignment: TeamAssignment, path: Path
) -> None:
    """Redraw the tracked frames with ellipses in each team's shirt colour."""
    # Palette index = team + 1, so NO_TEAM (-1) -> referee/ball colour.
    palette = sv.ColorPalette.from_hex(
        [REFEREE_HEX, assignment.team_colour_hex(config.TEAM_A), assignment.team_colour_hex(config.TEAM_B)]
    )
    ellipse = sv.EllipseAnnotator(color=palette, thickness=3)
    label = sv.LabelAnnotator(color=palette, text_color=sv.Color.BLACK,
                              text_position=sv.Position.BOTTOM_CENTER, text_scale=0.5)
    ball_marker = sv.TriangleAnnotator(color=sv.Color.from_hex(BALL_HEX), base=20, height=17,
                                       outline_thickness=1, color_lookup=sv.ColorLookup.INDEX)

    frame_indices = np.sort(tracks["frame_idx"].unique())
    source = sv.VideoInfo.from_video_path(str(video_path))
    stride = int(np.median(np.diff(frame_indices))) if len(frame_indices) > 1 else 1
    info = sv.VideoInfo(width=source.width, height=source.height,
                        fps=max(1, round(source.fps / stride)))

    by_frame = {idx: group for idx, group in tracks.groupby("frame_idx")}
    frames = sv.get_video_frames_generator(str(video_path), end=int(frame_indices[-1]) + 1)
    with sv.VideoSink(str(path), info) as sink:
        for frame_idx, frame in enumerate(frames):
            group = by_frame.get(frame_idx)
            if group is None:
                continue
            people = group[group["class_id"] != config.BALL_ID]
            ball = group[group["class_id"] == config.BALL_ID]
            people_det = sv.Detections(
                xyxy=people[["x1", "y1", "x2", "y2"]].to_numpy(),
                class_id=(people["team"] + 1).to_numpy(),
            )
            labels = [
                f"#{tid} {'GK' if cls == 'goalkeeper' else ''}".strip()
                for tid, cls in zip(people["tracker_id"], people["role"])
            ]
            scene = ellipse.annotate(frame.copy(), people_det)
            scene = label.annotate(scene, people_det, labels=labels)
            scene = ball_marker.annotate(
                scene, sv.Detections(xyxy=ball[["x1", "y1", "x2", "y2"]].to_numpy())
            )
            sink.write_frame(scene)


def plot_teams(tracks: pd.DataFrame, assignment: TeamAssignment, path: Path) -> None:
    """Plot every person's position in the last frame, coloured by team."""
    last = tracks[tracks["frame_idx"] == tracks["frame_idx"].max()].dropna(subset=["pitch_x"])
    pitch = Pitch(pitch_type="uefa", pitch_color="#1e4d2b", line_color="white")
    fig, ax = pitch.draw(figsize=(12, 8))
    colours = {
        config.TEAM_A: assignment.team_colour_hex(config.TEAM_A),
        config.TEAM_B: assignment.team_colour_hex(config.TEAM_B),
        config.NO_TEAM: REFEREE_HEX,
    }
    for row in last.itertuples():
        if row.class_id == config.BALL_ID:
            pitch.scatter(row.pitch_x, row.pitch_y, ax=ax, s=60, color=BALL_HEX,
                          edgecolors="black", zorder=4)
            continue
        marker = "s" if row.role == "goalkeeper" else "o"
        pitch.scatter(row.pitch_x, row.pitch_y, ax=ax, s=220, marker=marker,
                      color=colours[row.team], edgecolors="black", zorder=3)
        pitch.annotate(str(row.tracker_id), (row.pitch_x, row.pitch_y), ax=ax, fontsize=7,
                       ha="center", va="center", color="black", zorder=5)
    ax.set_title(f"Teams at frame {int(last['frame_idx'].iat[0])} (square = goalkeeper)")
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    stem = args.video.stem
    tracks_path = args.output_dir / f"{stem}_tracks_pitch.parquet"
    teams_path = args.output_dir / f"{stem}_tracks_teams.parquet"
    video_path = args.output_dir / f"{stem}_teams.mp4"
    plot_path = args.output_dir / f"{stem}_teams.png"

    tracks = load_tracks(tracks_path)
    started = time.perf_counter()
    features = extract_jersey_features(args.video, tracks)
    assignment = assign_teams(tracks, features)
    elapsed = time.perf_counter() - started
    tracks = add_team_column(tracks, assignment)
    save_tracks(tracks, teams_path)

    # --- Summary -------------------------------------------------------------
    track_info = tracks[tracks["class_id"] != config.BALL_ID].groupby("tracker_id").agg(
        cls=("role", "first"), team=("team", "first")
    )
    print(f"\nExtracted {len(features)} jersey crops and clustered in {elapsed:.1f}s")
    for team in (config.TEAM_A, config.TEAM_B):
        members = track_info[track_info["team"] == team]
        print(f"Team {team} ({assignment.team_colour_hex(team)}): "
              f"{(members['cls'] == 'player').sum()} players, "
              f"{(members['cls'] == 'goalkeeper').sum()} goalkeeper(s)")
    print(f"No team: {(track_info['team'] == config.NO_TEAM).sum()} "
          f"({', '.join(track_info.loc[track_info['team'] == config.NO_TEAM, 'cls'])})")
    print(f"Crop agreement with track's team: mean {assignment.agreement.mean():.0%}, "
          f"min {assignment.agreement.min():.0%}")
    shaky = assignment.agreement[assignment.agreement < 0.8]
    if not shaky.empty:
        print("Tracks below 80% agreement:", shaky.round(2).to_dict())
    print(f"\nVideo:  {video_path}\nPlot:   {plot_path}\nTracks: {teams_path}")

    write_team_video(args.video, tracks, assignment, video_path)
    plot_teams(tracks, assignment, plot_path)


if __name__ == "__main__":
    main()
