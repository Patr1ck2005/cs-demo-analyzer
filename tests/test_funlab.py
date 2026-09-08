"""Phase M: fun metrics module + /fun-lab page tests."""
from __future__ import annotations

import pandas as pd

from cs_analyzer.analysis import AnalysisRunner
from cs_analyzer.config import AnalysisConfig
from tests.conftest import S_ALICE, S_BOB, S_CAROL, S_DAVE, build_demo_data, build_parsed_demo


def _events() -> dict[str, pd.DataFrame]:
    """Synthetic demo exercising every fun metric.

    Round 1 (T buy = eco since purchases are tiny): Bob kills Alice who had
    only 20 HP left (vulture); Dave kills nobody and dies without dealing
    damage (whiff life); Carol wallbangs Bob (fun flag); a teammate trade
    happens inside the window.
    """
    purchases = pd.DataFrame({
        "tick": [10] * 4,
        "steamid": [S_ALICE, S_BOB, S_CAROL, S_DAVE],
        "item_name": ["glock", "glock", "usp_silencer", "usp_silencer"],
        "cost": [0, 0, 0, 0],
    })
    hurts = pd.DataFrame({
        "tick": [400, 500, 600],
        # Alice (CT) softened by Carol first (100 -> 80), then Bob finishes
        # her at 20 HP left -> vulture for Bob
        "attacker_steamid": [S_CAROL, S_BOB, S_DAVE],
        "user_steamid": [S_ALICE, S_ALICE, S_BOB],
        "attacker_name": ["Carol", "Bob", "Dave"],
        "user_name": ["Alice", "Alice", "Bob"],
        "dmg_health": [20.0, 80.0, 30.0],
        "user_health": [100.0, 20.0, 100.0],
        "health": [80.0, 0.0, 70.0],
    })
    deaths = pd.DataFrame({
        "tick": [600, 700],
        "attacker_steamid": [S_BOB, S_CAROL],
        "user_steamid": [S_ALICE, S_BOB],
        "attacker_name": ["Bob", "Carol"],
        "user_name": ["Alice", "Bob"],
        "assister_steamid": ["", ""],
        "weapon": ["ak47", "ak47"],
        "penetrated": [False, True],
        "thrusmoke": [False, False],
        "noscope": [False, False],
        "attackerblind": [False, False],
        "attackerinair": [False, False],
        "dmg_health": [80.0, 70.0],
        "user_health": [20.0, 70.0],
    })
    return {"item_purchase": purchases, "player_hurt": hurts, "player_death": deaths}


def test_funlab_module_metrics() -> None:
    demo = build_parsed_demo(events=_events())
    r = AnalysisRunner(AnalysisConfig(enabled_modules=["funlab"])).run_one(demo, "funlab")
    by_sid = {p["steamid"]: p for p in r.players}

    bob = by_sid[S_BOB]
    assert bob["kills"] == 1
    assert bob["snipe_kills"] == 1  # Alice was at 20 HP when Bob landed the final blow
    assert bob["stolen_from"] == 0
    assert bob["whiff_lives"] == 0  # Bob dealt 80 dmg softening Alice in his life
    alice = by_sid[S_ALICE]
    assert alice["stolen_from"] == 0  # Alice only took 100->80, never crossed <=30
    assert alice["whiff_lives"] == 1  # Alice died having dealt <10 damage
    carol = by_sid[S_CAROL]
    assert carol["kills"] == 1
    assert carol["wallbang"] == 1  # her kill of Bob was a wallbang


def test_funlab_nan_steamid_is_not_a_player() -> None:
    """attacker_steamid=NaN must not create a fake 'nan' player (§7.8)."""
    deaths = pd.DataFrame({
        "tick": [600],
        "attacker_steamid": [float("nan")],  # world damage (fall death)
        "user_steamid": [S_ALICE],
        "user_name": ["Alice"],
        "weapon": ["world"],
    })
    demo = build_parsed_demo(events={"player_death": deaths})
    r = AnalysisRunner(AnalysisConfig(enabled_modules=["funlab"])).run_one(demo, "funlab")
    assert all(p["steamid"] != "nan" for p in r.players)


def test_funlab_web_contract(web_client) -> None:
    """The lab lives at /players?tab=lab (Phase X merge); /fun-lab 301s there
    and the API enforces the >=3 demos gate."""
    c, h, _ = web_client
    page = c.get("/fun-lab", follow_redirects=False)
    assert page.status_code == 301
    assert page.headers["location"] == "/players?tab=lab"
    lab = c.get("/players?tab=lab")
    assert lab.status_code == 200
    assert "fl-quadrant" in lab.text  # the lazy-mounted lab containers ship SSR
    d = c.get("/api/funlab.json").json()
    assert d["gate"]["min_demos"] == 3
    # synthetic library has 1 demo -> everything gated, empty chart data
    assert d["players"] == []
    assert d["gate"]["gated"] > 0


def test_funlab_merge_across_demos(web_client) -> None:
    """The gate counts demo appearances, so 3 demos let a player through."""
    from cs_analyzer.cache import DemoCache
    from cs_analyzer.model.types import ProviderKind
    from cs_analyzer.web import app as web_app

    cache: DemoCache = web_app._cache()
    for i in range(3):
        demo = build_parsed_demo(events=_events())
        demo.data.metadata.demo_hash = f"fun{i}"
        demo.data.metadata.demo_path = f"fun{i}.dem"
        demo.data.metadata.provider = ProviderKind.UNKNOWN
        cache.save(f"fun{i}", demo)
    from cs_analyzer.web import aggregation, funlab_data

    aggregation.invalidate_aggregate()
    d = c_get_json(web_app)
    assert isinstance(d["players"], list) and d["players"], "3 demos pass the gate"
    bob = next(p for p in d["players"] if p["name"] == "Bob")
    assert bob["snipe_rate"] > 0
    assert bob["kills"] >= 3


def _g161_parsed(demo_hash: str) -> "object":
    """A synthetic demo whose FILENAME carries the g161- 5E marker."""
    demo = build_parsed_demo(events=_events())
    demo.data.metadata.demo_hash = demo_hash
    demo.data.metadata.demo_path = f"g161-2026090{demo_hash[-1]}2200000000000000_de_mirage.dem"
    return demo


def test_funlab_platform_filter(web_client) -> None:
    """Y2: platform= divides the library (filename-derived); the unfiltered
    report reports the per-platform counts."""
    from cs_analyzer.cache import DemoCache
    from cs_analyzer.web import aggregation, app as web_app

    cache: DemoCache = web_app._cache()
    # base fixture demo = numeric-named path "synthetic.dem" -> perfect_world
    for i in range(3):
        demo = _g161_parsed(f"p{i}")
        demo.data.metadata.demo_hash = f"p{i}"
        cache.save(f"p{i}", demo)
    from cs_analyzer.web import funlab_data

    aggregation.invalidate_aggregate()
    funlab_data.invalidate_funlab()
    c = web_client[0]
    all_r = c.get("/api/funlab.json").json()
    assert all_r["platform_counts"] == {"five_e": 3, "perfect_world": 1}
    fe = c.get("/api/funlab.json?platform=five_e").json()
    assert fe["selected_demos"] == 3
    pw = c.get("/api/funlab.json?platform=perfect_world").json()
    assert pw["selected_demos"] == 1
    # an unknown platform value falls back to all (route contract)
    junk = c.get("/api/funlab.json?platform=nonsense").json()
    assert junk["selected_demos"] == 4
    funlab_data.invalidate_funlab()


def test_donor_board_is_per_demo(web_client, monkeypatch) -> None:
    """Y2 用户裁决：donor 榜按 Σ发枪价值÷场次 排序（每场均值），绝对值进行内括号。"""
    from cs_analyzer.web import funlab_data

    fake_players = [
        {"steamid": "s1", "name": "A", "kills": 20, "demos": 2,
         "drops_value": 8000, "own_spend": 10000},
        {"steamid": "s2", "name": "B", "kills": 20, "demos": 8,
         "drops_value": 9000, "own_spend": 10000},
    ]

    def fake_scan():
        return {"entries": [], "regulars": set(), "dates": []}

    monkeypatch.setattr(funlab_data, "_scan_all", fake_scan)
    monkeypatch.setattr(funlab_data, "_merge",
                        lambda scan, stack, dates, platform: {
                            "players": fake_players,
                            "boards": {"donor": sorted(
                                fake_players,
                                key=lambda x: -(x["drops_value"] / x["demos"]))},
                        })
    funlab_data.invalidate_funlab()
    d = funlab_data.funlab_report()
    funlab_data.invalidate_funlab()
    board = d["boards"]["donor"]
    # B has more total value (9000 > 8000) but a lower per-demo mean
    # (1125 vs 4000) — per-demo ordering puts A first
    assert board[0]["steamid"] == "s1"
    defs = funlab_data.BOARD_DEFS["donor"]
    assert "每场" in defs["title"] and "÷ 场次" in defs["formula"]


def c_get_json(web_app):
    from fastapi.testclient import TestClient

    c = TestClient(web_app.app)
    return c.get("/api/funlab.json").json()
