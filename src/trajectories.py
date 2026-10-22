"""Post-processing of pitch trajectories: smoothing and ball gap filling."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import config


def _frame_interval(tracks: pd.DataFrame) -> float:
    """Typical time between processed frames, in seconds."""
    timestamps = np.sort(tracks["timestamp"].unique())
    if len(timestamps) < 2:
        return 1.0
    return float(np.median(np.diff(timestamps)))


def smooth_positions(
    tracks: pd.DataFrame, window_seconds: float = config.SMOOTHING_WINDOW_SECONDS
) -> pd.DataFrame:
    """Smooth each person's ``pitch_x``/``pitch_y`` with a centred rolling mean.

    Raw values are kept in ``pitch_x_raw``/``pitch_y_raw``. Ball rows are left
    untouched: the ball changes direction abruptly and must not be averaged.
    """
    if "pitch_x" not in tracks.columns:
        raise ValueError("Tracks have no pitch coordinates; run project_tracks first")
    window = max(1, round(window_seconds / _frame_interval(tracks)))

    out = tracks.sort_values(["tracker_id", "frame_idx"]).copy()
    out["pitch_x_raw"] = out["pitch_x"]
    out["pitch_y_raw"] = out["pitch_y"]
    people = out["class_id"] != config.BALL_ID
    for column in ("pitch_x", "pitch_y"):
        out.loc[people, column] = (
            out.loc[people]
            .groupby("tracker_id")[column]
            .transform(lambda s: s.rolling(window, center=True, min_periods=1).mean())
        )
    return out.sort_values(["frame_idx", "tracker_id"]).reset_index(drop=True)


def interpolate_ball(
    tracks: pd.DataFrame, max_gap_seconds: float = config.BALL_MAX_GAP_SECONDS
) -> pd.DataFrame:
    """Fill short gaps in the ball trajectory by linear interpolation.

    New rows are added for frames where the ball was missed; an ``interpolated``
    column marks them. Gaps longer than ``max_gap_seconds`` stay empty, since the
    ball may have left the camera view.
    """
    out = tracks.assign(interpolated=False)
    ball = out[out["class_id"] == config.BALL_ID].drop_duplicates("frame_idx").set_index("frame_idx")
    if len(ball) < 2:
        return out

    frame_times = out.groupby("frame_idx")["timestamp"].first()
    max_gap = max(1, round(max_gap_seconds / _frame_interval(tracks)))
    position_columns = [c for c in ("foot_x", "foot_y", "pitch_x", "pitch_y") if c in out.columns]

    filled = ball.reindex(frame_times.index)
    filled[position_columns] = filled[position_columns].interpolate(
        limit=max_gap, limit_area="inside"
    )
    new = filled[filled["class_id"].isna() & filled["pitch_x"].notna()].copy()
    if new.empty:
        return out

    new["timestamp"] = frame_times.loc[new.index]
    new["tracker_id"] = ball["tracker_id"].iat[0]
    new["class_id"] = config.BALL_ID
    new["class_name"] = "ball"
    new["interpolated"] = True
    if "team" in out.columns:
        new["team"] = config.NO_TEAM
    if "role" in out.columns:
        new["role"] = "ball"
    new = new.reset_index().astype({c: out[c].dtype for c in ("frame_idx", "tracker_id", "class_id")})
    return (
        pd.concat([out, new[out.columns]], ignore_index=True)
        .sort_values(["frame_idx", "tracker_id"])
        .reset_index(drop=True)
    )
