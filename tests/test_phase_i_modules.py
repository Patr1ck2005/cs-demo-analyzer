"""Tests for Phase I M3 analysis modules: kill_context, hitgroups, aim,
postplant, weapon_splits (+ F8 first_deaths in basic_stats, F4 flash assists).
"""
from __future__ import annotations

import pandas as pd
import pytest

from cs_analyzer.analysis.aim import AimModule
from cs_analyzer.analysis.base import AnalysisContext
from cs_analyzer.analysis.basic_stats import BasicStatsModule
from cs_analyzer.analysis.hitgroups import HitgroupsModule
from cs_analyzer.analysis.kill_context import KillContextModule
from cs_analyzer.analysis.postplant import PostPlantModule
from cs_analyzer.analysis.utility_effect import UtilityEffectModule
from cs_analyzer.analysis.weapon_splits import WeaponSplitsModule
from cs_analyzer.config import AnalysisConfig

from .conftest import S_ALICE, S_BOB, S_CAROL, build_parsed_demo


def _run(module, demo):
    return module.run(demo, AnalysisContext(AnalysisConfig()))


def _deaths(**extra) -> pd.DataFrame:
    base = {
        "tick": [100, 200],
        "attacker_steamid": [S_ALICE, S_BOB],
        "user_steamid": [S_CAROL, S_ALICE],
        "attacker_name": ["Alice", "Bob"],
        "user_name": ["Carol", "Alice"],
        "weapon": ["ak47_txz03", "awp"],
        "penetrated": [True, False],
        "thrusmoke": [False, True],
        "noscope": [False, False],
        "attackerinair": [False, True],
        "headshot": [True, False],
        "distance": [1200.5, 800.0],
        "is_warmup_period": [False, False],
        "attacker_team_name": ["Team 3", "Team 3"],
        "user_team_name": ["Team 2", "Team 3"],  # row2 = TK (excluded)
    }
    base.update(extra)
    return pd.DataFrame(base)


# ---- kill_context (F1+F5) ----


def test_kill_context_badges_and_distance() -> None:
    demo = build_parsed_demo(events={"player_death": _deaths()})
    res = _run(KillContextModule(), demo)
    by = {p["steamid"]: p for p in res.players}
    alice = by[S_ALICE]
    assert alice["kills"] == 1
    assert alice["penetrated_kills"] == 1   # 穿墙
    assert alice["thrusmoke_kills"] == 0
    assert alice["noscope_kills"] == 0
    assert alice["airborne_kills"] == 0
    assert alice["avg_distance"] == 1200.5
    assert alice["max_distance"] == 1200.5
    # Bob's row was a teamkill -> excluded entirely
    assert S_BOB not in by or by[S_BOB]["kills"] == 0
    # feed carries per-kill badges with skin variant canonicalized
    assert len(res.feed) == 1
    f = res.feed[0]
    assert f["weapon"] == "ak47"
    assert f["badges"]["penetrated"] is True
    assert f["badges"]["distance"] == 1200.5
    assert res.weapon_mix == {"ak47": 1}


def test_kill_context_mvp_and_pickups() -> None:
    mvp = pd.DataFrame({
        "tick": [1500],
        "user_steamid": [S_ALICE],
        "user_name": ["Alice"],
        "reason": ["round_win"],
    })
    pickups = pd.DataFrame({
        "tick": [300, 400, 500],
        "user_steamid": [S_ALICE] * 3,
        "item": ["kevlar & helmet", "defuse kit", "Flashbang"],
    })
    demo = build_parsed_demo(events={"round_mvp": mvp, "item_pickup": pickups})
    res = _run(KillContextModule(), demo)
    alice = next(p for p in res.players if p["steamid"] == S_ALICE)
    assert alice["mvp_total"] == 1
    assert alice["mvp_counts"]["round_win"] == 1
    assert alice["pickups"].get("kevlarhelmet") == 1
    assert alice["pickups"].get("defuser") == 1
    assert alice["pickups"].get("grenade") == 1


# ---- hitgroups (F2) ----


def test_hitgroups_damage_distribution() -> None:
    hurts = pd.DataFrame({
        "tick": [100, 120, 140, 160, 180],
        "attacker_steamid": [S_ALICE] * 5,
        "attacker_name": ["Alice"] * 5,
        "hitgroup": ["head", "chest", "left_arm", "generic", "stomach"],
        "dmg_health": [100, 30, 20, 40, 25],
        "dmg_armor": [0, 10, 10, 0, 0],   # stomach hit: no armor interaction
        "is_warmup_period": [False] * 5,
        "attacker_team_name": ["Team 3"] * 5,
        "user_team_name": ["Team 2"] * 5,
    })
    demo = build_parsed_demo(events={"player_hurt": hurts})
    res = _run(HitgroupsModule(), demo)
    alice = res.players[0]
    assert alice["damage"]["head"] == 100.0
    assert alice["damage"]["chest"] == 30.0
    assert alice["damage"]["arm"] == 20.0      # left_arm folds into arm
    assert alice["damage"]["generic"] == 40.0
    # efficiency counts only armor-interacting hits: (10+10) / ((30+10)+(20+10))
    assert alice["armor_efficiency"] == pytest.approx(20 / 70, abs=1e-3)


# ---- aim (F3) ----


def test_aim_fire_kill_conversion_and_states() -> None:
    fires = pd.DataFrame({
        "tick": [1100, 1105, 1110],          # three shots, same weapon
        "user_steamid": [S_ALICE] * 3,
        "weapon": ["ak47", "ak47", "ak47"],
    })
    deaths = pd.DataFrame({
        "tick": [1120],                       # within 32t of the shots
        "attacker_steamid": [S_ALICE],
        "user_steamid": [S_CAROL],
        "attacker_team_name": ["Team 3"],
        "user_team_name": ["Team 2"],
        "weapon": ["ak47"],
        "is_warmup_period": [False],
    })
    ticks = pd.DataFrame({
        "tick": [1100, 1105, 1110],
        "steamid": [S_ALICE] * 3,
        "is_walking": [1.0, 0.0, 0.0],
        "is_scoped": [0.0, 0.0, 0.0],
        "duck_amount": [0.0, 0.9, 0.0],
    })
    demo = build_parsed_demo(events={"weapon_fire": fires, "player_death": deaths},
                             ticks=ticks)
    res = _run(AimModule(), demo)
    alice = res.players[0]
    assert alice["shots_fired"] == 3
    assert alice["fire_kills"] == 1           # conversion counted once
    assert alice["fire_kill_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert alice.get("walk_share") == pytest.approx(1 / 3, abs=1e-3)
    assert alice.get("crouch_share") == pytest.approx(1 / 3, abs=1e-3)


def test_aim_empty_without_fires() -> None:
    demo = build_parsed_demo(events={})
    res = _run(AimModule(), demo)
    assert res.players == []


# ---- postplant (F6) ----


def test_postplant_hold_retake_defuse() -> None:
    plants = pd.DataFrame({
        "tick": [1000, 9000],
        "site": ["A", "B"],
        "user_last_place_name": ["BombsiteA", "BombsiteB"],
    })
    rounds = [
        __import__("tests.conftest", fromlist=["make_round"]).make_round(
            1, 500, 5000, "T", winner="Team 2", t_score=1),
        __import__("tests.conftest", fromlist=["make_round"]).make_round(
            2, 8500, 13000, "CT", winner="Team 3", ct_score=1),
    ]
    defused = pd.DataFrame({"tick": [4200]})
    begins = pd.DataFrame({"tick": [4000, 4100], "haskit": [True, True]})
    demo = build_parsed_demo(
        events={"bomb_planted": plants, "bomb_defused": defused,
                "bomb_begindefuse": begins},
    )
    demo.data.rounds = rounds
    res = _run(PostPlantModule(), demo)
    assert len(res.rounds) == 2
    r1, r2 = res.rounds
    assert r1["site"] == "A" and r1["winner_side"] == "T"
    assert r1["defused"] is True
    assert r1["time_to_defuse_s"] == pytest.approx((4200 - 1000) / 64.0, abs=0.01)
    assert r1["defuse_attempts"] == 2
    assert r2["winner_side"] == "CT" and r2["defused"] is False
    s = res.summary
    assert s["planted_rounds"] == 2
    assert s["t_hold_rate"] == 0.5
    assert s["ct_retake_rate"] == 0.5
    assert s["defusal_count"] == 1


# ---- weapon_splits (F7) ----


def test_weapon_splits_skin_collapse_and_categories() -> None:
    deaths = pd.DataFrame({
        "tick": [100, 200, 300],
        "attacker_steamid": [S_ALICE] * 3,
        "user_steamid": [S_CAROL, S_CAROL, S_BOB],
        "attacker_name": ["Alice"] * 3,
        "user_name": ["Carol", "Carol", "Bob"],
        "weapon": ["ak47_txz03", "ak-47", "knife_bayonet"],
        "is_warmup_period": [False] * 3,
        "attacker_team_name": ["Team 3"] * 3,
        "user_team_name": ["Team 2", "Team 2", "Team 2"],
    })
    demo = build_parsed_demo(events={"player_death": deaths})
    res = _run(WeaponSplitsModule(), demo)
    alice = res.players[0]
    # both ak spellings collapse to one category entry; knife separate
    assert alice["kills_by_category"] == {"rifle": 2, "knife": 1}
    top = {w["weapon"]: w["kills"] for w in alice["top_weapons"]}
    assert top == {"ak47": 2, "knife": 1}
    carol = next(p for p in res.players if p["steamid"] == S_CAROL)
    assert carol["deaths_by_category"] == {"rifle": 2}


# ---- basic_stats first_deaths (F8) ----


def test_basic_stats_first_deaths() -> None:
    deaths = _deaths()
    demo = build_parsed_demo(events={"player_death": deaths})
    res = _run(BasicStatsModule(), demo)
    by = {p.steamid: p for p in res.players}
    # R1 first death: Carol (killed by Alice); R2's only death is a TK (excluded)
    assert by[S_CAROL].first_deaths == 1
    assert by[S_CAROL].FirstDeathsPerRound == pytest.approx(0.5)
    assert by[S_ALICE].first_deaths == 0


# ---- utility flash assists (F4) ----


def test_flash_assists_folded_into_flashers() -> None:
    det = pd.DataFrame({
        "tick": [1000],
        "user_steamid": [S_BOB],
        "user_name": ["Bob"],
    })
    blind = pd.DataFrame({
        "tick": [1010],
        "user_steamid": [S_CAROL],
        "blind_duration": [2.0],
    })
    deaths = pd.DataFrame({
        "tick": [1100],
        "attacker_steamid": [S_ALICE],
        "user_steamid": [S_CAROL],
        "assister_steamid": [S_BOB],
        "assistedflash": [True],
        "is_warmup_period": [False],
        "attacker_team_name": ["Team 3"],
        "user_team_name": ["Team 2"],
    })
    demo = build_parsed_demo(events={
        "flashbang_detonate": det, "player_blind": blind, "player_death": deaths,
    })
    res = _run(UtilityEffectModule(), demo)
    bob = next(f for f in res.flashers if f["steamid"] == S_BOB)
    assert bob["flash_assists"] == 1
