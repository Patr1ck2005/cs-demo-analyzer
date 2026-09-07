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


def c_get_json(web_app):
    from fastapi.testclient import TestClient

    c = TestClient(web_app.app)
    return c.get("/api/funlab.json").json()
