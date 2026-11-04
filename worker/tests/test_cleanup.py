"""Clean-up steps: sideline people, choosing the real ball, joining broken tracks."""

import numpy as np
import pandas as pd

from src import config
from src.cleanup import remove_off_pitch_people, select_ball, stitch_tracks


def person(track: int, frames, x, y, name: str = "player", team: int = 0) -> pd.DataFrame:
    """Rows for one tracked person at the given pitch positions (25 fps)."""
    frames = np.asarray(frames)
    return pd.DataFrame({
        "frame_idx": frames, "timestamp": frames / 25, "tracker_id": track,
        "class_id": config.PLAYER_ID if name == "player" else config.REFEREE_ID,
        "class_name": name, "confidence": 0.9,
        "pitch_x": np.broadcast_to(x, frames.shape).astype(float),
        "pitch_y": np.broadcast_to(y, frames.shape).astype(float),
        "team": team, "role": name,
    })


def ball(frame: int, x: float, y: float, confidence: float) -> dict:
    return {"frame_idx": frame, "timestamp": frame / 25, "tracker_id": -1, "class_id": config.BALL_ID,
            "class_name": "ball", "confidence": confidence, "pitch_x": x, "pitch_y": y}


def test_people_standing_off_the_pitch_are_removed_but_not_a_throw_in():
    frames = range(0, 50, 2)
    coach = person(1, frames, 50, -3.0)  # always 3 m behind the touchline
    winger = person(2, frames, 50, np.r_[np.full(20, 2.0), np.full(5, -0.8)])  # steps out briefly
    assistant = person(3, frames, 30, -1.5, name="referee")  # runs the line: kept
    kept = remove_off_pitch_people(pd.concat([coach, winger, assistant]))
    assert set(kept["tracker_id"]) == {2, 3}


def test_spare_ball_off_the_pitch_is_ignored_and_the_ball_path_is_followed():
    rows = []
    for i, frame in enumerate(range(0, 20, 2)):
        rows.append(ball(frame, 50 + 0.5 * i, 30, 0.4))  # the real ball, rolling
        rows.append(ball(frame, 40, -4, 0.9))  # a sharp spare ball by the touchline
        rows.append(ball(frame, 80, 50, 0.3 if i else 0.2))  # something far away on the pitch
    chosen = select_ball(pd.DataFrame(rows))
    assert len(chosen) == 10  # one ball per frame
    assert np.allclose(chosen["pitch_y"], 30)  # always the rolling ball


def test_penalty_spot_is_not_taken_as_the_ball():
    spot = ball(0, 94, 34, 0.8)  # right penalty spot
    real = ball(0, 60, 20, 0.3)
    chosen = select_ball(pd.DataFrame([spot, real]))
    assert chosen["pitch_x"].tolist() == [60]


def test_two_pieces_of_one_player_are_joined_and_renumbered():
    first = person(40, range(0, 50, 2), np.linspace(20, 25, 25), 30)  # ends at x=25, t=1.92 s
    second = person(97, range(100, 150, 2), np.linspace(27, 30, 25), 30)  # 2 s later, 2 m on
    stranger = person(98, range(100, 150, 2), 80, 10)  # starts far away: a different player
    out = stitch_tracks(pd.concat([first, second, stranger], ignore_index=True))
    ids = out.groupby("tracker_id")["frame_idx"].agg(["min", "max"])
    assert sorted(out["tracker_id"].unique()) == [1, 2]  # small numbers from 1
    assert ids.loc[1, "min"] == 0 and ids.loc[1, "max"] == 148  # pieces joined
