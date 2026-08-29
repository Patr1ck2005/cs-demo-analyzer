"""Tests for the weapon metadata system (Phase F M3)."""
from __future__ import annotations

import json

import pytest

from cs_analyzer.web import weapons
from cs_analyzer.web.weapons import (
    ICONS_DIR,
    canonical,
    category,
    has_icon,
    icon_url,
    is_gun,
    label_zh,

)

pytest.importorskip("fastapi.testclient")
# web_client fixture now lives in conftest.py (shared across modules)


def test_canonical_aliases_cover_all_naming_schemes() -> None:
    # event short names
    assert canonical("ak47") == "ak47"
    assert canonical("weapon_ak47") == "ak47"
    assert canonical("m4a1_silencer") == "m4a1_silencer"
    assert canonical("usp_silencer") == "usp"
    assert canonical("planted_c4") == "c4"
    # WMPVP skin suffixes
    assert canonical("ak47_txz03") == "ak47"
    assert canonical("ak47_vip") == "ak47"
    assert canonical("usp_silencer_txz12") == "usp"
    # tick display names
    assert canonical("ak-47") == "ak47"
    assert canonical("desert eagle") == "deagle"
    assert canonical("kevlar & helmet") == "kevlarhelmet"
    assert canonical("zeus x27") == "taser"
    assert canonical("sg 553") == "sg553"
    assert canonical("five-seven") == "fiveseven"
    # knife family collapses to one key
    assert canonical("knife_flip") == "knife"
    assert canonical("butterfly knife") == "knife"
    # unknown -> default
    assert canonical("totally_made_up_gun") == "_default"
    assert canonical(None) == "_default"


def test_icon_url_fallback() -> None:
    assert icon_url("ak47").endswith("/static/img/weapons/ak47.svg")
    assert icon_url("ak47_txz19").endswith("/weapons/ak47.svg")
    assert icon_url("inferno").endswith("/molotov.svg")  # fire damage -> fire icon
    assert icon_url("nonexistent_blaster").endswith("/_default.svg")


def test_all_alias_targets_have_vendored_icons() -> None:
    """Every alias target that claims an icon must exist on disk.

    inferno is exempt: it's fire-zone damage in kill feeds, rendered via the
    molotov icon by icon_url(), not its own file.
    """
    missing = [
        canon for canon in set(weapons.WEAPON_ALIASES.values())
        if canon not in ("_default", "inferno")
        and not (ICONS_DIR / f"{canon}.svg").exists()
    ]
    assert missing == []


def test_categories_and_labels() -> None:
    assert category("awp") == "sniper"
    assert category("mp9") == "smg"
    assert category("flashbang") == "grenade"
    assert category("c4 explosive") == "bomb"
    assert is_gun("ak47")
    assert is_gun("deagle_txz05")
    assert not is_gun("flashbang")
    assert not is_gun("knife")
    assert label_zh("ak47") == "AK-47"
    assert label_zh("desert eagle")  # any non-empty zh label


def test_payload_shape() -> None:
    p = weapons.payload()
    assert p["icons_base"] == "/static/img/weapons/"
    assert "aliases" in p and "labels" in p and "categories" in p


def test_api_meta_weapons_endpoint(web_client) -> None:
    c, _, _ = web_client
    r = c.get("/api/meta/weapons.json")
    assert r.status_code == 200
    data = r.json()
    assert data["icons_base"] == "/static/img/weapons/"
    assert data["aliases"]["ak47"] == "ak47"


def test_weapon_icon_served(web_client) -> None:
    c, _, _ = web_client
    r = c.get("/static/img/weapons/ak47.svg")
    assert r.status_code == 200
    assert b"<svg" in r.content[:200]


def test_demo_detail_kill_lines_have_icons(web_client) -> None:
    c, h, _ = web_client
    r = c.get(f"/match/{h}")
    assert r.status_code == 200
    assert "wpn-ico" in r.text  # kill lines render <img class="wpn-ico">


def test_js_mirror_matches_python() -> None:
    """Drift guard: key python tables must appear in the generated JS mirror."""
    from pathlib import Path

    js = Path(__file__).resolve().parents[1] / "cs_analyzer" / "web" / "static" / "js" / "weapon_meta.js"
    text = js.read_text(encoding="utf-8")
    payload = weapons.payload()
    for key in ("ak47", "desert eagle", "usp_silencer", "hkp2000"):
        assert f'"{key}"' in text, f"alias {key} missing from JS mirror"
        assert payload["aliases"][key] in text
    for canon in ("ak47", "awp", "taser", "_default"):
        assert f'"{canon}"' in text
    assert "window.WeaponMeta" in text
