"""Tests for the replay timeline data layer."""
from __future__ import annotations

import numpy as np
import pandas as pd

from cs_analyzer.replay.sides import side_for_round
from cs_analyzer.replay.timeline import build_timeline

from .conftest import S_ALICE, S_BOB, S_CAROL, S_DAVE, build_demo_data, build_parsed_demo


def _demo_with_ticks_and_events():
    ticks = pd.DataFrame(
        {
            "tick": [0, 128, 256, 384, 512],
            "steamid": [S_ALICE] * 5,
            "X": [0.0, 100.0, 200.0, 300.0, 400.0],
            "Y": [0.0, 10.0, 20.0, 30.0, 40.0],
            "is_alive": [True, True, True, True, False],
            "team_num": [3, 3, 3, 3, 3],
        }
    )
    deaths = pd.DataFrame(
        {
            "tick": [100, 300],
            "attacker_steamid": [S_ALICE, S_BOB],
            "user_steamid": [S_BOB, S_ALICE],
            "attacker_X": [50.0, 250.0],
            "attacker_Y": [5.0, 25.0],
            "user_X": [60.0, 260.0],
            "user_Y": [6.0, 26.0],
            "user_name": ["Bob", "Alice"],
            "weapon": ["ak47", "deagle"],
        }
    )
    shots = pd.DataFrame(
        {
            "tick": [120, 200],
            "user_steamid": [S_ALICE, S_ALICE],
            "user_X": [95.0, 150.0],
            "user_Y": [9.0, 15.0],
            "weapon": ["ak47", "pistol"],
        }
    )
    jumps = pd.DataFrame(
        {"tick": [150, 250], "user_steamid": [S_ALICE, S_ALICE]}
    )
    smoke = pd.DataFrame(
        {
            "tick": [180],
            "user_steamid": [S_ALICE],
            "x": [130.0],  # impact point (not thrower position)
            "y": [13.0],
            "user_X": [140.0],  # thrower position
            "user_Y": [14.0],
        }
    )
    demo = build_parsed_demo(
        events={
            "player_death": deaths,
            "weapon_fire": shots,
            "player_jump": jumps,
            "smokegrenade_detonate": smoke,
        },
        ticks=ticks,
    )
    return demo


def test_position_at_interpolation() -> None:
    demo = _demo_with_ticks_and_events()
    tl = build_timeline(demo, S_ALICE)
    # midpoint of tick 0->128: x = 50, y = 5
    assert tl.position_at(64.0) == (50.0, 5.0)
    # exact tick
    assert tl.position_at(256.0) == (200.0, 20.0)


def test_frame_positions_vectorized() -> None:
    demo = _demo_with_ticks_and_events()
    tl = build_timeline(demo, S_ALICE)
    xs, ys, alive = tl.frame_positions(np.array([0.0, 256.0, 512.0]))
    assert xs.tolist() == [0.0, 200.0, 400.0]
    assert ys.tolist() == [0.0, 20.0, 40.0]
    assert alive.tolist() == [True, True, False]


def test_side_at_tick_team_num() -> None:
    demo = _demo_with_ticks_and_events()
    tl = build_timeline(demo, S_ALICE)
    assert tl.side_at_tick(128) == "CT"  # team_num 3


def test_side_for_round_halftime() -> None:
    # Team starts CT; round 1 = CT, round 13 = T (after halftime), round 15 = CT? no: 13=T, 14=T...
    assert side_for_round(1, "CT") == "CT"
    assert side_for_round(12, "CT") == "CT"
    assert side_for_round(13, "CT") == "T"
    assert side_for_round(24, "CT") == "T"
    assert side_for_round(1, "T") == "T"
    assert side_for_round(13, "T") == "CT"


def test_side_for_round_overtime() -> None:
    # OT round 13 (= 1st OT round, ot_num=1) keeps starting side? swap=0
    assert side_for_round(13, "CT", is_overtime=True) == "CT"
    # OT round 19 (= ot_num 7) -> swap=1
    assert side_for_round(19, "CT", is_overtime=True) == "T"


def test_extract_shots_and_kills() -> None:
    demo = _demo_with_ticks_and_events()
    tl = build_timeline(demo, S_ALICE)
    assert [s.weapon for s in tl.shots] == ["ak47", "pistol"]
    assert tl.shots[0].x == 95.0
    # Alice's kill of Bob at tick 100
    assert len(tl.kills) == 1
    assert tl.kills[0].victim_name == "Bob"
    assert tl.kills[0].weapon == "ak47"
    # Alice's death at tick 300
    assert len(tl.deaths) == 1
    assert tl.deaths[0].tick == 300


def test_extract_jumps_no_position_uses_interpolation() -> None:
    demo = _demo_with_ticks_and_events()
    tl = build_timeline(demo, S_ALICE)
    assert len(tl.jumps) == 2
    # tick 150 between 128 (x=100) and 256 (x=200) -> x = 100 + 22/128*100
    assert tl.jumps[0].x == 100 + 22 / 128 * 100
    assert tl.jumps[0].y == 10 + 22 / 128 * 10
    assert tl.jumps[0].tick == 150


def test_utility_impact_point_used() -> None:
    demo = _demo_with_ticks_and_events()
    tl = build_timeline(demo, S_ALICE)
    smoke = tl.utilities.get("smoke", [])
    assert len(smoke) == 1
    # impact point is lowercase x/y (130), NOT thrower user_X (140)
    assert smoke[0].x == 130.0
    assert smoke[0].y == 13.0


def test_build_timeline_unknown_player_raises() -> None:
    demo = build_parsed_demo()
    try:
        build_timeline(demo, "nobody")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_empty_ticks_ok() -> None:
    demo = build_parsed_demo()
    tl = build_timeline(demo, S_ALICE)
    assert len(tl.ticks) == 0
    assert tl.shots == []
