"""Phase U2 — weapon hold timeline module tests."""
from __future__ import annotations

import pandas as pd

from tests.conftest import build_parsed_demo, S_ALICE, S_BOB


def _demo():
    """Two players; Alice holds ak47 ticks 100-500 then deagle 500-800.
    Bob holds ak47 throughout. One kill each with matching weapons."""
    rows = []
    tick = 64
    while tick <= 1000:
        rows.append((tick, S_ALICE, "Alice", 3.0, True,
                     "ak47" if tick <= 500 else "deagle"))
        rows.append((tick, S_BOB, "Bob", 2.0, True, "ak47"))
        tick += 64
    ticks = pd.DataFrame(rows, columns=["tick", "steamid", "name", "team_num",
                                        "is_alive", "active_weapon_name"])
    events = {
        "player_death": pd.DataFrame({
            "tick": [400, 600],
            "attacker_name": ["Alice", "Bob"],
            "user_name": ["Carol", "Dave"],
            "attacker_steamid": [S_ALICE, S_BOB],
            "user_steamid": ["76561111111110003", "76561111111110004"],
            "assister_steamid": ["", ""],
            "weapon": ["ak47", "ak47"],
        })
    }
    return build_parsed_demo(ticks=ticks, events=events)


def test_segments_and_holds():
    from cs_analyzer.analysis.runner import AnalysisRunner

    demo = _demo()
    res = AnalysisRunner().run_one(demo, "weapon_timeline")
    alice = next(p for p in res.players if p.name == "Alice")
    holds = {h.weapon: h for h in alice.holds}
    assert "ak47" in holds and "deagle" in holds
    # hold time: ticks 64..500 ak47 (384 ticks), 500..1000 deagle (~448)
    assert holds["ak47"].ticks >= 300
    assert holds["deagle"].ticks >= 300
    # kill attribution matches the weapon actually held (canonical names)
    assert holds["ak47"].kills == 1
    seg_weapons = {s.weapon for s in alice.segments}
    assert seg_weapons == {"ak47", "deagle"}


def test_round_equips():
    from cs_analyzer.analysis.runner import AnalysisRunner

    demo = _demo()
    res = AnalysisRunner().run_one(demo, "weapon_timeline")
    alice = next(p for p in res.players if p.name == "Alice")
    assert alice.round_equips, "round equips must be recorded"
    assert all(isinstance(v, str) for v in alice.round_equips.values())


def test_weapon_switch_at_death_split():
    """Death interrupts the hold run (is_alive False gap) — the post-respawn
    segment is a new one even with the same weapon."""
    from cs_analyzer.analysis.runner import AnalysisRunner

    rows = []
    for tick in range(64, 1000, 64):
        alive = not (300 <= tick <= 500)
        rows.append((tick, S_ALICE, "Alice", 3.0, alive, "ak47"))
    ticks = pd.DataFrame(rows, columns=["tick", "steamid", "name", "team_num",
                                        "is_alive", "active_weapon_name"])
    demo = build_parsed_demo(ticks=ticks)
    res = AnalysisRunner().run_one(demo, "weapon_timeline")
    alice = next(p for p in res.players if p.name == "Alice")
    ak = next(h for h in alice.holds if h.weapon == "ak47")
    assert ak.segments >= 2, "death must split the ak47 hold run"
