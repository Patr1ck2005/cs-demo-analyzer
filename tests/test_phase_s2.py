"""Phase S2 tests: conf display completion, scan-sources dry-run, hygiene."""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from cs_analyzer.model.parsed_demo import ParsedDemo
from tests.conftest import S_ALICE, build_demo_data, build_parsed_demo


# ---------- S2-A1: stats.py participates in the snapshot fingerprint ----------

def test_stats_registered_in_snapshot_sources():
    from cs_analyzer.web import snapshots

    assert "analysis/stats.py" in snapshots._SNAPSHOT_SOURCES


# ---------- S2-A5: /api/system/scan-sources.json dry-run ----------

def _make_zip(path: Path, inner_name: str, payload: bytes) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(inner_name, payload)


@pytest.fixture
def scan_client(tmp_path, monkeypatch):
    """web_client with demos/ + configs/demo_sources.yaml pointed at tmp."""
    from fastapi.testclient import TestClient

    from cs_analyzer.cache import DemoCache
    from cs_analyzer.config import Settings
    from cs_analyzer.web import aggregation, app as web_app

    demo = build_parsed_demo()
    cache = DemoCache(tmp_path / "cache")
    cache.save(demo.metadata.demo_hash, demo)

    demos_dir = tmp_path / "demos"
    demos_dir.mkdir()
    # one existing demo inside demos/ whose content equals the dup zip payload
    (demos_dir / "existing.dem").write_bytes(b"EXISTING-DEMO-BYTES")

    cfg = tmp_path / "configs"
    cfg.mkdir()
    (cfg / "demo_sources.yaml").write_text(
        "perfect:\n"
        f"  path: {tmp_path / 'src1'}\n"
        "  enabled: true\n"
        "  pattern: '*.zip'\n"
        "disabled_plat:\n"
        f"  path: {tmp_path / 'src2'}\n"
        "  enabled: false\n",
        encoding="utf-8",
    )

    src1 = tmp_path / "src1"
    src1.mkdir()
    _make_zip(src1 / "new.zip", "brand_new.dem", b"BRAND-NEW-DEMO-PAYLOAD")
    _make_zip(src1 / "dup.zip", "existing.dem", b"EXISTING-DEMO-BYTES")
    _make_zip(src1 / "bad.zip", "truncated.dem", b"x")  # then truncate it
    raw = (src1 / "bad.zip").read_bytes()
    (src1 / "bad.zip").write_bytes(raw[: len(raw) // 2])  # EOCD gone

    monkeypatch.setattr(web_app, "_cache", lambda: cache)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "web")
    monkeypatch.setattr(web_app, "_demos_dir", lambda: demos_dir)
    monkeypatch.setattr(web_app, "_settings", lambda: Settings())
    monkeypatch.chdir(tmp_path)  # app reads configs/demo_sources.yaml relatively
    aggregation.invalidate_aggregate()
    return TestClient(web_app.app), demos_dir


def test_scan_sources_dry_run(scan_client):
    client, demos_dir = scan_client
    r = client.get("/api/system/scan-sources.json")
    assert r.status_code == 200
    body = r.json()
    assert body["total_new"] == 1
    src = next(s for s in body["sources"] if s["name"] == "perfect")
    assert src["zips"] == 3
    assert src["new"] == 1 and src["new_files"] == ["brand_new.dem"]
    assert src["duplicates"] == 1  # content hash matches existing.dem
    assert src["corrupt"] == 1     # truncated EOCD
    # disabled platform not reported
    assert all(s["name"] != "disabled_plat" for s in body["sources"])
    # dry-run: demos/ untouched
    assert sorted(p.name for p in demos_dir.glob("*.dem")) == ["existing.dem"]


def test_scan_sources_missing_config(web_client, monkeypatch, tmp_path):
    client, _h, _demo = web_client
    monkeypatch.chdir(tmp_path)  # no configs/demo_sources.yaml here
    r = client.get("/api/system/scan-sources.json")
    assert r.status_code == 404


# ---------- S2-A2: conf display contract (templates render the payload) ----------

def test_compare_template_renders_conf(web_client):
    client, _h, _demo = web_client
    html = client.get("/compare").text
    assert "fmtConf" in html and "m.conf" in html


def test_mapdata_payload_carries_conf_for_map_page(web_client):
    client, _h, _demo = web_client
    r = client.get("/api/map-analysis.json")
    assert r.status_code == 200
    for m in r.json()["maps"]:
        assert "t_win_conf" in m
        for bp in m["best_players"]:
            assert "conf" in bp and "rating_shrunk" in bp


# ---------- S2-V4: failure settles placeholders (static locks) ----------

def test_utilitylab_failure_resets_placeholders():
    js = Path("cs_analyzer/web/static/js/utilitylab.js").read_text(encoding="utf-8")
    assert "数据不可用（服务端错误）" in js


def test_career_conf_failure_settles():
    html = Path("cs_analyzer/web/templates/player_career.html").read_text(encoding="utf-8")
    assert "区间不可用" in html


# ---------- S2-A3: dead code gone ----------

def test_funlab_data_has_no_dead_conf_note():
    src = Path("cs_analyzer/web/funlab_data.py").read_text(encoding="utf-8")
    assert "_CONF_DEFS_NOTE" not in src
