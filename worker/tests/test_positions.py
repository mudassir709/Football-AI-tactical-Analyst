"""Position labels and finding referees by their kit colour."""

import numpy as np
import pandas as pd

from src.clustering import find_referees
from src.positions import slot_names


def test_slot_names_match_the_template_order():
    # Templates list each line from the team's right to its left.
    assert slot_names("4-4-2") == ["RB", "RCB", "LCB", "LB", "RM", "RCM", "LCM", "LM", "RS", "LS"]
    assert slot_names("4-2-3-1")[4:] == ["RDM", "LDM", "RAM", "AM", "LAM", "ST"]
    assert all(len(slot_names(f)) == 10 for f in ("4-3-3", "3-5-2", "5-4-1", "4-1-4-1"))


def test_a_player_wearing_the_referee_kit_is_found():
    # Lab colours: referees in mint, Team A in white, Team B in dark.
    mint, white, dark = (180, 105, 130), (205, 125, 140), (85, 126, 136)
    colours = {1: mint, 2: mint, 10: white, 11: dark, 12: mint}  # 12 is the referee, called "player"
    jerseys = pd.DataFrame(
        [(i, *c) for i, c in colours.items() for _ in range(3)],
        columns=["tracker_id", "L", "a", "b"],
    )
    roles = pd.Series({1: "referee", 2: "referee", 10: "player", 11: "player", 12: "player"})
    assert find_referees(jerseys, roles, np.array([white, dark], dtype=float)) == {12}


def test_a_goalkeeper_in_their_box_stays_a_goalkeeper():
    # Regression test: goalkeepers wear a kit unlike both teams, so on the
    # demo clips some were turned into referees by the colour test alone.
    mint, white, dark, keeper = (180, 105, 130), (205, 125, 140), (85, 126, 136), (175, 110, 128)
    colours = {1: mint, 10: white, 11: dark, 20: keeper, 21: keeper}
    jerseys = pd.DataFrame(
        [(i, *c) for i, c in colours.items() for _ in range(3)],
        columns=["tracker_id", "L", "a", "b"],
    )
    roles = pd.Series({1: "referee", 10: "player", 11: "player", 20: "goalkeeper", 21: "goalkeeper"})
    # Track 20 stands in front of its goal; track 21 in midfield (a referee the model got wrong).
    usual = pd.DataFrame({"pitch_x": [3.0, 50.0], "pitch_y": [34.0, 30.0]}, index=[20, 21])
    found = find_referees(jerseys, roles, np.array([white, dark], dtype=float), usual_positions=usual)
    assert found == {21}
