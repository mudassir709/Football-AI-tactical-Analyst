"""Tactical and physical metrics computed from pitch trajectories.

- Team shape: how compact each team is every frame (convex-hull area of the
  outfield players, plus the team's width and depth).
- Player stats: distance covered and speeds per track.
- Heatmaps: share of time spent in each cell of a grid over the pitch.

All inputs are the tracks table after ``project_tracks`` and ``add_team_column``
(ideally smoothed with ``trajectories.smooth_positions``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial import ConvexHull, QhullError

from src import config
from src.homography import PitchDimensions

TEAMS = (config.TEAM_A, config.TEAM_B)


def team_shape(tracks: pd.DataFrame) -> pd.DataFrame:
    """Per frame and team: outfield player count, hull area (m^2), width, depth, centroid.

    Width spans the touchlines (y), depth runs goal to goal (x). A smaller
    area means a more compact team, typical when defending.
    """
    outfield = tracks[
        (tracks["role"] == "player") & tracks["team"].isin(TEAMS) & tracks["pitch_x"].notna()
    ]
    rows = []
    for (frame_idx, team), group in outfield.groupby(["frame_idx", "team"]):
        points = group[["pitch_x", "pitch_y"]].to_numpy()
        area = np.nan
        if len(points) >= 3:
            try:
                area = ConvexHull(points).volume  # in 2D, "volume" is the area
            except QhullError:  # all points on one line
                area = 0.0
        rows.append({
            "frame_idx": frame_idx,
            "timestamp": group["timestamp"].iat[0],
            "team": int(team),
            "n_players": len(points),
            "area": area,
            "width": np.ptp(points[:, 1]),
            "depth": np.ptp(points[:, 0]),
            "centroid_x": points[:, 0].mean(),
            "centroid_y": points[:, 1].mean(),
        })
    return pd.DataFrame(rows)


def player_stats(
    tracks: pd.DataFrame, max_speed: float = config.MAX_PLAYER_SPEED
) -> pd.DataFrame:
    """Distance and speed per person track (players, goalkeepers, referees).

    Steps across gaps (the track was lost for a while) or faster than
    ``max_speed`` m/s (an ID jump, not real running) are not counted.
    """
    people = tracks[(tracks["role"] != "ball") & tracks["pitch_x"].notna()]
    people = people.sort_values(["tracker_id", "frame_idx"])
    timestamps = np.sort(tracks["timestamp"].unique())
    frame_interval = float(np.median(np.diff(timestamps))) if len(timestamps) > 1 else 1.0

    by_track = people.groupby("tracker_id")
    dt = by_track["timestamp"].diff()
    step = np.hypot(by_track["pitch_x"].diff(), by_track["pitch_y"].diff())
    speed = step / dt
    valid = dt.notna() & (dt <= 3 * frame_interval) & (speed <= max_speed)
    people = people.assign(step=step.where(valid, 0.0), speed=speed.where(valid))

    stats = people.groupby("tracker_id").agg(
        team=("team", "first"),
        role=("role", "first"),
        frames=("frame_idx", "nunique"),
        distance_m=("step", "sum"),
        max_speed=("speed", "max"),
        mean_x=("pitch_x", "mean"),
        mean_y=("pitch_y", "mean"),
    )
    stats["seconds_visible"] = stats["frames"] * frame_interval
    stats["avg_speed_kmh"] = stats["distance_m"] / stats["seconds_visible"] * 3.6
    stats["max_speed_kmh"] = stats["max_speed"] * 3.6
    return stats.drop(columns="max_speed").reset_index()


def heatmap(
    x: np.ndarray,
    y: np.ndarray,
    bins: tuple[int, int] = config.HEATMAP_BINS,
    pitch: PitchDimensions | None = None,
) -> list[list[float]]:
    """Share of positions in each pitch cell, as rows (y, bottom->top) of columns (x).

    Values sum to 1 (or are all 0 when there are no positions).
    """
    pitch = pitch or PitchDimensions()
    mask = ~(np.isnan(x) | np.isnan(y))
    counts, _, _ = np.histogram2d(
        y[mask], x[mask],
        bins=(bins[1], bins[0]),
        range=[[0, pitch.width], [0, pitch.length]],
    )
    total = counts.sum()
    shares = counts / total if total > 0 else counts
    return np.round(shares, 4).tolist()
