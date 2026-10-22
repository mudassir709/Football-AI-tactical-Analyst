"""Clustering stages of the pipeline: team assignment from jersey colour.

Team assignment works per *track*, not per detection: each track's shirt colour
is the median over several sampled crops, which smooths out occlusions, motion
blur and lighting changes, and K-Means then splits those colours into two teams.
Goalkeepers wear a distinct kit, so they are assigned by pitch proximity instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import supervision as sv
from sklearn.cluster import KMeans

from src import config

JERSEY_FEATURE_COLUMNS: list[str] = ["L", "a", "b"]  # OpenCV 8-bit Lab


def jersey_colour(crop: np.ndarray) -> np.ndarray | None:
    """Median Lab colour of the shirt in a BGR player crop, ignoring grass.

    Returns ``None`` if too few shirt pixels are visible.
    """
    height, width = crop.shape[:2]
    y0, y1 = (int(f * height) for f in config.TORSO_Y_RANGE)
    x0, x1 = (int(f * width) for f in config.TORSO_X_RANGE)
    torso = crop[y0:y1, x0:x1]
    if torso.size == 0:
        return None

    hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
    grass = cv2.inRange(hsv, config.GRASS_HSV_LOWER, config.GRASS_HSV_UPPER).astype(bool)
    pixels = cv2.cvtColor(torso, cv2.COLOR_BGR2LAB)[~grass]
    if len(pixels) < config.MIN_JERSEY_PIXELS:
        return None
    return np.median(pixels, axis=0)


def track_majority_class(tracks: pd.DataFrame) -> pd.Series:
    """Most frequent class name per tracker ID (labels can flicker between frames)."""
    people = tracks[tracks["class_id"] != config.BALL_ID]
    return people.groupby("tracker_id")["class_name"].agg(lambda s: s.mode().iat[0])


def _sample_rows(tracks: pd.DataFrame, samples_per_track: int) -> pd.DataFrame:
    """Pick up to ``samples_per_track`` detections per track, evenly spaced in time."""
    def take(group: pd.DataFrame) -> pd.DataFrame:
        idx = np.linspace(0, len(group) - 1, min(samples_per_track, len(group))).round()
        return group.iloc[np.unique(idx.astype(int))]

    ordered = tracks.sort_values(["tracker_id", "frame_idx"])
    return ordered.groupby("tracker_id", group_keys=False)[ordered.columns].apply(take)


def extract_jersey_features(
    video_path: str | Path,
    tracks: pd.DataFrame,
    samples_per_track: int = config.JERSEY_SAMPLES_PER_TRACK,
) -> pd.DataFrame:
    """Sample shirt colours for every player and goalkeeper track.

    The video is decoded once, sequentially (cheap compared with inference);
    only frames that contain a sampled detection are cropped.

    Returns:
        One row per usable crop: ``frame_idx``, ``tracker_id`` and Lab colour.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    majority = track_majority_class(tracks)
    outfield_ids = majority.index[majority.isin(["player", "goalkeeper"])]
    candidates = tracks[tracks["tracker_id"].isin(outfield_ids)]
    if candidates.empty:
        return pd.DataFrame(columns=["frame_idx", "tracker_id", *JERSEY_FEATURE_COLUMNS])

    samples = _sample_rows(candidates, samples_per_track)
    by_frame = {idx: group for idx, group in samples.groupby("frame_idx")}
    last_frame = max(by_frame)

    rows = []
    frames = sv.get_video_frames_generator(str(video_path), end=last_frame + 1)
    for frame_idx, frame in enumerate(frames):
        group = by_frame.get(frame_idx)
        if group is None:
            continue
        frame_h, frame_w = frame.shape[:2]
        for det in group.itertuples():
            x1, y1 = max(int(det.x1), 0), max(int(det.y1), 0)
            x2, y2 = min(int(det.x2), frame_w), min(int(det.y2), frame_h)
            colour = jersey_colour(frame[y1:y2, x1:x2])
            if colour is not None:
                rows.append((frame_idx, det.tracker_id, *colour))
    return pd.DataFrame(rows, columns=["frame_idx", "tracker_id", *JERSEY_FEATURE_COLUMNS])


@dataclass
class TeamAssignment:
    """Result of team clustering for one clip."""

    track_teams: dict[int, int]  # tracker_id -> TEAM_A / TEAM_B
    team_colours_bgr: np.ndarray  # (2, 3) uint8 shirt colour of each team
    agreement: pd.Series  # per player track: share of crops voting for its team

    def team_colour_hex(self, team: int) -> str:
        """Shirt colour of ``team`` as ``#RRGGBB`` for plotting."""
        b, g, r = self.team_colours_bgr[team]
        return f"#{r:02X}{g:02X}{b:02X}"


def _lab_to_bgr(lab: np.ndarray) -> np.ndarray:
    """Convert one 8-bit Lab colour to BGR."""
    pixel = np.clip(lab, 0, 255).astype(np.uint8).reshape(1, 1, 3)
    return cv2.cvtColor(pixel, cv2.COLOR_LAB2BGR).reshape(3)


def _assign_goalkeepers(
    tracks: pd.DataFrame,
    track_teams: dict[int, int],
    goalkeeper_ids: list[int],
    position_columns: tuple[str, str],
) -> dict[int, int]:
    """Assign each goalkeeper to the team whose centroid is closest on average."""
    columns = list(position_columns)
    team = tracks["tracker_id"].map(track_teams)
    # Per-frame centroid of each team, indexed by frame_idx.
    centroids = {
        t: tracks[team == t].dropna(subset=columns).groupby("frame_idx")[columns].mean()
        for t in (config.TEAM_A, config.TEAM_B)
    }
    result = {}
    for gk_id in goalkeeper_ids:
        gk = tracks[tracks["tracker_id"] == gk_id].dropna(subset=columns).set_index("frame_idx")[columns]
        distances = []
        for t in (config.TEAM_A, config.TEAM_B):
            common = gk.index.intersection(centroids[t].index)
            offset = gk.loc[common].to_numpy() - centroids[t].loc[common].to_numpy()
            distances.append(np.linalg.norm(offset, axis=1).mean() if len(common) else np.inf)
        if np.isfinite(distances).any():
            result[gk_id] = int(np.argmin(distances))
    return result


def assign_teams(
    tracks: pd.DataFrame,
    jersey_features: pd.DataFrame,
    random_state: int = 0,
) -> TeamAssignment:
    """Cluster player tracks into two teams by shirt colour, then place goalkeepers.

    Args:
        tracks: Tracks table; ``pitch_x``/``pitch_y`` are used for goalkeepers
            when present, otherwise image foot points.
        jersey_features: Output of ``extract_jersey_features``.
        random_state: K-Means seed, for reproducible results.
    """
    majority = track_majority_class(tracks)
    player_ids = majority.index[majority == "player"]
    goalkeeper_ids = list(majority.index[majority == "goalkeeper"])

    player_features = jersey_features[jersey_features["tracker_id"].isin(player_ids)]
    track_colours = player_features.groupby("tracker_id")[JERSEY_FEATURE_COLUMNS].median()
    if len(track_colours) < 2:
        raise ValueError(f"Need at least 2 player tracks with jersey colours, got {len(track_colours)}")

    kmeans = KMeans(n_clusters=2, n_init=10, random_state=random_state)
    labels = kmeans.fit_predict(track_colours.to_numpy())

    # K-Means numbering is arbitrary; make it deterministic: lighter shirt = TEAM_A.
    order = np.argsort(-kmeans.cluster_centers_[:, 0])
    relabel = np.empty(2, dtype=int)
    relabel[order] = [config.TEAM_A, config.TEAM_B]
    track_teams = dict(zip(track_colours.index.astype(int), relabel[labels].tolist()))

    # Per-crop votes measure how consistently each track looks like its team.
    crop_teams = relabel[kmeans.predict(player_features[JERSEY_FEATURE_COLUMNS].to_numpy())]
    agreement = (
        pd.Series(crop_teams == player_features["tracker_id"].map(track_teams).to_numpy())
        .groupby(player_features["tracker_id"].to_numpy())
        .mean()
    )

    has_pitch = {"pitch_x", "pitch_y"} <= set(tracks.columns) and tracks["pitch_x"].notna().any()
    position_columns = ("pitch_x", "pitch_y") if has_pitch else ("foot_x", "foot_y")
    track_teams.update(_assign_goalkeepers(tracks, track_teams, goalkeeper_ids, position_columns))

    team_colours = np.stack([_lab_to_bgr(kmeans.cluster_centers_[i]) for i in order])
    return TeamAssignment(track_teams, team_colours, agreement)


def add_team_column(tracks: pd.DataFrame, assignment: TeamAssignment) -> pd.DataFrame:
    """Add a ``team`` column (``NO_TEAM`` for referees, the ball and unassigned tracks)."""
    team = tracks["tracker_id"].map(assignment.track_teams).fillna(config.NO_TEAM).astype(int)
    team[tracks["class_id"] == config.BALL_ID] = config.NO_TEAM
    return tracks.assign(team=team)
