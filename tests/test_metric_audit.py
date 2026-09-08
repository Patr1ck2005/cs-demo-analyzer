"""Phase M5 口径审计 (2026-09-05): "打得越多数据越高" 反样本量偏差回归测试.

用户裁决:
- eco 局买鸟狙 = 装逼枪（SSG 从 RIFLE_WEAPONS 移除 — 修复 v4 代码自相矛盾）
- 舔包王榜 = 白嫖次数 ÷ 总回合数（每回合口径）
- 榜单/画像取王一律比率口径；回合池化取代场次平均
- /fun-lab 页面每个指标必须带可点开的口径说明（METRIC_DEFS 随 API 下发）
"""
from __future__ import annotations

import pandas as pd

from cs_analyzer.analysis import AnalysisRunner
from cs_analyzer.config import AnalysisConfig
from cs_analyzer.web.funlab_data import METRIC_DEFS, funlab_report
from tests.conftest import S_ALICE, S_BOB, S_CAROL, S_DAVE, build_parsed_demo


def _eco_purchase_events(bob_buys: list[str]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """One demo: Bob buys whatever the test wants; Alice buys 200$ armor so the
    CT-side average stays under the 2000$ eco line even with an AK (a lone
    2700$ buyer averages to 'force', which would never classify as eco).
    Tick rows are required — round_player_sides derives live sides from
    ticks, without them no buy gets classified."""
    buys = [("AK-47", 2700) if w == "rifle" else ("SSG 08", 1700) if w == "ssg"
            else ("Desert Eagle", 700) for w in bob_buys]
    rows = [(10, S_BOB, buys[0][0], buys[0][1]), (20, S_ALICE, "armor", 200)]
    purchases = pd.DataFrame({
        "tick": [r[0] for r in rows],
        "steamid": [r[1] for r in rows],
        "item_name": [r[2] for r in rows],
        "cost": [r[3] for r in rows],
    })
    ticks = pd.DataFrame({
        "tick": [100, 1000] * 4,
        "steamid": [S_ALICE, S_ALICE, S_BOB, S_BOB, S_CAROL, S_CAROL, S_DAVE, S_DAVE],
        # Alice/Bob = Team 3 (CT), Carol/Dave = Team 2 (T) — conftest layout
        "team_num": [3.0, 3.0, 3.0, 3.0, 2.0, 2.0, 2.0, 2.0],
        "X": [0.0] * 8, "Y": [0.0] * 8, "is_alive": [True] * 8,
    })
    return {"item_purchase": purchases}, ticks


def _run_funlab(events: dict, ticks: pd.DataFrame | None = None) -> dict:
    demo = build_parsed_demo(events=events, ticks=ticks)
    r = AnalysisRunner(AnalysisConfig(enabled_modules=["funlab"])).run_one(demo, "funlab")
    return {p["steamid"]: p for p in r.players}


def test_ssg_in_eco_is_showoff_not_rebel() -> None:
    """用户裁决 v5: eco 局唯一买鸟狙 = 装逼（不是叛逆长枪）。
    v4 代码把 ssg08 同时放进 RIFLE_WEAPONS 与 SHOWOFF_WEAPONS，装逼路径死路。"""
    ev, ticks = _eco_purchase_events(["ssg"])
    by_sid = _run_funlab(ev, ticks)
    bob = by_sid[S_BOB]
    assert bob["showoff_rounds"] == 1, "鸟狙必须计入装逼"
    assert bob["rebel_rounds"] == 0, "鸟狙不是长枪（用户裁决）"


def test_ssg_display_name_normalizes() -> None:
    """'SSG 08' 显示名（含空格）必须归一为 ssg08（别名表）。"""
    ev, ticks = _eco_purchase_events(["ssg"])
    assert _run_funlab(ev, ticks)[S_BOB]["showoff_rounds"] == 1


def test_deagle_display_name_is_showoff() -> None:
    """'Desert Eagle' 显示名归一为 deagle（v5 补别名）→ 装逼。"""
    ev, ticks = _eco_purchase_events(["deagle"])
    assert _run_funlab(ev, ticks)[S_BOB]["showoff_rounds"] == 1


def test_rebel_rifle_still_works() -> None:
    """AK 唯一起枪 = 叛逆者（回归保护）。"""
    ev, ticks = _eco_purchase_events(["rifle"])
    bob = _run_funlab(ev, ticks)[S_BOB]
    assert bob["rebel_rounds"] == 1
    assert bob["showoff_rounds"] == 0


def test_web_funlab_metric_defs_present(web_client) -> None:
    """/api/funlab.json 必须下发全部指标的口径字典（网页点开可见）。"""
    c, _, _ = web_client
    d = c.get("/api/funlab.json").json()
    defs = d["metric_defs"]
    assert len(defs) >= 26, "口径字典覆盖全部散点指标"
    for key, m in defs.items():
        assert m.get("label"), f"{key} 缺 label"
        assert m.get("formula"), f"{key} 缺 formula（口径说明必须可点开）"
    # 舔包王榜键存在（用户裁决：每回合口径）；数值口径由 funlab_report 测试覆盖
    assert "free_pickup" in d["boards"]
    assert "free_pickup_pr" in defs


def test_metric_defs_have_no_vulture_label_regression() -> None:
    """吸血鬼=被供枪占比（v3 裁决不回退）；保枪率注明断后偏差。"""
    assert "被供枪" in METRIC_DEFS["vulture_rate"]["label"]
    assert "断后" in METRIC_DEFS["jame_index"]["note"]


def test_funlab_report_free_pickup_pr_round_denominator(web_client) -> None:
    """白嫖频率分母 = 总回合数（非场次/非收枪数）——用户裁决『除总回合数』。"""
    from cs_analyzer.web import aggregation

    aggregation.invalidate_aggregate()
    d = funlab_report()
    for p in d["players"]:
        expected = round(p["free_pickups"] / max(p["rounds"], 1), 4)
        assert p["free_pickup_pr"] == expected


def test_map_best_players_pools_and_rates() -> None:
    """本图最强: 同图多场必须池化（旧实现同图覆盖只留最后一场），
    排序按回合加权 Rating（比率），<10 回合被门槛挡住。"""
    from types import SimpleNamespace

    from cs_analyzer.web.mapdata import _pool_map_players, best_players_for_map

    def row(map_name, rounds, rating):
        return {"map_name": map_name, "rounds": rounds, "Rating": rating}

    p1 = SimpleNamespace(steamid="a", name="A", demo_count=3, demos=[
        row("de_mirage", 12, 1.4), row("de_mirage", 12, 1.2),
        row("de_mirage", 12, 1.0)])           # pooled rating 1.2 over 36 rounds
    p2 = SimpleNamespace(steamid="b", name="B", demo_count=1, demos=[
        row("de_mirage", 24, 1.5)])           # one hot map (24 rounds, 1.5)
    p3 = SimpleNamespace(steamid="c", name="C", demo_count=1, demos=[
        row("de_mirage", 8, 2.0)])            # below the 10-round gate
    cells = _pool_map_players([p1, p2, p3])
    best = best_players_for_map(cells["de_mirage"])
    assert [b["steamid"] for b in best] == ["b", "a"], "排序只看加权 Rating"
    assert best[0]["rounds"] == 24 and best[1]["rounds"] == 36, "同图多场池化"
    assert all(b["steamid"] != "c" for b in best), "10 回合门槛"


def test_lineups_group_win_rate_is_round_pooled() -> None:
    """车队/单排组胜率 = Σ胜回合/Σ总回合（场次简单平均有偏）。R1: 返回
    {rate, conf}——conf 带 Wilson 区间与 n。"""
    from cs_analyzer.web.lineups_data import pooled_win_rate

    ms = [
        {"our_rounds_won": 10, "our_rounds": 20},   # 50%
        {"our_rounds_won": 2, "our_rounds": 4},     # 50%
        {"our_rounds_won": 0, "our_rounds": 1},     # 0% — 旧均值会被它拉低
    ]
    # 池化 = 12/25 = 0.48；旧简单平均 = 0.333
    out = pooled_win_rate(ms)
    assert out["rate"] == 0.48
    assert out["conf"]["n"] == 25
    assert out["conf"]["lo"] < 0.48 < out["conf"]["hi"]
    assert pooled_win_rate([{"our_rounds_won": 0, "our_rounds": 0}]) is None


def test_nan_steamid_never_becomes_a_player_m5_sweep() -> None:
    """M5 视觉审计发现：weapon_splits/duels 等模块 str(NaN)->'nan' 伪造选手
    （§7.8 陷阱的全库清扫）。C4 爆炸击杀 attacker=NaN 不得出现在任何玩家列表。"""
    deaths = pd.DataFrame({
        "tick": [500, 600],
        "attacker_steamid": [float("nan"), S_BOB],
        "user_steamid": [S_ALICE, float("nan")],
        "attacker_name": ["", "Bob"],
        "user_name": ["Alice", ""],
        "weapon": ["c4", "ak47"],
    })
    demo = build_parsed_demo(events={"player_death": deaths})
    runner = AnalysisRunner(AnalysisConfig(
        enabled_modules=["weapon_splits", "duels", "hitgroups", "kill_context", "aim"]))
    for mod in ("weapon_splits", "duels", "hitgroups", "kill_context", "aim"):
        r = runner.run_one(demo, mod)
        players = getattr(r, "players", [])
        assert all(p.get("steamid") != "nan" for p in players), f"{mod} 泄漏 nan 选手"
    duel = runner.run_one(demo, "duels")
    assert duel.players == [S_BOB] or duel.players == [], "nan 不得进入对枪矩阵轴"
