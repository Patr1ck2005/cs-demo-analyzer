"""Phase T1 鈥?disk snapshot round-trip, fingerprint invalidation, warmup wiring.

The snapshots feature must be invisible when it works and harmless when it
fails: a corrupt file is a miss, a fingerprint mismatch is a miss, and a
failing save never breaks the prewarm that just finished.
"""
from __future__ import annotations

import json


# ---------------------------------------------------------------- fingerprint


def test_fingerprint_changes_with_library(tmp_path):
    from cs_analyzer.web.snapshots import library_fingerprint

    (tmp_path / "demoA").mkdir()
    (tmp_path / "demoA" / "model.json").write_text('{"metadata": {"demo_path": "a.dem"}}',
                                                   encoding="utf-8")
    fp1 = library_fingerprint(tmp_path)
    (tmp_path / "demoB").mkdir()
    (tmp_path / "demoB" / "model.json").write_text('{"metadata": {"demo_path": "b.dem"}}',
                                                   encoding="utf-8")
    fp2 = library_fingerprint(tmp_path)
    assert fp1 != fp2, "adding a demo must change the fingerprint"

    # content change in an existing model.json also counts (metadata rewrite)
    (tmp_path / "demoA" / "model.json").write_text('{"metadata": {"demo_path": "a2.dem"}}',
                                                   encoding="utf-8")
    fp3 = library_fingerprint(tmp_path)
    assert fp2 != fp3, "model.json content change must change the fingerprint"

    # stable across calls (same inputs -> same digest)
    assert library_fingerprint(tmp_path) == fp3


def test_fingerprint_changes_with_source_code(tmp_path, monkeypatch):
    """A correctness fix in a producing module must invalidate snapshots 鈥?    the source digest is part of the fingerprint."""
    import cs_analyzer.web.snapshots as snaps

    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "model.json").write_text("{}", encoding="utf-8")
    fp1 = snaps.library_fingerprint(tmp_path)
    monkeypatch.setattr(snaps, "_src_digest_cache", "changed-digest-value")
    fp2 = snaps.library_fingerprint(tmp_path)
    assert fp1 != fp2


def test_fingerprint_ignores_empty_subdirs_and_files(tmp_path):
    from cs_analyzer.web.snapshots import library_fingerprint

    (tmp_path / "demoA").mkdir()
    (tmp_path / "demoA" / "model.json").write_text("{}", encoding="utf-8")
    fp1 = library_fingerprint(tmp_path)
    (tmp_path / "not_a_demo_file.txt").write_text("x", encoding="utf-8")
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    (empty / "ticks.parquet").write_bytes(b"")  # cache dir without model.json
    assert library_fingerprint(tmp_path) == fp1


def test_snapshot_sources_cover_produced_numbers():
    """S2-A1 + S3-A1: every layer that produces persisted numbers must sit
    inside _SNAPSHOT_SOURCES (T1 payloads AND T3 shard families — src8 is
    the digest of this list, so a missing producer means its numbers survive
    a code change under a fingerprint-identical rebuild). Kept as a
    family->producer map so the next shard family cannot be added without
    naming its producer file."""
    import cs_analyzer.web.snapshots as snaps

    family_producers = {
        # T1 whole-payload snapshot payloads (merge layer)
        "t1_conf_math": ["analysis/stats.py"],
        "aimsci": ["analysis/aim_science.py", "web/aim_data.py"],
        "lossattr": ["analysis/loss_attribution.py", "web/loss_data.py"],
        "ev_cells": ["analysis/economy_ev.py", "web/ev_data.py"],
        "winloo": ["analysis/win_probability.py", "web/winprob_loo.py"],
        "rating21": ["analysis/ratings21.py", "web/rating21_data.py"],
    }
    for family, producers in family_producers.items():
        for need in producers:
            assert need in snaps._SNAPSHOT_SOURCES, (
                f"{family}: {need} missing from _SNAPSHOT_SOURCES — its "
                "numbers would survive a code change inside a "
                "fingerprint-identical rebuild"
            )


# -------------------------------------------------------------- load / save


def test_save_load_roundtrip(tmp_path):
    from cs_analyzer.web.snapshots import library_fingerprint, load_snapshot, save_snapshot

    fp = library_fingerprint(tmp_path)
    payload = {"entries": [{"a": 1}], "regulars": ["s1", "s2"]}
    assert save_snapshot("map", fp, payload, tmp_path) is True
    assert load_snapshot("map", fp, tmp_path) == payload


def test_load_missing_returns_none(tmp_path):
    from cs_analyzer.web.snapshots import load_snapshot

    assert load_snapshot("map", "fp", tmp_path) is None


def test_load_corrupt_returns_none(tmp_path):
    """A truncated/garbage file is a miss, never an exception."""
    from cs_analyzer.web.snapshots import load_snapshot

    d = tmp_path / "snapshots"
    d.mkdir()
    (d / "map.json").write_text("{corrupt!!", encoding="utf-8")
    assert load_snapshot("map", "fp", tmp_path) is None


def test_load_fingerprint_mismatch_returns_none(tmp_path):
    from cs_analyzer.web.snapshots import load_snapshot, save_snapshot

    save_snapshot("map", "fp-old", {"v": 1}, tmp_path)
    assert load_snapshot("map", "fp-new", tmp_path) is None
    assert load_snapshot("map", "fp-old", tmp_path) == {"v": 1}


def test_save_failure_is_fail_soft(tmp_path):
    """An unwritable target must not raise 鈥?the prewarm just finished and
    must not die in its snapshot pass (snapshots_dir == an existing FILE
    makes the mkdir/store fail)."""
    import cs_analyzer.web.snapshots as snaps

    blocker = tmp_path / "snapshots"
    blocker.write_text("i am a file", encoding="utf-8")
    assert snaps.save_snapshot("map", "fp", {"v": 1}, tmp_path) is False


# ------------------------------------------------------------ memo adapters


def test_aggregate_payload_roundtrip(web_client):
    """The dataclass survives asdict -> JSON -> PlayerRow/DemoRow rebuild,
    including the derived-property fields NOT stored (they recompute)."""
    from cs_analyzer.web import aggregation

    agg = aggregation.aggregated()
    payload = aggregation._snapshot_payload()
    assert payload is not None and payload["players"] and payload["demos"]

    aggregation.invalidate_aggregate()
    assert aggregation._result is None
    aggregation.restore_snapshot(json.loads(json.dumps(payload)))  # JSON round trip
    agg2 = aggregation.aggregated()

    assert agg2.total_demos == agg.total_demos
    assert agg2.total_players == agg.total_players
    by_sid = {p.steamid: p for p in agg2.players}
    for p in agg.players:
        q = by_sid[p.steamid]
        assert (q.total_kills, q.total_rounds, q.total_damage) == \
               (p.total_kills, p.total_rounds, p.total_damage)
        assert q.demo_count == p.demo_count
        # derived property from restored additive totals
        assert abs(q.avg_rating - p.avg_rating) < 1e-9


def test_aggregate_restore_rejects_garbage(web_client):
    from cs_analyzer.web import aggregation
    import pytest

    with pytest.raises(Exception):
        aggregation.restore_snapshot({"players": [{"steamid": 1, "bogus_field": 2}]})
    # the failed restore left the memo cold; a normal request still works
    assert aggregation.aggregated() is not None


def test_funlab_scan_roundtrip_keeps_sets(web_client):
    from cs_analyzer.web import funlab_data

    funlab_data.funlab_report()  # materialize the scan
    payload = funlab_data._snapshot_payload()
    assert payload is not None and payload["entries"]
    entry = payload["entries"][0]
    assert isinstance(entry["player_ids"], list), "sets encode as sorted lists"

    funlab_data.invalidate_funlab()
    funlab_data.restore_scan_snapshot(json.loads(json.dumps(payload)))
    scan = funlab_data._scan_all()
    assert isinstance(scan["entries"][0]["player_ids"], set), "decode back to set"
    assert isinstance(scan["regulars"], set)
    # report rebuilds from the restored scan; the web_client fixture has ONE
    # demo so the >=3-demo gate leaves players empty — that is the gate
    # working, not a restore failure. selected_demos must match the scan.
    r1 = funlab_data.funlab_report()
    assert r1["selected_demos"] == len(payload["entries"])
    assert r1["gate"]["players_total"] > 0


def test_plain_dict_memo_payloads(web_client):
    """feed/teamplay/utilitylab/map/lineups/style_map: payload is the live
    memo object itself (all JSON-able dicts)."""
    from cs_analyzer.web import (feed_data, lineups_data, mapdata, style_map,
                                 teamplay_data, utilitylab_data)

    for mod, build in ((feed_data, feed_data.all_highlights),
                       (teamplay_data, teamplay_data.teamplay_report),
                       (utilitylab_data, utilitylab_data.utilitylab_report),
                       (mapdata, mapdata.map_report),
                       (lineups_data, lineups_data.lineups_report),
                       (style_map, style_map.style_map_report)):
        build()
        with mod._lock:
            payload = mod._snapshot_payload()
        assert payload is not None, mod.__name__
        json.dumps(payload)  # must be JSON-able (raise = fail)


# ------------------------------------------------------- warmup integration


def test_restore_all_and_save_all_end_to_end(tmp_path, monkeypatch):
    """Full cycle on a temp library: rebuild -> save -> invalidate ->
    restore -> memos come back without any demo load."""
    import pandas as pd

    from cs_analyzer.cache import DemoCache
    from cs_analyzer.web import (aggregation, feed_data, snapshots, warmup)
    from cs_analyzer.web import app as web_app_module

    # tiny synthetic library (2 demos of the conftest shape)
    from tests.conftest import build_parsed_demo

    cache = DemoCache(tmp_path / "cache")
    for h in ("aaaa", "bbbb"):
        demo = build_parsed_demo(
            ticks=pd.DataFrame({"tick": [0, 640], "steamid": ["76561111111110001"] * 2,
                                "X": [0.0, 1.0], "Y": [0.0, 0.0],
                                "is_alive": [True, True], "team_num": [3.0, 3.0]}))
        demo.metadata.demo_hash = h
        cache.save(h, demo)
    monkeypatch.setattr(web_app_module, "_cache", lambda: cache)
    monkeypatch.setattr(web_app_module, "OUT_DIR", tmp_path / "out")
    # T2: pin settings to defaults (thread executor — no spawns in tests)
    from cs_analyzer.config import Settings as _Settings

    monkeypatch.setattr(web_app_module, "_settings", lambda: _Settings())

    aggregation.invalidate_aggregate()
    feed_data.invalidate_feed()
    # wave-1 build through the real steps
    warmup._step_aggregate()
    warmup._step_highlights()
    assert aggregation.aggregated() is not None

    saved = snapshots.save_all(web_app_module.OUT_DIR, cache.cache_dir)
    assert saved["aggregate"] and saved["feed"]

    # cold memos + restore: zero demo loads (the cache still exists but the
    # restore path must not need it)
    aggregation.invalidate_aggregate()
    feed_data.invalidate_feed()
    hits = snapshots.restore_all(web_app_module.OUT_DIR, cache.cache_dir)
    assert "aggregate" in hits and "feed" in hits
    assert aggregation.aggregated() is not None
    assert feed_data.all_highlights() is not None


def test_warmup_skips_restored_steps(tmp_path, monkeypatch):
    """When snapshots hit, the expensive steps never run and ready flips."""
    import time as _t

    from cs_analyzer.web import snapshots, warmup
    from cs_analyzer.web import app as web_app_module

    warmup.reset_for_tests()
    ran = []
    for name in ("_step_aggregate", "_step_highlights", "_step_teamplay",
                 "_step_utilitylab", "_step_funlab"):
        monkeypatch.setattr(warmup, name, lambda ran=ran, name=name: ran.append(name))
    monkeypatch.setattr(snapshots, "restore_all",
                        lambda out_dir, cache_dir: ["aggregate", "feed", "teamplay",
                                                    "utilitylab", "funlab_scan"])
    monkeypatch.setattr(snapshots, "save_all",
                        lambda out_dir, cache_dir: {n: True for n in snapshots.SNAPSHOT_NAMES})
    monkeypatch.setattr(web_app_module, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(web_app_module, "_cache",
                        lambda: type("C", (), {"cache_dir": tmp_path / "cache"})())
    # wave2 also stubbed (it would scan the temp cache otherwise)
    for name in ("_step_map", "_step_lineups", "_step_stylemap"):
        monkeypatch.setattr(warmup, name, lambda: None)

    warmup.start_once()
    deadline = _t.monotonic() + 10
    while warmup.status()["phase"] not in ("done", "error") and _t.monotonic() < deadline:
        _t.sleep(0.02)
    st = warmup.status()
    assert st["phase"] == "done" and st["ready"] is True
    assert ran == [], "all five steps were snapshot-restored 鈥?none may run"
    assert st["snapshot_hits"] == ["aggregate", "feed", "teamplay", "utilitylab", "funlab_scan"]
    warmup.reset_for_tests()


def test_warmup_runs_steps_on_miss(tmp_path, monkeypatch):
    """No snapshots -> the normal five steps run (old L0 behavior kept)."""
    import time as _t

    from cs_analyzer.web import snapshots, warmup
    from cs_analyzer.web import app as web_app_module

    warmup.reset_for_tests()
    ran = []
    for name in ("_step_aggregate", "_step_highlights", "_step_teamplay",
                 "_step_utilitylab", "_step_funlab"):
        monkeypatch.setattr(warmup, name, lambda ran=ran, name=name: ran.append(name))
    monkeypatch.setattr(snapshots, "restore_all", lambda out_dir, cache_dir: [])
    monkeypatch.setattr(snapshots, "save_all", lambda out_dir, cache_dir: {})
    monkeypatch.setattr(web_app_module, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(web_app_module, "_cache",
                        lambda: type("C", (), {"cache_dir": tmp_path / "cache"})())
    for name in ("_step_map", "_step_lineups", "_step_stylemap"):
        monkeypatch.setattr(warmup, name, lambda: None)

    warmup.start_once()
    deadline = _t.monotonic() + 10
    while warmup.status()["phase"] not in ("done", "error") and _t.monotonic() < deadline:
        _t.sleep(0.02)
    st = warmup.status()
    assert st["phase"] == "done" and st["ready"] is True
    assert len(ran) == 5, f"all five steps must run on a total miss, ran {ran}"
    warmup.reset_for_tests()


def test_status_inventory(tmp_path, monkeypatch):
    from cs_analyzer.web.snapshots import SNAPSHOT_NAMES, library_fingerprint, save_snapshot, status

    save_snapshot("map", library_fingerprint(tmp_path), {"v": 1}, tmp_path)
    save_snapshot("feed", "stale-fp", {"v": 2}, tmp_path)
    inv = status(tmp_path, tmp_path)
    by_name = {s["name"]: s for s in inv["snapshots"]}
    assert len(inv["snapshots"]) == len(SNAPSHOT_NAMES)
    assert by_name["map"]["current"] is True and by_name["map"]["exists"] is True
    assert by_name["feed"]["current"] is False
    assert by_name["teamplay"]["exists"] is False
