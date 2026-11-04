"""Position labels for players: LB, LCB, DM, ST...

With one broadcast camera the tracker cannot keep the same number for a player
all match: the camera follows the ball, so players keep leaving the picture
and come back as someone "new" (shirt numbers are unreadable at this size).
Instead, every player is labelled with the position they play in their team's
formation. The formation step already matches each team's shape to a
template every few seconds; here we also note which slot of the template each
player filled, and use that as their label. Stats and heatmaps are then worked
out per position ("Real Madrid's left back"), which is also how coaches talk
about tactics.

The label follows the position, not the person: if two players swap sides,
their labels swap too.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from src import config
from src.clustering import FormationResult, _normalise_shape, formation_template

# Names of the players in one line of a formation, from left to right as the
# team sees it (attacking forwards). The first line is the defence and the
# last the attack; formations with four lines (4-2-3-1, 4-1-4-1) have a
# deeper ("holding") and a more advanced midfield line.
DEFENCE = {3: ["LCB", "CB", "RCB"], 4: ["LB", "LCB", "RCB", "RB"], 5: ["LWB", "LCB", "CB", "RCB", "RWB"]}
MIDFIELD = {2: ["LCM", "RCM"], 3: ["LCM", "CM", "RCM"], 4: ["LM", "LCM", "RCM", "RM"],
            5: ["LM", "LCM", "CM", "RCM", "RM"]}
HOLDING = {1: ["DM"], 2: ["LDM", "RDM"], 3: ["LDM", "DM", "RDM"]}
ADVANCED = {1: ["AM"], 2: ["LAM", "RAM"], 3: ["LAM", "AM", "RAM"], 4: ["LM", "LCM", "RCM", "RM"]}
ATTACK = {1: ["ST"], 2: ["LS", "RS"], 3: ["LW", "ST", "RW"]}

# Labels for goalkeepers and referees, who are not part of the formation.
GOALKEEPER, REFEREE = "GK", "REF"
# Order in which positions are listed: goalkeeper, then defence to attack,
# each line from left to right.
POSITION_ORDER: list[str] = [
    GOALKEEPER, "LWB", "LB", "LCB", "CB", "RCB", "RB", "RWB", "LDM", "DM", "RDM",
    "LM", "LCM", "CM", "RCM", "RM", "LAM", "AM", "RAM", "LW", "LS", "ST", "RS", "RW",
]

# A player's label is the most common one over this many formation windows
# around them, so it does not flicker between e.g. LCM and RCM.
SMOOTHING_WINDOWS: int = 5


def slot_names(formation: str) -> list[str]:
    """Position names in the same order as ``formation_template(formation)``.

    The template lists each line from width 0 to width 1. Width grows towards
    the team's left (see to_attacking_frame), so each line's names, written
    left to right above, are reversed.
    """
    lines = [int(n) for n in formation.split("-")]
    names: list[str] = []
    for i, count in enumerate(lines):
        if i == 0:
            table = DEFENCE
        elif i == len(lines) - 1:
            table = ATTACK
        elif len(lines) == 3:
            table = MIDFIELD
        else:
            table = HOLDING if i == 1 else ADVANCED
        line = table.get(count) or [f"M{i}{k + 1}" for k in range(count)]  # unusual shapes
        names.extend(reversed(line))
    return names


def main_formations(formations: FormationResult) -> dict[int, str]:
    """Each team's most common formation over the whole video."""
    classified = formations.windows.dropna(subset=["formation"])
    return {int(team): rows.mode().iat[0] for team, rows in classified.groupby("team")["formation"]}


def _window_labels(formations: FormationResult) -> pd.DataFrame:
    """For every classified window, the position each visible player filled.

    The same matching as the formation step (Hungarian algorithm on the
    normalised shape), always against the team's main formation. That keeps
    the labels to the 10 outfield positions of one shape per team (plus GK),
    instead of mixing names from every formation tried during the match. The
    formation timeline still shows when the shape changed.
    """
    classified = formations.windows.dropna(subset=["formation"]).set_index(["team", "window"])
    main = main_formations(formations)
    rows = []
    for (team, window), players in formations.positions.groupby(["team", "window"]):
        formation = main.get(int(team))
        if (team, window) not in classified.index or formation is None or len(players) < 2:
            continue
        observed = _normalise_shape(players[["depth", "width"]].to_numpy())
        template = formation_template(formation)
        distances = np.linalg.norm(observed[:, None, :] - template[None, :, :], axis=2)
        player_rows, slots = linear_sum_assignment(distances)
        names = slot_names(formation)
        for r, s in zip(player_rows, slots):
            rows.append((int(players["tracker_id"].iat[r]), int(window), names[s]))
    return pd.DataFrame(rows, columns=["tracker_id", "window", "label"])


def assign_positions(
    tracks: pd.DataFrame,
    formations: FormationResult | None,
    window_seconds: float = config.FORMATION_WINDOW_SECONDS,
) -> pd.Series:
    """A position label for every row: "LB", "ST"..., "GK", "REF", or None.

    Steps:
      1. each formation window gives the visible players a slot (see above);
      2. per player track, smooth the labels over neighbouring windows;
      3. windows where the track was not matched (too few players visible,
         or the player was only briefly in view) take the label from the
         nearest matched window of the same track;
      4. no label is used twice at the same moment in one team.
    Tracks that were never matched get no label.
    """
    labels = pd.Series(None, index=tracks.index, dtype=object)
    labels[tracks["role"] == "goalkeeper"] = GOALKEEPER
    labels[tracks["role"] == "referee"] = REFEREE
    if formations is None or formations.positions.empty:
        return labels

    matched = _window_labels(formations)
    if matched.empty:
        return labels

    # Same windows as detect_formations uses.
    start_time = tracks["timestamp"].min()
    window = ((tracks["timestamp"] - start_time) // window_seconds).astype(int)
    players = tracks[tracks["role"] == "player"]
    track_windows = (pd.DataFrame({"tracker_id": players["tracker_id"], "window": window[players.index]})
                     .drop_duplicates().sort_values(["tracker_id", "window"]))
    track_windows = track_windows.merge(matched, on=["tracker_id", "window"], how="left")

    def smooth(group: pd.DataFrame) -> pd.Series:
        known = group["label"]
        # Most common label among the nearest few matched windows...
        codes, names = pd.factorize(known)
        codes = pd.Series(np.where(codes < 0, np.nan, codes), index=group.index)
        common = codes.rolling(SMOOTHING_WINDOWS, center=True, min_periods=1).apply(
            lambda c: pd.Series(c).mode().iat[0] if pd.Series(c).notna().any() else np.nan, raw=True)
        # ...then fill unmatched windows from the nearest matched one.
        common = common.ffill().bfill()
        return common.map(lambda c: names[int(c)] if pd.notna(c) else None)

    track_windows["smoothed"] = track_windows.groupby("tracker_id", group_keys=False)[["label"]].apply(smooth)
    lookup = track_windows.set_index(["tracker_id", "window"])
    keys = pd.MultiIndex.from_arrays([players["tracker_id"], window[players.index]])
    found = lookup.reindex(keys)
    labels[players.index] = found["smoothed"].to_numpy()

    # 4. Smoothing and filling can give two players the same label at the same
    #    moment. Then the one who really filled that slot in this window keeps
    #    it (the longer track if both or neither did); the other gets none.
    rows = pd.DataFrame({
        "frame_idx": players["frame_idx"].to_numpy(), "team": players["team"].to_numpy(),
        "label": found["smoothed"].to_numpy(),
        "matched": (found["label"] == found["smoothed"]).to_numpy(),
        "track_rows": players["tracker_id"].map(players["tracker_id"].value_counts()).to_numpy(),
    }, index=players.index).dropna(subset=["label"])
    rows = rows.sort_values(["matched", "track_rows"], ascending=False)
    second = rows.duplicated(["frame_idx", "team", "label"], keep="first")
    labels[rows.index[second]] = None
    return labels
