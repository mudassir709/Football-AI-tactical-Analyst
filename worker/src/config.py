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
# The strides above are written for 25 fps video (most broadcasts). A 50 fps
# video gets twice the stride, so every video is analysed at the same number
# of frames per second and takes about the same time per minute of football.
REFERENCE_FPS: float = 25.0

# Optional remote GPU analysis service (worker/gpu_server.py, e.g. on RunPod).
# When GPU_SERVER_URL is set, the worker sends videos there and falls back to
# local analysis if the service cannot be reached. Both sides share the token.
GPU_SERVER_URL: str = os.environ.get("GPU_SERVER_URL", "").rstrip("/")
GPU_SERVER_TOKEN: str = os.environ.get("GPU_SERVER_TOKEN", "")

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
# Set DEVICE=cuda:0 (environment variable) on machines with a stronger NVIDIA GPU,
# such as the cloud GPU analysis service.
DEVICE: str = os.environ.get("DEVICE", "cpu")

# --- Detection defaults ------------------------------------------------------
# The Roboflow model was trained at 1280px; the ball is only a few pixels wide,
# so lowering this hurts ball recall noticeably.
DEFAULT_IMGSZ: int = 1280
NMS_IOU: float = 0.5

# Per-class confidence thresholds. The ball is small and often blurred, so it
# gets a lower bar; false positives are removed by cleanup.select_ball.
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
# The camera model is smoothed over this many seconds (homography.
# smooth_homographies), because the broadcast camera moves smoothly while
# models fitted frame by frame wobble a little. On the first half of the
# Barcelona - Real Madrid match, 1.5 s cut the large wobbles by about 3/4
# while the picture stayed within about 6 pixels of the unsmoothed model.
HOMOGRAPHY_SMOOTHING_SECONDS: float = 1.5

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
# Grass is removed from shirt crops by comparing pixels with the pitch colour
# measured in a ring around each player (ring width = margin x box width).
# A fixed "green" range would also remove green kits.
GRASS_RING_MARGIN: float = 0.6
# Lab distance (OpenCV 8-bit units) below which a pixel counts as grass;
# brightness (L) is weighted down so mowing stripes still match.
GRASS_LAB_DISTANCE: float = 22.0
GRASS_L_WEIGHT: float = 0.5
# Fallback when the local grass colour cannot be measured (OpenCV hue 0-179).
GRASS_HSV_LOWER: tuple[int, int, int] = (35, 40, 40)
GRASS_HSV_UPPER: tuple[int, int, int] = (85, 255, 255)
MIN_JERSEY_PIXELS: int = 30
# Far-away players in a wide camera view can be only 8 x 17 pixels, so their
# whole shirt is smaller than 30 pixels. For them it is enough that this share
# of the shirt area is not grass (but never fewer than MIN_SMALL_JERSEY_PIXELS).
MIN_JERSEY_SHARE: float = 0.5
MIN_SMALL_JERSEY_PIXELS: int = 6
# A track is a goalkeeper if at least this share of its detections say so.
GOALKEEPER_MIN_SHARE: float = 0.25

# A player or goalkeeper whose shirt is clearly closer to the referees' kit
# colour than to their own team's colour is really a referee: their distance
# to the referee colour must be below this share of the distance to the team.
# Checked on the Barcelona - Real Madrid first half (referees in mint, close to
# Real Madrid's white): below 0.65 almost every track was an official, above
# about 0.68 white Real Madrid players start to appear.
REFEREE_COLOUR_RATIO: float = 0.65

# --- Clean-up defaults (src/cleanup.py) ----------------------------------------
# People whose usual (median) position is further than this outside the pitch
# lines are substitutes, coaches or staff, not part of the game.
OFF_PITCH_MARGIN_M: float = 0.5
# The model finds up to this many "balls" per frame (spare balls, the penalty
# spot...); cleanup.select_ball picks the real one.
MAX_BALL_CANDIDATES: int = 5
# Ball candidates further than this outside the pitch are ignored.
BALL_OFF_PITCH_MARGIN_M: float = 1.0
# The fastest a ball can move (about 145 km/h, a very hard shot), plus a
# margin for measurement error. A candidate further away than the ball could
# have travelled since the last frame is a different object.
BALL_MAX_SPEED_MS: float = 40.0
BALL_POSITION_TOLERANCE_M: float = 2.0
# After the ball has been lost for this long, we stop following its path and
# start again from the most confident candidate.
BALL_LOST_SECONDS: float = 1.0
# The penalty spots look like a ball. A candidate this close to a spot is only
# accepted if we followed the ball there.
PENALTY_SPOT_RADIUS_M: float = 1.0
# Two pieces of track are joined into one player when the second starts at
# most this many seconds after the first ends...
STITCH_MAX_GAP_SECONDS: float = 5.0
# ...and no further away than a player could run in that time (7 m/s, a fast
# run) plus a margin for measurement error.
STITCH_MAX_SPEED_MS: float = 7.0
STITCH_POSITION_TOLERANCE_M: float = 2.0

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
# Positions are averaged over windows of this length before matching. Short, so
# 30 s clips get several windows; on long videos FORMATION_MIN_STABLE_SECONDS
# stops brief wobbles from counting as formation changes.
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
# A new formation must also be the best match for this long before we accept
# the change. Without it, a full half showed 282 changes: brief wobbles between
# two similar shapes (e.g. 4-1-4-1 and 4-5-1) each counted as a new formation.
FORMATION_MIN_STABLE_SECONDS: float = 20.0

# --- Metrics defaults --------------------------------------------------------
# Heatmap grid over the 105 x 68 m pitch: 21 x 14 cells of 5 x ~4.9 m.
HEATMAP_BINS: tuple[int, int] = (21, 14)
# Steps implying a faster speed are tracking glitches (ID jumps), not running;
# elite sprinters peak around 10-11 m/s.
MAX_PLAYER_SPEED: float = 12.0
# Top speed is measured as the average speed over this many seconds. Speeds
# between two single frames are too noisy: a small jump in the measured
# position (e.g. when the camera model switches) looked like a 39.6 km/h
# sprint in clip 3. Over one second, those jumps average out.
TOP_SPEED_WINDOW_SECONDS: float = 1.0
