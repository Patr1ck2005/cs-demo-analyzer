"""Phase W button-level audit regressions (高危交互审计修复).

One test per audited server-side defect fix, hermetic (no real parses, no
playwright):
  F3  ev_table total_rounds sums per-demo rounds + ev_cells shard roundtrip
  F5  weapon_timeline exposes/respects the demo's real tick_rate
  F7  concurrent parse jobs for the same content serialize on a per-hash lock
  F9  export filenames carry microseconds (same-second collisions impossible)
  F10 /upload rejects non-.dem names before anything hits demos/
  F11 TaskManager evicts finished jobs above the cap
  W1b favorites.js / funlab.js / viewer_control.js / warmup.js /
      viewer_prefs.js behavior is browser-side — covered by
      scripts/accept_buttons.py instead.
"""
from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor

from cs_analyzer.web import app as web_app


# ---------- F3: EV table rounds + shards ----------


def test_ev_table_rounds_sum(web_client, monkeypatch, tmp_path) -> None:
    """total_rounds = SUM of per-demo rounds (was hardcoded 0 → '本表 N=0')."""
    from cs_analyzer.web import ev_data

    ev_data.invalidate_ev()
    fake = [
        {"rounds": 24, "cells": [
            {"buy": "eco", "side": "T", "score_bin": "even", "streak_bin": "warm",
             "n": 10, "wins": 4, "survived_sum": 3.0},
        ]},
        {"rounds": 13, "cells": [
            {"buy": "eco", "side": "T", "score_bin": "even", "streak_bin": "warm",
             "n": 8, "wins": 2, "survived_sum": 0.0},
        ]},
    ]
    monkeypatch.setattr(ev_data, "_scan_all", lambda: fake)
    table = ev_data.ev_table()
    assert table["total_rounds"] == 37
    cell = next(c for c in table["cells"] if c["n"] == 18)
    assert cell["n"] == 18 and cell["wins"] == 6
    assert cell["win_rate"] == round(6 / 18, 3)
    # survived=0.0 contribution is a legitimate rate (must not collapse to None)
    assert cell["survived"] == round(3.0 / 18, 3)
    ev_data.invalidate_ev()


def test_ev_shards_roundtrip(web_client, monkeypatch, tmp_path) -> None:
    """_scan_all persists per-demo payloads as ev_cells shards; a warm cache
    reloads them without re-running the module fn."""
    from cs_analyzer.web import ev_data, snapshots

    _c, h, _demo = web_client
    cache_dir = web_app._cache().cache_dir
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "web")
    ev_data.invalidate_ev()

    calls = {"n": 0}

    def fake_payload(d):
        calls["n"] += 1
        return {"rounds": 7, "cells": []}

    monkeypatch.setattr(ev_data, "_demo_payload", fake_payload)
    entries = ev_data._scan_all()
    assert calls["n"] == 1 and entries[0]["rounds"] == 7
    shard_root = tmp_path / "web" / "snapshots" / "shards" / "ev_cells"
    assert any(shard_root.rglob(f"{h}_*.json")), "shard file must be written"
    # warm path: memo reset + shard hit — fn must NOT run again
    ev_data.invalidate_ev()
    entries2 = ev_data._scan_all()
    assert calls["n"] == 1 and entries2 == entries
    got, missing = snapshots.load_shards("ev_cells", tmp_path / "web", cache_dir, [h])
    assert got and not missing
    ev_data.invalidate_ev()


# ---------- F5: weapon timeline tick rate ----------


def test_weapon_timeline_uses_demo_tick_rate(web_client) -> None:
    """The response carries the demo's real tick_rate (the seconds math now
    divides by it instead of a hardcoded 64 — 128-tick demos doubled)."""
    c, h, demo = web_client
    r = c.get(f"/api/demo/{h}/analysis/weapon_timeline.json")
    assert r.status_code == 200
    data = r.json()
    assert data["tick_rate"] == demo.metadata.tick_rate
    # synthetic demo has no active_weapon_name ticks -> no holds rendered
    assert data["players"] == []


# ---------- W1-surprise: rating21 career card shard cache ----------


def test_rating21_card_sharded_and_stable(web_client, monkeypatch, tmp_path) -> None:
    """_player_rating21 reads per-demo rating21 shards: first call writes
    them, later calls hit them, and the card value stays stable."""
    from tests.conftest import S_ALICE

    _c, h, _demo = web_client
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "web")

    card1 = web_app._player_rating21(S_ALICE)
    assert card1 is not None
    for key in ("rating21", "rating20", "kast21", "save_rounds"):
        assert key in card1
    shard_root = tmp_path / "web" / "snapshots" / "shards" / "rating21"
    assert any(shard_root.rglob(f"{h}_*.json")), "rating21 shard must exist"

    card2 = web_app._player_rating21(S_ALICE)
    assert card2 == card1, "round-weighted card drifted between calls"
    unknown = web_app._player_rating21("76561199999999999")
    assert unknown is None  # player absent from the library


# ---------- F7: per-hash parse serialization ----------


def test_parse_job_serializes_same_hash(web_client, monkeypatch, tmp_path) -> None:
    """Two concurrent _parse_job calls for identical content must run
    ParseManager.parse exactly once — the second reuses the cache."""
    _c, h, demo = web_client
    payload = b"CSDEMO-parity" * 100
    digest = hashlib.sha256(payload).hexdigest()
    dem_dir = tmp_path / "demos"
    dem_dir.mkdir(exist_ok=True)
    dem_file = dem_dir / "parity.dem"
    dem_file.write_bytes(payload)
    cache = web_app._cache()
    calls = {"parse": 0}

    class FakeManager:
        def __init__(self, cache=None):
            pass

        def parse(self, path, use_cache=True):
            calls["parse"] += 1
            time.sleep(0.15)  # widen the race window
            cache.save(digest, demo)
            return demo

    import cs_analyzer.parser.manager as pm

    monkeypatch.setattr(pm, "ParseManager", FakeManager)
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(web_app._parse_job, str(dem_file)) for _ in range(2)]
        results = [f.result(timeout=20) for f in futs]
    assert all(r == demo.metadata.demo_hash for r in results)
    assert calls["parse"] == 1, f"parse ran {calls['parse']}x for identical content"
    dem_file.unlink()


def test_parse_lock_registry_is_shared() -> None:
    """Same hash → the SAME lock object (the whole serialization contract)."""
    a = web_app._parse_lock("deadbeef")
    b = web_app._parse_lock("deadbeef")
    assert a is b
    assert web_app._parse_lock("cafe") is not a


# ---------- F9: export filename collision ----------


def test_export_stamp_has_microseconds() -> None:
    """Two stamps from the same second differ (µs suffix) — exports of the
    same demo in one second can no longer overwrite each other."""
    from cs_analyzer.web.report_export import _export_stamp

    s1 = _export_stamp()
    time.sleep(0.002)
    s2 = _export_stamp()
    assert s1 != s2
    assert len(s1.split("_")) == 3  # date_time_micros


# ---------- F10: upload extension gate ----------


def test_upload_rejects_non_dem(web_client, tmp_path) -> None:
    """A crafted POST with a .txt name is rejected before hitting demos/."""
    c, _, _ = web_client
    r = c.post("/upload", files=[("files", ("evil.txt", b"not a demo" * 10,
                                             "application/octet-stream"))])
    assert r.status_code == 200  # per-row error, not a 500
    assert "只支持 .dem" in r.text
    assert not (tmp_path / "demos" / "evil.txt").exists()


def test_upload_mixed_batch_partial_reject(web_client, tmp_path) -> None:
    """One bad name must not block the good file in the same batch."""
    c, _, _ = web_client
    r = c.post("/upload", files=[
        ("files", ("evil.txt", b"junk", "application/octet-stream")),
        ("files", ("good.dem", b"CSDEMO-good" * 40, "application/octet-stream")),
    ])
    assert r.status_code == 200
    assert "只支持 .dem" in r.text
    assert "good.dem" in r.text
    (tmp_path / "demos" / "good.dem").unlink(missing_ok=True)


# ---------- F11: job registry cap ----------


def test_task_manager_evicts_finished_jobs() -> None:
    """Above the cap, oldest FINISHED jobs are evicted; pending stay."""
    from cs_analyzer.web.tasks import TaskManager

    tm = TaskManager(max_workers=1)
    tm._MAX_JOBS = 5
    done_ids = [tm.submit(lambda: "x") for _ in range(6)]
    deadline = time.time() + 5
    while time.time() < deadline:
        # evicted jobs (None) count as finished for this wait
        if all((tm.get_status(j) or tm._jobs.get(j)) is None
               or tm.get_status(j).status == "done" for j in done_ids):
            break
        time.sleep(0.05)
    last = tm.submit(lambda: "y")
    assert len(tm._jobs) <= 5
    assert tm.get_status(last) is not None
    assert done_ids[0] not in tm._jobs  # oldest finished job evicted
