"""Compare manual annotations with the AI's results (the accuracy check).

Reads tests/accuracy/annotations.json (made with annotate.html) and the
analysis results of the same frames, and measures:

  - detection: how many annotated people the AI found (recall) and how many of
    its detections are real people (precision)
  - roles: player / goalkeeper / referee correct for the people it found
  - teams: share of players put in the right team
  - ball: in how many frames with a visible ball the AI had it
  - pitch positions in metres:
      * landmark error: manually clicked pitch landmarks are projected with the
        AI's camera model and compared with their true position on the pitch
      * player error: distance on the pitch between the AI's foot point and the
        clicked foot point

    python tests/accuracy/evaluate.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

HERE = Path(__file__).parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "worker"))
from src.homography import PitchDimensions  # noqa: E402

# A click counts as the same person as a detection if their foot points are at
# most this far apart (pixels in a 1080-pixel-high frame; scaled for others).
MATCH_DISTANCE_PX = 35
BALL_DISTANCE_PX = 20
ROLE_OF_LABEL = {"team1": 0, "team2": 0, "goalkeeper": 1, "referee": 2}
PEOPLE_LABELS = set(ROLE_OF_LABEL)


def image_to_pitch(pitch_to_image: list[float], points: np.ndarray) -> np.ndarray:
    """Project image pixels onto the pitch with the inverse of the frame's camera matrix."""
    h = np.linalg.inv(np.array(pitch_to_image).reshape(3, 3))
    homogeneous = np.c_[points, np.ones(len(points))] @ h.T
    return homogeneous[:, :2] / homogeneous[:, 2:]


def evaluate(annotation_file: Path) -> dict:
    data = json.loads(annotation_file.read_text(encoding="utf-8"))
    keypoints = PitchDimensions().keypoints
    results_cache: dict[str, dict] = {}

    totals = defaultdict(int)
    landmark_errors, player_errors = [], []
    # For team accuracy: per clip, how often "team1" matched AI team 0 / 1, etc.
    team_votes: dict[str, dict[tuple[str, int], int]] = defaultdict(lambda: defaultdict(int))

    for frame in data["frames"]:
        marks = data["annotations"].get(frame["file"], [])
        if not marks:
            continue  # this frame was not annotated
        if frame["matchId"] not in results_cache:
            path = REPO / "storage" / "results" / f"{frame['matchId']}.json"
            results_cache[frame["matchId"]] = json.loads(path.read_text(encoding="utf-8"))
        results = results_cache[frame["matchId"]]
        analysed = next(f for f in results["frames"] if f["f"] == frame["frame"])
        scale = frame["height"] / 1080
        totals["frames"] += 1

        # --- People: pair clicks with detections (Hungarian = best one-to-one pairing)
        clicked = [m for m in marks if m["label"] in PEOPLE_LABELS]
        detected = analysed["p"]  # [id, team, role, x1, y1, x2, y2, pitchX, pitchY]
        clicked_xy = np.array([[m["x"], m["y"]] for m in clicked], dtype=float).reshape(-1, 2)
        detected_xy = np.array([[(d[3] + d[5]) / 2, d[6]] for d in detected], dtype=float).reshape(-1, 2)
        pairs = []
        if len(clicked) and len(detected):
            distance = np.linalg.norm(clicked_xy[:, None] - detected_xy[None], axis=2)
            rows, cols = linear_sum_assignment(distance)
            pairs = [(r, c) for r, c in zip(rows, cols) if distance[r, c] <= MATCH_DISTANCE_PX * scale]
        totals["annotated_people"] += len(clicked)
        totals["detected_people"] += len(detected)
        totals["matched_people"] += len(pairs)

        for r, c in pairs:
            mark, detection = clicked[r], detected[c]
            totals["role_correct"] += ROLE_OF_LABEL[mark["label"]] == detection[2]
            if mark["label"] in ("team1", "team2"):
                totals["team_players"] += 1
                team_votes[frame["clip"]][(mark["label"], detection[1])] += 1

        # --- Pitch positions in metres (needs the frame's camera matrix)
        if analysed.get("h"):
            for r, c in pairs:
                both = np.array([clicked_xy[r], detected_xy[c]])
                on_pitch = image_to_pitch(analysed["h"], both)
                player_errors.append(float(np.linalg.norm(on_pitch[0] - on_pitch[1])))
            for mark in (m for m in marks if m["label"] == "landmark"):
                projected = image_to_pitch(analysed["h"], np.array([[mark["x"], mark["y"]]], dtype=float))[0]
                landmark_errors.append(float(np.linalg.norm(projected - keypoints[mark["landmark"] - 1])))

        # --- Ball
        ball_marks = [m for m in marks if m["label"] == "ball"]
        ai_ball = analysed["b"] if analysed["b"] and analysed["b"][0] is not None else None
        if ball_marks:
            totals["ball_visible"] += 1
            if ai_ball and np.hypot(ai_ball[0] - ball_marks[0]["x"], ai_ball[1] - ball_marks[0]["y"]) <= BALL_DISTANCE_PX * scale:
                totals["ball_found"] += 1
        elif ai_ball:
            totals["ball_false"] += 1

    # Team names are arbitrary ("team1" may be the AI's team 0 or 1), so per clip
    # use whichever pairing agrees best, then count the agreeing players.
    team_correct = 0
    for votes in team_votes.values():
        straight = votes[("team1", 0)] + votes[("team2", 1)]
        swapped = votes[("team1", 1)] + votes[("team2", 0)]
        team_correct += max(straight, swapped)

    def share(part: int, whole: int) -> float | None:
        return round(part / whole, 3) if whole else None

    def stats(values: list[float]) -> dict:
        if not values:
            return {"n": 0}
        return {"n": len(values), "mean": round(float(np.mean(values)), 2),
                "median": round(float(np.median(values)), 2), "p90": round(float(np.percentile(values, 90)), 2)}

    return {
        "frames": totals["frames"],
        "people": {
            "annotated": totals["annotated_people"], "detected": totals["detected_people"],
            "matched": totals["matched_people"],
            "recall": share(totals["matched_people"], totals["annotated_people"]),
            "precision": share(totals["matched_people"], totals["detected_people"]),
            "role_accuracy": share(totals["role_correct"], totals["matched_people"]),
        },
        "teams": {"players": totals["team_players"], "accuracy": share(team_correct, totals["team_players"])},
        "ball": {"visible": totals["ball_visible"], "found": totals["ball_found"],
                 "recall": share(totals["ball_found"], totals["ball_visible"]),
                 "reported_but_not_visible": totals["ball_false"]},
        "landmark_error_m": stats(landmark_errors),
        "player_position_error_m": stats(player_errors),
    }


def main() -> None:
    annotation_file = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "annotations.json"
    report = evaluate(annotation_file)
    (HERE / "accuracy_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
