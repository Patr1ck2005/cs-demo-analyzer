"""M3 复盘教练线: focus store + per-demo series + progress windows.

The store follows favorites_store (lock + atomic write + fail-soft reads).
Series read the persistent per-demo layers directly (shard files written
via snapshots.save_shard / the funlab_scan snapshot via save_snapshot with
the fixture cache's real model tags) — no producer modules involved.
"""
from __future__ import annotations

import cs_analyzer.web.focus_data as focus_data
import cs_analyzer.web.focus_store as focus_store
from tests.conftest import S_ALICE


# ---- store ----

def test_focus_store_set_replace_clear() -> None:
    doc = focus_store.empty_doc()
    focus_store.set_focus(doc, "S1", "aim", ["h1", "h2"])
    assert doc["active"]["S1"]["dim"] == "aim" and doc["history"] == []
    # replace: the old focus moves to history (single-active holds)
    focus_store.set_focus(doc, "S1", "eco", ["h3"])
    assert doc["active"]["S1"]["dim"] == "eco"
    assert len(doc["history"]) == 1
    assert doc["history"][0]["dim"] == "aim" and doc["history"][0]["cleared_at"]
    # base_hashes dedupe + order preserved
    focus_store.set_focus(doc, "S2", "duel", ["h1", "h1", "h2"])
    assert doc["active"]["S2"]["base_hashes"] == ["h1", "h2"]
    prev = focus_store.clear_focus(doc, "S1")
    assert prev["dim"] == "eco" and "S1" not in doc["active"]
    assert focus_store.clear_focus(doc, "S1") is None


def test_focus_store_roundtrip_and_corrupt(tmp_path) -> None:
    out = tmp_path / "web"
    doc = focus_store.empty_doc()
    focus_store.set_focus(doc, "S1", "loss", ["a", "b"])
    focus_store.save_focus(out, doc)
    assert focus_store.load_focus(out)["active"]["S1"]["dim"] == "loss"
    focus_store.focus_path(out).write_text("{not json", encoding="utf-8")
    assert focus_store.load_focus(out) == focus_store.empty_doc()


# ---- progress windows (C3 trend gates) ----

def test_progress_windows_and_gates() -> None:
    series = {"points": [
        {"demo_hash": f"h{i}", "seq": i, "value": v, "n": 10}
        for i, v in enumerate([0.2, 0.3, 0.4, 0.6, 0.7, 0.8])
    ], "unit": "u"}
    prog = focus_data.progress(series, ["h0", "h1", "h2"])
    assert prog["before"] == {"n": 3, "mean": 0.3}
    assert prog["after"] == {"n": 3, "mean": 0.7}
    assert prog["delta"] == 0.4
    # a window below the gate greys out (mean None) and kills the delta
    prog = focus_data.progress(series, ["h0", "h1", "h2", "h3", "h4"])
    assert prog["before"]["n"] == 5 and prog["before"]["mean"] == 0.44
    assert prog["after"] == {"n": 1, "mean": None}
    assert prog["delta"] is None


# ---- series from the real shard/snapshot layers (fixture cache) ----

def _out_cache(tmp_path):
    return tmp_path / "web", tmp_path / "cache"  # web_client fixture layout


def test_series_loss_aim_duel_from_shards(web_client, tmp_path) -> None:
    c, h, demo = web_client
    from cs_analyzer.web import snapshots

    out, cache = _out_cache(tmp_path)
    snapshots.save_shard("lossattr", out, cache, h,
                         {"players": [{"steamid": S_ALICE,
                                       "lost_deaths": 4,
                                       "untraded_deaths": 1}]})
    s = focus_data.dim_series("loss", S_ALICE, [h], out, cache)
    assert s["points"] == [{"demo_hash": h, "seq": 0, "value": 0.25, "n": 4}]

    snapshots.save_shard("aimsci", out, cache, h,
                         {"players": [{"steamid": S_ALICE, "n_shots": 200}],
                          "samples": {S_ALICE: {"stopped_shots": 90}}})
    s = focus_data.dim_series("aim", S_ALICE, [h], out, cache)
    assert s["points"][0]["value"] == 0.45 and s["points"][0]["n"] == 200

    snapshots.save_shard("duelmo", out, cache, h,
                         {"duels": [{"att": S_ALICE, "vic": "X", "y": 1},
                                    {"att": "Y", "vic": S_ALICE, "y": 0},
                                    {"att": "Y", "vic": "X", "y": 1}],
                          "roster": {S_ALICE: "Alice"}})
    s = focus_data.dim_series("duel", S_ALICE, [h], out, cache)
    # attacker win (y=1) + victim survival (y=0) -> 2/2 from Alice's view
    assert s["points"][0]["value"] == 1.0 and s["points"][0]["n"] == 2


def test_series_eco_from_snapshot_and_fingerprint_miss(web_client, tmp_path) -> None:
    c, h, demo = web_client
    from cs_analyzer.web import snapshots

    out, cache = _out_cache(tmp_path)
    fp = snapshots.library_fingerprint(cache)
    snapshots.save_snapshot(
        "funlab_scan", fp,
        {"entries": [{"demo_hash": h,
                      "players": [{"steamid": S_ALICE,
                                   "eco_rounds_played": 4,
                                   "eco_frag_self": 3}]}],
         "regulars": [], "dates": []},
        out)
    s = focus_data.dim_series("eco", S_ALICE, [h], out, cache)
    assert s["points"] == [{"demo_hash": h, "seq": 0, "value": 0.75, "n": 4}]
    # fingerprint mismatch -> honest None (never computes)
    snapshots.save_snapshot("funlab_scan", "stale-fp",
                            {"entries": []}, out)
    assert focus_data.dim_series("eco", S_ALICE, [h], out, cache) is None
    assert focus_data.dim_series("utility", S_ALICE, [h], out, cache) is None


# ---- API + career page integration ----

def test_focus_api_and_career_progress(web_client, tmp_path) -> None:
    c, h, demo = web_client
    from cs_analyzer.web import snapshots

    out, cache = _out_cache(tmp_path)
    snapshots.save_shard("aimsci", out, cache, h,
                         {"players": [{"steamid": S_ALICE, "n_shots": 100}],
                          "samples": {S_ALICE: {"stopped_shots": 40}}})

    # invalid dim -> 400; valid flow -> store + progress card (both windows
    # below the gate on the 1-demo fixture -> honest grey values)
    r = c.post("/api/focus", json={"steamid": S_ALICE, "dim": "utility"})
    assert r.status_code == 400
    r = c.post("/api/focus", json={"steamid": S_ALICE, "dim": "aim"})
    assert r.status_code == 200 and r.json()["entry"]["base_n"] == 1
    g = c.get("/api/focus").json()
    assert g["active"] == [{"steamid": S_ALICE, "dim": "aim",
                            "set_at": g["active"][0]["set_at"], "base_n": 1}]

    r = c.get(f"/player/{S_ALICE}")
    assert r.status_code == 200
    assert "data-focus-progress" in r.text and "关注进展" in r.text
    assert "新打 ≥3 场后出对比" in r.text  # after-window gate note

    # replace then clear via API; the card disappears
    r = c.post("/api/focus", json={"steamid": S_ALICE, "dim": "duel"})
    assert r.status_code == 200
    assert c.get("/api/focus").json()["active"][0]["dim"] == "duel"
    r = c.delete(f"/api/focus?steamid={S_ALICE}")
    assert r.status_code == 200 and r.json()["cleared"] is True
    assert c.get("/api/focus").json()["active"] == []
    assert "data-focus-progress" not in c.get(f"/player/{S_ALICE}").text
