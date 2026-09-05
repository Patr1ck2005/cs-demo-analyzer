"""Weapon metadata web adapter: icons / labels / vendored SVG URLs.

The canonical/alias/category tables live in the analysis layer
(:mod:`cs_analyzer.analysis.weapons`) so analysis modules can use them
without importing web code. This module re-exports them and adds the
web-only concerns: zh labels for Jinja filters, vendored icon lookup.
JS mirror: ``static/js/weapon_meta.js`` (drift-guarded by tests).
"""
from __future__ import annotations

from pathlib import Path

from cs_analyzer.analysis.weapons import (  # noqa: F401  (re-exported)
    WEAPON_ALIASES,
    WEAPON_CATEGORY,
    WEAPON_LABELS_ZH,
    canonical,
    category,
)

ICONS_DIR = Path(__file__).resolve().parent / "static" / "img" / "weapons"


def label_zh(name: str | None) -> str:
    canon = canonical(name)
    return WEAPON_LABELS_ZH.get(canon, canon)


def has_icon(canon: str) -> bool:
    return canon != "_default" and (ICONS_DIR / f"{canon}.svg").exists()


def icon_url(name: str | None) -> str:
    """Static URL of the weapon's vendored SVG (fallback: _default.svg).

    inferno (fire zone damage in kill feeds) reuses the molotov icon — it is
    fire, visually.
    """
    canon = canonical(name)
    if not has_icon(canon):
        canon = "molotov" if canon == "inferno" else "_default"
    return f"/static/img/weapons/{canon}.svg"


# weapons that count as guns for combat rendering (muzzle flash / tracers)
_GUN_CATEGORIES = {"rifle", "sniper", "pistol", "smg", "heavy"}


def is_gun(name: str | None) -> bool:
    return category(name) in _GUN_CATEGORIES


def payload() -> dict:
    """Full table for /api/meta/weapons.json and the JS mirror."""
    canons = sorted(WEAPON_LABELS_ZH)
    return {
        "icons_base": "/static/img/weapons/",
        "default_icon": "/static/img/weapons/_default.svg",
        "aliases": WEAPON_ALIASES,
        "labels": {c: WEAPON_LABELS_ZH[c] for c in canons},
        "categories": WEAPON_CATEGORY,
    }
