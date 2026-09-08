"""Phase X IA-重组 + 遗留小件 regressions.

One test per structural change or deferred-item fix, hermetic (no real
parses, no playwright):
  X1  single-row clustered nav: /report/{hash} highlights 报告 (was dark),
      retired pages are gone from the nav, cluster labels render
  X2  five-stack teamplay: /api/teams/teamplay.json is the canonical route,
      /api/compare/teamplay.json stays as an alias, /teams carries the
      section, /compare no longer does
  X3  /fun-lab → /players?tab=lab and /utility-lab → /map-analysis#utility
      are 301s passing query strings through; players renders the lab tab
      markup; /system swaps the duplicate topic cards for a site index
  X4a utilitylab/mapdata per-demo payloads persist as shards and warm-reload
  X4b win-probability LOO: shards roundtrip; synthetic separable data gets
      AUC > 0.5; loo_peek never triggers a cold whole-library scan; the
      win_probability response shape survives (loo_auc key added)
  X4c trajectory drift threshold: n_features is emitted for the client
      judgment (server note stays at the default σ)
"""
from __future__ import annotations


from cs_analyzer.web import app as web_app


# ---------- X1: clustered nav ----------


def test_nav_report_page_highlights_reports(web_client) -> None:
    """/report/{hash} must highlight the 报告 nav item (the old =='/reports'
    check left every report page with no active item)."""
    _c, h, _demo = web_client
    html = web_client[0].get(f"/report/{h}").text
    import re

    m = re.search(r'<a href="/reports" class="([^"]*)"', html)
    assert m, "reports nav link missing"
    assert "active" in m.group(1)


def test_nav_single_row_has_no_retired_pages(web_client) -> None:
    """The retired one-off pages no longer appear as nav destinations, and
    the cluster labels are rendered."""
    html = web_client[0].get("/matches").text
    assert 'href="/fun-lab"' not in html
    assert 'href="/utility-lab"' not in html
    assert "nav-cluster-label" in html
    assert "nav-secondary" not in html


# ---------- X2: teamplay new home ----------


def test_teamplay_canonical_and_alias_routes(web_client, monkeypatch) -> None:
    """/api/teams/teamplay.json is canonical; the compare path is a live
    alias returning the SAME payload (old bookmarks must not 404)."""
    from cs_analyzer.web import teamplay_data

    monkeypatch.setattr(teamplay_data, "teamplay_report",
                        lambda: {"ok": True, "regulars": []})
    c = web_client[0]
    a = c.get("/api/teams/teamplay.json")
    b = c.get("/api/compare/teamplay.json")
    assert a.status_code == 200 and b.status_code == 200
    assert a.json() == b.json()


def test_teams_page_carries_teamplay_section(web_client) -> None:
    """/teams renders the ported 五排协同 containers; /compare no longer
    ships them (one home, not two)."""
    c = web_client[0]
    teams_html = c.get("/teams").text
    assert 'id="tp-heatmap"' in teams_html
    assert 'id="tp-contrast"' in teams_html
    compare_html = c.get("/compare").text
    assert 'id="tp-heatmap"' not in compare_html


# ---------- X3: retired pages are 301s, content moved ----------


def test_fun_lab_redirects_to_players_lab(web_client) -> None:
    c = web_client[0]
    r = c.get("/fun-lab", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == "/players?tab=lab"
    # query strings pass through (same contract as the /demo/* 301s)
    r2 = c.get("/fun-lab?stack=2", follow_redirects=False)
    assert r2.headers["location"] == "/players?tab=lab&stack=2"


def test_utility_lab_redirects_to_map_analysis(web_client) -> None:
    c = web_client[0]
    r = c.get("/utility-lab", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == "/map-analysis#utility"


def test_players_page_renders_lab_tab_markup(web_client) -> None:
    """The lab tab ships its containers server-side (charts lazy-mount only
    when the tab activates) and the tab URLs deep-link."""
    c, _h, _demo = web_client
    html = c.get("/players").text
    for dom in ("fl-quadrant", "sm-galaxy", "fl-boards", "players-tabs"):
        assert dom in html, f"lab markup missing: {dom}"
    assert 'data-tab="lab"' in html


def test_map_analysis_carries_utility_section(web_client) -> None:
    """/map-analysis ships the merged 道具专题 containers and loads both
    page modules."""
    html = web_client[0].get("/map-analysis").text
    for dom in ("ul-tiles", "ul-flash-table", "ul-smoke-table", "ul-spots",
                'id="utility"'):
        assert dom in html, f"utility markup missing: {dom}"


def test_system_page_has_site_index_not_topic_cards(web_client) -> None:
    """The duplicated 专题工具 card block is gone; the sitemap-style index
    covers the pages it missed (favorites included)."""
    html = web_client[0].get("/system").text
    assert "站点索引" in html
    assert "专题工具" not in html
    assert 'href="/favorites"' in html


# ---------- W2: interaction-audit regression locks ----------


def test_players_page_shares_script_loader(web_client) -> None:
    """W2 F-A: the lab and matrix mount paths must share one promise-cached
    script loader — two independent echarts injections split the instance
    registry and the 0x0 resize silently stopped working."""
    html = web_client[0].get("/players").text
    assert "loadScriptCache" in html, "shared loader cache missing"
    assert html.count("loadScript('/static/vendor/echarts.min.js')") == 2  # both paths call it
    assert "new Promise" in html  # created once per src via the cache


def test_reports_js_syncs_preview_href() -> None:
    """W2 F-B: the preview link href is synced on load/change (middle-click
    opened '#' before), the click handler is fallback-only."""
    js = (web_app.STATIC_DIR / "js" / "reports.js").read_text(encoding="utf-8")
    assert "function syncPreview" in js
    assert "syncPreview();" in js  # called outside the click handler
    assert "if (!currentHash) { ev.preventDefault(); return false; }" in js


# ---------- X4a: shard-backed utilitylab / mapdata ----------


def test_utilitylab_shards_roundtrip(web_client, monkeypatch, tmp_path) -> None:
    """_scan_all persists per-demo payloads as utilitylab shards; a warm
    cache reloads them without re-running the module fn."""
    from cs_analyzer.web import utilitylab_data

    _c, h, _demo = web_client
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "web")
    utilitylab_data.invalidate_utilitylab()

    calls = {"n": 0}

    def fake_payload(d):
        calls["n"] += 1
        return {"demo_hash": h, "map_name": "de_mirage",
                "flashers": [], "smoke": [], "smoke_events": []}

    monkeypatch.setattr(utilitylab_data, "_demo_payload", fake_payload)
    entries = utilitylab_data._scan_all()
    assert calls["n"] == 1 and entries[0]["demo_hash"] == h
    shard_root = tmp_path / "web" / "snapshots" / "shards" / "utilitylab"
    assert any(shard_root.rglob(f"{h}_*.json")), "shard file must be written"
    # warm path: memo reset + shard hit — fn must NOT run again
    utilitylab_data.invalidate_utilitylab()
    entries2 = utilitylab_data._scan_all()
    assert calls["n"] == 1 and entries2 == entries
    utilitylab_data.invalidate_utilitylab()


def test_mapdata_shards_roundtrip(web_client, monkeypatch, tmp_path) -> None:
    """Same contract for the map memo (shard family ``map``)."""
    from cs_analyzer.web import mapdata

    _c, h, _demo = web_client
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "web")
    mapdata.invalidate_map_report()

    calls = {"n": 0}

    def fake_payload(d):
        calls["n"] += 1
        return {"map_name": "de_mirage", "rounds": 2, "t_wins": 1, "ct_wins": 1,
                "t_routes": [], "ct_routes": [], "plants": []}

    monkeypatch.setattr(mapdata, "_demo_payload", fake_payload)
    entries = mapdata._scan_all()
    assert calls["n"] == 1 and entries[0]["rounds"] == 2
    shard_root = tmp_path / "web" / "snapshots" / "shards" / "map"
    assert any(shard_root.rglob(f"{h}_*.json")), "shard file must be written"
    mapdata.invalidate_map_report()
    entries2 = mapdata._scan_all()
    assert calls["n"] == 1 and entries2 == entries
    mapdata.invalidate_map_report()


# ---------- X4b: win-probability cross-demo LOO ----------


def test_winloo_shards_roundtrip(web_client, monkeypatch, tmp_path) -> None:
    """Per-demo win_probability snapshots persist as winloo shards and
    warm-reload without re-running the module."""
    from cs_analyzer.web import winprob_loo

    _c, h, _demo = web_client
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "web")
    winprob_loo.invalidate_winloo()

    entries = winprob_loo._scan_all()
    assert h in entries
    shard_root = tmp_path / "web" / "snapshots" / "shards" / "winloo"
    assert any(shard_root.rglob(f"{h}_*.json")), "shard file must be written"
    winprob_loo.invalidate_winloo()
    entries2 = winprob_loo._scan_all()
    assert entries2 == entries
    winprob_loo.invalidate_winloo()


def test_winloo_synthetic_separable_auc(monkeypatch) -> None:
    """Two well-separated fake demos → LOO AUC must exceed 0.5 (the model
    genuinely transfers across matches), and the mean is snapshot-weighted."""
    from cs_analyzer.web import winprob_loo

    def fake_scan():
        # both demos: alive_diff drives the outcome in the SAME direction
        # (pooled training must not cancel) — LOO AUC ≈ 1 if the model
        # genuinely transfers across matches
        return {
            "aaa": {"rows": [[float(i), 1.0, 0.0, 0.0] for i in range(20)],
                    "y": [0] * 10 + [1] * 10},
            "bbb": {"rows": [[float(i) * 2, 0.5, 1.0, 1.0] for i in range(20)],
                    "y": [0] * 10 + [1] * 10},
        }

    monkeypatch.setattr(winprob_loo, "_scan_all", fake_scan)
    winprob_loo.invalidate_winloo()
    report = winprob_loo.loo_report()
    winprob_loo.invalidate_winloo()
    assert report["n_computed"] == 2
    assert report["mean_auc"] is not None and report["mean_auc"] > 0.5
    assert all(d["auc"] is not None for d in report["demos"].values())


def test_winloo_peek_never_computes(monkeypatch) -> None:
    """loo_peek returns None on a cold memo WITHOUT calling loo_report —
    a match-page request must never pay the whole-library scan (U1 lesson)."""
    from cs_analyzer.web import winprob_loo

    winprob_loo.invalidate_winloo()

    def boom():
        raise AssertionError("loo_peek must not trigger a compute")

    monkeypatch.setattr(winprob_loo, "loo_report", boom)
    assert winprob_loo.loo_peek("whatever") is None


def test_win_probability_response_shape(web_client) -> None:
    """The V1 response keeps every existing key and adds loo_auc (None when
    the LOO memo is cold — the key must exist for JS destructuring)."""
    c, h, _demo = web_client
    from cs_analyzer.web import winprob_loo

    winprob_loo.invalidate_winloo()
    data = c.get(f"/api/demo/{h}/analysis/win_probability.json").json()
    for key in ("rounds", "auc", "n_train_rounds", "note", "loo_auc"):
        assert key in data, f"missing key: {key}"


# ---------- X4c: client-side drift threshold ----------


def test_trajectories_expose_n_features(monkeypatch) -> None:
    """Each trajectory carries n_features so the client can judge
    max_jump > σ·√k with the user's σ (server note stays default-σ)."""
    from cs_analyzer.web import style_map

    # 10 dated demos per player → 2 windows of 5 (WINDOW=5 needs ≥2 windows)
    entries = []
    for i in range(10):
        v = 0.5 if i < 5 else 0.9  # mid-history jump for s1
        entries.append({
            "demo_hash": f"d{i}", "date": f"2026010{i + 1}",
            "player_ids": ["s1", "s2"],
            "players": [{"steamid": "s1", "drop_generosity": v,
                         "vulture_rate": 1.0 - v},
                        {"steamid": "s2", "drop_generosity": 0.2,
                         "vulture_rate": 0.2}],
        })
    fake_players = [
        {"steamid": "s1", "name": "A", "demos": 10, "kills": 100,
         "drop_generosity": 0.5, "vulture_rate": 0.5},
        {"steamid": "s2", "name": "B", "demos": 10, "kills": 100,
         "drop_generosity": 0.2, "vulture_rate": 0.2},
    ]

    class FakeScanMod:
        @staticmethod
        def _scan_all():
            return {"entries": entries}

    import sys

    monkeypatch.setitem(sys.modules, "cs_analyzer.web.funlab_data", FakeScanMod)
    keys = ["drop_generosity", "vulture_rate"]
    out = style_map._style_trajectories(fake_players, keys,
                                        list(keys), {k: k for k in keys})
    assert out, "trajectories must be produced"
    for t in out:
        assert "n_features" in t and t["n_features"] == len(keys)
        assert "max_jump" in t and "change_note" in t


# ---------- navigation regression: batch page canonical links ----------


def test_batch_jobs_links_are_canonical(web_client, tmp_path) -> None:
    """The upload→batch page carries no legacy /demo/ links (both the SSR
    duplicate-row link and the JS done-link now go to /match/ directly)."""
    import time

    c, _, _ = web_client
    cache_root = tmp_path / "cache"
    before = set(p.name for p in cache_root.glob("*"))
    r = c.post("/upload", files=[
        ("files", ("x.dem", b"CSDEMO-x" * 64, "application/octet-stream"))])
    assert r.status_code == 200
    assert "/demo/" not in r.text, "legacy /demo link must be gone"
    # the batch page submitted a real parse job — wait for it so the
    # background thread doesn't race tmp_path teardown with noisy errors
    deadline = time.time() + 10
    while time.time() < deadline:
        if set(p.name for p in cache_root.glob("*")) - before:
            break
        time.sleep(0.1)
