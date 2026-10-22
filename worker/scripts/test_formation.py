"""Smoke test for trajectory smoothing and formation detection.

Uses the cached team tracks from test_teams.py, smooths positions, fills ball
gaps, classifies each team's formation per time window and plots the average
shapes on mplsoccer pitches.

Usage:
    python scripts/test_formation.py
    python scripts/test_formation.py --window 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # render to file, no window
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from mplsoccer import Pitch  # noqa: E402

# Allow "python scripts/test_formation.py" from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.clustering import FormationResult, detect_formations  # noqa: E402
from src.tracker import load_tracks, save_tracks  # noqa: E402
from src.trajectories import interpolate_ball, smooth_positions  # noqa: E402

TEAM_COLOURS = {config.TEAM_A: "#E8E3D4", config.TEAM_B: "#C0392B"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", type=Path, default=config.DEFAULT_VIDEO)
    parser.add_argument("--window", type=float, default=config.FORMATION_WINDOW_SECONDS,
                        help="formation window length in seconds")
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR)
    return parser.parse_args()


def plot_formations(result: FormationResult, path: Path) -> None:
    """Grid of pitches: one row per team, one column per window."""
    windows = sorted(result.windows["window"].unique())
    teams = (config.TEAM_A, config.TEAM_B)
    pitch = Pitch(pitch_type="uefa", pitch_color="#1e4d2b", line_color="white", linewidth=1)
    fig, axes = plt.subplots(len(teams), len(windows), figsize=(4 * len(windows), 6), squeeze=False)

    for r, team in enumerate(teams):
        for c, window in enumerate(windows):
            ax = axes[r][c]
            pitch.draw(ax=ax)
            info = result.windows[(result.windows["team"] == team) & (result.windows["window"] == window)]
            pos = result.positions[(result.positions["team"] == team) & (result.positions["window"] == window)]
            if not pos.empty:
                pitch.scatter(pos["pitch_x"], pos["pitch_y"], ax=ax, s=60,
                              color=TEAM_COLOURS[team], edgecolors="black", zorder=3)
            if info.empty:
                title = f"Team {team} | window {window}\nno players"
            else:
                row = info.iloc[0]
                label = (f"{row.formation} (margin {row.confidence_margin:.3f})"
                         if pd.notna(row.formation) else f"too few players ({row.n_players})")
                title = f"Team {team} | {row.start:.0f}-{row.end:.0f}s\n{label}"
            ax.set_title(title, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    stem = args.video.stem
    teams_path = args.output_dir / f"{stem}_tracks_teams.parquet"
    final_path = args.output_dir / f"{stem}_tracks_final.parquet"
    windows_path = args.output_dir / f"{stem}_formations.parquet"
    plot_path = args.output_dir / f"{stem}_formations.png"

    tracks = load_tracks(teams_path)
    tracks = interpolate_ball(smooth_positions(tracks))
    save_tracks(tracks, final_path)

    result = detect_formations(tracks, window_seconds=args.window)
    save_tracks(result.windows, windows_path)

    duration = tracks["timestamp"].max() - tracks["timestamp"].min()
    print(f"\nClip duration analysed: {duration:.1f}s, window {args.window:.0f}s")
    columns = ["team", "start", "end", "n_players", "formation", "best_match",
               "runner_up", "cost", "confidence_margin", "defends"]
    print(result.windows[columns].round(3).to_string(index=False))
    changes = result.changes
    print("\nFormation changes:" if not changes.empty else "\nNo formation changes detected.")
    if not changes.empty:
        print(changes.round(2).to_string(index=False))

    plot_formations(result, plot_path)
    print(f"\nPlot:    {plot_path}\nWindows: {windows_path}\nTracks:  {final_path}")


if __name__ == "__main__":
    main()
