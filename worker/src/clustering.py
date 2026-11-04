"""Clustering stages of the pipeline: team assignment and formation detection.

Team assignment works per *track*, not per detection: each track's shirt colour
is the median over several sampled crops, which smooths out occlusions, motion
blur and lighting changes, and K-Means then splits those colours into two teams.
Goalkeepers wear a distinct kit, so they are assigned by pitch proximity instead.

Formation detection averages each outfield player's position over a time window
(their "role centroid"), normalises the team's shape, and matches it to formation
templates with the Hungarian algorithm. Hysteresis stops flicker between
similar templates, so a reported change reflects a real shift in shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import supervision as sv
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import KMeans

from src import config
from src.homography import PitchDimensions

JERSEY_FEATURE_COLUMNS: list[str] = ["L", "a", "b"]  # OpenCV 8-bit Lab


def local_grass_lab(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> np.ndarray | None:
    """Median Lab colour of the grass in a ring around a player's box.

    Measuring the pitch next to each player (instead of assuming a fixed
    "green") copes with mowing stripes, shadows and floodlights, and lets
    green kits be told apart from the grass they stand on.
    """
    frame_h, frame_w = frame.shape[:2]
    margin_x = int((x2 - x1) * config.GRASS_RING_MARGIN)
    margin_y = int((y2 - y1) * config.GRASS_RING_MARGIN / 3)
    ox1, oy1 = max(x1 - margin_x, 0), max(y1 - margin_y, 0)
    ox2, oy2 = min(x2 + margin_x, frame_w), min(y2 + margin_y, frame_h)
    ring = np.ones((oy2 - oy1, ox2 - ox1), dtype=bool)
    ring[y1 - oy1:y2 - oy1, x1 - ox1:x2 - ox1] = False  # exclude the player's own box
    if ring.sum() < config.MIN_JERSEY_PIXELS:
        return None
    lab = cv2.cvtColor(frame[oy1:oy2, ox1:ox2], cv2.COLOR_BGR2LAB)
    return np.median(lab[ring], axis=0)


def jersey_colour(crop: np.ndarray, grass_lab: np.ndarray | None = None) -> np.ndarray | None:
    """Median Lab colour of the shirt in a BGR player crop, ignoring grass.

    Args:
        grass_lab: The pitch colour around this player (``local_grass_lab``).
            Pixels close to it are treated as grass. Without it, a fixed
            green range is used, which also removes green shirts.

    Returns ``None`` if too few shirt pixels are visible.
    """
    height, width = crop.shape[:2]
    y0, y1 = (int(f * height) for f in config.TORSO_Y_RANGE)
    x0, x1 = (int(f * width) for f in config.TORSO_X_RANGE)
    torso = crop[y0:y1, x0:x1]
    if torso.size == 0:
        return None

    lab = cv2.cvtColor(torso, cv2.COLOR_BGR2LAB)
    if grass_lab is not None:
        # Brightness counts half, so lighter/darker mowing stripes still match
        # the grass while a bright lime shirt does not.
        diff = lab.astype(np.float32) - grass_lab.astype(np.float32)
        diff[..., 0] *= config.GRASS_L_WEIGHT
        grass = np.linalg.norm(diff, axis=-1) < config.GRASS_LAB_DISTANCE
    else:
        hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
        grass = cv2.inRange(hsv, config.GRASS_HSV_LOWER, config.GRASS_HSV_UPPER).astype(bool)
    pixels = lab[~grass]
    # Normally we want 30 shirt pixels; for tiny far-away players, half of
    # their shirt area is enough (see MIN_JERSEY_SHARE in config.py).
    torso_pixels = torso.shape[0] * torso.shape[1]
    needed = max(config.MIN_SMALL_JERSEY_PIXELS,
                 min(config.MIN_JERSEY_PIXELS, config.MIN_JERSEY_SHARE * torso_pixels))
    if len(pixels) < needed:
        return None
    return np.median(pixels, axis=0)


def track_roles(tracks: pd.DataFrame) -> pd.Series:
    """Role (``player``/``goalkeeper``/``referee``) per tracker ID.

    Detector labels flicker between frames, so roles are decided per track: the
    most frequent class, except that ``goalkeeper`` wins whenever it reaches
    ``config.GOALKEEPER_MIN_SHARE`` - the detector often calls goalkeepers
    "player", but rarely calls an outfield player "goalkeeper".
    """
    people = tracks[tracks["class_id"] != config.BALL_ID]

    def role(classes: pd.Series) -> str:
        if (classes == "goalkeeper").mean() >= config.GOALKEEPER_MIN_SHARE:
            return "goalkeeper"
        return classes.mode().iat[0]

    return people.groupby("tracker_id")["class_name"].agg(role)


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
    """Sample shirt colours for every player, goalkeeper and referee track.

    Referees are included so their kit colour can be learned (see
    assign_teams), which lets us spot a referee the model called a player.

    The video is decoded once, sequentially (cheap compared with inference);
    only frames that contain a sampled detection are cropped.

    Returns:
        One row per usable crop: ``frame_idx``, ``tracker_id`` and Lab colour.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    roles = track_roles(tracks)
    outfield_ids = roles.index[roles.isin(["player", "goalkeeper", "referee"])]
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
            if x2 <= x1 or y2 <= y1:
                continue
            grass = local_grass_lab(frame, x1, y1, x2, y2)
            colour = jersey_colour(frame[y1:y2, x1:x2], grass)
            if colour is not None:
                rows.append((frame_idx, det.tracker_id, *colour))
    return pd.DataFrame(rows, columns=["frame_idx", "tracker_id", *JERSEY_FEATURE_COLUMNS])


@dataclass
class TeamAssignment:
    """Result of team clustering for one clip."""

    track_teams: dict[int, int]  # tracker_id -> TEAM_A / TEAM_B
    team_colours_bgr: np.ndarray  # (2, 3) uint8 shirt colour of each team
    agreement: pd.Series  # per player track: share of crops voting for its team
    # Tracks the model called player or goalkeeper but whose shirt matches the
    # referees' kit; they are shown as referees and get no team.
    referee_ids: frozenset[int] = frozenset()

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


def find_referees(
    jersey_features: pd.DataFrame,
    roles: pd.Series,
    team_centres: np.ndarray,
    ratio: float = config.REFEREE_COLOUR_RATIO,
) -> set[int]:
    """Players and goalkeepers whose shirt matches the referees' kit.

    The model recognises the assistant referees well but sometimes calls the
    main referee a player. So we learn the referee kit colour from the tracks
    the model *does* call referees, then look for "players" wearing it: a
    track counts as a referee when its shirt is much closer to the referee
    colour than to the nearest team colour (see REFEREE_COLOUR_RATIO).

    Args:
        roles: Role of every track (``track_roles``).
        team_centres: ``(2, 3)`` Lab shirt colour of each team.
    """
    referee_rows = jersey_features[jersey_features["tracker_id"].isin(roles.index[roles == "referee"])]
    if referee_rows.empty:
        return set()
    referee_colour = referee_rows[JERSEY_FEATURE_COLUMNS].median().to_numpy()

    candidate_ids = roles.index[roles.isin(["player", "goalkeeper"])]
    colours = (jersey_features[jersey_features["tracker_id"].isin(candidate_ids)]
               .groupby("tracker_id")[JERSEY_FEATURE_COLUMNS].median())
    if colours.empty:
        return set()
    to_referee = np.linalg.norm(colours.to_numpy() - referee_colour, axis=1)
    to_team = np.linalg.norm(colours.to_numpy()[:, None, :] - team_centres[None, :, :], axis=2).min(axis=1)
    return set(colours.index[to_referee < ratio * to_team].astype(int))


def assign_teams(
    tracks: pd.DataFrame,
    jersey_features: pd.DataFrame,
    random_state: int = 0,
) -> TeamAssignment:
    """Cluster player tracks into two teams by shirt colour, then place goalkeepers.

    Tracks wearing the referees' kit (see find_referees) are taken out first,
    so the referee never ends up in a team.

    Args:
        tracks: Tracks table; ``pitch_x``/``pitch_y`` are used for goalkeepers
            when present, otherwise image foot points.
        jersey_features: Output of ``extract_jersey_features``.
        random_state: K-Means seed, for reproducible results.
    """
    roles = track_roles(tracks)
    player_ids = roles.index[roles == "player"]
    goalkeeper_ids = list(roles.index[roles == "goalkeeper"])

    def cluster(ids) -> tuple[pd.DataFrame, pd.DataFrame, KMeans]:
        """Split the shirt colours of these player tracks into two teams."""
        features = jersey_features[jersey_features["tracker_id"].isin(ids)]
        colours = features.groupby("tracker_id")[JERSEY_FEATURE_COLUMNS].median()
        if len(colours) < 2:
            raise ValueError(f"Need at least 2 player tracks with jersey colours, got {len(colours)}")
        return features, colours, KMeans(n_clusters=2, n_init=10, random_state=random_state).fit(colours.to_numpy())

    # First split, then find referees dressed as "players", and split again without them.
    player_features, track_colours, kmeans = cluster(player_ids)
    referee_ids = find_referees(jersey_features, roles, kmeans.cluster_centers_)
    if referee_ids:
        player_ids = player_ids.difference(list(referee_ids))
        goalkeeper_ids = [i for i in goalkeeper_ids if i not in referee_ids]
        player_features, track_colours, kmeans = cluster(player_ids)
    labels = kmeans.labels_

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
    return TeamAssignment(track_teams, team_colours, agreement, frozenset(referee_ids))


def add_team_column(tracks: pd.DataFrame, assignment: TeamAssignment) -> pd.DataFrame:
    """Add ``team`` (``NO_TEAM`` for referees, the ball and unassigned tracks) and
    the per-track ``role`` (``"ball"`` for ball rows)."""
    is_ball = tracks["class_id"] == config.BALL_ID
    team = tracks["tracker_id"].map(assignment.track_teams).fillna(config.NO_TEAM).astype(int)
    team[is_ball] = config.NO_TEAM
    role = tracks["tracker_id"].map(track_roles(tracks)).where(~is_ball, "ball")
    # Referees the model mistook for players (they have no team, see find_referees).
    role = role.mask(tracks["tracker_id"].isin(assignment.referee_ids) & ~is_ball, "referee")
    return tracks.assign(team=team, role=role)


# =============================================================================
# Formation detection
# =============================================================================


def formation_template(formation: str) -> np.ndarray:
    """Normalised ``(depth, width)`` slots for a formation such as ``"4-2-3-1"``.

    Depth runs 0 (defensive line) -> 1 (most advanced line); width 0 -> 1 across
    the pitch. Lines are evenly spaced; players spread evenly within a line.
    """
    lines = [int(n) for n in formation.split("-")]
    if sum(lines) != 10:
        raise ValueError(f"Formation {formation!r} must have 10 outfield players")
    slots = []
    for i, count in enumerate(lines):
        depth = i / (len(lines) - 1)
        if count == 1:
            widths = [0.5]
        elif count == 2:
            widths = [0.3, 0.7]  # pairs (e.g. strikers) play inside, not on the touchlines
        else:
            widths = np.linspace(0, 1, count)
        slots.extend((depth, w) for w in widths)
    return np.array(slots, dtype=float)


def _roles(tracks: pd.DataFrame) -> pd.Series:
    """Per-track ``role`` column if present, else the per-frame detector class."""
    return tracks["role"] if "role" in tracks.columns else tracks["class_name"]


def _normalise_shape(points: np.ndarray) -> np.ndarray:
    """Scale points to the unit square so shape, not position or spread, is compared."""
    mins = points.min(axis=0)
    span = points.max(axis=0) - mins
    return (points - mins) / np.where(span > 0, span, 1.0)


def match_formation(
    positions: np.ndarray, formations: tuple[str, ...] = config.FORMATIONS
) -> dict[str, float]:
    """Matching cost of each formation for ``(n, 2)`` outfield ``(depth, width)`` positions.

    Each player is assigned to one template slot (Hungarian algorithm, so no
    slot is used twice); the cost is the mean player-to-slot distance in
    normalised units. With fewer than 10 players, the best subset of slots is used.
    """
    observed = _normalise_shape(positions)
    costs = {}
    for formation in formations:
        template = formation_template(formation)
        distances = np.linalg.norm(observed[:, None, :] - template[None, :, :], axis=2)
        rows, cols = linear_sum_assignment(distances)
        costs[formation] = float(distances[rows, cols].mean())
    return costs


def defending_sides(tracks: pd.DataFrame, pitch: PitchDimensions | None = None) -> dict[int, str]:
    """Which goal (``"left"``/``"right"``) each team defends.

    Uses the goalkeeper's average position when available. Otherwise the team
    whose players are on average closer to the left goal is assumed to defend it,
    since defenders stay goal-side of attackers.
    """
    pitch = pitch or PitchDimensions()
    teams = (config.TEAM_A, config.TEAM_B)
    located = tracks.dropna(subset=["pitch_x"])
    sides: dict[int, str] = {}

    goalkeepers = located[(_roles(located) == "goalkeeper") & located["team"].isin(teams)]
    for team, gk_x in goalkeepers.groupby("team")["pitch_x"].mean().items():
        sides[int(team)] = "left" if gk_x < pitch.length / 2 else "right"

    if len(sides) == 1:  # the other team defends the opposite goal
        known, side = next(iter(sides.items()))
        sides[teams[1 - teams.index(known)]] = "right" if side == "left" else "left"
    elif not sides:
        mean_x = located[located["team"].isin(teams)].groupby("team")["pitch_x"].mean()
        if len(mean_x) == 2:
            left_team = int(mean_x.idxmin())
            sides = {left_team: "left", teams[1 - teams.index(left_team)]: "right"}
    return sides


def to_attacking_frame(
    tracks: pd.DataFrame, sides: dict[int, str], pitch: PitchDimensions | None = None
) -> pd.DataFrame:
    """Add ``depth``/``width`` so every team attacks towards +depth.

    Teams defending the right goal are rotated 180 degrees, which keeps their
    left/right sides consistent too.
    """
    pitch = pitch or PitchDimensions()
    flip = tracks["team"].map({team: side == "right" for team, side in sides.items()})
    flip = flip.fillna(False).astype(bool)
    depth = np.where(flip, pitch.length - tracks["pitch_x"], tracks["pitch_x"])
    width = np.where(flip, pitch.width - tracks["pitch_y"], tracks["pitch_y"])
    return tracks.assign(depth=depth, width=width)


@dataclass
class FormationResult:
    """Per-window formations for both teams."""

    windows: pd.DataFrame  # one row per (team, window)
    positions: pd.DataFrame  # average position per (team, window, player)

    @property
    def changes(self) -> pd.DataFrame:
        """Windows where a team's (hysteresis-filtered) formation changed."""
        rows = []
        for team, group in self.windows.dropna(subset=["formation"]).groupby("team"):
            previous = group["formation"].shift()
            changed = group[previous.notna() & (group["formation"] != previous)]
            for row, before in zip(changed.itertuples(), previous[changed.index]):
                rows.append({"team": team, "time": row.start, "from": before, "to": row.formation})
        return pd.DataFrame(rows, columns=["team", "time", "from", "to"])


def detect_formations(
    tracks: pd.DataFrame,
    window_seconds: float = config.FORMATION_WINDOW_SECONDS,
    min_players: int = config.FORMATION_MIN_PLAYERS,
    min_presence: float = config.FORMATION_MIN_PRESENCE,
    switch_margin: float = config.FORMATION_SWITCH_MARGIN,
    formations: tuple[str, ...] = config.FORMATIONS,
    min_stable_seconds: float = config.FORMATION_MIN_STABLE_SECONDS,
) -> FormationResult:
    """Classify each team's formation in consecutive time windows.

    Args:
        tracks: Tracks with ``team`` and (ideally smoothed) ``pitch_x``/``pitch_y``.
        window_seconds: Length of each analysis window.
        min_players: Windows with fewer qualifying outfield players are left
            unclassified (the broadcast camera rarely shows everyone).
        min_presence: Share of a window's frames a player must appear in.
        switch_margin: Hysteresis margin, see ``config.FORMATION_SWITCH_MARGIN``.
        min_stable_seconds: A new formation must win for this long before the
            change is accepted, see ``config.FORMATION_MIN_STABLE_SECONDS``.
        formations: Candidate formation templates.
    """
    sides = defending_sides(tracks)
    start_time = tracks["timestamp"].min()
    tracks = tracks.assign(window=((tracks["timestamp"] - start_time) // window_seconds).astype(int))
    frames_per_window = tracks.groupby("window")["frame_idx"].nunique()

    outfield = tracks[
        (_roles(tracks) == "player")
        & tracks["team"].isin([config.TEAM_A, config.TEAM_B])
        & tracks["pitch_x"].notna()
    ]
    outfield = to_attacking_frame(outfield, sides)

    # How many windows in a row a new formation must win before we switch to it.
    windows_needed = max(1, int(np.ceil(min_stable_seconds / window_seconds)))
    window_rows, position_rows = [], []
    for team, team_rows in outfield.groupby("team"):
        current: str | None = None
        challenger, challenger_wins = None, 0  # the formation trying to take over
        for window, rows in team_rows.groupby("window"):
            per_player = rows.groupby("tracker_id").agg(
                depth=("depth", "mean"), width=("width", "mean"),
                pitch_x=("pitch_x", "mean"), pitch_y=("pitch_y", "mean"),
                frames=("frame_idx", "nunique"),
            )
            per_player["presence"] = per_player["frames"] / frames_per_window[window]
            # Keep the 10 most visible; more than 10 means a duplicated ID.
            players = per_player[per_player["presence"] >= min_presence].nlargest(10, "presence")

            row = {
                "team": int(team), "window": int(window),
                "start": start_time + window * window_seconds,
                "end": start_time + (window + 1) * window_seconds,
                "n_players": len(players), "formation": None, "best_match": None,
                "cost": np.nan, "runner_up": None, "confidence_margin": np.nan,
                "defends": sides.get(int(team)),
            }
            if len(players) >= min_players:
                costs = match_formation(players[["depth", "width"]].to_numpy(), formations)
                best, runner_up = sorted(costs, key=costs.get)[:2]
                if current is None:
                    current = best
                elif best != current and costs[current] - costs[best] > switch_margin:
                    # Clearly better than the current formation: count how many
                    # windows in a row it stays the best, and switch once it
                    # has lasted long enough.
                    challenger_wins = challenger_wins + 1 if best == challenger else 1
                    challenger = best
                    if challenger_wins >= windows_needed:
                        current, challenger, challenger_wins = best, None, 0
                else:
                    challenger, challenger_wins = None, 0
                row.update(
                    formation=current, best_match=best, cost=costs[current], runner_up=runner_up,
                    # Small margins mean the shape sits between two templates.
                    confidence_margin=costs[runner_up] - costs[best],
                )
            window_rows.append(row)
            position_rows.append(players.reset_index().assign(team=int(team), window=int(window)))

    positions = pd.concat(position_rows, ignore_index=True) if position_rows else pd.DataFrame()
    return FormationResult(pd.DataFrame(window_rows), positions)
