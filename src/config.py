"""Central configuration: paths, class scheme and default thresholds.

Every module imports its defaults from here so experiments only need to
change values in one place.
"""

from __future__ import annotations

from pathlib import Path

# --- Paths -------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = PROJECT_ROOT / "data"
MODELS_DIR: Path = PROJECT_ROOT / "models"
OUTPUT_DIR: Path = PROJECT_ROOT / "outputs"

DEFAULT_VIDEO: Path = DATA_DIR / "sample.mp4"
# Roboflow's pretrained football detector (classes: ball, goalkeeper, player, referee).
DEFAULT_WEIGHTS: Path = MODELS_DIR / "football-player-detection.pt"

# --- Canonical class scheme --------------------------------------------------
# All downstream modules work with these IDs, regardless of which model produced
# the detections. They match the Roboflow model's own IDs.
BALL_ID: int = 0
GOALKEEPER_ID: int = 1
PLAYER_ID: int = 2
REFEREE_ID: int = 3

CLASS_NAMES: dict[int, str] = {
    BALL_ID: "ball",
    GOALKEEPER_ID: "goalkeeper",
    PLAYER_ID: "player",
    REFEREE_ID: "referee",
}

# Model label (lower-cased) -> canonical class ID. Labels not listed are dropped.
# The COCO entries let a stock "yolov8n.pt" work as a rough fallback.
CLASS_ALIASES: dict[str, int] = {
    "ball": BALL_ID,
    "football": BALL_ID,
    "sports ball": BALL_ID,  # COCO
    "goalkeeper": GOALKEEPER_ID,
    "player": PLAYER_ID,
    "person": PLAYER_ID,  # COCO
    "referee": REFEREE_ID,
}

# --- Detection defaults ------------------------------------------------------
# The Roboflow model was trained at 1280px; the ball is only a few pixels wide,
# so lowering this hurts ball recall noticeably.
DEFAULT_IMGSZ: int = 1280
NMS_IOU: float = 0.5

# Per-class confidence thresholds. The ball is small and often blurred, so it
# gets a lower bar; false positives are cleaned up by keeping one ball per frame.
CLASS_CONFIDENCE: dict[int, float] = {
    BALL_ID: 0.15,
    GOALKEEPER_ID: 0.30,
    PLAYER_ID: 0.30,
    REFEREE_ID: 0.30,
}

# --- Tracking defaults -------------------------------------------------------
# Measured in frames at the source video's frame rate (2 s at 25 fps), so a
# player can be occluded briefly without losing their ID.
LOST_TRACK_BUFFER: int = 50
TRACK_ACTIVATION_THRESHOLD: float = 0.5
HIGH_CONF_DET_THRESHOLD: float = 0.5
MINIMUM_CONSECUTIVE_FRAMES: int = 2

# --- Homography defaults -----------------------------------------------------
# Roboflow's pitch keypoint model (YOLOv8-pose, 32 landmarks, trained at 640px).
PITCH_WEIGHTS: Path = MODELS_DIR / "football-pitch-detection.pt"
PITCH_IMGSZ: int = 640
PITCH_KEYPOINT_CONFIDENCE: float = 0.5
MIN_HOMOGRAPHY_KEYPOINTS: int = 4
# RANSAC tolerance in pitch metres: keypoints that land further than this from
# their true pitch position are treated as outliers.
HOMOGRAPHY_RANSAC_THRESHOLD: float = 1.0
# Keypoints spanning less than this area (m^2) are nearly collinear and give an
# unstable homography, e.g. when only the halfway line is visible.
MIN_KEYPOINT_HULL_AREA: float = 50.0
# When a frame has no usable keypoints, reuse the last homography for at most
# this many processed frames; beyond that the camera has likely moved too far.
MAX_HOMOGRAPHY_REUSE: int = 10
