"""Tests for the LTG-2 web platform (FastAPI routes + rendering smoke)."""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from cs_analyzer.cache import DemoCache
from cs_analyzer.web import app as web_app

from .conftest import S_ALICE, S_BOB, S_CAROL, build_parsed_demo


@pytest.fixture
def web_client(tmp_path, monkeypatch):
    """Temp-cached synthetic demo + monkeypatched app (cache dir & output)."""
    ticks = pd.DataFrame(
        {
            "tick": [0, 640, 1280, 1920, 2560, 3200],
            "steamid": [S_ALICE] * 6,
            "X": [0.0, 100.0, 200.0, 300.0, 400.0, 500.0],
            "Y": [0.0] * 6,
            "is_alive": [True] * 6,
            "team_num": [3.0] * 6,
        }
    )
    events = {
        "player_death": pd.DataFrame(
            {"tick": [1000, 2000, 3000],
             "attacker_name": ["Bob", "Alice", "Bob"],
             "user_name": ["Alice", "Bob", "Carol"],
             "attacker_steamid": [S_BOB, S_ALICE, S_BOB],
             "user_steamid": [S_ALICE, S_BOB, S_CAROL],
             "assister_steamid": ["", "", ""],
             "weapon": ["ak47", "usp", "knife"]}
        )
    }
    demo = build_parsed_demo(ticks=ticks, events=events)
    demo_hash = demo.metadata.demo_hash
    cache = DemoCache(tmp_path / "cache")
    cache.save(demo_hash, demo)
    monkeypatch.setattr(web_app, "_cache", lambda: cache)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "web")
    return TestClient(web_app.app), demo_hash, demo


def test_index(web_client) -> None:
    c, _, _ = web_client
    r = c.get("/")
    assert r.status_code == 200
    assert "Demo 库" in r.text
    for token in ("dropzone", "跨场聚合", "实时回放"):
        assert token in r.text
    assert "视频导出" not in r.text  # video studio retired in Phase E


# ---------- Phase B: 2D map viewer + export studio ----------


def test_viewer_page(web_client) -> None:
    c, h, _ = web_client
    r = c.get(f"/demo/{h}/viewer")
    assert r.status_code == 200
    # Phase C: real-time canvas OB layout replaces the pre-rendered video MVP
    for token in ("ob-layout", "main-layer", "viewer_canvas.js"):
        assert token in r.text
    assert "frm-prerender" not in r.text
    assert "<video" not in r.text


def test_viewer_data_route(web_client) -> None:
    """GET viewer-data builds (or serves) the canvas payload with gzip."""
    c, h, _ = web_client
    r = c.get(f"/api/demo/{h}/viewer-data", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    data = r.json()
    assert data["viewer_version"] >= 1
    assert "segments" in data and "players" in data and "map" in data
    assert "weapon_table" in data and "teams" in data
    # second hit serves from disk
    r2 = c.get(f"/api/demo/{h}/viewer-data")
    assert r2.status_code == 200


def test_viewer_layers_route(web_client) -> None:
    """/viewer-layers builds once, then serves the cached artifact."""
    c, h, _ = web_client
    r = c.get(f"/api/demo/{h}/viewer-layers?with=shots,economy")
    assert r.status_code == 200
    data = r.json()
    assert data["layer_version"] == 1
    assert "shots" in data and "economy" in data and "weapon_table" in data
    r2 = c.get(f"/api/demo/{h}/viewer-layers?with=shots")
    assert r2.status_code == 200
    assert r2.json()["layer_version"] == 1


def test_maps_route(web_client) -> None:
    c, _, _ = web_client
    r = c.get("/maps/de_mirage.png")
    if r.status_code == 200:  # image present in this checkout
        assert r.headers["cache-control"].startswith("public")
        assert len(r.content) > 1000
    r404 = c.get("/maps/not_a_map.png")
    assert r404.status_code == 404
    r_trav = c.get("/maps/..%2fapp.py")
    assert r_trav.status_code in (404, 400)


def test_demo_detail(web_client) -> None:
    c, h, _ = web_client
    r = c.get(f"/demo/{h}")
    assert r.status_code == 200
    for token in ("选手统计", "回合时间线", "击杀流"):
        assert token in r.text
    # D3: kills grouped by round, collapsed <details> per round
    assert "kill-group" in r.text
    assert "<details" in r.text


def test_coverage_route(web_client, monkeypatch, tmp_path) -> None:
    """/coverage serves the CLI artifact when present, else a hint page."""
    c, _, _ = web_client
    # cwd without the report -> hint page (HTTP 200 + message, error.html convention)
    monkeypatch.chdir(tmp_path)
    r = c.get("/coverage")
    assert r.status_code == 200
    assert "csa coverage" in r.text
    # with the artifact present -> served as file
    d = tmp_path / "output" / "coverage"
    d.mkdir(parents=True)
    (d / "coverage.html").write_text("<html>覆盖度报告 OK</html>", encoding="utf-8")
    r2 = c.get("/coverage")
    assert r2.status_code == 200
    assert "覆盖度报告 OK" in r2.text


def test_player_detail(web_client) -> None:
    c, h, demo = web_client
    sid = demo.players[0].steamid
    r = c.get(f"/demo/{h}/player/{sid}")
    assert r.status_code == 200
    for token in ("属性雷达", "Rating", "团队实时回放"):
        assert token in r.text
    # video recipes retired: no render buttons / <video> tags remain
    assert "startReplay" not in r.text
    assert "<video" not in r.text


def test_player_detail_untracked_explainer(web_client) -> None:
    """Team 0 / untracked players get the explanation card; stats stay complete."""
    from .conftest import S_BOB

    c, h, _ = web_client
    r = c.get(f"/demo/{h}/player/{S_BOB}")  # Bob has no tick rows
    assert r.status_code == 200
    assert "无位置数据" in r.text
    assert "团队视角回放仍可用" in r.text
    assert "startReplay" not in r.text


def test_demo_detail_links_viewer(web_client) -> None:
    c, h, _ = web_client
    r = c.get(f"/demo/{h}")
    assert r.status_code == 200
    assert "/demo/" + h + "/viewer" in r.text
    assert "进入实时回放" in r.text


def test_aggregate(web_client) -> None:
    c, _, _ = web_client
    r = c.get("/aggregate")
    assert r.status_code == 200
    assert "跨场聚合" in r.text
    assert "matrix-chart" in r.text  # ECharts container present


def test_chart_endpoints(web_client) -> None:
    """/charts.json endpoints return ECharts payloads on the synthetic demo."""
    c, h, demo = web_client
    r = c.get(f"/api/demo/{h}/charts.json")
    assert r.status_code == 200
    data = r.json()
    assert len(data["indicators"]) == 6
    assert data["series"] and 0 <= data["series"][0]["values"][0] <= 100

    sid = demo.players[0].steamid
    r2 = c.get(f"/api/demo/{h}/player/{sid}/charts.json")
    assert r2.status_code == 200
    pdata = r2.json()
    assert "heatmap" in pdata and "utility" in pdata and "style" in pdata
    assert pdata["heatmap"]["points"] == [] or all(
        0 <= p[0] <= 1 and 0 <= p[1] <= 1 for p in pdata["heatmap"]["points"])

    r3 = c.get("/api/aggregate/charts.json")
    assert r3.status_code == 200
    adata = r3.json()
    assert "matrix" in adata and "bars" in adata and "trends" in adata
