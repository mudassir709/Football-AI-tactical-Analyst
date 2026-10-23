"""Central configuration: paths, class scheme and default thresholds.

Every module imports its defaults from here so experiments only need to
change values in one place.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Paths -------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent  # worker/
REPO_ROOT: Path = PROJECT_ROOT.parent
DATA_DIR: Path = PROJECT_ROOT / "data"
MODELS_DIR: Path = PROJECT_ROOT / "models"
OUTPUT_DIR: Path = PROJECT_ROOT / "outputs"


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ without overriding real variables.

    Locally, settings live in the shared .env at the repository root; in Docker
    they arrive as real environment variables, which take precedence.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


_load_env_file(REPO_ROOT / ".env")

# --- Platform integration ----------------------------------------------------
# Must match the API's queue name (backend/src/queue.ts).
QUEUE_NAME: str = "match-analysis"
REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379")
# Uploaded videos and results; relative paths are resolved from the repo root,
# exactly like the API does, so both see the same files.
STORAGE_DIR: Path = (REPO_ROOT / os.environ.get("STORAGE_DIR", "storage")).resolve()
# Analysis modes offered when uploading. "stride": analyse every Nth frame;
# "imgsz": detection resolution (lower is faster but misses more balls);
# "pitch_every": run the pitch model on every Nth analysed frame and share its
# homography with the frames around it (the broadcast camera moves smoothly).
ANALYSIS_MODES: dict[str, dict[str, int]] = {
    "standard": {"stride": 2, "imgsz": 1280, "pitch_every": 3},
    "quick": {"stride": 5, "imgsz": 960, "pitch_every": 2},  # for live demos
}
DEFAULT_ANALYSIS_MODE: str = "standard"

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

# --- Hardware ----------------------------------------------------------------
# Inference device. Benchmarked on the dev laptop (i7-1255U vs GeForce MX550 2 GB):
# the CPU was ~2x faster than the GPU for these YOLOv8 models, so default to CPU.
# Set to "cuda:0" on machines with a stronger NVIDIA GPU.
DEVICE: str = "cpu"

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

# --- Team assignment defaults ------------------------------------------------
# Team labels used in the tracks table.
TEAM_A: int = 0
TEAM_B: int = 1
NO_TEAM: int = -1  # referees, ball, or players that could not be assigned
# Jersey crops sampled per track; spread evenly over the track's lifetime.
JERSEY_SAMPLES_PER_TRACK: int = 10
# Torso region of a player box, as fractions of box height/width. Skips the
# head and the shorts, which are often a different colour to the shirt.
TORSO_Y_RANGE: tuple[float, float] = (0.15, 0.50)
TORSO_X_RANGE: tuple[float, float] = (0.25, 0.75)
# HSV range treated as grass and removed from crops (OpenCV hue is 0-179).
GRASS_HSV_LOWER: tuple[int, int, int] = (35, 40, 40)
GRASS_HSV_UPPER: tuple[int, int, int] = (85, 255, 255)
MIN_JERSEY_PIXELS: int = 30
# A track is a goalkeeper if at least this share of its detections say so.
GOALKEEPER_MIN_SHARE: float = 0.25

# --- Trajectory defaults -----------------------------------------------------
# Centred rolling mean over this span removes box jitter from pitch positions.
SMOOTHING_WINDOW_SECONDS: float = 1.0
# Ball gaps up to this long are filled by linear interpolation.
BALL_MAX_GAP_SECONDS: float = 1.0

# --- Formation defaults ------------------------------------------------------
# Candidate formations (outfield lines from defence to attack).
FORMATIONS: tuple[str, ...] = (
    "4-4-2", "4-3-3", "4-2-3-1", "4-1-4-1", "4-5-1", "3-5-2", "3-4-3", "5-3-2", "5-4-1",
)
# Positions are averaged over windows of this length before matching. Short for
# the 30 s sample clip; use 60-300 s for full matches.
FORMATION_WINDOW_SECONDS: float = 5.0
# A window is only classified if this many outfield players are visible...
FORMATION_MIN_PLAYERS: int = 8
# ...each for at least this share of the window's frames.
FORMATION_MIN_PRESENCE: float = 0.5
# Hysteresis: switch formation only when the new template's matching cost is
# lower than the current one's by more than this (normalised pitch units). On
# the sample clip, best-vs-runner-up gaps were 0.001-0.025, so 0.03 sits just
# above that noise level.
FORMATION_SWITCH_MARGIN: float = 0.03

# --- Metrics defaults --------------------------------------------------------
# Heatmap grid over the 105 x 68 m pitch: 21 x 14 cells of 5 x ~4.9 m.
HEATMAP_BINS: tuple[int, int] = (21, 14)
# Steps implying a faster speed are tracking glitches (ID jumps), not running;
# elite sprinters peak around 10-11 m/s.
MAX_PLAYER_SPEED: float = 12.0
