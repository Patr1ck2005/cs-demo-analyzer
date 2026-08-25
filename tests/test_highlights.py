"""Tests for Phase H: highlights module + compare payload math."""
from __future__ import annotations

import pandas as pd

from cs_analyzer.analysis.aggregate import AggregateResult, PlayerRow
from cs_analyzer.analysis.highlights import HighlightsModule
from cs_analyzer.web.chart_data import compare_payload

from .conftest import (
    S_ALICE,
    S_BOB,
    S_CAROL,
    S_DAVE,
    build_parsed_demo,
    make_round,
)
from .conftest import build_demo_data


def _demo_with_rounds(rounds, deaths_df, ticks_df):
    data = build_demo_data()
    data.rounds = rounds
    return build_parsed_demo(events={"player_death": deaths_df}, ticks=ticks_df)


def test_multi_kill_and_ace() -> None:
    """5 kills by one attacker in a round -> ACE; 3 kills -> k3."""
    rounds = [make_round(1, 0, 2560, "CT", ct_score=1)]
    rows = []
    for i in range(5):  # Carol (T) kills 5 different victims -> ACE
        rows.append({
            "tick": [100 + i * 50],
            "attacker_name": ["Carol"],
            "user_name": [f"V{i}"],
            "attacker_steamid": [S_CAROL],
            "user_steamid": [f"victim{i}"],
            "weapon": ["ak47"],
        })
    # Alice gets 3 kills -> k3
    for i in range(3):
        rows.append({
            "tick": [400 + i * 50],
            "attacker_name": ["Alice"],
            "user_name": [f"W{i}"],
            "attacker_steamid": [S_ALICE],
            "user_steamid": [f"other{i}"],
            "weapon": ["ak47"],
        })
    deaths = pd.concat([pd.DataFrame(r) for r in rows], ignore_index=True)
    demo = _demo_with_rounds(rounds, deaths, pd.DataFrame())
    result = HighlightsModule().run(demo, None)
    tiers = {(h.steamid, h.tier) for h in result.highlights}
    assert (S_CAROL, "ace") in tiers
    assert (S_ALICE, "k3") in tiers


def test_suicides_and_self_kills_excluded() -> None:
    """attacker==victim (suicide) and empty attacker don't count."""
    rounds = [make_round(1, 0, 2560, "CT", ct_score=1)]
    deaths = pd.DataFrame({
        "tick": [100, 150, 200],
        "attacker_name": ["Carol", "", "Carol"],
        "user_name": ["Carol", "Alice", "Alice"],
        "attacker_steamid": [S_CAROL, "", S_CAROL],
        "user_steamid": [S_CAROL, S_ALICE, S_ALICE],
        "weapon": ["world", "ak47", "deagle"],
    })
    demo = _demo_with_rounds(rounds, deaths, pd.DataFrame())
    result = HighlightsModule().run(demo, None)
    # Carol has 1 real kill (the suicide is excluded) -> below multi-kill
    assert not any(h.steamid == S_CAROL for h in result.highlights)


def test_clutch_detection() -> None:
    """Winner side down to last man vs 2+ opponents who then lose -> 1vN."""
    # Round won by CT; Alice (CT) is last alive vs Carol+Dave (T)
    rounds = [make_round(1, 0, 2560, "CT", winner="Team 3", ct_score=1)]
    deaths = pd.DataFrame({
        # Bob (CT) dies first; then Carol and Dave (T) die to Alice
        "tick": [100, 200, 300],
        "attacker_name": ["Carol", "Alice", "Alice"],
        "user_name": ["Bob", "Carol", "Dave"],
        "attacker_steamid": [S_CAROL, S_ALICE, S_ALICE],
        "user_steamid": [S_BOB, S_CAROL, S_DAVE],
        "attacker_team_num": [2.0, 3.0, 3.0],
        "user_team_num": [3.0, 2.0, 2.0],
        "weapon": ["ak47", "ak47", "ak47"],
    })
    # side map comes from tick team_num majorities (T=2 / CT=3)
    ticks = pd.DataFrame({
        "tick": [10] * 4,
        "steamid": [S_ALICE, S_BOB, S_CAROL, S_DAVE],
        "team_num": [3.0, 3.0, 2.0, 2.0],
    })
    demo = _demo_with_rounds(rounds, deaths, ticks)
    result = HighlightsModule().run(demo, None)
    clutches = [h for h in result.highlights if h.kind == "clutch"]
    assert len(clutches) == 1
    h = clutches[0]
    assert h.steamid == S_ALICE
    assert h.tier == "1v2"  # two opponents alive at the clutch moment
    assert h.side == "CT"


def test_no_clutch_when_winner_side_never_down_to_one() -> None:
    rounds = [make_round(1, 0, 2560, "CT", ct_score=1)]
    deaths = pd.DataFrame({
        "tick": [100],
        "attacker_name": ["Alice"],
        "user_name": ["Carol"],
        "attacker_steamid": [S_ALICE],
        "user_steamid": [S_CAROL],
        "attacker_team_num": [3.0],
        "user_team_num": [2.0],
        "weapon": ["ak47"],
    })
    demo = _demo_with_rounds(rounds, deaths, pd.DataFrame())
    result = HighlightsModule().run(demo, None)
    assert not any(h.kind == "clutch" for h in result.highlights)


def _agg_with_counts(counts: list[int]) -> AggregateResult:
    players = []
    for i, n in enumerate(counts):
        demos = [{"demo": f"d{j}", "demo_hash": f"h{j}", "map_name": "de_mirage",
                  "rounds": 20, "kills": 15, "deaths": 10, "KPR": 0.75,
                  "ADR": 100.0 + j, "Rating": 1.0 + 0.01 * j, "KAST": 70.0,
                  "RWS": 8.0} for j in range(n)]
        players.append(PlayerRow(steamid=str(i), name=f"P{i}", demos=demos,
                                 total_kills=15 * n, total_deaths=10 * n,
                                 total_rounds=20 * n,
                                 total_headshot_kills=5 * n,
                                 total_first_kills=n,
                                 total_survival_weighted=0.6 * 20 * n))
    return AggregateResult(players=players, demos=[])


def test_compare_percentile_and_eligibility() -> None:
    """>=5 demos eligible; percentile rank = share of eligible strictly below."""
    # P0: 4 demos (ineligible), P1: 5, P2: 6, P3: 7 — ratings rise with count
    agg = _agg_with_counts([4, 5, 6, 7])
    payload = compare_payload(agg)
    assert payload["min_sample"] == 5
    by_id = {p["steamid"]: p for p in payload["players"]}
    assert by_id["0"]["eligible"] is False
    assert by_id["0"]["radar"] == []  # no radar for ineligible players
    assert by_id["3"]["eligible"] is True
    # P1 has the lowest rating among eligible -> pct 0.0
    assert by_id["1"]["ratings"]["rating"]["pct"] == 0.0
    # P3 has the highest -> share strictly below = 2/3 (payload rounds to 3dp)
    assert abs(by_id["3"]["ratings"]["rating"]["pct"] - 2 / 3) < 1e-3
    # radar values are 0-100
    assert all(0 <= v <= 100 for v in by_id["3"]["radar"])


def test_compare_empty_pool() -> None:
    """No eligible players -> empty ratings, no crash."""
    agg = _agg_with_counts([1, 2])
    payload = compare_payload(agg)
    for p in payload["players"]:
        assert p["eligible"] is False
        assert p["ratings"] == {}
