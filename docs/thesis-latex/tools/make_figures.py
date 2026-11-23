"""Charts and algorithm illustrations for the thesis (matplotlib).

Vector PDFs for the LaTeX thesis (figures/*.pdf). Run with the worker's Python
environment from the repository root, so the
pipeline's own code (pitch geometry, formation templates) is used:

    venv/Scripts/python docs/thesis-latex/tools/make_figures.py
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

REPO = Path(__file__).resolve().parents[3]  # docs/thesis-latex/tools -> repository root
sys.path.insert(0, str(REPO / "worker"))
from src import config  # noqa: E402
from src.clustering import _normalise_shape, formation_template  # noqa: E402
from src.homography import PitchDimensions  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "figures"
RESULTS = REPO / "storage" / "results"
SHOWCASE = "cmw1hnfoj000130rve1d3g2s7"  # Bundesliga clip 1 (sample)
CLIPS = {
    "Clip 1 (sample)": "cmw1hnfoj000130rve1d3g2s7",
    "Clip 2 (08fd33_0)": "cmw1hnfxm000230rvzjwi8jlh",
    "Clip 3 (121364_0)": "cmw1hng61000330rvlu25c485",
    "Clip 4 (2e57b9_0)": "cmw1hngfd000430rvsi9fr1eh",
    "Clip 5 (573e61_0)": "cmw1hngo5000530rvrknmt5li",
}
# TrueType fonts embedded in the PDF (type 42), so the text stays selectable and sharp.
plt.rcParams.update({"font.family": "Arial", "font.size": 13, "figure.dpi": 200, "pdf.fonttype": 42})
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
        ax.annotate(str(i), (x, y), xytext=(4, 4), textcoords="offset points", fontsize=10.5,
                    color="white", weight="bold", zorder=4)
    ax.set_title("The 32 pitch landmarks located by the keypoint model (pitch metres)")
    ax.text(0, -3.6, "x = 0 m", color="white", fontsize=10.5)
    ax.text(pitch.length - 8, -3.6, "x = 105 m", color="white", fontsize=10.5)
    fig.savefig(OUT / "pitch_keypoints.pdf", bbox_inches="tight")
    plt.close(fig)


def formation_templates() -> None:
    fig, axes = plt.subplots(3, 3, figsize=(8, 8))
    for ax, name in zip(axes.flat, config.FORMATIONS):
        slots = formation_template(name)
        ax.add_patch(plt.Rectangle((-0.1, -0.1), 1.2, 1.2, color=GRASS))
        ax.scatter(slots[:, 1], slots[:, 0], s=90, color="white", edgecolor="black", zorder=3)
        ax.set_title(name, fontsize=14, weight="bold")
        ax.set_xlim(-0.12, 1.12)
        ax.set_ylim(-0.12, 1.12)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle("Formation templates (depth 0 = defensive line, bottom; width across)", y=0.995)
    fig.tight_layout()
    fig.savefig(OUT / "formation_templates.pdf", bbox_inches="tight")
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
        # Person rows: [id, team, role, x1, y1, x2, y2, pitchX, pitchY, position?]
        for row in frame["p"]:
            pid, team, role, px, py = row[0], row[1], row[2], row[7], row[8]
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
    legend = axes[0].legend(loc="lower center", bbox_to_anchor=(0.5, -0.22), ncol=2, fontsize=10.5, facecolor=GRASS, edgecolor=GRASS)
    for text in legend.get_texts():
        text.set_color("white")
    fig.suptitle(f"Clip 1, Team B, {window['start']:.0f}–{window['end']:.0f} s: best template vs runner-up")
    fig.tight_layout()
    fig.savefig(OUT / "formation_matching.pdf", bbox_inches="tight")
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
    fig.savefig(OUT / "performance.pdf", bbox_inches="tight")
    plt.close(fig)


def use_case_diagram() -> None:
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 8.6)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((2.15, 0.2), 6.75, 8.2, boxstyle="round,pad=0.02", fc="#f8fafc", ec="#475569"))
    ax.text(5.5, 8.12, "Tactical Eye", ha="center", weight="bold", fontsize=15)

    def actor(x, y, name):
        ax.add_patch(plt.Circle((x, y + 0.42), 0.13, fill=False, lw=1.5))
        ax.plot([x, x], [y + 0.29, y - 0.05], color="black", lw=1.5)
        ax.plot([x - 0.22, x + 0.22], [y + 0.18, y + 0.18], color="black", lw=1.5)
        ax.plot([x, x - 0.18], [y - 0.05, y - 0.35], color="black", lw=1.5)
        ax.plot([x, x + 0.18], [y - 0.05, y - 0.35], color="black", lw=1.5)
        ax.text(x, y - 0.6, name, ha="center", va="top", fontsize=11.5)

    # Each use case is an oval; the two columns have room for the larger print text.
    widths = {}
    def case(x, y, text, width):
        ax.add_patch(Ellipse((x, y), width, 0.55, fc="white", ec="#0f766e", lw=1.3))
        ax.text(x, y, text, ha="center", va="center", fontsize=10.5)
        widths[text] = width
        return x, y

    user_cases = ["Log out", "Upload match video", "Follow progress live", "Cancel analysis",
                  "List own matches", "Watch video with overlays", "Toggle layers / heatmaps",
                  "Inspect a position", "View summary & formations", "Generate AI coaching report",
                  "Re-analyse match", "Delete match"]
    left = [(name, 7.55 - 0.62 * i) for i, name in enumerate(user_cases)]
    right = [("Register", 7.4), ("Log in", 6.75), ("Analyse video", 5.0), ("Report progress", 4.35),
             ("Deploy with Docker", 2.75), ("Check /api/health", 2.1), ("Enable GPU / LLM", 1.45)]
    pos = {name: case(4.0, y, name, 3.3) for name, y in left} | {name: case(7.4, y, name, 2.55) for name, y in right}

    user, worker = "Registered user\n(coach / analyst)", "AI worker\n(system)"
    actors = {user: (0.9, 4.2), "Visitor": (10.1, 6.9), worker: (10.1, 4.5), "Operator": (10.1, 1.9)}
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
            edge = cx - widths[c] / 2 if cx > ax0 else cx + widths[c] / 2
            ax.plot([ax0 + (0.3 if cx > ax0 else -0.3), edge], [ay0 + 0.1, cy], color="#64748b", lw=0.8)
    fig.savefig(OUT / "usecase.pdf", bbox_inches="tight")
    plt.close(fig)


def long_video_stages() -> None:
    """Where the time goes on a full half (NVIDIA L4), per pipeline stage.

    Seconds measured by the worker (summary.stageSeconds) on 4 November 2026.
    """
    stages = ["Playback copy (CPU)", "Detection + tracking", "Pitch mapping", "Teams", "Tactics", "Saving"]
    halves = {
        "Barcelona – Real Madrid\n47:20 · 1080p · 25 fps": [910.5, 1900.7, 259.3, 94.5, 38.5, 32.1],
        "PSG – Barcelona\n48:14 · 720p · 50 fps": [661.1, 1851.1, 231.5, 91.2, 41.6, 33.0],
    }
    colours = ["#94a3b8", "#10b981", "#0ea5e9", "#f59e0b", "#a855f7", "#64748b"]
    fig, ax = plt.subplots(figsize=(7.2, 3.3))
    for row, (label, seconds) in enumerate(halves.items()):
        left = 0.0
        for stage, value, colour in zip(stages, seconds, colours):
            ax.barh(row, value / 60, left=left, color=colour, height=0.55, label=stage if row == 0 else None)
            if value > 200:
                ax.text(left + value / 120, row, f"{value / 60:.1f}", ha="center", va="center", color="white", fontsize=11.5)
            left += value / 60
        ax.text(left + 0.6, row, f"{left:.0f} min", va="center", fontsize=11.5)
    ax.set_yticks(range(len(halves)), list(halves))
    ax.invert_yaxis()
    ax.set_xlabel("Processing time on an NVIDIA L4 (minutes)")
    ax.set_xlim(0, 62)
    ax.legend(ncol=3, fontsize=10.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.3))
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "long_video_stages.pdf", bbox_inches="tight")
    plt.close(fig)


def camera_wobble() -> None:
    """Camera-model wobble on the first half before and after smoothing."""
    data = json.loads((Path(__file__).parent / "data" / "camera_wobble.json").read_text(encoding="utf-8"))
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    ax.plot(data["before"], data["percentiles"], color="#ef4444", label="fitted per frame (before)")
    ax.plot(data["after"], data["percentiles"], color="#10b981", label="smoothed over 1.5 s (after)")
    ax.set_xscale("log")
    ax.set_xlim(0.5, 3000)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Wobble of the drawing between camera updates (pixels, log scale)")
    ax.set_ylabel("Share of updates (%)")
    for q in (95,):
        index = data["percentiles"].index(q)
        for key, colour in (("before", "#ef4444"), ("after", "#10b981")):
            ax.plot(data[key][index], q, "o", color=colour)
            ax.annotate(f"{data[key][index]:.0f} px", (data[key][index], q), textcoords="offset points",
                        xytext=(6, -12), fontsize=10.5, color=colour)
    ax.axhline(95, color="#cbd5e1", lw=0.8, ls="--")
    ax.legend(frameon=False, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "camera_wobble.pdf", bbox_inches="tight")
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


def wireframes() -> None:
    """Simple screen plans of the four main pages: grey boxes with labels, no styling."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 7.6))

    def box(ax, x, y, w, h, text="", dashed=False, filled=False, size=11):
        # One labelled rectangle of a wireframe (coordinates: 0-100 wide, 0-62 high)
        ax.add_patch(plt.Rectangle((x, y), w, h, fill=filled, facecolor="#d9d9d9", edgecolor="#555",
                                   linewidth=1.2, linestyle="--" if dashed else "-"))
        if text:
            ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size, color="#222")

    def page(ax, title, header=True):
        # Browser frame of a page, with the shared header bar when logged in
        ax.set_xlim(0, 100), ax.set_ylim(0, 62), ax.set_aspect("equal"), ax.axis("off")
        ax.set_title(title, fontsize=14, pad=6)
        box(ax, 0, 0, 100, 62)
        if header:
            box(ax, 0, 56, 100, 6, filled=True)
            ax.text(2, 59, "Tactical Eye   Matches   Upload", va="center", fontsize=10)
            ax.text(98, 59, "name · Log out", va="center", ha="right", fontsize=10)

    # (a) Log-in page: illustration on the left, form on the right
    ax = axes[0][0]
    page(ax, "(a) Log in / register", header=False)
    box(ax, 4, 6, 42, 50, "chalk pitch\nillustration", dashed=True)
    ax.text(58, 50, "Log in", fontsize=12, weight="bold")
    box(ax, 58, 38, 36, 6, "E-mail")
    box(ax, 58, 29, 36, 6, "Password")
    box(ax, 58, 19, 36, 6, "Log in", filled=True)
    ax.text(58, 11, "New here? Create an account", fontsize=10)

    # (b) Match list: one row per match
    ax = axes[0][1]
    page(ax, "(b) Match list")
    ax.text(4, 50, "Matches", fontsize=12, weight="bold")
    box(ax, 74, 47, 22, 6, "+ Upload a match", filled=True, size=10)
    for i, y in enumerate((36, 27, 18, 9)):
        box(ax, 4, y, 92, 8)
        ax.text(6, y + 4, "title · date · size", va="center", fontsize=10)
        ax.text(43, y + 4, "formations", va="center", fontsize=10)
        ax.text(62, y + 4, "status", va="center", fontsize=10, style="italic")
        ax.text(73, y + 4, "Delete", va="center", fontsize=10)
        box(ax, 84, y + 1.5, 11, 5, "Open", size=9)

    # (c) Upload page: three numbered steps and a tips box
    ax = axes[1][0]
    page(ax, "(c) Upload")
    ax.text(4, 51, "Upload a match", fontsize=12, weight="bold")
    box(ax, 4, 34, 62, 13, "1  drop or choose the video", dashed=True)
    box(ax, 4, 24, 62, 6, "2  title")
    box(ax, 4, 13, 30, 8, "3  Standard", size=10)
    box(ax, 36, 13, 30, 8, "Quick", size=10)
    box(ax, 4, 3, 30, 7, "Upload and analyse", filled=True, size=10)
    box(ax, 70, 24, 26, 23, "tips for\ngood results", dashed=True, size=10)

    # (d) Match page: video with controls, tactical board, tabs
    ax = axes[1][1]
    page(ax, "(d) Analysis of a match")
    ax.text(4, 51, "Match title · status", fontsize=12, weight="bold")
    box(ax, 80, 49, 16, 5, "Re-analyse", size=10)
    box(ax, 4, 22, 58, 25, "video with overlays\n(full-screen button)")
    box(ax, 4, 16, 58, 5, "play · ±1 frame · seek bar · speed", size=9)
    box(ax, 4, 10, 58, 5, "layer buttons", size=9)
    box(ax, 65, 22, 31, 25, "tactical board")
    box(ax, 65, 10, 15, 11, "formation\nTeam A", size=9)
    box(ax, 81, 10, 15, 11, "formation\nTeam B", size=9)
    box(ax, 4, 2, 92, 6, "tabs: Summary · Player · AI coaching report", size=10)

    fig.tight_layout()
    fig.savefig(OUT / "wireframes.pdf", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    # Figures can be named on the command line to rebuild only those, e.g. "wireframes"
    selected = sys.argv[1:]
    for figure in (pitch_keypoints, formation_templates, formation_matching, performance,
                   use_case_diagram, long_video_stages, camera_wobble, wireframes):
        if not selected or figure.__name__ in selected:
            figure()
    if not selected:
        clip_statistics()
