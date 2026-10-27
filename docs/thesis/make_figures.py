"""Charts and algorithm illustrations for the thesis (matplotlib).

Run with the worker's Python environment from the repository root, so the
pipeline's own code (pitch geometry, formation templates) is used:

    venv/Scripts/python docs/thesis/make_figures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Ellipse, FancyBboxPatch
from scipy.optimize import linear_sum_assignment

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "worker"))
from src import config  # noqa: E402
from src.clustering import _normalise_shape, formation_template  # noqa: E402
from src.homography import PitchDimensions  # noqa: E402

OUT = Path(__file__).parent / "figures"
RESULTS = REPO / "storage" / "results"
SHOWCASE = "cmvqif0ab000031o34exw7hnz"  # Bundesliga clip 1 (sample)
CLIPS = {
    "Clip 1 (sample)": "cmvqif0ab000031o34exw7hnz",
    "Clip 2 (08fd33_0)": "cmvqif0od000131o3tfgh10iu",
    "Clip 3 (121364_0)": "cmvqif109000231o3gmz8aqn1",
    "Clip 4 (2e57b9_0)": "cmvqif1d4000331o3x0rg09x1",
    "Clip 5 (573e61_0)": "cmvqif1mz000431o3yzva2zv8",
}
plt.rcParams.update({"font.family": "Segoe UI", "font.size": 10, "figure.dpi": 200})
GRASS, LINE = "#3f8f4a", "white"


def draw_pitch(ax, pitch: PitchDimensions) -> None:
    ax.add_patch(plt.Rectangle((-3, -3), pitch.length + 6, pitch.width + 6, color=GRASS, zorder=0))
    for segment in pitch.line_segments():
        ax.plot(segment[:, 0], segment[:, 1], color=LINE, lw=1.2, zorder=1)
    ax.set_xlim(-4, pitch.length + 4)
    ax.set_ylim(-4, pitch.width + 4)
    ax.set_aspect("equal")
    ax.axis("off")


def pitch_keypoints() -> None:
    pitch = PitchDimensions()
    fig, ax = plt.subplots(figsize=(8, 5.4))
    draw_pitch(ax, pitch)
    for i, (x, y) in enumerate(pitch.keypoints, start=1):
        ax.scatter(x, y, s=60, color="#facc15", edgecolor="black", zorder=3)
        ax.annotate(str(i), (x, y), xytext=(4, 4), textcoords="offset points", fontsize=8,
                    color="white", weight="bold", zorder=4)
    ax.set_title("The 32 pitch landmarks located by the keypoint model (pitch metres)")
    ax.text(0, -3.6, "x = 0 m", color="white", fontsize=8)
    ax.text(pitch.length - 8, -3.6, "x = 105 m", color="white", fontsize=8)
    fig.savefig(OUT / "pitch_keypoints.png", bbox_inches="tight")
    plt.close(fig)


def formation_templates() -> None:
    fig, axes = plt.subplots(3, 3, figsize=(8, 8))
    for ax, name in zip(axes.flat, config.FORMATIONS):
        slots = formation_template(name)
        ax.add_patch(plt.Rectangle((-0.1, -0.1), 1.2, 1.2, color=GRASS))
        ax.scatter(slots[:, 1], slots[:, 0], s=90, color="white", edgecolor="black", zorder=3)
        ax.set_title(name, fontsize=11, weight="bold")
        ax.set_xlim(-0.12, 1.12)
        ax.set_ylim(-0.12, 1.12)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle("Formation templates (depth 0 = defensive line, bottom; width across)", y=0.995)
    fig.tight_layout()
    fig.savefig(OUT / "formation_templates.png", bbox_inches="tight")
    plt.close(fig)


def formation_matching() -> None:
    """Re-run the matching for one real window of clip 1 and draw the assignment."""
    results = json.loads((RESULTS / f"{SHOWCASE}.json").read_text(encoding="utf-8"))
    pitch = PitchDimensions()
    window = next(w for w in results["formations"]["windows"] if w["formation"] and w["team"] == 1)
    defends = {t["id"]: t["defends"] for t in results["teams"]}
    positions: dict[int, list[tuple[float, float]]] = {}
    for frame in results["frames"]:
        if not window["start"] <= frame["t"] < window["end"]:
            continue
        for pid, team, role, *_box, px, py in frame["p"]:
            if team == window["team"] and role == 0 and px is not None:
                positions.setdefault(pid, []).append((px, py))
    frames = sum(window["start"] <= f["t"] < window["end"] for f in results["frames"])
    means = [np.mean(v, axis=0) for v in positions.values() if len(v) >= 0.5 * frames]
    means = sorted(means, key=lambda m: -len(m))[:10]
    points = np.array(means)
    if defends[window["team"]] == "right":  # rotate so the team attacks upwards
        points = np.column_stack([pitch.length - points[:, 0], pitch.width - points[:, 1]])
    observed = _normalise_shape(np.column_stack([points[:, 0], points[:, 1]]))

    fig, axes = plt.subplots(1, 2, figsize=(9, 4.6), gridspec_kw={"width_ratios": [1.4, 1]})
    for ax, name in zip(axes, [window["formation"], window["runnerUp"]]):
        template = formation_template(name)
        dist = np.linalg.norm(observed[:, None, :] - template[None, :, :], axis=2)
        rows, cols = linear_sum_assignment(dist)
        ax.add_patch(plt.Rectangle((-0.1, -0.1), 1.2, 1.2, color=GRASS))
        for r, c in zip(rows, cols):
            ax.plot([observed[r, 1], template[c, 1]], [observed[r, 0], template[c, 0]], color="#facc15", lw=1.5)
        ax.scatter(template[:, 1], template[:, 0], s=110, facecolor="none", edgecolor="white", lw=2, label="template slot")
        ax.scatter(observed[:, 1], observed[:, 0], s=60, color="#ef4444", edgecolor="black", zorder=3, label="player (mean position)")
        ax.set_title(f"{name}: mean distance {dist[rows, cols].mean():.3f}")
        ax.set_xlim(-0.12, 1.12)
        ax.set_ylim(-0.12, 1.12)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
    legend = axes[0].legend(loc="lower center", bbox_to_anchor=(0.5, -0.22), ncol=2, fontsize=8, facecolor=GRASS, edgecolor=GRASS)
    for text in legend.get_texts():
        text.set_color("white")
    fig.suptitle(f"Clip 1, Team B, {window['start']:.0f}–{window['end']:.0f} s: best template vs runner-up")
    fig.tight_layout()
    fig.savefig(OUT / "formation_matching.png", bbox_inches="tight")
    plt.close(fig)


def performance() -> None:
    labels = ["3 s clip, Quick", "30 s clip, Standard"]
    cpu = [60, 25 * 60]  # laptop i7-1255U (44-75 s; ~25 min)
    gpu = [5.1, 40]  # RunPod NVIDIA L4
    fig, ax = plt.subplots(figsize=(7, 3.4))
    y = np.arange(len(labels))
    ax.barh(y + 0.2, cpu, height=0.38, color="#94a3b8", label="Laptop CPU (Intel i7-1255U)")
    ax.barh(y - 0.2, gpu, height=0.38, color="#10b981", label="Cloud GPU (NVIDIA L4)")
    for yi, c, g in zip(y, cpu, gpu):
        ax.text(c * 1.1, yi + 0.2, f"{c / 60:.0f} min" if c >= 120 else f"~{c:.0f} s", va="center")
        ax.text(g * 1.1, yi - 0.2, f"{g:.0f} s  ({c / g:.0f}× faster)", va="center")
    ax.set_xscale("log")
    ax.set_xlim(1, 20000)
    ax.set_yticks(y, labels)
    ax.set_xlabel("Processing time (seconds, logarithmic scale)")
    ax.legend(loc="lower right", frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "performance.png", bbox_inches="tight")
    plt.close(fig)


def use_case_diagram() -> None:
    fig, ax = plt.subplots(figsize=(9, 7.2))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 8.4)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((2.2, 0.2), 5.6, 8.0, boxstyle="round,pad=0.02", fc="#f8fafc", ec="#475569"))
    ax.text(5.0, 7.95, "Tactical Eye", ha="center", weight="bold", fontsize=12)

    def actor(x, y, name):
        ax.add_patch(plt.Circle((x, y + 0.42), 0.13, fill=False, lw=1.5))
        ax.plot([x, x], [y + 0.29, y - 0.05], color="black", lw=1.5)
        ax.plot([x - 0.22, x + 0.22], [y + 0.18, y + 0.18], color="black", lw=1.5)
        ax.plot([x, x - 0.18], [y - 0.05, y - 0.35], color="black", lw=1.5)
        ax.plot([x, x + 0.18], [y - 0.05, y - 0.35], color="black", lw=1.5)
        ax.text(x, y - 0.6, name, ha="center", va="top", fontsize=9)

    def case(x, y, text):
        ax.add_patch(Ellipse((x, y), 2.5, 0.52, fc="white", ec="#0f766e", lw=1.3))
        ax.text(x, y, text, ha="center", va="center", fontsize=8.2)
        return x, y

    user_cases = ["Log out", "Upload match video", "Follow progress live", "List own matches",
                  "Watch video with overlays", "Toggle layers / heatmaps", "Inspect a player",
                  "View summary & formations", "Generate AI coaching report", "Re-analyse match",
                  "Delete match"]
    left = [(name, 7.3 - 0.62 * i) for i, name in enumerate(user_cases)]
    right = [("Register", 7.3), ("Log in", 6.65), ("Analyse video", 5.0), ("Report progress", 4.35),
             ("Deploy with Docker", 2.75), ("Check /api/health", 2.1), ("Enable GPU / LLM", 1.45)]
    pos = {name: case(3.6, y, name) for name, y in left} | {name: case(6.4, y, name) for name, y in right}

    user, worker = "Registered user\n(coach / analyst)", "AI worker\n(system)"
    actors = {user: (0.8, 4.2), "Visitor": (9.2, 6.8), worker: (9.2, 4.5), "Operator": (9.2, 1.9)}
    for name, (x, y) in actors.items():
        actor(x, y, name)
    links = {
        "Visitor": ["Register", "Log in"],
        user: user_cases,
        worker: ["Analyse video", "Report progress"],
        "Operator": ["Deploy with Docker", "Check /api/health", "Enable GPU / LLM"],
    }
    for name, cases in links.items():
        ax0, ay0 = actors[name]
        for c in cases:
            cx, cy = pos[c]
            edge = cx - 1.25 if cx > ax0 else cx + 1.25
            ax.plot([ax0 + (0.3 if cx > ax0 else -0.3), edge], [ay0 + 0.1, cy], color="#64748b", lw=0.8)
    fig.savefig(OUT / "usecase.png", bbox_inches="tight")
    plt.close(fig)


def clip_statistics() -> None:
    """Print the per-clip numbers used in the testing chapter."""
    for label, match_id in CLIPS.items():
        r = json.loads((RESULTS / f"{match_id}.json").read_text(encoding="utf-8"))
        windows = r["formations"]["windows"]
        classified = [w for w in windows if w["formation"]]
        players = [p for p in r["players"] if p["role"] == "player"]
        per_team = {t: sum(p["team"] == t for p in players) for t in (0, 1)}
        unassigned = sum(p["team"] == -1 for p in players)
        ball = sum(f["b"] is not None for f in r["frames"]) / len(r["frames"])
        print(f"{label}: frames={len(r['frames'])} validH={r['homography']['validShare']} "
              f"reprojErr={r['homography']['meanReprojectionErrorM']} tracks/team={per_team} "
              f"unassigned={unassigned} windows={len(classified)}/{len(windows)} "
              f"changes={len(r['formations']['changes'])} ballRows={ball:.2f} "
              f"margins={[w['confidenceMargin'] for w in classified]}")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    pitch_keypoints()
    formation_templates()
    formation_matching()
    performance()
    use_case_diagram()
    clip_statistics()
