"""Player distance and speed measurements."""

import numpy as np
import pandas as pd

from src.metrics import player_stats


def running_player(jump_at: int | None = None, jump_m: float = 0.0) -> pd.DataFrame:
    """A player running in a straight line at 7 m/s (25.2 km/h) for 3 seconds.

    Every 2nd frame of a 25 fps video is analysed, like in Standard mode, so
    the player moves 0.56 m between rows. Optionally, the measured position
    jumps forward by ``jump_m`` metres at row ``jump_at`` and stays shifted,
    like when the camera model switches to a slightly different one.
    """
    frames = np.arange(0, 75, 2)
    x = 10 + 7.0 * frames / 25
    if jump_at is not None:
        x[jump_at:] += jump_m
    return pd.DataFrame({
        "frame_idx": frames, "timestamp": frames / 25, "tracker_id": 5,
        "role": "player", "team": 0, "pitch_x": x, "pitch_y": 30.0,
    })


def test_steady_run_gives_the_true_speed():
    stats = player_stats(running_player()).iloc[0]
    assert abs(stats["max_speed_kmh"] - 25.2) < 0.1
    assert abs(stats["distance_m"] - 7.0 * 74 / 25) < 0.01  # frames 0 to 74


def test_one_position_jump_does_not_create_a_fake_sprint():
    # Regression test: a 0.35 m jump in one step used to be reported as the
    # top speed (0.91 m in 0.08 s = 41 km/h). Averaged over a second it only
    # adds a little, so the top speed stays close to the real 25.2 km/h.
    stats = player_stats(running_player(jump_at=15, jump_m=0.35)).iloc[0]
    assert stats["max_speed_kmh"] < 27.0


def test_tracks_shorter_than_a_second_have_no_top_speed():
    short = running_player().head(8)  # about 0.6 s
    assert np.isnan(player_stats(short).iloc[0]["max_speed_kmh"])
