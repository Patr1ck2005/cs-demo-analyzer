"""Tests for analysis modules: basic_stats, ratings, preference.

Expected values are hand-derived from the synthetic fixture in conftest.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from cs_analyzer.analysis.base import AnalysisContext
from cs_analyzer.analysis.basic_stats import BasicStatsModule, BasicStatsResult
from cs_analyzer.analysis.preference import PreferenceModule
from cs_analyzer.analysis.ratings import RatingsModule, RatingsResult
from cs_analyzer.config import AnalysisConfig

from .conftest import S_ALICE, S_BOB, S_CAROL, S_DAVE, build_demo_data, build_parsed_demo


def _deaths_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "tick": [100, 200, 3000],
            "attacker_steamid": [S_ALICE, S_BOB, S_CAROL],
            "user_steamid": [S_DAVE, S_CAROL, S_ALICE],
            "assister_steamid": [None, S_ALICE, None],
            "headshot": [True, False, False],
            "attacker_team_name": ["Team 3", "Team 3", "Team 2"],
            "user_team_name": ["Team 2", "Team 2", "Team 3"],
            "is_warmup_period": [False, False, False],
        }
    )


def _hurts_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "tick": [150, 250, 3100],
            "attacker_steamid": [S_ALICE, S_BOB, S_CAROL],
            "dmg_health": [50, 25, 30],
            "is_warmup_period": [False, False, False],
        }
    )


def _demo() -> "object":
    return build_parsed_demo(events={"player_death": _deaths_df(), "player_hurt": _hurts_df()})


def _run_basic(demo) -> BasicStatsResult:
    ctx = AnalysisContext(AnalysisConfig())
    result = BasicStatsModule().run(demo, ctx)
    assert isinstance(result, BasicStatsResult)
    return result


def _run_ratings(demo, basic: BasicStatsResult) -> RatingsResult:
    ctx = AnalysisContext(AnalysisConfig())
    ctx.put(basic)
    result = RatingsModule().run(demo, ctx)
    assert isinstance(result, RatingsResult)
    return result


def test_basic_stats_counts() -> None:
    result = _run_basic(_demo())
    by = {p.steamid: p for p in result.players}

    assert by[S_ALICE].kills == 1
    assert by[S_ALICE].deaths == 1
    assert by[S_ALICE].assists == 1
    assert by[S_ALICE].headshot_kills == 1
    assert by[S_ALICE].first_kills == 1
    assert by[S_ALICE].damage == 50

    assert by[S_BOB].kills == 1
    assert by[S_BOB].damage == 25

    assert by[S_CAROL].kills == 1
    assert by[S_CAROL].deaths == 1
    assert by[S_CAROL].first_kills == 1  # first death of round 2
    assert by[S_CAROL].damage == 30

    assert by[S_DAVE].kills == 0
    assert by[S_DAVE].deaths == 1


def test_basic_stats_derived_rates() -> None:
    result = _run_basic(_demo())
    alice = result.by_steamid(S_ALICE)
    assert alice.rounds == 2
    assert alice.KPR == pytest.approx(0.5)
    assert alice.ADR == pytest.approx(25.0)
    assert alice.Survivals == pytest.approx(0.5)
    assert alice.headshot_pct == pytest.approx(100.0)
    assert alice.FirstKillsPerRound == pytest.approx(0.5)

    bob = result.by_steamid(S_BOB)
    assert bob.Survivals == pytest.approx(1.0)
    assert bob.headshot_pct == pytest.approx(0.0)


def test_basic_stats_excludes_teamkills() -> None:
    df = _deaths_df()
    df.loc[len(df)] = [150, S_ALICE, S_BOB, None, False, "Team 3", "Team 3", False]  # teamkill
    demo = build_parsed_demo(events={"player_death": df, "player_hurt": _hurts_df()})
    result = _run_basic(demo)
    # teamkill not counted for either attacker (Alice) or victim (Bob)
    assert result.by_steamid(S_ALICE).kills == 1
    assert result.by_steamid(S_BOB).deaths == 0


def test_ratings_rws_and_impact() -> None:
    demo = _demo()
    basic = _run_basic(demo)
    result = _run_ratings(demo, basic)
    by = {p.steamid: p for p in result.players}

    # RWS only counts won rounds (winner == team), divided by total rounds.
    assert by[S_ALICE].RWS == pytest.approx((50 / 75 * 100) / 2, abs=0.01)  # ~33.33
    assert by[S_BOB].RWS == pytest.approx((25 / 75 * 100) / 2, abs=0.01)  # ~16.67
    assert by[S_CAROL].RWS == pytest.approx(50.0, abs=0.01)  # 30/30*100 / 2
    assert by[S_DAVE].RWS == pytest.approx(0.0)

    # Impact = 2.13*KPR + 0.42*APR - 0.41
    assert by[S_ALICE].Impact == pytest.approx(2.13 * 0.5 + 0.42 * 0.5 - 0.41, abs=0.001)
    assert by[S_BOB].Impact == pytest.approx(2.13 * 0.5 - 0.41, abs=0.001)


def test_ratings_kast() -> None:
    demo = _demo()
    basic = _run_basic(demo)
    result = _run_ratings(demo, basic)
    by = {p.steamid: p for p in result.players}
    # Alice: K in R1, dies R2 (untraded) -> 1/2; Bob: K in R1 + survived R2 -> 2/2
    assert by[S_ALICE].KAST == pytest.approx(50.0)
    assert by[S_BOB].KAST == pytest.approx(100.0)
    assert by[S_CAROL].KAST == pytest.approx(50.0)
    assert by[S_DAVE].KAST == pytest.approx(50.0)


def test_ratings_rating_formula() -> None:
    demo = _demo()
    basic = _run_basic(demo)
    result = _run_ratings(demo, basic)
    alice = result.by_steamid(S_ALICE)
    expected = (
        0.0073 * 50.0
        + 0.3591 * 0.5
        - 0.5329 * 0.5
        + 0.2372 * alice.Impact
        + 0.0032 * 25.0
        + 0.1587
    )
    assert alice.Rating == pytest.approx(expected, abs=0.001)
    assert alice.Rating_Pro == pytest.approx(alice.Rating)


# ---- preference ----

def _demo_with_ticks() -> "object":
    ticks = pd.DataFrame(
        {
            "tick": [256, 256, 3840, 3840],  # 0.1 of R1 (2560), 0.25 of R2
            "steamid": [S_ALICE, S_BOB, S_ALICE, S_BOB],
            "X": [10.0, 20.0, 30.0, 40.0],
            "Y": [11.0, 21.0, 31.0, 41.0],
            "pitch": [0.0, 0.1, -0.1, 0.2],
            "is_alive": [True, True, True, True],
        }
    )
    return build_parsed_demo(
        events={"player_death": _deaths_df()},
        ticks=ticks,
    )


def test_preference_position_samples() -> None:
    demo = _demo_with_ticks()
    ctx = AnalysisContext(AnalysisConfig())
    result = PreferenceModule().run(demo, ctx)
    alice = result.by_steamid(S_ALICE)
    # R1 phase 0.1 -> tick 256; R2 phase 0.5 -> tick 3840. Both are PHASE_SAMPLE ticks.
    assert alice.position_samples == [(10.0, 11.0), (30.0, 31.0)]


def test_preference_crosshair_placement() -> None:
    demo = _demo_with_ticks()
    ctx = AnalysisContext(AnalysisConfig())
    result = PreferenceModule().run(demo, ctx)
    alice = result.by_steamid(S_ALICE)
    # pitch 0.0 and -0.1 rad -> degrees mean = degrees((0 + -0.1)/2)
    assert alice.avg_pitch == pytest.approx(math.degrees(-0.05), abs=0.01)
    assert alice.pitch_samples == 2


def test_preference_utility_placement() -> None:
    smoke = pd.DataFrame(
        {
            "tick": [100, 500],
            "thrower_steamid": [S_ALICE, S_BOB],
            "X": [1.0, 2.0],
            "Y": [3.0, 4.0],
        }
    )
    demo = build_parsed_demo(events={"smokegrenade_detonate": smoke})
    ctx = AnalysisContext(AnalysisConfig())
    result = PreferenceModule().run(demo, ctx)
    alice = result.by_steamid(S_ALICE)
    assert alice.utility_counts == {"smoke": 1}
    assert alice.utility_positions["smoke"] == [(1.0, 3.0)]


def test_preference_peek_style() -> None:
    demo = _demo()
    ctx = AnalysisContext(AnalysisConfig())
    result = PreferenceModule().run(demo, ctx)
    alice = result.by_steamid(S_ALICE)
    # Alice first involved in R1 at tick 100 (as attacker) and R2 at tick 3000 (as victim)
    # R1 fraction = 100/2560; R2 fraction = (3000-2560)/2560 = 440/2560
    expected = (100 / 2560 + 440 / 2560) / 2
    assert alice.avg_first_engagement_fraction == pytest.approx(expected, abs=0.001)
    assert alice.engagement_rounds == 2


def test_module_requires_topology() -> None:
    assert RatingsModule.requires == ("basic_stats",)
    assert BasicStatsModule.requires == ()
