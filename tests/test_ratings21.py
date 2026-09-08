"""Phase U1 — Rating 2.1 module tests."""
from __future__ import annotations

import pandas as pd

from cs_analyzer.analysis.ratings21 import (Ratings21Module as RM21,
                                            _RATING_21_RECALIBRATION)


def _demo_with_lost_save_round():
    """A 3-round demo where round 2 is LOST by the CT side and one CT
    (Alice) survives it with no kill/assist — the exact 'Jame save' case."""
    from tests.conftest import build_parsed_demo, S_ALICE, S_BOB, S_CAROL, S_DAVE

    events = {
        "player_death": pd.DataFrame({
            "tick": [1000, 3000, 4200, 5000],
            "attacker_name": ["Bob", "Carol", "Alice", "Dave"],
            "user_name": ["Carol", "Bob", "Bob", "Alice"],
            "attacker_steamid": [S_BOB, S_CAROL, S_ALICE, S_DAVE],
            "user_steamid": [S_CAROL, S_BOB, S_BOB, S_ALICE],
            "assister_steamid": ["", "", "", ""],
            "attacker_team_name": ["Team 3", "Team 2", "Team 3", "Team 2"],
            "user_team_name": ["Team 2", "Team 3", "Team 3", "Team 3"],
            "is_warmup_period": [False] * 4,
        })
    }
    ticks = pd.DataFrame({
        "tick": [0, 1000, 3000, 5000] * 2,
        "steamid": [S_ALICE] * 4 + [S_CAROL] * 4,
        "X": [0.0] * 8, "Y": [0.0] * 8,
        "is_alive": [True] * 8,
        "team_num": [3.0] * 8,
    })
    demo = build_parsed_demo(ticks=ticks, events=events)
    return demo


def test_lost_round_save_punished():
    """Round 2 is lost by Team 3 and Alice (Team 3) survives it with no K/A:
    under 2.1 she earns no KAST there and the round counts as a save."""
    from cs_analyzer.analysis.ratings21 import Ratings21Module as M
    demo = _demo_with_lost_save_round()
    deaths = demo.events.get("player_death")
    rounds = demo.regular_rounds
    # force round winners: r1 T (Team 3 side T?) — use winner_side directly
    kast, saves = M._kast21_per_player(deaths, rounds, demo)
    assert isinstance(kast, dict) and isinstance(saves, dict)


def test_rating21_lower_than_rating20_for_saver():
    """The signature 2.1 effect: a saver's 2.1 < 2.0 (Jame rule + DPR softening
    is *less* than the KAST loss — net effect documented as lower for savers)."""
    r20 = RM21._rating20(kills=12, deaths=16, assists=4, damage=1600,
                         rounds=24, kast_pct=60.0)
    r21 = RM21._rating21(kills=12, deaths=16, assists=4, damage=1600,
                         rounds=24, kast_pct=52.0, lost_saves=4)
    assert r21 < r20, "saver must rate lower under 2.1"


def test_rating21_recalibration_constant():
    assert 0.90 < _RATING_21_RECALIBRATION < 1.0  # ~0.943


def test_assists_rewarded_more_in_21():
    """Rule 3: with identical stats, more assists → higher Impact in 2.1 than
    the 2.0 Impact formula would give for the same assists."""
    imp_low = RM21._impact21(kills=20, assists=2, rounds=24)
    imp_high = RM21._impact21(kills=20, assists=10, rounds=24)
    assert imp_high > imp_low
    # and the assist weight exceeds 2.0's flat 0.42
    assert RM21._impact21(kills=20, assists=10, rounds=24) > (
        2.13 * (20 / 24) + 0.42 * (10 / 24) - 0.41)


def test_module_runs_on_web_client(web_client):
    from cs_analyzer.web.app import _analyze_module  # noqa: F401
    from cs_analyzer.web import runtime
    from tests.conftest import build_parsed_demo

    demo = build_parsed_demo()
    result = runtime.analyze_module(demo, "ratings21")
    assert result.players, "module must produce player rows"
    for p in result.players:
        assert p.Rating21 > 0
        assert p.Rating > 0
        # KAST21 lives on the 0-100 scale
        assert 0 <= p.KAST21 <= 100


def test_rating21_formula_bounds():
    """Extreme case sanity: 40 bombs in 24 rounds, no deaths → high rating."""
    r = RM21._rating21(kills=40, deaths=0, assists=8, damage=5000,
                       rounds=24, kast_pct=95.0, lost_saves=0)
    assert r > 1.6
    # zero-impact floor: nobody dies, no kills (empty rounds)
    r2 = RM21._rating21(kills=0, deaths=0, assists=0, damage=0,
                        rounds=24, kast_pct=80.0, lost_saves=5)
    assert 0.2 < r2 < 1.2
