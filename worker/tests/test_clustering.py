"""Shirt colour measurement and formation matching."""
import numpy as np
import pytest

from src import config
from src.clustering import formation_template, jersey_colour, local_grass_lab, match_formation

GRASS_BGR = (40, 120, 50)  # pitch green
LIME_BGR = (120, 245, 175)  # bright lime-green kit
RED_BGR = (40, 40, 200)


def player_on_grass(shirt_bgr: tuple[int, int, int]) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """A frame of grass with one 'player' box whose torso has the given colour."""
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    frame[:] = GRASS_BGR
    x1, y1, x2, y2 = 80, 40, 120, 160
    frame[y1 + 20:y1 + 60, x1 + 8:x2 - 8] = shirt_bgr
    return frame, (x1, y1, x2, y2)


@pytest.mark.parametrize("shirt", [RED_BGR, LIME_BGR])
def test_shirt_colour_is_measured_with_local_grass(shirt):
    frame, (x1, y1, x2, y2) = player_on_grass(shirt)
    grass = local_grass_lab(frame, x1, y1, x2, y2)
    colour = jersey_colour(frame[y1:y2, x1:x2], grass)
    expected = np.array(
        __import__("cv2").cvtColor(np.uint8([[shirt]]), __import__("cv2").COLOR_BGR2LAB)[0, 0], dtype=float
    )
    assert colour is not None
    assert np.linalg.norm(colour - expected) < 5


def test_fixed_green_range_loses_green_kits():
    # Documents why grass is measured locally: the old fixed range removes lime shirts.
    frame, (x1, y1, x2, y2) = player_on_grass(LIME_BGR)
    assert jersey_colour(frame[y1:y2, x1:x2], grass_lab=None) is None


@pytest.mark.parametrize("formation", config.FORMATIONS)
def test_formation_templates_have_ten_outfield_players(formation):
    assert formation_template(formation).shape == (10, 2)


@pytest.mark.parametrize("formation", config.FORMATIONS)
def test_noisy_formation_is_recognised(formation):
    rng = np.random.default_rng(0)
    # Scale the template to a realistic team shape in metres and add 1.5 m noise.
    positions = formation_template(formation) * [35, 50] + [20, 9] + rng.normal(0, 1.5, (10, 2))
    costs = match_formation(positions)
    assert min(costs, key=costs.get) == formation
