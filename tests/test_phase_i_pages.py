"""Tests for Phase I M4: page completions (tabs, badges, routes toggle,
career deep-dive) and the B8 recency ordering."""
from __future__ import annotations

from pathlib import Path

from cs_analyzer.analysis.aggregate import DemoRow
from cs_analyzer.web import app as web_app
from cs_analyzer.web import store


def test_match_key_ordering() -> None:
    """B8: platform numeric match ids sort chronologically; unprefixed
    files sort after by name. Covers WMPVP + 5E (g161-) shapes + stored id."""
    entries = [
        {"filename": "9211306538981998348_0.dem"},
        {"filename": "g161-20260828233826747829917_de_cache.dem"},
        {"filename": "9206943388297116556_0.dem"},
        {"filename": "faceit-match.dem"},
    ]
    ordered = sorted(entries, key=store.match_key)
    assert [e["filename"] for e in ordered] == [
        "9206943388297116556_0.dem",
        "9211306538981998348_0.dem",
        "g161-20260828233826747829917_de_cache.dem",
        "faceit-match.dem",
    ]
    # stored metadata match_id wins over filename patterns
    stored = dict(entries[0], match_id="9999999999999999999")
    assert store.match_key(stored) == (0, 9999999999999999999, "")


def test_demo_row_match_key() -> None:
    row = DemoRow(demo_hash="h", filename="9206943388297116556_0.dem",
                  map_name="de_mirage", rounds=10, t_score=5, ct_score=5,
                  match_id="9206943388297116556")
    assert row.match_key == (0, 9206943388297116556, "")
    plain = DemoRow(demo_hash="h", filename="b.dem", map_name="x", rounds=1,
                    t_score=1, ct_score=0)
    assert plain.match_key == (1, 0, "b.dem")


def test_kill_feed_badges(web_client) -> None:
    """P5: kill lines carry badge flags from player_death columns."""
    c, h, demo = web_client
    r = c.get(f"/match/{h}?tab=kills")
    assert r.status_code == 200
    # Alice's synthetic kill is a headshot -> HS badge rendered
    assert 'kb-headshot' in r.text
    assert '爆头' in r.text


def test_routes_payload_has_both_sides(web_client) -> None:
    """P3: routes.json ships sides.T + sides.CT (legacy keys intact)."""
    c, h, _ = web_client
    r = c.get(f"/api/demo/{h}/analysis/routes.json")
    assert r.status_code == 200
    data = r.json()
    # synthetic demo has too few rounds to cluster — but the shape must hold
    assert "routes" in data and "sides" in data
    assert set(data["sides"].keys()) == {"T", "CT"}
    assert isinstance(data["sides"]["CT"]["routes"], list)


def test_new_analysis_endpoints(web_client) -> None:
    """Phase I endpoints respond on the synthetic demo (shape contracts)."""
    c, h, _ = web_client
    for path, keys in (
        ("/analysis/kill_context.json", ("players", "feed", "weapon_mix")),
        ("/analysis/hitgroups.json", ("players", "groups", "labels")),
        ("/analysis/aim.json", ("players",)),
        ("/analysis/postplant.json", ("rounds", "summary")),
        ("/analysis/weapons.json", ("players",)),
    ):
        r = c.get(f"/api/demo/{h}{path}")
        assert r.status_code == 200, path
        body = r.json()
        for k in keys:
            assert k in body, f"{path} missing {k}"


def test_tactics_tab_and_route_toggle(web_client) -> None:
    c, h, _ = web_client
    r = c.get(f"/match/{h}")
    assert r.status_code == 200
    for token in ('data-tab="tactics"', 'data-side="CT"', 'route-side',
                  'winbybuy-chart', 'smoke-chart', 'weapon-mix-chart'):
        assert token in r.text, token
    # Phase J: overlap is a replay sub-mode — no standalone entry button
    assert "回合重叠</a>" not in r.text
    assert "viewer?mode=overlap" in r.text


def test_viewer_buy_strip_contract() -> None:
    """P6: viewer JS must consume layersData.economy and render the strip."""
    static = Path(web_app.__file__).parent / "static"
    js = (static / "viewer_canvas.js").read_text(encoding="utf-8")
    assert "layersData.economy" in js
    assert "buy-strip" in js
    html = (static.parent / "templates" / "replay_viewer.html").read_text(encoding="utf-8")
    assert 'id="buy-strip"' in html


def test_career_radar_uses_server_ranges(web_client) -> None:
    """B4: career page ships server RADAR_AXES ranges (no stale literals)."""
    from .conftest import S_ALICE

    c, _, _ = web_client
    r = c.get(f"/player/{S_ALICE}")
    assert r.status_code == 200
    assert "radar-ranges" in r.text
    assert '"min": 0.5' in r.text          # KPR range from RADAR_AXES
    assert "[[0, 0.15]" not in r.text       # old hardcoded ranges gone
