"""End-to-end analysis of one match video.

``run_analysis`` chains every stage of the pipeline, reports progress through a
callback (the queue worker forwards it to the user's browser), writes the full
results JSON consumed by the dashboard, and returns a small summary that the
API stores in the database.

Stages and their share of the progress bar:
    Detecting and tracking players    0-60 %   (YOLOv8 + ByteTrack)
    Mapping positions to the pitch   60-88 %   (pitch keypoints + homography)
    Assigning teams                  88-93 %   (jersey colour clustering)
    Analysing tactics                93-98 %   (smoothing, formations, metrics)
    Saving results                   98-100 %
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable, Iterable, Iterator
from functools import cache
from pathlib import Path
from typing import Any, TypeVar

import numpy as np
import pandas as pd

from src import config
from src.clustering import (
    TeamAssignment,
    add_team_column,
    assign_teams,
    detect_formations,
    extract_jersey_features,
    track_roles,
)
from src.detector import FootballDetector
from src.homography import (
    PitchDimensions,
    PitchKeypointDetector,
    homographies_to_dataframe,
    iter_homographies,
    project_tracks,
)
from src.metrics import heatmap, player_stats, team_shape
from src.tracker import frame_tracks_to_dataframe, iter_tracks
from src.trajectories import interpolate_ball, smooth_positions
from src.video import get_video_info

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]
T = TypeVar("T")

RESULTS_VERSION = 1
ROLE_CODES = {"player": 0, "goalkeeper": 1, "referee": 2}


@cache
def _player_detector() -> FootballDetector:
    """Load the detection model once per worker process, not once per job."""
    return FootballDetector()


@cache
def _pitch_detector() -> PitchKeypointDetector:
    return PitchKeypointDetector()


class _Progress:
    """Forward progress to a callback, skipping updates smaller than 1 %."""

    def __init__(self, callback: ProgressCallback | None) -> None:
        self._callback = callback
        self._last: tuple[int, str] | None = None

    def __call__(self, percent: float, stage: str) -> None:
        key = (int(percent), stage)
        if self._callback and key != self._last:
            self._last = key
            self._callback(min(percent, 100.0), stage)

    def iterate(self, items: Iterable[T], total: int, start: float, end: float, stage: str) -> Iterator[T]:
        """Yield ``items`` while moving progress from ``start`` to ``end``."""
        self(start, stage)
        for i, item in enumerate(items, start=1):
            yield item
            self(start + (end - start) * min(i / max(total, 1), 1.0), stage)


def run_analysis(
    video_path: str | Path,
    output_path: str | Path,
    progress: ProgressCallback | None = None,
    stride: int = config.PIPELINE_STRIDE,
) -> dict[str, Any]:
    """Analyse a match video and write the dashboard results JSON.

    Args:
        video_path: Input video.
        output_path: Where to write the results JSON.
        progress: Called with ``(percent, stage)`` as work advances.
        stride: Process every ``stride``-th frame.

    Returns:
        A JSON-serialisable summary of headline numbers.
    """
    started = time.perf_counter()
    report = _Progress(progress)
    video_path, output_path = Path(video_path), Path(output_path)
    info = get_video_info(video_path)
    expected_frames = math.ceil(info.total_frames / stride)

    # 1. Detection + tracking
    frames = iter_tracks(video_path, _player_detector(), stride=stride)
    tracks = frame_tracks_to_dataframe(
        report.iterate(frames, expected_frames, 0, 60, "Detecting and tracking players")
    )
    if tracks.empty:
        raise RuntimeError("No players were detected in this video")

    # 2. Pitch coordinates
    homography_frames = iter_homographies(video_path, _pitch_detector(), stride=stride)
    homographies = homographies_to_dataframe(
        report.iterate(homography_frames, expected_frames, 60, 88, "Mapping positions to the pitch")
    )
    tracks = project_tracks(tracks, homographies)

    # 3. Teams
    report(88, "Assigning teams")
    assignment: TeamAssignment | None
    try:
        assignment = assign_teams(tracks, extract_jersey_features(video_path, tracks))
        tracks = add_team_column(tracks, assignment)
    except ValueError as exc:  # e.g. too few players visible to tell teams apart
        logger.warning("Team assignment skipped: %s", exc)
        assignment = None
        roles = tracks["tracker_id"].map(track_roles(tracks))
        is_ball = tracks["class_id"] == config.BALL_ID
        tracks = tracks.assign(team=config.NO_TEAM, role=roles.where(~is_ball, "ball"))

    # 4. Tactics
    report(93, "Analysing tactics")
    tracks = interpolate_ball(smooth_positions(tracks))
    formations = detect_formations(tracks) if assignment else None
    shape = team_shape(tracks)
    stats = player_stats(tracks)

    # 5. Export
    report(98, "Saving results")
    results = _build_results(info, stride, tracks, homographies, assignment, formations, shape, stats)
    _write_json_atomic(results, output_path)
    summary = _build_summary(info, tracks, assignment, formations, shape, stats, time.perf_counter() - started)
    report(100, "Done")
    return summary


# ---------------------------------------------------------------------------
# Results JSON
# ---------------------------------------------------------------------------


def _num(value: Any, digits: int = 2) -> float | None:
    """Round a number for JSON, mapping NaN/None to null."""
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return None
    return round(float(value), digits)


def _build_frames(tracks: pd.DataFrame) -> list[dict[str, Any]]:
    """One entry per processed frame with every person and the ball.

    Person rows are compact arrays (see ``legend`` in the results file):
    ``[id, team, role, x1, y1, x2, y2, pitch_x, pitch_y]``.
    """
    frames = []
    for frame_idx, group in tracks.groupby("frame_idx", sort=True):
        people, ball = [], None
        for row in group.itertuples():
            if row.role == "ball":
                ball = [_num(row.foot_x, 1), _num(row.foot_y, 1), _num(row.pitch_x), _num(row.pitch_y)]
                continue
            people.append([
                int(row.tracker_id), int(row.team), ROLE_CODES.get(row.role, 0),
                _num(row.x1, 0), _num(row.y1, 0), _num(row.x2, 0), _num(row.y2, 0),
                _num(row.pitch_x), _num(row.pitch_y),
            ])
        frames.append({"f": int(frame_idx), "t": _num(group["timestamp"].iat[0], 3), "p": people, "b": ball})
    return frames


def _build_results(
    info, stride: int, tracks: pd.DataFrame, homographies: pd.DataFrame,
    assignment: TeamAssignment | None, formations, shape: pd.DataFrame, stats: pd.DataFrame,
) -> dict[str, Any]:
    pitch = PitchDimensions()
    teams = []
    if assignment:
        sides = formations.windows.groupby("team")["defends"].first().to_dict() if formations and not formations.windows.empty else {}
        teams = [
            {"id": t, "colour": assignment.team_colour_hex(t), "defends": sides.get(t)}
            for t in (config.TEAM_A, config.TEAM_B)
        ]

    people = tracks[tracks["role"] != "ball"]
    players = [
        {
            "id": int(s.tracker_id), "team": int(s.team), "role": s.role,
            "secondsVisible": _num(s.seconds_visible, 1),
            "distanceM": _num(s.distance_m, 1),
            "avgSpeedKmh": _num(s.avg_speed_kmh, 1),
            "maxSpeedKmh": _num(s.max_speed_kmh, 1),
            "heatmap": heatmap(*_xy(people[people["tracker_id"] == s.tracker_id])),
        }
        for s in stats.itertuples()
    ]

    team_heatmaps = {
        str(t): heatmap(*_xy(people[(people["team"] == t) & (people["role"] == "player")]))
        for t in (config.TEAM_A, config.TEAM_B)
    }
    team_heatmaps["ball"] = heatmap(*_xy(tracks[tracks["role"] == "ball"]))

    formation_windows, formation_changes = [], []
    if formations and not formations.windows.empty:
        formation_windows = [
            {
                "team": int(w.team), "start": _num(w.start), "end": _num(w.end),
                "formation": w.formation, "bestMatch": w.best_match, "runnerUp": w.runner_up,
                "cost": _num(w.cost, 4), "confidenceMargin": _num(w.confidence_margin, 4),
                "players": int(w.n_players),
            }
            for w in formations.windows.itertuples()
        ]
        formation_changes = [
            {"team": int(c["team"]), "time": _num(c["time"]), "from": c["from"], "to": c["to"]}
            for c in formations.changes.to_dict("records")
        ]

    return {
        "version": RESULTS_VERSION,
        "video": {
            "fps": info.fps, "width": info.width, "height": info.height,
            "totalFrames": info.total_frames, "durationSeconds": _num(info.total_frames / info.fps),
            "stride": stride,
        },
        "pitch": {"length": pitch.length, "width": pitch.width},
        "legend": {
            "person": ["id", "team", "role", "x1", "y1", "x2", "y2", "pitchX", "pitchY"],
            "ball": ["x", "y", "pitchX", "pitchY"],
            "roles": {str(code): name for name, code in ROLE_CODES.items()},
            "team": "-1 = no team (referee or unassigned)",
            "heatmap": "rows = y cells from y=0 upwards, columns = x cells from x=0",
        },
        "teams": teams,
        "frames": _build_frames(tracks),
        "players": players,
        "teamShape": [
            {
                "t": _num(r.timestamp, 3), "team": int(r.team), "n": int(r.n_players),
                "area": _num(r.area, 1), "width": _num(r.width, 1), "depth": _num(r.depth, 1),
                "cx": _num(r.centroid_x), "cy": _num(r.centroid_y),
            }
            for r in shape.itertuples()
        ],
        "heatmaps": team_heatmaps,
        "heatmapBins": {"x": config.HEATMAP_BINS[0], "y": config.HEATMAP_BINS[1]},
        "formations": {"windows": formation_windows, "changes": formation_changes},
        "homography": {
            "validShare": _num(homographies["valid"].mean(), 3),
            "meanReprojectionErrorM": _num(homographies["reprojection_error"].mean(), 3),
        },
    }


def _xy(rows: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    return rows["pitch_x"].to_numpy(dtype=float), rows["pitch_y"].to_numpy(dtype=float)


def _write_json_atomic(data: dict[str, Any], path: Path) -> None:
    """Write to a temporary file first, so readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Summary (stored in the database)
# ---------------------------------------------------------------------------


def _build_summary(
    info, tracks: pd.DataFrame, assignment: TeamAssignment | None, formations,
    shape: pd.DataFrame, stats: pd.DataFrame, processing_seconds: float,
) -> dict[str, Any]:
    n_frames = tracks["frame_idx"].nunique()
    detected_ball = tracks[(tracks["role"] == "ball") & ~tracks["interpolated"]]["frame_idx"].nunique()

    teams = []
    if assignment:
        for t in (config.TEAM_A, config.TEAM_B):
            team_shape_rows = shape[shape["team"] == t] if not shape.empty else shape
            team_stats = stats[(stats["team"] == t) & (stats["role"] == "player")]
            formation = None
            if formations and not formations.windows.empty:
                labels = formations.windows.loc[formations.windows["team"] == t, "formation"].dropna()
                formation = labels.mode().iat[0] if not labels.empty else None
            teams.append({
                "id": t,
                "colour": assignment.team_colour_hex(t),
                "formation": formation,
                "playersVisible": int(team_shape_rows["n_players"].median()) if not team_shape_rows.empty else 0,
                "avgCompactnessM2": _num(team_shape_rows["area"].mean(), 0) if not team_shape_rows.empty else None,
                "avgWidthM": _num(team_shape_rows["width"].mean(), 1) if not team_shape_rows.empty else None,
                "avgDepthM": _num(team_shape_rows["depth"].mean(), 1) if not team_shape_rows.empty else None,
                "distanceKm": _num(team_stats["distance_m"].sum() / 1000, 2),
            })

    return {
        "durationSeconds": _num(info.total_frames / info.fps, 1),
        "framesAnalysed": int(n_frames),
        "processingSeconds": _num(processing_seconds, 1),
        "ballDetectionRate": _num(detected_ball / max(n_frames, 1), 3),
        "teams": teams,
        "formationChanges": int(len(formations.changes)) if formations else 0,
    }
