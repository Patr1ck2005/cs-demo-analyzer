"""Phase N: style-galaxy clustering tests (math + web contract)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from cs_analyzer.web.style_map import (
    _feature_matrix,
    cluster_labels,
    nearest_neighbors,
    pca_2d,
    personal_style,
    robust_scale,
    ward_clusters,
)
from tests.conftest import S_ALICE, S_BOB, S_CAROL, S_DAVE, build_parsed_demo


def test_feature_matrix_drops_constant_columns() -> None:
    players = [
        {"a": 1.0, "b": 0.2, "c": 5.0},
        {"a": 2.0, "b": 0.8, "c": 5.0},   # c constant
        {"a": 3.0, "b": 0.4, "c": 5.0},
    ]
    x, used, excluded = _feature_matrix(players, ["a", "b", "c"])
    assert used == ["a", "b"]
    assert excluded == ["c"]
    assert x.shape == (3, 2)


def test_robust_scale_drops_zero_variance() -> None:
    x = np.array([[1.0, 2.0], [1.0, 4.0], [1.0, 6.0]])  # col0 constant
    z, drop = robust_scale(x)
    assert drop == [0]
    assert z.shape == (3, 1)
    # IQR scaling: col1 median 4, IQR 2 -> z = [-1, 0, 1]
    assert np.allclose(z[:, 0], [-1.0, 0.0, 1.0])


def test_pca_shapes_and_variance() -> None:
    rng = np.random.default_rng(7)
    z = rng.normal(size=(20, 5))
    coords, v1, v2 = pca_2d(z)
    assert coords.shape == (20, 2)
    assert 0.0 < v1 < 1.0 and 0.0 <= v2 < 1.0 and v1 >= v2


def test_ward_separates_two_blobs() -> None:
    blob_a = np.random.default_rng(1).normal(loc=[3, 3], scale=0.1, size=(4, 2))
    blob_b = np.random.default_rng(2).normal(loc=[-3, -3], scale=0.1, size=(4, 2))
    z = np.vstack([blob_a, blob_b])
    labels = ward_clusters(z)
    assert len(set(labels)) == 2, "two far blobs must split into two clusters"
    assert labels[0] == labels[1] == labels[2] == labels[3]
    assert labels[4] == labels[5] == labels[6] == labels[7]
    assert labels[0] != labels[4]


def test_cluster_labels_high_low_direction() -> None:
    # col0: cluster0 way above median, cluster1 below; col1 the reverse
    z = np.array([
        [5.0, -5.0], [5.0, -5.0],
        [-5.0, 5.0], [-5.0, 5.0],
    ])
    labels = [0, 0, 1, 1]
    names = cluster_labels(z, labels, ["kill_rate", "dist"], {"kill_rate": "击杀率", "dist": "距离"}, top=1)
    assert "高击杀率" in names[0]
    assert "低击杀率" in names[1]


def test_nearest_neighbor_excludes_self() -> None:
    z = np.array([[0.0], [0.1], [9.0]])
    nn = nearest_neighbors(z)
    assert nn[0][1] == 1 and nn[1][1] == 0
    assert nn[2][1] in (0, 1)
    assert all(i != j for i, j, _ in nn)


def test_personal_style_falls_back_when_single_cluster() -> None:
    """全员一簇时个人画像兜底：每人标签按自己对中位数的偏离生成，互不相同。"""
    z = np.array([
        [4.0, -1.0, 0.2],    # 高特征0
        [-4.0, 2.0, 0.1],    # 低特征0
        [0.1, -0.2, 5.0],    # 高特征2
    ])
    med = np.median(z, axis=0)
    keys = ["k0", "k1", "k2"]
    labels_map = {k: k for k in keys}
    s = [personal_style(z[i], med, keys, labels_map) for i in range(3)]
    assert "高k0" in s[0] and "低k0" in s[1] and "高k2" in s[2]
    assert len(set(s)) == 3, "个人画像必须逐人不同"


def _style_events() -> dict[str, pd.DataFrame]:
    """Two distinct styles: Bob the aggro rifler (many close kills) vs
    Carol the passive awper (few, distant kills); purchases make round classes."""
    purchases = pd.DataFrame({
        "tick": [10, 20, 30, 40],
        "steamid": [S_ALICE, S_BOB, S_CAROL, S_DAVE],
        "item_name": ["glock", "AK-47", "SSG 08", "glock"],
        "cost": [0, 2700, 1700, 0],
    })
    deaths = pd.DataFrame({
        "tick": [600, 700, 800, 900],
        "attacker_steamid": [S_BOB, S_BOB, S_CAROL, S_ALICE],
        "user_steamid": [S_ALICE, S_DAVE, S_BOB, S_CAROL],
        "attacker_name": ["Bob", "Bob", "Carol", "Alice"],
        "user_name": ["Alice", "Dave", "Bob", "Carol"],
        "assister_steamid": ["", "", "", ""],
        "weapon": ["ak47", "ak47", "ssg08", "knife"],
        "penetrated": [False] * 4, "thrusmoke": [False] * 4,
        "noscope": [False] * 4, "attackerblind": [False] * 4,
        "attackerinair": [False] * 4,
        "user_health": [100.0, 100.0, 100.0, 100.0],
        "distance": [3.0, 4.0, 40.0, 1.0],
    })
    return {"item_purchase": purchases, "player_death": deaths}


def test_style_map_api_contract(web_client) -> None:
    """/fun-lab renders the galaxy container; the API returns valid points."""
    c, _, _ = web_client
    page = c.get("/fun-lab")
    assert page.status_code == 200
    assert "风格星系" in page.text
    d = c.get("/api/style-map.json").json()
    assert "note" in d and "cut_ratio" in d
    # single synthetic demo -> funlab gate blocks everyone -> empty but valid
    assert d["points"] == []


def test_style_map_with_three_demos(web_client) -> None:
    """3 demos pass the gate; points carry cluster/color/nearest and the PCA
    note sums to a share of variance."""
    from cs_analyzer.model.types import ProviderKind
    from cs_analyzer.web import aggregation

    c, h, _ = web_client
    from cs_analyzer.cache import DemoCache
    from cs_analyzer.web import app as web_app

    cache: DemoCache = web_app._cache()
    for i in range(3):
        demo = build_parsed_demo(events=_style_events())
        demo.data.metadata.demo_hash = f"sty{i}"
        demo.data.metadata.demo_path = f"sty{i}.dem"
        demo.data.metadata.provider = ProviderKind.UNKNOWN
        cache.save(f"sty{i}", demo)
    aggregation.invalidate_aggregate()
    d = c.get("/api/style-map.json").json()
    assert d["points"], "3 demos must pass the gate"
    assert len(d["points"]) == d["n_players"]
    for p in d["points"]:
        assert p["name"] and isinstance(p["cluster"], int)
        assert p["color"].startswith("#")
        assert -1e6 < p["x"] < 1e6 and -1e6 < p["y"] < 1e6
    if d["n_players"] >= 2:
        assert any(p["nearest"] for p in d["points"]), "n>=2 must have neighbors"
    var = d["pca"]["var_pc1"] + d["pca"]["var_pc2"]
    assert 0.0 < var <= 1.0 + 1e-9
