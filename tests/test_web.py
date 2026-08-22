"""Tests for the LTG-2 web platform (FastAPI routes + rendering smoke)."""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from cs_analyzer.cache import DemoCache
from cs_analyzer.web import app as web_app

from .conftest import S_ALICE, build_parsed_demo


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
    demo = build_parsed_demo(ticks=ticks)
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
    assert "CS2 Demo 分析器" in r.text
    for token in ("定量分析视角", "空间-时间回放视角", "跨场聚合", "视频导出"):
        assert token in r.text


# ---------- Phase B: 2D map viewer + export studio ----------


def test_viewer_page(web_client) -> None:
    c, h, _ = web_client
    r = c.get(f"/demo/{h}/viewer")
    assert r.status_code == 200
    for token in ("2D 地图回放", "预渲染整局回放"):
        assert token in r.text


def test_replay_map_missing(web_client) -> None:
    c, h, _ = web_client
    r = c.get(f"/api/demo/{h}/replay-map")
    assert r.status_code == 200
    assert r.json()["status"] == "missing"


def test_replay_map_start_job(web_client, monkeypatch) -> None:
    c, h, _ = web_client
    captured: dict = {}

    def fake_submit(fn, **kwargs):
        captured["kwargs"] = kwargs
        return "vjob"

    monkeypatch.setattr(web_app.tasks.tasks, "submit", fake_submit)
    r = c.post(f"/api/demo/{h}/replay-map", data={"speed": "10"})
    assert r.status_code == 200
    assert r.json()["job_id"] == "vjob"
    assert captured["kwargs"]["speed"] == 10.0


def test_viewer_segments_structure() -> None:
    from cs_analyzer.config import ReplayConfig
    from cs_analyzer.web import replay_map

    demo = build_parsed_demo()  # rounds [0,2560] and [2560,5120]
    cfg = ReplayConfig(fps=10, round_end_hold_seconds=1.0)
    segs = replay_map.build_viewer_segments(demo, cfg, speed=10.0)
    assert len(segs) == 2
    s1 = segs[0]
    assert s1["round"] == 1
    assert s1["start_tick"] == 0 and s1["end_tick"] == 2560
    assert s1["n_frames"] == 40  # 2560 ticks / (64*10/10) = 40
    assert s1["hold_frames"] == 10  # 10 fps * 1.0s
    assert s1["video_end"] - s1["video_start"] == 50
    assert segs[1]["video_start"] == 50
    assert segs[0]["winner_side"] == "CT"


def test_viewer_events_extraction() -> None:
    from cs_analyzer.web import replay_map

    demo = build_parsed_demo(
        events={
            "player_death": pd.DataFrame(
                {"tick": [1000, 2000], "attacker_name": ["Bob", "Alice"],
                 "user_name": ["Alice", "Bob"], "weapon": ["ak47", "usp"]}
            ),
            "smokegrenade_detonate": pd.DataFrame({"tick": [1500], "x": [10.0], "y": [20.0]}),
        }
    )
    ev = replay_map.build_viewer_events(demo)
    assert [k["victim"] for k in ev["kills"]] == ["Alice", "Bob"]
    assert ev["kills"][0]["attacker"] == "Bob"
    assert len(ev["utilities"]) == 1
    assert ev["utilities"][0]["kind"] == "烟雾"
    assert len(ev["rounds"]) == 2


def test_viewer_events_sanitizes_nan() -> None:
    """Team 0 players carry NaN positions/names in raw events; the viewer payload
    must stay finite so it serializes as strict JSON."""
    import json

    from cs_analyzer.web import replay_map

    demo = build_parsed_demo(
        events={
            "player_death": pd.DataFrame(
                {"tick": [1000], "attacker_name": [float("nan")],
                 "user_name": ["Alice"], "weapon": ["knife"]}
            ),
            "smokegrenade_detonate": pd.DataFrame(
                {"tick": [1500], "x": [float("nan")], "y": [5.0]}
            ),
        }
    )
    ev = replay_map.build_viewer_events(demo)
    assert ev["kills"][0]["attacker"] == ""
    assert ev["utilities"][0]["x"] == 0.0
    json.dumps(ev, allow_nan=False)  # must not raise


def test_studio_landing(web_client) -> None:
    c, _, _ = web_client
    r = c.get("/studio")
    assert r.status_code == 200
    assert "视频导出工作室" in r.text


def test_studio_replay_page(web_client) -> None:
    c, h, _ = web_client
    r = c.get(f"/studio/replay/{h}")
    assert r.status_code == 200
    assert "导出 2D 回放视频" in r.text
    assert "配方" in r.text


def test_studio_radar_page(web_client) -> None:
    c, h, _ = web_client
    r = c.get(f"/studio/radar/{h}")
    assert r.status_code == 200
    assert "导出雷达图视频" in r.text


def test_api_studio_replay(web_client, monkeypatch) -> None:
    c, h, _ = web_client
    captured: dict = {}

    def fake_submit(fn, **kwargs):
        captured["kwargs"] = kwargs
        return "sjob"

    monkeypatch.setattr(web_app.tasks.tasks, "submit", fake_submit)
    r = c.post(
        "/api/studio/replay",
        json={"demo_hash": h, "recipe": "s-openings", "override": {"canvas": {"width": 640}}},
    )
    assert r.status_code == 200
    assert r.json()["job_id"] == "sjob"
    assert captured["kwargs"]["recipe"] == "s-openings"
    assert captured["kwargs"]["override"]["canvas"]["width"] == 640


def test_api_studio_radar(web_client, monkeypatch) -> None:
    c, h, _ = web_client
    captured: dict = {}

    def fake_submit(fn, **kwargs):
        captured["kwargs"] = kwargs
        return "rjob"

    monkeypatch.setattr(web_app.tasks.tasks, "submit", fake_submit)
    r = c.post("/api/studio/radar", json={"demo_hash": h, "radar": {"title": "对局"}})
    assert r.status_code == 200
    assert r.json()["job_id"] == "rjob"
    assert captured["kwargs"]["radar"]["title"] == "对局"


def test_demo_detail(web_client) -> None:
    c, h, _ = web_client
    r = c.get(f"/demo/{h}")
    assert r.status_code == 200
    for token in ("选手统计", "回合时间线", "击杀流"):
        assert token in r.text


def test_player_detail(web_client) -> None:
    c, h, demo = web_client
    sid = demo.players[0].steamid
    r = c.get(f"/demo/{h}/player/{sid}")
    assert r.status_code == 200
    for token in ("属性雷达图", "回放", "生成回放"):
        assert token in r.text


def test_media_serves_radar(web_client) -> None:
    c, h, demo = web_client
    sid = demo.players[0].steamid
    c.get(f"/demo/{h}/player/{sid}")  # triggers radar PNG render
    r = c.get(f"/media/{h}/radar/{sid}.png")
    assert r.status_code == 200
    assert r.headers.get("content-type") == "image/png"
    assert len(r.content) > 1000


def test_aggregate(web_client) -> None:
    c, _, _ = web_client
    r = c.get("/aggregate")
    assert r.status_code == 200
    assert "跨场聚合分析" in r.text


def test_replay_endpoint_returns_job(web_client, monkeypatch) -> None:
    c, h, _ = web_client
    captured: dict = {}

    def fake_submit(fn, **kwargs):
        captured["kwargs"] = kwargs
        return "fakejob"

    monkeypatch.setattr(web_app.tasks.tasks, "submit", fake_submit)
    r = c.post(f"/api/demo/{h}/replay", data={"recipe": "s-openings", "player": "1"})
    assert r.status_code == 200
    assert r.json()["job_id"] == "fakejob"
    assert captured["kwargs"]["recipe"] == "s-openings"


def test_replay_unknown_recipe(web_client) -> None:
    c, h, _ = web_client
    r = c.post(f"/api/demo/{h}/replay", data={"recipe": "nope"})
    assert r.status_code == 400
