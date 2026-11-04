"""Clean-up steps that use pitch positions to fix tracking mistakes.

They run once every detection has a position on the pitch (in metres):
    remove_off_pitch_people  substitutes, coaches and staff on the sidelines
    select_ball              the real ball among spare balls and the penalty spot
    stitch_tracks            join the pieces of one player's track and renumber
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from src import config
from src.clustering import track_roles
from src.homography import PitchDimensions


def distance_outside_pitch(x: pd.Series, y: pd.Series, pitch: PitchDimensions | None = None) -> pd.Series:
    """How far each point is outside the pitch lines, in metres (0 = on the pitch).

    Unknown positions stay NaN.
    """
    pitch = pitch or PitchDimensions()
    beyond = np.maximum.reduce([-x, x - pitch.length, -y, y - pitch.width, np.zeros(len(x))])
    return pd.Series(beyond, index=x.index).where(x.notna() & y.notna())


def remove_off_pitch_people(
    tracks: pd.DataFrame, margin: float = config.OFF_PITCH_MARGIN_M, pitch: PitchDimensions | None = None,
) -> pd.DataFrame:
    """Remove people who stay outside the pitch (substitutes, coaches, staff).

    We look at each tracked person's usual (median) position over their whole
    time on screen, not frame by frame, so a player who steps off the pitch
    for a throw-in is kept. Referees are kept too: the assistant referees run
    along the touchlines.
    """
    is_person = tracks["class_id"] != config.BALL_ID
    people = tracks[is_person]
    outside = distance_outside_pitch(people["pitch_x"], people["pitch_y"], pitch)
    usual = outside.groupby(people["tracker_id"]).median()
    roles = track_roles(people)
    off_pitch = usual.index[(usual > margin) & (roles.reindex(usual.index) != "referee")]
    return tracks[~(is_person & tracks["tracker_id"].isin(off_pitch))].reset_index(drop=True)


def select_ball(tracks: pd.DataFrame, pitch: PitchDimensions | None = None) -> pd.DataFrame:
    """Keep at most one ball per frame: the one that continues the ball's path.

    The detector can report several "balls" in a frame: the match ball, spare
    balls by the touchline and the white penalty spot. We go through the
    frames in order and:
      1. ignore candidates outside the pitch;
      2. while we know where the ball was a moment ago, take the candidate
         closest to that spot, as long as the ball could have got there
         (it cannot fly faster than about 40 m/s);
      3. after the ball has been lost for a while, start again from the most
         confident candidate, but not one lying on a penalty spot.
    """
    pitch = pitch or PitchDimensions()
    is_ball = tracks["class_id"] == config.BALL_ID
    balls = tracks[is_ball].sort_values(["frame_idx", "confidence"], ascending=[True, False])
    outside = distance_outside_pitch(balls["pitch_x"], balls["pitch_y"], pitch)
    balls = balls[~(outside > config.BALL_OFF_PITCH_MARGIN_M)]  # unknown positions are kept

    spots = np.array([
        [pitch.penalty_spot_distance, pitch.width / 2],
        [pitch.length - pitch.penalty_spot_distance, pitch.width / 2],
    ])
    keep: list[int] = []
    last_position, last_time = None, -np.inf
    for _, candidates in balls.groupby("frame_idx", sort=True):
        time = candidates["timestamp"].iat[0]
        positions = candidates[["pitch_x", "pitch_y"]].to_numpy()
        known = ~np.isnan(positions).any(axis=1)
        if not known.any():
            # No pitch position (no camera model): keep the most confident one.
            keep.append(candidates.index[0])
            continue
        candidates, positions = candidates[known], positions[known]

        if time - last_time <= config.BALL_LOST_SECONDS:
            # Follow the path: the nearest candidate the ball could have reached.
            distances = np.linalg.norm(positions - last_position, axis=1)
            reach = config.BALL_MAX_SPEED_MS * (time - last_time) + config.BALL_POSITION_TOLERANCE_M
            if distances.min() > reach:
                continue  # nothing plausible in this frame: the ball was missed
            best = int(np.argmin(distances))
        else:
            # Start again: the most confident candidate (they are sorted by
            # confidence) that is not lying on a penalty spot.
            to_spot = np.linalg.norm(positions[:, None, :] - spots[None, :, :], axis=2).min(axis=1)
            allowed = np.flatnonzero(to_spot > config.PENALTY_SPOT_RADIUS_M)
            if len(allowed) == 0:
                continue
            best = int(allowed[0])

        keep.append(candidates.index[best])
        last_position, last_time = positions[best], time

    return pd.concat([tracks[~is_ball], tracks.loc[keep]]).sort_values(
        ["frame_idx", "tracker_id"]).reset_index(drop=True)


def _track_ends(people: pd.DataFrame, rows: int = 5) -> pd.DataFrame:
    """Start and end of every track: time and position (median of a few rows,
    so one jittery detection doesn't decide where the track ended)."""
    ordered = people.sort_values(["tracker_id", "frame_idx"])
    grouped = ordered.groupby("tracker_id")
    first, last = grouped.head(rows).groupby("tracker_id"), grouped.tail(rows).groupby("tracker_id")
    return pd.DataFrame({
        "start": grouped["timestamp"].min(), "end": grouped["timestamp"].max(),
        "start_x": first["pitch_x"].median(), "start_y": first["pitch_y"].median(),
        "end_x": last["pitch_x"].median(), "end_y": last["pitch_y"].median(),
        "team": grouped["team"].first(), "role": grouped["role"].first(),
    })


def stitch_tracks(tracks: pd.DataFrame) -> pd.DataFrame:
    """Join broken pieces of the same player's track, then renumber everyone 1, 2, 3...

    The tracker gives a player a new ID whenever it loses them for a moment
    (hidden behind another player, a camera pan...). Here a track that ends
    is joined to a track that starts soon after (within 5 s), nearby (no
    further than a player could run in that time), with the same team and
    role. All endings are matched with all beginnings at once (Hungarian
    algorithm), so each piece is joined to at most one other piece.

    Players who leave the camera view for longer still come back with a new
    number: nothing in the video tells us who they are.
    """
    is_person = tracks["class_id"] != config.BALL_ID
    people = tracks[is_person & tracks["pitch_x"].notna()]
    ends = _track_ends(people)
    ids = ends.index.to_numpy()

    # Cost of joining the end of track i to the start of track j: the distance
    # between them. Impossible joins get a cost that is never chosen.
    gap = ends["start"].to_numpy()[None, :] - ends["end"].to_numpy()[:, None]
    distance = np.hypot(
        ends["start_x"].to_numpy()[None, :] - ends["end_x"].to_numpy()[:, None],
        ends["start_y"].to_numpy()[None, :] - ends["end_y"].to_numpy()[:, None],
    )
    possible = (
        (gap > 0) & (gap <= config.STITCH_MAX_GAP_SECONDS)
        & (distance <= config.STITCH_MAX_SPEED_MS * gap + config.STITCH_POSITION_TOLERANCE_M)
        & (ends["team"].to_numpy()[None, :] == ends["team"].to_numpy()[:, None])
        & (ends["role"].to_numpy()[None, :] == ends["role"].to_numpy()[:, None])
    )
    impossible = 1e6
    cost = np.where(possible, distance, impossible)
    rows, cols = linear_sum_assignment(cost)

    # Follow the joins: each track points to the track it continues.
    continues = {ids[c]: ids[r] for r, c in zip(rows, cols) if cost[r, c] < impossible}

    def first_piece(track_id: int) -> int:
        while track_id in continues:
            track_id = continues[track_id]
        return track_id

    joined = {track_id: first_piece(track_id) for track_id in tracks.loc[is_person, "tracker_id"].unique()}
    # New, small numbers in order of first appearance: 1, 2, 3...
    first_seen = tracks[is_person].assign(player=lambda t: t["tracker_id"].map(joined)).groupby("player")["frame_idx"].min()
    new_number = {player: number for number, player in enumerate(first_seen.sort_values().index, start=1)}

    out = tracks.copy()
    out.loc[is_person, "tracker_id"] = out.loc[is_person, "tracker_id"].map(joined).map(new_number)
    out["tracker_id"] = out["tracker_id"].astype(int)
    return out
