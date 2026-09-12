"""结论合成层 (conclusions.py) 规则单测 — 复盘提升包 B1/A2 口径表.

All tests inject fake payloads (SimpleNamespace) — no memos, no scans.
"""
from __future__ import annotations

from types import SimpleNamespace

from cs_analyzer.web.conclusions import (
    ADV_PEAK_MIN,
    ADV_START_MIN,
    ADV_SWING_MIN,
    LOSS_TOP_SHARE,
    match_conclusions,
    player_profile,
)


def _demo(t=13, ct=11, players=(("sid_a", "Alice"), ("sid_b", "Bob"))):
    return SimpleNamespace(
        regular_rounds=[SimpleNamespace(t_score=t, ct_score=ct)],
        metadata=SimpleNamespace(demo_hash="h" * 64),
        players=[SimpleNamespace(steamid=s, name=n) for s, n in players],
    )


def _snap(rnd, tick, p, outcome):
    return SimpleNamespace(round=rnd, tick=tick, p_win=p, outcome=outcome)


def _winprob(rounds):
    return SimpleNamespace(rounds=rounds)


def _lossattr(rounds):
    return SimpleNamespace(rounds=rounds)


# ---- B1: key-round rules ----

def test_rule1_comeback_lost_round_picked():
    # loser = T (ct 13 > t 11); T led 0.90 at tick 2, ended 0.45 → swing 0.45
    demo = _demo(t=11, ct=13)
    wp = _winprob([[_snap(1, 10, 0.55, 0), _snap(1, 20, 0.90, 0),
                    _snap(1, 30, 0.45, 0)]])
    out = match_conclusions(demo, winprob=wp,
                            lossattr=_lossattr([]), oos_t={(1, 20): 0.90})
    assert out["curve_source"] == "oos"  # non-empty oos_t → oos source
    assert out["key_rounds"], "R1 round must be picked"
    kr = out["key_rounds"][0]
    assert kr["rule"] == "本该赢却输"
    assert kr["round"] == 1
    assert "摆幅" in kr["sentence"]


def test_rule1_needs_peak_and_swing():
    # peak below 0.85 → not picked even with a big swing
    demo = _demo(t=11, ct=13)
    wp = _winprob([[_snap(1, 10, 0.55, 0), _snap(1, 20, 0.80, 0),
                    _snap(1, 30, 0.40, 0)]])
    out = match_conclusions(demo, winprob=wp, lossattr=_lossattr([]), oos_t=None)
    assert out["curve_source"] == "insample"
    assert out["key_rounds"] == []
    assert ADV_PEAK_MIN == 0.85 and ADV_SWING_MIN == 0.35


def test_rule2_advantage_start_lost():
    # T starts 0.70 with 优势局失守; round won check: outcome=0 → T lost
    demo = _demo(t=11, ct=13)
    wp = _winprob([[_snap(2, 10, 0.70, 0), _snap(2, 30, 0.60, 0)]])
    out = match_conclusions(demo, winprob=wp, lossattr=_lossattr([]), oos_t=None)
    rules = [k["rule"] for k in out["key_rounds"]]
    assert rules == ["优势局失守"]
    assert out["key_rounds"][0]["adv_start"] >= ADV_START_MIN


def test_rule3_loss_tag_hit_and_loser_perspective():
    # loser = T; loss round tags carry lost_clutch; T actually WON the round
    # per outcome=1 — R3 must NOT fire (tags only count on lost rounds)
    demo = _demo(t=11, ct=13)
    wp = _winprob([[_snap(3, 10, 0.40, 1)]])
    la = _lossattr([{"round": 3, "loser_side": "T", "tags": ["lost_clutch"]}])
    out = match_conclusions(demo, winprob=wp, lossattr=la, oos_t=None)
    assert out["key_rounds"] == []
    # now a lost round with the tag → picked
    wp2 = _winprob([[_snap(3, 10, 0.40, 0)]])
    out2 = match_conclusions(demo, winprob=wp2, lossattr=la, oos_t=None)
    assert out2["key_rounds"][0]["rule"] == "失利模式命中"
    assert "lost_clutch" in out2["key_rounds"][0]["sentence"]


def test_cap_and_round_dedup():
    demo = _demo(t=11, ct=13)
    wp = _winprob([
        [_snap(1, 10, 0.95, 0), _snap(1, 30, 0.30, 0)],   # R1+R2 both hit
        [_snap(2, 10, 0.95, 0), _snap(2, 30, 0.30, 0)],   # R1+R2
        [_snap(3, 10, 0.95, 0), _snap(3, 30, 0.30, 0)],   # R1+R2
        [_snap(4, 10, 0.95, 0), _snap(4, 30, 0.30, 0)],   # overflow
    ])
    out = match_conclusions(demo, winprob=wp, lossattr=_lossattr([]), oos_t=None)
    assert len(out["key_rounds"]) == 3
    rounds = [k["round"] for k in out["key_rounds"]]
    assert len(set(rounds)) == 3
    # best swings first by round order after sort: all equal swing → lowest rounds win
    assert rounds == [1, 2, 3]


def test_tie_score_degrades():
    demo = _demo(t=12, ct=12)
    out = match_conclusions(demo, winprob=_winprob([]),
                            lossattr=_lossattr([]), oos_t=None)
    assert out["key_rounds"] == []
    assert "tie" in out["notes"]


def test_ct_loser_perspective_flips_advantage():
    # loser = CT (t 13 > ct 11): T-view p=0.10 means CT advantage 0.90 mid
    # round, then T claws back (p 0.85) and wins (outcome=1) → CT lost a
    # round their advantage series peaked 0.90 and collapsed to 0.15.
    demo = _demo(t=13, ct=11)
    wp = _winprob([[_snap(5, 10, 0.85, 1), _snap(5, 20, 0.10, 1),
                    _snap(5, 30, 0.85, 1)]])
    out = match_conclusions(demo, winprob=wp, lossattr=_lossattr([]), oos_t=None)
    kr = out["key_rounds"][0]
    assert kr["rule"] == "本该赢却输"
    assert kr["adv_max"] >= 0.85  # 1 - 0.10


# ---- B1: improvement points ----

def test_improvements_capped_at_two_per_player():
    demo = _demo()
    duel_board = {"players": [
        {"steamid": "sid_a", "name": "Alice", "n": 100, "wins": 30,
         "win_rate": 0.30, "conf": {"lo": -0.35, "hi": -0.15, "n": 100, "gated": False},
         "expected_rate": 0.55, "diff": -0.25, "diff_shrunk": -0.2},
    ]}
    aim_rep = {"players": [
        {"steamid": "sid_a", "n_shots": 5000, "stopped_fire_rate": 0.10},
    ] + [{"steamid": f"o{i}", "n_shots": 9000, "stopped_fire_rate": 0.55}
         for i in range(8)]}
    loss_rep = {"players": [
        {"steamid": "sid_a", "name": "Alice", "lost_rounds": 20,
         "tags": {"lost_opening": 12, "untraded": 6}},
    ]}
    util_rep = {"flashers": [
        {"steamid": "sid_a", "throws": 40, "value_per_throw": 0.5},
    ] + [{"steamid": f"u{i}", "throws": 30, "value_per_throw": 2.0}
         for i in range(8)]}
    prof = player_profile("sid_a", "Alice", duel_board=duel_board,
                          aim_rep=aim_rep, loss_rep=loss_rep, util_rep=util_rep,
                          funlab_rep={"players": []})
    verdicts = {d["key"]: d["verdict"] for d in prof["dims"]}
    assert verdicts == {"duel": "weak", "aim": "weak", "loss": "weak",
                        "utility": "weak", "eco": "na"}
    assert len(prof["weak_items"]) == 4
    # match level: per-player cap 2 (fakes injected so no real memos touched)
    out = match_conclusions(demo, winprob=_winprob([]), lossattr=_lossattr([]),
                            oos_t=None, duel_board=duel_board, aim_rep=aim_rep,
                            loss_rep=loss_rep, util_rep=util_rep,
                            funlab_rep={"players": []})
    alice = next(x for x in out["improvements"] if x["name"] == "Alice")
    assert len(alice["points"]) == 2
    assert any("对枪" in i for i in alice["points"])
    assert any("急停下开火" in i for i in alice["points"])


def test_profile_na_paths():
    # no duel row at all + cold aim/loss/utility → all na, no crash
    prof = player_profile("sid_none", None, duel_board={"players": []},
                          aim_rep={"players": []}, loss_rep={"players": []},
                          util_rep={"flashers": []})
    assert all(d["verdict"] == "na" for d in prof["dims"])
    assert prof["weak_items"] == []


def test_duel_gated_row_is_na():
    duel_board = {"players": [
        {"steamid": "sid_a", "name": "Alice", "n": 10, "wins": 8,
         "win_rate": 0.8, "conf": {"lo": 0.5, "hi": 0.95, "n": 10, "gated": True},
         "expected_rate": 0.5, "diff": 0.3, "diff_shrunk": 0.2},
    ]}
    prof = player_profile("sid_a", None, duel_board=duel_board,
                          aim_rep={"players": []}, loss_rep={"players": []},
                          util_rep={"flashers": []})
    duel = next(d for d in prof["dims"] if d["key"] == "duel")
    assert duel["verdict"] == "na"
    assert "灰显" in duel["anchor"]


def test_duel_interval_containing_zero_is_normal():
    duel_board = {"players": [
        {"steamid": "sid_a", "name": "Alice", "n": 100, "wins": 52,
         "win_rate": 0.52, "conf": {"lo": -0.05, "hi": 0.08, "n": 100, "gated": False},
         "expected_rate": 0.50, "diff": 0.02, "diff_shrunk": 0.016},
    ]}
    prof = player_profile("sid_a", None, duel_board=duel_board,
                          aim_rep={"players": []}, loss_rep={"players": []},
                          util_rep={"flashers": []})
    duel = next(d for d in prof["dims"] if d["key"] == "duel")
    assert duel["verdict"] == "normal"


def test_utility_throws_gate():
    util_rep = {"flashers": [
        {"steamid": "sid_a", "throws": 2, "value_per_throw": 9.9},
    ] + [{"steamid": f"u{i}", "throws": 30, "value_per_throw": 2.0}
         for i in range(8)]}
    prof = player_profile("sid_a", None, duel_board={"players": []},
                          aim_rep={"players": []}, loss_rep={"players": []},
                          util_rep=util_rep)
    util = next(d for d in prof["dims"] if d["key"] == "utility")
    assert util["verdict"] == "na"
    assert LOSS_TOP_SHARE == 0.25


def test_report_template_uses_points_not_items():
    """Regression: `p.items` in Jinja resolves to dict.items() — the report
    page 500'd on real data once improvements were non-empty. Lock the key
    name at template level (viewer-js path-contract precedent)."""
    from pathlib import Path

    tpl = (Path(__file__).resolve().parents[1] / "cs_analyzer" / "web"
           / "templates" / "report_match.html").read_text(encoding="utf-8")
    assert "p.points|join" in tpl
    assert "p.items|join" not in tpl
