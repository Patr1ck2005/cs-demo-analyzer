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
    assert "Demo 复盘平台" in r.text


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
