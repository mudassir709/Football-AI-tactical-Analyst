"""Results export safety and trajectory post-processing."""
import json
import math

import pandas as pd

from src import config
from src.pipeline import _replace_non_finite, _write_json_atomic
from src.trajectories import interpolate_ball, smooth_positions


def test_non_finite_numbers_become_null(tmp_path):
    data = {"a": [1.0, math.nan, {"b": math.inf}], "c": "text", "d": 3}
    counter = [0]
    assert _replace_non_finite(data, counter) == {"a": [1.0, None, {"b": None}], "c": "text", "d": 3}
    assert counter == [2]

    target = tmp_path / "results.json"
    _write_json_atomic(data, target)  # must not raise, even though data contains NaN
    assert json.loads(target.read_text()) == {"a": [1.0, None, {"b": None}], "c": "text", "d": 3}


def ball_rows(frames: list[int], xs: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "frame_idx": frames, "timestamp": [f / 25 for f in frames], "tracker_id": -1,
        "class_id": config.BALL_ID, "class_name": "ball", "role": "ball", "team": config.NO_TEAM,
        "foot_x": xs, "foot_y": 0.0, "pitch_x": xs, "pitch_y": 0.0,
    })


def test_short_ball_gaps_are_interpolated():
    # Ball seen at frames 0 and 6 only; the other frames come from players.
    tracks = pd.concat([
        ball_rows([0, 6], [0.0, 6.0]),
        pd.DataFrame({"frame_idx": [2, 4], "timestamp": [0.08, 0.16], "tracker_id": 1,
                      "class_id": config.PLAYER_ID, "class_name": "player", "role": "player", "team": 0,
                      "foot_x": 0.0, "foot_y": 0.0, "pitch_x": 0.0, "pitch_y": 0.0}),
    ], ignore_index=True)
    filled = interpolate_ball(tracks)
    ball = filled[filled["role"] == "ball"].set_index("frame_idx")["pitch_x"]
    assert list(ball.index) == [0, 2, 4, 6]
    assert ball.loc[2] == 2.0 and ball.loc[4] == 4.0
    assert filled["interpolated"].sum() == 2


def test_smoothing_keeps_raw_positions_and_reduces_jitter():
    frames = list(range(0, 50, 2))
    jitter = [10.0 + (1 if i % 2 else -1) for i in range(len(frames))]
    tracks = pd.DataFrame({"frame_idx": frames, "timestamp": [f / 25 for f in frames], "tracker_id": 7,
                           "class_id": config.PLAYER_ID, "pitch_x": jitter, "pitch_y": 0.0})
    smoothed = smooth_positions(tracks)
    assert (smoothed["pitch_x_raw"] == jitter).all()
    assert smoothed["pitch_x"].diff().abs().mean() < 0.5  # raw jumps by 2 m every frame
