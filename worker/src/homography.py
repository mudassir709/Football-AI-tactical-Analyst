"""Map image coordinates to 2D pitch coordinates (metres) with a per-frame homography.

Each frame, a YOLOv8-pose model locates up to 32 pitch landmarks (corners,
box corners, centre circle...). Matching their image positions to their known
positions on a real pitch gives a homography: a 3x3 matrix that projects any
point on the grass from the image onto the pitch plane.

Pitch coordinate system (identical to mplsoccer's ``"uefa"`` pitch):
    x: 0 -> 105 m along the touchlines, from the left goal line to the right one
       as seen from the main broadcast camera.
    y: 0 -> 68 m across the pitch, from the near touchline (bottom of the image)
       to the far touchline.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from ultralytics import YOLO

from src import config
from src.video import iter_frame_batches

N_PITCH_KEYPOINTS: int = 32
HOMOGRAPHY_COLUMNS: list[str] = [f"h{i}" for i in range(9)]


@dataclass(frozen=True)
class PitchDimensions:
    """Pitch markings in metres (FIFA standard sizes by default)."""

    length: float = 105.0
    width: float = 68.0
    penalty_area_length: float = 16.5
    penalty_area_width: float = 40.32
    goal_area_length: float = 5.5
    goal_area_width: float = 18.32
    penalty_spot_distance: float = 11.0
    centre_circle_radius: float = 9.15

    @property
    def keypoints(self) -> np.ndarray:
        """``(32, 2)`` pitch positions of the keypoint model's landmarks, in model order.

        The order follows Roboflow's ``SoccerPitchConfiguration``, which measures
        y downwards from the far touchline; we flip y at the end so it grows
        towards the far touchline instead.
        """
        length, width = self.length, self.width
        pa_off = (width - self.penalty_area_width) / 2  # far touchline -> penalty area side
        ga_off = (width - self.goal_area_width) / 2  # far touchline -> goal area side
        pa_len, ga_len = self.penalty_area_length, self.goal_area_length
        spot, radius, mid = self.penalty_spot_distance, self.centre_circle_radius, width / 2

        points = [
            # Left goal line, far -> near (1-6)
            (0, 0), (0, pa_off), (0, ga_off), (0, width - ga_off), (0, width - pa_off), (0, width),
            # Left goal area, penalty spot, penalty area (7-13)
            (ga_len, ga_off), (ga_len, width - ga_off), (spot, mid),
            (pa_len, pa_off), (pa_len, ga_off), (pa_len, width - ga_off), (pa_len, width - pa_off),
            # Halfway line (14-17)
            (length / 2, 0), (length / 2, mid - radius), (length / 2, mid + radius), (length / 2, width),
            # Right penalty area, penalty spot, goal area (18-24)
            (length - pa_len, pa_off), (length - pa_len, ga_off),
            (length - pa_len, width - ga_off), (length - pa_len, width - pa_off),
            (length - spot, mid), (length - ga_len, ga_off), (length - ga_len, width - ga_off),
            # Right goal line, far -> near (25-30)
            (length, 0), (length, pa_off), (length, ga_off),
            (length, width - ga_off), (length, width - pa_off), (length, width),
            # Centre circle on the halfway axis (31-32)
            (length / 2 - radius, mid), (length / 2 + radius, mid),
        ]
        keypoints = np.array(points, dtype=np.float32)
        keypoints[:, 1] = width - keypoints[:, 1]
        return keypoints

    def line_segments(self, circle_points: int = 64) -> list[np.ndarray]:
        """Pitch markings as polylines in pitch metres, for drawing overlays."""
        length, width = self.length, self.width

        def box(x0: float, x1: float, box_width: float) -> np.ndarray:
            y0, y1 = (width - box_width) / 2, (width + box_width) / 2
            return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)

        angles = np.linspace(0, 2 * np.pi, circle_points, dtype=np.float32)
        circle = np.stack([
            length / 2 + self.centre_circle_radius * np.cos(angles),
            width / 2 + self.centre_circle_radius * np.sin(angles),
        ], axis=1)

        return [
            np.array([[0, 0], [length, 0], [length, width], [0, width], [0, 0]], dtype=np.float32),
            np.array([[length / 2, 0], [length / 2, width]], dtype=np.float32),
            circle,
            box(0, self.penalty_area_length, self.penalty_area_width),
            box(length, length - self.penalty_area_length, self.penalty_area_width),
            box(0, self.goal_area_length, self.goal_area_width),
            box(length, length - self.goal_area_length, self.goal_area_width),
        ]


@dataclass
class Homography:
    """A fitted image -> pitch projection with quality statistics."""

    matrix: np.ndarray  # 3x3, image pixels -> pitch metres
    n_keypoints: int  # confident keypoints used for fitting
    n_inliers: int  # keypoints consistent with the fit (RANSAC inliers)
    reprojection_error: float  # mean inlier error in metres

    @classmethod
    def fit(
        cls,
        image_points: np.ndarray,
        pitch_points: np.ndarray,
        ransac_threshold: float = config.HOMOGRAPHY_RANSAC_THRESHOLD,
        min_hull_area: float = config.MIN_KEYPOINT_HULL_AREA,
    ) -> Homography | None:
        """Fit with RANSAC; return ``None`` if the points cannot give a stable result."""
        if len(image_points) < config.MIN_HOMOGRAPHY_KEYPOINTS:
            return None
        image_points = image_points.astype(np.float32)
        pitch_points = pitch_points.astype(np.float32)

        # Nearly collinear landmarks (e.g. only the halfway line) are degenerate.
        if cv2.contourArea(cv2.convexHull(pitch_points)) < min_hull_area:
            return None

        matrix, inlier_mask = cv2.findHomography(
            image_points, pitch_points, cv2.RANSAC, ransac_threshold
        )
        if matrix is None:
            return None
        inliers = inlier_mask.ravel().astype(bool)
        if inliers.sum() < config.MIN_HOMOGRAPHY_KEYPOINTS:
            return None

        projected = _apply_homography(matrix, image_points[inliers])
        error = float(np.linalg.norm(projected - pitch_points[inliers], axis=1).mean())
        return cls(matrix, len(image_points), int(inliers.sum()), error)

    def image_to_pitch(self, points: np.ndarray) -> np.ndarray:
        """Project ``(N, 2)`` image pixel points onto the pitch (metres)."""
        return _apply_homography(self.matrix, points)

    def pitch_to_image(self, points: np.ndarray) -> np.ndarray:
        """Project ``(N, 2)`` pitch points (metres) back into the image (pixels)."""
        return _apply_homography(np.linalg.inv(self.matrix), points)


def _apply_homography(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Apply a 3x3 homography to ``(N, 2)`` points."""
    if len(points) == 0:
        return np.empty((0, 2), dtype=np.float32)
    points = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(points, matrix).reshape(-1, 2)


class PitchKeypointDetector:
    """Locate the 32 pitch landmarks in broadcast frames."""

    def __init__(
        self,
        weights_path: str | Path = config.PITCH_WEIGHTS,
        imgsz: int = config.PITCH_IMGSZ,
        device: str | None = config.DEVICE,
    ) -> None:
        weights_path = Path(weights_path)
        if not weights_path.exists():
            raise FileNotFoundError(f"Pitch keypoint weights not found: {weights_path}")
        try:
            self.model = YOLO(str(weights_path))
        except Exception as exc:
            raise RuntimeError(f"Could not load pitch model from {weights_path}: {exc}") from exc

        kpt_shape = self.model.model.yaml.get("kpt_shape") if self.model.task == "pose" else None
        if not kpt_shape or kpt_shape[0] != N_PITCH_KEYPOINTS:
            raise ValueError(
                f"Expected a pose model with {N_PITCH_KEYPOINTS} keypoints, got {kpt_shape}"
            )
        self.imgsz = imgsz
        self.device = device

    def detect_batch(self, frames: Sequence[np.ndarray]) -> list[tuple[np.ndarray, np.ndarray]]:
        """Return ``(xy, confidence)`` per frame with shapes ``(32, 2)`` and ``(32,)``.

        If the pitch is not found, all confidences are zero.
        """
        if len(frames) == 0:
            return []
        results = self.model.predict(
            list(frames), imgsz=self.imgsz, device=self.device, verbose=False
        )
        outputs = []
        for result in results:
            if result.keypoints is None or len(result.boxes) == 0:
                outputs.append((
                    np.zeros((N_PITCH_KEYPOINTS, 2), dtype=np.float32),
                    np.zeros(N_PITCH_KEYPOINTS, dtype=np.float32),
                ))
                continue
            best = int(result.boxes.conf.argmax())  # one pitch per frame
            outputs.append((
                result.keypoints.xy[best].cpu().numpy(),
                result.keypoints.conf[best].cpu().numpy(),
            ))
        return outputs


class HomographyEstimator:
    """Turn detected keypoints into a homography, reusing the last one on bad frames."""

    def __init__(
        self,
        pitch: PitchDimensions | None = None,
        keypoint_confidence: float = config.PITCH_KEYPOINT_CONFIDENCE,
        ransac_threshold: float = config.HOMOGRAPHY_RANSAC_THRESHOLD,
        max_reuse: int = config.MAX_HOMOGRAPHY_REUSE,
    ) -> None:
        self.pitch = pitch or PitchDimensions()
        self.keypoint_confidence = keypoint_confidence
        self.ransac_threshold = ransac_threshold
        self.max_reuse = max_reuse
        self._pitch_keypoints = self.pitch.keypoints
        self._last: Homography | None = None
        self._reuse_count = 0

    def reset(self) -> None:
        """Forget the last homography, e.g. before a new video or after a scene cut."""
        self._last = None
        self._reuse_count = 0

    def update(self, xy: np.ndarray, confidence: np.ndarray) -> tuple[Homography | None, bool]:
        """Estimate this frame's homography.

        Returns:
            ``(homography, reused)``; ``reused`` is True when this frame's own
            keypoints were unusable and the previous homography was carried over.
        """
        mask = confidence >= self.keypoint_confidence
        homography = Homography.fit(xy[mask], self._pitch_keypoints[mask], self.ransac_threshold)
        if homography is not None:
            self._last, self._reuse_count = homography, 0
            return homography, False
        if self._last is not None and self._reuse_count < self.max_reuse:
            self._reuse_count += 1
            return self._last, True
        return None, False


@dataclass
class FrameHomography:
    """Homography output for one processed video frame."""

    frame_idx: int
    frame: np.ndarray  # BGR image, kept so callers can draw overlays
    keypoints_xy: np.ndarray  # (32, 2) image pixels
    keypoints_conf: np.ndarray  # (32,)
    homography: Homography | None
    reused: bool


def iter_homographies(
    video_path: str | Path,
    keypoint_detector: PitchKeypointDetector,
    estimator: HomographyEstimator | None = None,
    stride: int = 1,
    start: int = 0,
    max_frames: int | None = None,
    batch_size: int = 4,
) -> Iterator[FrameHomography]:
    """Stream per-frame homographies; use the same stride/start as tracking so frames line up."""
    estimator = estimator or HomographyEstimator()
    for frame_indices, images in iter_frame_batches(
        video_path, stride=stride, start=start, max_frames=max_frames, batch_size=batch_size
    ):
        for frame_idx, image, (xy, conf) in zip(
            frame_indices, images, keypoint_detector.detect_batch(images)
        ):
            homography, reused = estimator.update(xy, conf)
            yield FrameHomography(frame_idx, image, xy, conf, homography, reused)


def homographies_to_dataframe(frames: Iterable[FrameHomography]) -> pd.DataFrame:
    """One row per frame: quality stats plus the flattened matrix (NaN when unavailable)."""
    rows = []
    for frame in frames:
        h = frame.homography
        row = {
            "frame_idx": frame.frame_idx,
            "valid": h is not None,
            "reused": frame.reused,
            "n_keypoints": h.n_keypoints if h else 0,
            "n_inliers": h.n_inliers if h else 0,
            "reprojection_error": h.reprojection_error if h else np.nan,
        }
        matrix = h.matrix.ravel() if h else np.full(9, np.nan)
        row.update(zip(HOMOGRAPHY_COLUMNS, matrix))
        rows.append(row)
    return pd.DataFrame(rows)


def project_tracks(
    tracks: pd.DataFrame, homographies: pd.DataFrame, max_frame_gap: int = 0
) -> pd.DataFrame:
    """Add ``pitch_x``/``pitch_y`` (metres) by projecting each foot point.

    Fully vectorised: each row is projected with its frame's matrix. With
    ``max_frame_gap > 0``, homographies only computed for some frames are
    shared with the frames around them (the nearest one within the gap is
    used); this is how the pitch model can run on fewer frames than tracking.
    Rows without a usable homography get NaN.
    """
    columns = homographies[["frame_idx", *HOMOGRAPHY_COLUMNS]].dropna()
    if max_frame_gap > 0:
        merged = pd.merge_asof(
            tracks.reset_index(drop=True).sort_values("frame_idx"),
            columns.sort_values("frame_idx"),
            on="frame_idx", direction="nearest", tolerance=max_frame_gap,
        ).sort_index()
    else:
        merged = tracks.merge(columns, on="frame_idx", how="left")
    h = merged[HOMOGRAPHY_COLUMNS].to_numpy()
    x, y = merged["foot_x"].to_numpy(), merged["foot_y"].to_numpy()
    w = h[:, 6] * x + h[:, 7] * y + h[:, 8]
    merged["pitch_x"] = (h[:, 0] * x + h[:, 1] * y + h[:, 2]) / w
    merged["pitch_y"] = (h[:, 3] * x + h[:, 4] * y + h[:, 5]) / w
    return merged.drop(columns=HOMOGRAPHY_COLUMNS)
