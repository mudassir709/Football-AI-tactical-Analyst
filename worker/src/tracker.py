"""Multi-object tracking over a match video.

People (players, goalkeepers, referees) are tracked with ByteTrack so each keeps
a stable ID. The ball is not given to ByteTrack: there is only one, it moves too
fast for IoU matching, and it is frequently missed. Instead we keep the few
most confident "ball" detections per frame; once their pitch positions are
known, cleanup.select_ball picks the real ball among them (spare balls and the
penalty spot also look like a ball), and gaps are interpolated later.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import supervision as sv
from tqdm import tqdm
from trackers import ByteTrackTracker

from src import config
from src.detector import FootballDetector
from src.video import get_video_info, iter_frame_batches

# The ball is not tracked by ByteTrack; its rows get this placeholder ID.
BALL_TRACK_ID: int = -1

TRACK_COLUMNS: list[str] = [
    "frame_idx", "timestamp", "tracker_id", "class_id", "class_name", "confidence",
    "x1", "y1", "x2", "y2", "foot_x", "foot_y",
]


@dataclass
class FrameTracks:
    """Tracking output for one processed video frame."""

    frame_idx: int
    timestamp: float  # seconds from the start of the video
    frame: np.ndarray  # BGR image, kept so callers can annotate it
    people: sv.Detections  # players, goalkeepers and referees, with tracker_id
    ball: sv.Detections  # ball candidates, most confident first (at most MAX_BALL_CANDIDATES)


class FootballTracker:
    """ByteTrack for people; the ball's candidates are passed through untracked."""

    def __init__(
        self,
        frame_rate: float,
        lost_track_buffer: int = config.LOST_TRACK_BUFFER,
        track_activation_threshold: float = config.TRACK_ACTIVATION_THRESHOLD,
        high_conf_det_threshold: float = config.HIGH_CONF_DET_THRESHOLD,
        minimum_consecutive_frames: int = config.MINIMUM_CONSECUTIVE_FRAMES,
    ) -> None:
        """
        Args:
            frame_rate: Frame rate of the source video (not of the strided output);
                ``update`` receives real timestamps so skipped frames are handled.
        """
        self._tracker_kwargs = dict(
            frame_rate=frame_rate,
            lost_track_buffer=lost_track_buffer,
            track_activation_threshold=track_activation_threshold,
            high_conf_det_threshold=high_conf_det_threshold,
            minimum_consecutive_frames=minimum_consecutive_frames,
        )
        self._tracker = ByteTrackTracker(**self._tracker_kwargs)

    def reset(self) -> None:
        """Forget all tracks, e.g. before processing a new video."""
        self._tracker = ByteTrackTracker(**self._tracker_kwargs)

    def update(
        self, detections: sv.Detections, timestamp: float | None = None
    ) -> tuple[sv.Detections, sv.Detections]:
        """Advance the tracker by one frame.

        Args:
            detections: Canonical-class detections for the frame.
            timestamp: Frame time in seconds; required for correct motion
                prediction when frames are skipped.

        Returns:
            ``(people, ball)``. ``people`` only contains confirmed tracks.
        """
        is_ball = detections.class_id == config.BALL_ID
        ball = self._select_ball(detections[is_ball])
        people = detections[~is_ball]

        # The model sometimes labels one person as both player and goalkeeper;
        # tracking is class-agnostic, so collapse those duplicates first.
        if len(people) > 0:
            people = people.with_nms(threshold=config.NMS_IOU, class_agnostic=True)
        people = self._tracker.update(people, timestamp=timestamp)
        people = people[people.tracker_id >= 0]  # -1 = not yet confirmed
        return people, ball

    @staticmethod
    def _select_ball(balls: sv.Detections) -> sv.Detections:
        """Keep the most confident ball candidates (the real one is chosen later)."""
        order = np.argsort(-balls.confidence)[: config.MAX_BALL_CANDIDATES]
        balls = balls[order]
        balls.tracker_id = np.full(len(balls), BALL_TRACK_ID, dtype=int)
        return balls


def iter_tracks(
    video_path: str | Path,
    detector: FootballDetector,
    tracker: FootballTracker | None = None,
    stride: int = 1,
    start: int = 0,
    max_frames: int | None = None,
    batch_size: int = 4,
) -> Iterator[FrameTracks]:
    """Stream tracking results frame by frame without holding the video in memory.

    Args:
        video_path: Path to the input video.
        detector: Detector used for every processed frame.
        tracker: Tracker to use; a fresh one is created if omitted.
        stride: Process every ``stride``-th frame (2 halves the cost).
        start: Index of the first frame to process.
        max_frames: Stop after this many *processed* frames.
        batch_size: Frames per detector forward pass.
    """
    video_info = get_video_info(video_path)
    tracker = tracker or FootballTracker(frame_rate=video_info.fps)

    for frame_indices, images in iter_frame_batches(
        video_path, stride=stride, start=start, max_frames=max_frames, batch_size=batch_size
    ):
        for frame_idx, image, detections in zip(
            frame_indices, images, detector.detect_batch(images)
        ):
            timestamp = frame_idx / video_info.fps
            people, ball = tracker.update(detections, timestamp=timestamp)
            yield FrameTracks(frame_idx, timestamp, image, people, ball)


def frame_tracks_to_dataframe(frames: Iterable[FrameTracks]) -> pd.DataFrame:
    """Flatten tracking output into one row per detection (see ``TRACK_COLUMNS``)."""
    chunks: list[dict[str, np.ndarray]] = []
    for frame in frames:
        detections = sv.Detections.merge([frame.people, frame.ball])
        if len(detections) == 0:
            continue
        # Bottom-centre of the box approximates where the player touches the pitch;
        # this is the point the homography step projects onto the 2D pitch.
        foot = detections.get_anchors_coordinates(sv.Position.BOTTOM_CENTER)
        n = len(detections)
        chunks.append({
            "frame_idx": np.full(n, frame.frame_idx),
            "timestamp": np.full(n, frame.timestamp),
            "tracker_id": detections.tracker_id,
            "class_id": detections.class_id,
            "class_name": detections.data["class_name"],
            "confidence": detections.confidence,
            "x1": detections.xyxy[:, 0],
            "y1": detections.xyxy[:, 1],
            "x2": detections.xyxy[:, 2],
            "y2": detections.xyxy[:, 3],
            "foot_x": foot[:, 0],
            "foot_y": foot[:, 1],
        })

    if not chunks:
        return pd.DataFrame(columns=TRACK_COLUMNS)
    return pd.DataFrame({col: np.concatenate([c[col] for c in chunks]) for col in TRACK_COLUMNS})


def track_video(
    video_path: str | Path,
    detector: FootballDetector,
    stride: int = 1,
    start: int = 0,
    max_frames: int | None = None,
    batch_size: int = 4,
    show_progress: bool = True,
) -> pd.DataFrame:
    """Run detection + tracking over a video and return one row per detection."""
    frames = iter_tracks(
        video_path, detector, stride=stride, start=start,
        max_frames=max_frames, batch_size=batch_size,
    )
    if show_progress:
        frames = tqdm(frames, desc="Tracking", unit="frame", total=max_frames)
    return frame_tracks_to_dataframe(frames)


def save_tracks(tracks: pd.DataFrame, path: str | Path) -> Path:
    """Save tracks to parquet so later stages can skip inference."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tracks.to_parquet(path, index=False)
    return path


def load_tracks(path: str | Path) -> pd.DataFrame:
    """Load tracks previously written by ``save_tracks``."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Tracks file not found: {path}")
    return pd.read_parquet(path)
