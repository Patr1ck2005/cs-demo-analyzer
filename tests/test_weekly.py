"""M4 复盘教练线: weekly report windows, baseline state, route + entry.

Synthetic AggregateResult (6 demos, rising Rating for Alice; Bob gated) —
the same PlayerRow/DemoRow dataclasses the T1 merge produces.
"""
from __future__ import annotations

from cs_analyzer.analysis.aggregate import AggregateResult, DemoRow, PlayerRow
from cs_analyzer.web import weekly_data
from tests.conftest import S_ALICE, S_BOB


def _agg() -> AggregateResult:
    demos = []
    a_entries = []
    b_entries = []
    for i in range(6):
        h = f"h{i}"
        demos.append(DemoRow(demo_hash=h, filename=f"m{i}.dem",
                             map_name="de_mirage", rounds=24,
                             t_score=13 if i % 2 == 0 else 11,
                             ct_score=11 if i % 2 == 0 else 13))
        a_entries.append({"demo_hash": h, "rounds": 24,
                          "Rating": 0.9 + 0.05 * i, "ADR": 70.0 + i,
                          "KAST": 70.0})
        b_entries.append({"demo_hash": h, "rounds": 24,
                          "Rating": 1.0, "ADR": 80.0, "KAST": 75.0})
    players = [PlayerRow(steamid=S_ALICE, name="Alice", demos=a_entries),
               PlayerRow(steamid=S_BOB, name="Bob", demos=b_entries)]
    return AggregateResult(players=players, demos=demos)


def test_weekly_fallback_split_and_gates(tmp_path) -> None:
    r = weekly_data.weekly_report(agg=_agg(), out_dir=tmp_path, cache_dir=None)
    # 6 demos < fallback window 10 → all in AFTER, BEFORE empty → gated
    assert r["n_new"] == 6 and r["has_baseline"] is False
    assert "回退" in r["split_note"]
    alice = next(p for p in r["players"] if p["steamid"] == S_ALICE)
    assert alice["n_before"] == 0 and alice["n_after"] == 6
    assert alice["gated"] is True and alice["d_rating"] is None
    # scores: i%2==0 → 13:11 (T win) for i=0,2,4 → 3 T wins, 3 CT wins
    assert r["t_wins"] == 3 and r["ct_wins"] == 3


def test_weekly_baseline_window_math(tmp_path) -> None:
    weekly_data.set_baseline(tmp_path, ["h0", "h1", "h2"])
    r = weekly_data.weekly_report(agg=_agg(), out_dir=tmp_path, cache_dir=None)
    assert r["has_baseline"] is True and r["n_new"] == 3
    alice = next(p for p in r["players"] if p["steamid"] == S_ALICE)
    # before Ratings .9/.95/1.0 → 0.95 ; after 1.05/1.1/1.15 → 1.1
    assert alice["before"]["rating"] == 0.95
    assert alice["after"]["rating"] == 1.1
    assert alice["d_rating"] == 0.15 and alice["gated"] is False
    matches = [m["demo_hash"] for m in r["matches"]]
    assert matches == ["h3", "h4", "h5"]


def test_weekly_baseline_state_roundtrip_and_corrupt(tmp_path) -> None:
    weekly_data.set_baseline(tmp_path, ["a", "b"])
    doc = weekly_data.load_state(tmp_path)
    assert doc["base_hashes"] == ["a", "b"] and doc["generated_at"]
    weekly_data.state_path(tmp_path).write_text("{bad", encoding="utf-8")
    assert weekly_data.load_state(tmp_path)["base_hashes"] == []


# ---- route + reports entry (web_client fixture: OUT_DIR → tmp) ----

def test_weekly_page_and_baseline_api(web_client) -> None:
    c, h, demo = web_client
    r = c.get("/weekly")
    assert r.status_code == 200
    assert "周期报告" in r.text and "标记已读" in r.text
    assert "回退" in r.text  # no baseline yet → honest fallback note
    r = c.post("/api/weekly/baseline")
    assert r.status_code == 200 and r.json()["base_n"] == 1
    r2 = c.get("/weekly")
    assert "基线生成于" in r2.text
    assert "基线以来没有新对局" in r2.text  # baseline == whole library


def test_reports_page_carries_weekly_entry(web_client) -> None:
    c, _, _ = web_client
    r = c.get("/reports")
    assert r.status_code == 200
    assert 'href="/weekly"' in r.text
