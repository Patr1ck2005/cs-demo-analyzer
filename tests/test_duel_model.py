"""Round 2 — duel-model tests (对枪胜率模型).

Covers: the four label rules (victim first / attacker first / third-party
interruption / no-death & window & same-tick exclusions), feature fail-soft
paths, the duelmo shard payload + shape guard, the peek-503 route contract,
the per-player board gating, and the research_eval duel arities.
"""
from __future__ import annotations

import pandas as pd

from cs_analyzer.analysis.duel_model import (
    WEAPON_CLASSES, duel_feature_names,
)

from tests.conftest import (
    S_ALICE, S_BOB, S_CAROL, S_DAVE, build_demo_data,
)


def _ticks_frame(ticks_per_player: dict[str, list[tuple[int, bool, float, float, float]]]) -> pd.DataFrame:
    """steamid -> [(tick, alive, hp, armor, team_num)] full-column ticks."""
    rows = []
    for sid, entries in ticks_per_player.items():
        team = 3.0 if sid in (S_ALICE, S_BOB) else 2.0
        for tick, alive, hp, armor, _team in entries:
            rows.append({"steamid": sid, "tick": tick, "is_alive": alive,
                         "health": hp, "armor": armor, "team_num": team,
                         "X": 0.0, "Y": 0.0, "Z": 0.0,
                         "pitch": 0.0, "yaw": 0.0, "velocity": 0.0})
    return pd.DataFrame(rows)


def _full_ticks() -> pd.DataFrame:
    rows = []
    for sid in (S_ALICE, S_BOB, S_CAROL, S_DAVE):
        team = 3.0 if sid in (S_ALICE, S_BOB) else 2.0
        for t in (0, 640, 1280, 1920, 2560, 3000, 3200, 6400):
            rows.append({"steamid": sid, "tick": t, "is_alive": True,
                         "health": 100.0, "armor": 100.0, "team_num": team,
                         "X": 0.0, "Y": 0.0, "Z": 0.0,
                         "pitch": 0.0, "yaw": 0.0, "velocity": 0.0})
    return pd.DataFrame(rows)


def _demo(events: dict, ticks: pd.DataFrame | None = None):
    data = build_demo_data()
    if ticks is None:
        ticks = _full_ticks()
    from cs_analyzer.model.parsed_demo import ParsedDemo

    return ParsedDemo(data=data, events=events, ticks=ticks)


def _run(demo):
    from cs_analyzer.analysis.runner import AnalysisRunner

    return AnalysisRunner().run_one(demo, "duel_model")


# ---------------------------------------------------------------- label rules

def test_duel_label_victim_dies_first():
    """Victim dies first by the attacker's hand → y=1 (attacker won)."""
    events = {
        "player_hurt": pd.DataFrame({
            "tick": [1280], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
            "weapon": ["ak47"], "hitgroup": ["head"], "distance": [12.5],
        }),
        "player_death": pd.DataFrame({
            "tick": [1280], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
        }),
    }
    result = _run(_demo(events))
    assert len(result.samples) == 1
    s = result.samples[0]
    assert s.y == 1 and s.attacker == S_ALICE and s.victim == S_CAROL
    assert s.hitgroup_head == 1
    assert result.n_excluded["no_tick_state"] == 0


def test_duel_label_attacker_dies_first():
    """Attacker dies first → y=0."""
    events = {
        "player_hurt": pd.DataFrame({
            "tick": [1280], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
            "weapon": ["ak47"], "hitgroup": ["chest"],
        }),
        "player_death": pd.DataFrame({
            "tick": [1400], "attacker_steamid": [S_CAROL], "user_steamid": [S_ALICE],
        }),
    }
    result = _run(_demo(events))
    assert len(result.samples) == 1 and result.samples[0].y == 0


def test_duel_excluded_third_party_interrupts():
    """The first to die was killed by NEITHER member → excluded (交战被打断)."""
    events = {
        "player_hurt": pd.DataFrame({
            "tick": [1280], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
            "weapon": ["ak47"], "hitgroup": ["chest"],
        }),
        "player_death": pd.DataFrame({
            # S_BOB (a third party relative to ALICE vs CAROL) kills CAROL
            "tick": [1400], "attacker_steamid": [S_BOB], "user_steamid": [S_CAROL],
        }),
    }
    result = _run(_demo(events))
    assert not result.samples
    assert result.n_excluded["third_party"] == 1


def test_duel_excluded_no_death_in_round():
    events = {
        "player_hurt": pd.DataFrame({
            "tick": [1280], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
            "weapon": ["ak47"], "hitgroup": ["chest"],
        }),
        "player_death": pd.DataFrame({
            "tick": [3000], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
        }),
    }
    result = _run(_demo(events))
    # round 1 ends at 2560 — the 3000 death belongs to round 2 → no judged duel
    assert not result.samples
    assert result.n_excluded["no_death_in_round"] == 1


def test_duel_excluded_out_of_window():
    """Victim dies later than t0+15s but inside the round → 超出判定窗口."""
    events = {
        "player_hurt": pd.DataFrame({
            "tick": [1280], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
            "weapon": ["ak47"], "hitgroup": ["chest"],
        }),
        "player_death": pd.DataFrame({
            # round 1 spans 0..2560; t0+window = 1280+960 = 2240 < 2400
            "tick": [2400], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
        }),
    }
    result = _run(_demo(events))
    assert not result.samples
    assert result.n_excluded["out_of_window"] == 1


def test_duel_excluded_same_tick_double_kill():
    events = {
        "player_hurt": pd.DataFrame({
            "tick": [1280], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
            "weapon": ["ak47"], "hitgroup": ["chest"],
        }),
        "player_death": pd.DataFrame({
            "tick": [1400, 1400],
            "attacker_steamid": [S_ALICE, S_CAROL],
            "user_steamid": [S_CAROL, S_ALICE],
        }),
    }
    result = _run(_demo(events))
    assert not result.samples
    assert result.n_excluded["same_tick"] == 1


def test_duel_lethal_first_hit_survives_tick_flip():
    """A lethal first hit flips is_alive at the SAME tick — the t0-1 retry
    must keep the sample (the Round-2 probe finding)."""
    ticks = _full_ticks()
    # CAROL recorded dead from tick 1280 (the lethal-hit tick)
    mask = (ticks["steamid"] == S_CAROL) & (ticks["tick"] == 1280)
    ticks.loc[mask, ["is_alive", "health"]] = [False, 0.0]
    events = {
        "player_hurt": pd.DataFrame({
            "tick": [1280], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
            "weapon": ["awp"], "hitgroup": ["head"],
        }),
        "player_death": pd.DataFrame({
            "tick": [1280], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
        }),
    }
    result = _run(_demo(events, ticks))
    assert len(result.samples) == 1
    assert result.samples[0].y == 1
    assert result.samples[0].weapon_cls == "sniper"


# ---------------------------------------------------------------- features

def test_duel_feature_names_fixed_order():
    names = duel_feature_names()
    assert names[:4] == ["distance", "hp_diff", "armor_diff", "att_stopped"]
    assert names[-2:] == ["att_fired_before", "vic_fired_before"]
    assert "weapon_rifle" not in names
    assert len(names) == 19  # 12 numeric + 5 weapon one-hots + 2 fired_before
    assert set(WEAPON_CLASSES) == {"rifle", "sniper", "pistol", "smg",
                                   "heavy", "unknown"}


def test_duel_failsoft_without_ticks():
    """No tick table → sides unresolvable → zero engagements, no crash."""
    events = {
        "player_hurt": pd.DataFrame({
            "tick": [1280], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
            "weapon": ["ak47"], "hitgroup": ["chest"],
        }),
        "player_death": pd.DataFrame({
            "tick": [1300], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
        }),
    }
    demo = _demo(events, ticks=pd.DataFrame())
    result = _run(demo)
    assert not result.samples
    assert result.notes.get("skipped") is None  # ran through, just empty


def test_duel_team_damage_not_a_sample():
    events = {
        "player_hurt": pd.DataFrame({
            "tick": [1280], "attacker_steamid": [S_ALICE], "user_steamid": [S_BOB],
            "weapon": ["ak47"], "hitgroup": ["chest"],
        }),
        "player_death": pd.DataFrame({
            "tick": [1300], "attacker_steamid": [S_ALICE], "user_steamid": [S_BOB],
        }),
    }
    result = _run(_demo(events))
    assert not result.samples  # ALICE vs BOB are same-side: no engagement
    assert result.n_excluded == {"no_death_in_round": 0, "same_tick": 0,
                                 "third_party": 0, "out_of_window": 0,
                                 "no_tick_state": 0}


# ---------------------------------------------------------------- web layer

def test_duelmo_payload_shape():
    """duelmo shard payload carries fixed 17-wide rows + duels/roster meta.
    Uses a synthetic demo WITH player_hurt (the conftest demo has none)."""
    from cs_analyzer.web.duel_data import _demo_payload

    events = {
        "player_hurt": pd.DataFrame({
            "tick": [1280], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
            "weapon": ["ak47"], "hitgroup": ["head"],
        }),
        "player_death": pd.DataFrame({
            "tick": [1300], "attacker_steamid": [S_ALICE], "user_steamid": [S_CAROL],
        }),
    }
    payload = _demo_payload(_demo(events))
    assert payload["meta"]["n_features"] == len(duel_feature_names())
    assert payload["rows"] and len(payload["rows"][0]) == len(duel_feature_names())
    assert payload["duels"] and payload["duels"][0]["y"] == 1
    assert set(payload["roster"]) >= {S_ALICE, S_CAROL}
    assert payload["excluded"] == {"no_death_in_round": 0, "same_tick": 0,
                                   "third_party": 0, "out_of_window": 0,
                                   "no_tick_state": 0}


def test_duel_api_peek_503_then_board(web_client, monkeypatch):
    """Cold memo → 503 {"status":"warming"}; never triggers a compute."""
    c, _h, _demo = web_client
    from cs_analyzer.web import duel_data

    duel_data.invalidate_duelmo()

    def boom():
        raise AssertionError("peek must not trigger a compute")

    monkeypatch.setattr(duel_data, "duel_report", boom)
    r = c.get("/api/duel-model.json")
    assert r.status_code == 503
    assert r.json() == {"status": "warming"}
    rp = c.get("/api/duel-model.json", params={"player": S_ALICE})
    assert rp.status_code == 503


def test_duel_api_player_404_when_warm(web_client, monkeypatch):
    c, _h, _demo = web_client
    from cs_analyzer.web import duel_data

    monkeypatch.setattr(duel_data, "_report", {"players": [], "model": {},
                                               "notes": {}, "gate_n": 20})
    r = c.get("/api/duel-model.json", params={"player": "76561199999999999"})
    assert r.status_code == 404


def test_duel_eval_duel_runs(monkeypatch):
    """research_eval._eval_duel works off fake shards (arity-agnostic)."""
    from scripts.research_eval import _eval_duel

    from cs_analyzer.web import duel_data

    n = len(duel_feature_names())
    fake = {
        "aaa": {"rows": [[float(i % 3)] * n for i in range(20)],
                "y": [0] * 10 + [1] * 10,
                "duels": [], "roster": {}, "excluded": {},
                "meta": {"n_features": n}},
        "bbb": {"rows": [[float((i + 1) % 3)] * n for i in range(20)],
                "y": [1] * 10 + [0] * 10,
                "duels": [], "roster": {}, "excluded": {},
                "meta": {"n_features": n}},
    }
    monkeypatch.setattr(duel_data, "_scan_all", lambda: fake)
    out = _eval_duel()
    assert out["model"] == "duel"
    assert out["n_demos_evaluated"] == 2
    assert out["weighted_auc"] is not None


def web_app_module():
    import cs_analyzer.web.app as app_module

    return app_module
