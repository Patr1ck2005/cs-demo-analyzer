"""Tests for Phase F advanced analysis modules (M7/M8)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cs_analyzer.analysis.base import AnalysisContext
from cs_analyzer.analysis.duels import DuelsModule, DuelMatrixResult
from cs_analyzer.analysis.economy import EconomyModule, build_purchase_log
from cs_analyzer.analysis.routes import OpeningRouteModule, choose_k, kmeans, resample_path
from cs_analyzer.analysis.utility_effect import UtilityEffectModule
from cs_analyzer.config import AnalysisConfig

from .conftest import S_ALICE, S_BOB, S_CAROL, S_DAVE, build_parsed_demo

pytest.importorskip("fastapi.testclient")


def _ctx() -> AnalysisContext:
    return AnalysisContext(AnalysisConfig())


# ---------- duels ----------


def test_duel_matrix_symmetry_totals() -> None:
    """sum(kills) == total deaths attributed to killers; matrix is directional."""
    deaths = pd.DataFrame({
        "tick": [100, 200, 300, 400, 500, 600, 700, 800, 900],
        "attacker_name": ["Alice", "Bob", "Alice", "Carol", "Alice", "Bob", "Alice", "Carol", "Alice"],
        "user_name": ["Bob", "Alice", "Bob", "Alice", "Bob", "Alice", "Bob", "Alice", "Dave"],
        "attacker_steamid": [S_ALICE, S_BOB, S_ALICE, S_CAROL, S_ALICE, S_BOB, S_ALICE, S_CAROL, S_ALICE],
        "user_steamid": [S_BOB, S_ALICE, S_BOB, S_ALICE, S_BOB, S_ALICE, S_BOB, S_ALICE, S_DAVE],
    })
    demo = build_parsed_demo(ticks=pd.DataFrame({
        "tick": [0], "steamid": [S_ALICE], "X": [0.0], "Y": [0.0], "team_num": [3.0],
    }), events={"player_death": deaths})
    result = DuelsModule().run(demo, _ctx())
    assert isinstance(result, DuelMatrixResult)
    # Alice killed Bob 4 times; Bob killed Alice 2 times
    assert result.kills[S_ALICE][S_BOB] == 4
    assert result.kills[S_BOB][S_ALICE] == 2
    assert result.kills[S_CAROL][S_ALICE] == 2
    # Alice also killed Dave once (Dave has no kills back)
    assert result.kills[S_ALICE][S_DAVE] == 1
    # total kills in matrix == all 9 non-suicide rows (fixture rounds start at 0)
    assert result.total_kills() == 9


def test_duel_matrix_skips_suicides_and_warmup() -> None:
    deaths = pd.DataFrame({
        "tick": [0, 50, 100],
        "attacker_steamid": [S_ALICE, S_ALICE, S_ALICE],
        "user_steamid": [S_ALICE, S_ALICE, S_BOB],
        "attacker_name": ["Alice"] * 3,
        "user_name": ["Alice", "Alice", "Bob"],
    })
    demo = build_parsed_demo(ticks=pd.DataFrame({
        "tick": [0], "steamid": [S_ALICE], "X": [0.0], "Y": [0.0], "team_num": [3.0],
    }), events={"player_death": deaths})
    result = DuelsModule().run(demo, _ctx())
    # suicide rows (att==vic) dropped; warmup row (tick < round start) dropped
    assert result.total_kills() == 1


# ---------- economy ----------


def test_economy_thresholds() -> None:
    """Boundary spends classify as eco (<2000) / force (<3700) / full."""
    from cs_analyzer.analysis.economy import ECO_MAX, FORCE_MAX
    assert ECO_MAX == 2000 and FORCE_MAX == 3700
    demo = build_parsed_demo(
        ticks=pd.DataFrame({
            "tick": [0, 0, 0, 0, 2560, 2560, 2560, 2560],
            "steamid": [S_ALICE, S_BOB, S_CAROL, S_DAVE] * 2,
            "X": [0.0] * 8, "Y": [0.0] * 8,
            "team_num": [3.0, 3.0, 2.0, 2.0] * 2,
        }),
        events={"item_purchase": pd.DataFrame({
            "tick": [10, 10, 10, 10, 2570, 2570, 2570, 2570],
            "steamid": [S_ALICE, S_BOB, S_CAROL, S_DAVE] * 2,
            "item_name": ["ak47", "ak47", "deagle", "ump45",
                          "awp", "awp", "ak47", "ak47"],
            "cost": [2700, 2700, 900, 1250, 4750, 4750, 2700, 2700],
        })},
    )
    result = EconomyModule().run(demo, _ctx())
    by_round = {(r.round, r.side): r for r in result.rounds}
    # round 1 CT: (2700+2700)/2 = 2700 -> force
    assert by_round[(1, "CT")].buy == "force"
    # round 1 T: (900+1250)/2 = 1075 -> eco
    assert by_round[(1, "T")].buy == "eco"
    # round 2 CT: 4750 avg -> full
    assert by_round[(2, "CT")].buy == "full"
    # round 2 T: 2700 avg -> force
    assert by_round[(2, "T")].buy == "force"


def test_economy_win_by_buy() -> None:
    demo = build_parsed_demo(
        ticks=pd.DataFrame({
            "tick": [0, 0, 0, 0, 2560, 2560, 2560, 2560],
            "steamid": [S_ALICE, S_BOB, S_CAROL, S_DAVE] * 2,
            "X": [0.0] * 8, "Y": [0.0] * 8,
            "team_num": [3.0, 3.0, 2.0, 2.0] * 2,
        }),
        events={"item_purchase": pd.DataFrame({
            "tick": [10, 10, 10, 10, 2570, 2570, 2570, 2570],
            "steamid": [S_ALICE, S_BOB, S_CAROL, S_DAVE] * 2,
            "item_name": ["ak47"] * 8,
            "cost": [2700] * 8,
        })},
    )
    result = EconomyModule().run(demo, _ctx())
    # round winners come from the fixture rounds (R1 CT, R2 T)
    assert result.win_by_buy["CT"]["force"]["wins"] == 1
    assert result.win_by_buy["T"]["force"]["wins"] == 1


def test_purchase_log_shared_with_viewer_layers() -> None:
    """build_purchase_log is the single source: viewer layers consume it."""
    demo = build_parsed_demo(
        ticks=pd.DataFrame({
            "tick": [0, 0], "steamid": [S_ALICE, S_CAROL],
            "X": [0.0, 0.0], "Y": [0.0, 0.0], "team_num": [3.0, 2.0],
        }),
        events={"item_purchase": pd.DataFrame({
            "tick": [10, 10],
            "steamid": [S_ALICE, S_CAROL],
            "item_name": ["weapon_ak47", "flashbang"],
            "cost": [2700, 200],
        })},
    )
    log = build_purchase_log(demo)
    assert log[1][S_ALICE]["spend"] == 2700
    assert log[1][S_CAROL]["nades"] == 1
    assert log[1][S_CAROL]["weapons"] == ["flashbang"]  # weapon_ prefix stripped


# ---------- utility effect ----------


def test_flash_value_friendly_penalty() -> None:
    """Friendly blinds count at half value; enemy blinds at full."""
    det = pd.DataFrame({
        "tick": [1000],
        "user_steamid": [S_ALICE],
        "user_name": ["Alice"],
        "X": [0.0], "Y": [0.0],
    })
    blind = pd.DataFrame({
        "tick": [1005, 1006, 1010],
        "user_steamid": [S_BOB, S_CAROL, S_ALICE],
        "blind_duration": [3.0, 2.0, 1.0],
    })
    demo = build_parsed_demo(
        ticks=pd.DataFrame({
            "tick": [0, 0, 0, 0], "steamid": [S_ALICE, S_BOB, S_CAROL, S_DAVE],
            "X": [0.0] * 4, "Y": [0.0] * 4, "team_num": [3.0, 3.0, 2.0, 2.0],
        }),
        events={"flashbang_detonate": det, "player_blind": blind},
    )
    result = UtilityEffectModule().run(demo, _ctx())
    assert len(result.flashers) == 1
    f = result.flashers[0]
    # Bob (friendly) 3.0s at 0.5 = 1.5; Carol (enemy) 2.0s full; self-blind excluded
    assert f["enemy_blind_s"] == 2.0
    assert f["friendly_blind_s"] == 3.0
    assert f["value"] == 3.5


def test_smoke_denial_positional_predicate() -> None:
    """Kill counts as smoke kill when victim inside live smoke, attacker outside."""
    det = pd.DataFrame({
        "tick": [1000], "X": [500.0], "Y": [500.0], "entityid": [7],
    })
    deaths = pd.DataFrame({
        "tick": [1100, 1200],
        "attacker_steamid": [S_ALICE, S_BOB],
        "user_steamid": [S_BOB, S_ALICE],
        "attacker_name": ["Alice", "Bob"],
        "user_name": ["Bob", "Alice"],
        "attacker_X": [0.0, 500.0],   # Alice outside for kill 1; inside for kill 2
        "attacker_Y": [0.0, 500.0],
        "user_X": [500.0, 0.0],       # Bob inside for kill 1; outside for kill 2
        "user_Y": [500.0, 0.0],
    })
    demo = build_parsed_demo(
        ticks=pd.DataFrame({
            "tick": [0], "steamid": [S_ALICE], "X": [0.0], "Y": [0.0], "team_num": [3.0],
        }),
        events={"smokegrenade_detonate": det, "player_death": deaths},
    )
    result = UtilityEffectModule().run(demo, _ctx())
    by_sid = {s["steamid"]: s for s in result.smoke}
    assert by_sid[S_ALICE]["smoke_kills"] == 1  # killed Bob through the smoke
    assert by_sid[S_BOB]["smoke_deaths"] == 1


# ---------- opening routes ----------


def test_resample_path_equidistant() -> None:
    xs = np.array([0.0, 100.0, 200.0, 300.0])
    ys = np.zeros(4)
    out = resample_path(xs, ys, n=5)
    assert out.shape == (5, 2)
    np.testing.assert_allclose(out[:, 0], [0, 75, 150, 225, 300], atol=1e-6)


def test_kmeans_deterministic_and_separated() -> None:
    """Two obvious clusters: 100% separation, identical labels across runs."""
    rng = np.random.default_rng(0)
    cluster_a = np.column_stack([rng.normal(0, 1, 20), rng.normal(0, 1, 20)])
    cluster_b = np.column_stack([rng.normal(100, 1, 20), rng.normal(100, 1, 20)])
    data = np.vstack([cluster_a, cluster_b])
    centroids, labels, inertia = kmeans(data, k=2, seed=42)
    assert set(labels[:20]) != set(labels[20:]) or True  # labels may swap; check purity
    first20 = labels[:20]
    assert len(set(first20.tolist())) == 1
    assert len(set(labels[20:].tolist())) == 1
    assert first20[0] != labels[20]
    # deterministic: same seed -> same result
    _, labels2, _ = kmeans(data, k=2, seed=42)
    np.testing.assert_array_equal(labels, labels2)


def test_choose_k_picks_elbow() -> None:
    rng = np.random.default_rng(1)
    xs = np.concatenate([rng.normal(0, 0.5, 30), rng.normal(50, 0.5, 30),
                         rng.normal(100, 0.5, 30)])
    data = np.column_stack([xs, np.zeros(90)])
    assert choose_k(data) >= 2


def test_routes_module_clusters_synthetic_paths() -> None:
    """Two separated opening routes cluster into 2 centroids."""
    from .conftest import build_demo_data, make_round
    from cs_analyzer.model.parsed_demo import ParsedDemo

    # 5 rounds: R1-R2 walk +x at y=0; R3-R5 at y=1000 (25s each at 64 tick)
    rounds = [
        make_round(1, 0, 1600, "T"), make_round(2, 1600, 3200, "T"),
        make_round(3, 3200, 4800, "CT"), make_round(4, 4800, 6400, "CT"),
        make_round(5, 6400, 8000, "T"),
    ]
    data = build_demo_data()
    data.rounds = rounds  # DemoData.rounds drives regular_rounds
    ticks = []
    for (start, y) in [(0, 0.0), (1600, 0.0), (3200, 1000.0),
                       (4800, 1000.0), (6400, 1000.0)]:
        for t in range(start, start + 1600, 64):
            for sid in (S_CAROL, S_DAVE):
                ticks.append({"tick": float(t), "steamid": sid,
                              "X": float(t - start) * 2.0, "Y": y, "team_num": 2.0})
    demo = ParsedDemo(data=data, events={}, ticks=pd.DataFrame(ticks))
    result = OpeningRouteModule().run(demo, _ctx())
    assert result.side == "T"
    assert result.k == 2
    assert len(result.routes) == 2
    shares = sorted(r["share"] for r in result.routes)
    assert shares == [0.4, 0.6]  # 2 rounds on route A, 3 on route B
