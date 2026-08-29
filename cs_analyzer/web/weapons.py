"""Weapon metadata: the single source of truth for icon/label/category mapping.

demoparser2 emits three different weapon naming schemes depending on the table:
- event short names (``player_death.weapon`` / ``weapon_fire.weapon`` after
  ``_short_weapon``): ``ak47``, ``m4a1_silencer``, WMPVP skin variants ``*_txzNN``
- tick display names (``active_weapon_name`` / ``item_purchase.item_name``):
  ``ak-47``, ``desert eagle``, ``kevlar & helmet``

Everything resolves through :func:`canonical` to a stable key that maps to a
vendored SVG in ``static/img/weapons/<key>.svg`` (MIT, from akiver/cs-demo-manager).
Unknown names fall back to ``_default``.
"""
from __future__ import annotations

import re
from pathlib import Path

ICONS_DIR = Path(__file__).resolve().parent / "static" / "img" / "weapons"

# canonical key -> zh display name
WEAPON_LABELS_ZH: dict[str, str] = {
    # rifles
    "ak47": "AK-47", "m4a4": "M4A4", "m4a1": "M4A1", "m4a1_silencer": "M4A1 消音版",
    "galilar": "加利尔 AR", "famas": "FAMAS", "aug": "AUG", "sg553": "SG 553",
    # snipers
    "awp": "AWP", "ssg08": "SSG 08", "scar20": "SCAR-20", "g3sg1": "G3SG1",
    # pistols
    "glock": "格洛克 18 型", "usp": "USP-S", "p2000": "P2000", "p250": "P250",
    "fiveseven": "FN57", "tec9": "TEC-9", "cz75a": "CZ75 自动手枪",
    "deagle": "沙漠之鹰", "elite": "双持贝瑞塔", "revolver": "R8 左轮",
    # SMG / heavy
    "mac10": "MAC-10", "mp9": "MP9", "mp7": "MP7", "mp5sd": "MP5-SD",
    "ump45": "MP7 冲锋枪 UMP-45", "p90": "P90", "bizon": "PP-野牛",
    "nova": "新星", "xm1014": "XM1014", "mag7": "MAG-7", "sawed_off": "截短霰弹枪",
    "m249": "M249", "negev": "内格夫",
    # knife / gear / bomb
    "knife": "刀", "taser": "泰瑟枪",
    "smokegrenade": "烟雾弹", "flashbang": "闪光弹", "hegrenade": "高爆手雷",
    "molotov": "燃烧瓶", "incgrenade": "燃烧弹", "decoy": "诱饵手雷",
    "kevlar": "防弹衣", "kevlarhelmet": "防弹衣+头盔", "defuser": "拆弹器",
    "c4": "C4 炸药", "inferno": "火焰", "world": "环境伤害",
}

# category -> used for filtering (e.g. muzzle flash only for guns) and styling
WEAPON_CATEGORY: dict[str, str] = {
    **{k: "rifle" for k in ("ak47", "m4a4", "m4a1", "m4a1_silencer", "galilar", "famas", "aug", "sg553")},
    **{k: "sniper" for k in ("awp", "ssg08", "scar20", "g3sg1")},
    **{k: "pistol" for k in ("glock", "usp", "p2000", "p250", "fiveseven", "tec9", "cz75a", "deagle", "elite", "revolver")},
    **{k: "smg" for k in ("mac10", "mp9", "mp7", "mp5sd", "ump45", "p90", "bizon")},
    **{k: "heavy" for k in ("nova", "xm1014", "mag7", "sawed_off", "m249", "negev")},
    **{k: "knife" for k in ("knife",)},
    **{k: "gear" for k in ("kevlar", "kevlarhelmet", "defuser", "taser")},
    **{k: "grenade" for k in ("smokegrenade", "flashbang", "hegrenade", "molotov", "incgrenade", "decoy")},
    **{k: "bomb" for k in ("c4",)},
    **{k: "world" for k in ("inferno", "world")},
}

# observed alias -> canonical key (covers all three demoparser2 naming schemes)
WEAPON_ALIASES: dict[str, str] = {}
for _canon, _names in {
    "ak47": ("ak47", "ak-47"),
    "m4a4": ("m4a4",),
    "m4a1": ("m4a1",),
    "m4a1_silencer": ("m4a1_silencer", "m4a1-s", "m4a1s"),
    "galilar": ("galilar", "galil ar", "galil"),
    "famas": ("famas",),
    "aug": ("aug",),
    "sg553": ("sg553", "sg 553", "sg556"),
    "awp": ("awp",),
    "ssg08": ("ssg08", "ssg 08"),
    "scar20": ("scar20", "scar-20"),
    "g3sg1": ("g3sg1",),
    "glock": ("glock", "glock-18"),
    "usp": ("usp", "usp-s", "usps", "usp_silencer"),
    "p2000": ("p2000", "hkp2000"),
    "p250": ("p250",),
    "fiveseven": ("fiveseven", "five-seven"),
    "tec9": ("tec9", "tec-9"),
    "cz75a": ("cz75a", "cz75-auto"),
    "deagle": ("deagle", "desert eagle"),
    "elite": ("elite", "dual berettas"),
    "revolver": ("revolver", "r8 revolver"),
    "mac10": ("mac10", "mac-10"),
    "mp9": ("mp9",),
    "mp7": ("mp7",),
    "mp5sd": ("mp5sd", "mp5-sd"),
    "ump45": ("ump45",),
    "p90": ("p90",),
    "bizon": ("bizon", "pp-bizon"),
    "nova": ("nova",),
    "xm1014": ("xm1014",),
    "mag7": ("mag7", "mag-7"),
    "sawed_off": ("sawed-off", "sawed off"),
    "m249": ("m249",),
    "negev": ("negev",),
    "knife": ("knife", "knife_t", "bayonet", "butterfly knife", "flip knife", "gut knife",
              "karambit", "m9 bayonet", "skeleton knife", "stiletto knife", "bowie knife",
              "tactical knife", "widowmaker knife", "outdoor knife", "huntsman knife",
              "nomad knife", "talon knife", "paracord knife", "survival knife",
              "classic knife", "falchion knife", "shadow daggers", "navaja knife",
              "ursus knife", "kukri knife",
              "knife_butterfly", "knife_flip", "knife_gut", "knife_karambit",
              "knife_m9_bayonet", "knife_outdoor", "knife_skeleton", "knife_stiletto",
              "knife_survival_bowie", "knife_tactical", "knife_widowmaker",
              "knife_bayonet", "knife_falchion", "knife_flex", "knife_gypsy_jackknife",
              "knife_huntsman", "knife_push", "knife_survival_knife", "knife_ursus",
              "knife_canis", "knife_cord", "knife_css", "knife_kukri"),
    "taser": ("taser", "zeus x27", "zeus"),
    "smokegrenade": ("smokegrenade", "smoke grenade"),
    "flashbang": ("flashbang",),
    "hegrenade": ("hegrenade", "high explosive grenade"),
    "molotov": ("molotov",),
    "incgrenade": ("incgrenade", "incendiary grenade"),
    "decoy": ("decoy", "decoy grenade"),
    "kevlar": ("kevlar vest", "kevlar"),
    "kevlarhelmet": ("kevlar & helmet", "helmet"),
    "defuser": ("defuse kit", "defuser"),
    "c4": ("c4 explosive", "planted_c4", "c4"),
    "inferno": ("inferno",),
    "world": ("world",),
}.items():
    WEAPON_ALIASES[_canon] = _canon  # canonical keys resolve to themselves
    for _alias in _names:
        WEAPON_ALIASES.setdefault(_alias, _canon)

_SKIN_RE = re.compile(r"_(txz\d+|vip)$")


def canonical(name: str | None) -> str:
    """Resolve any demoparser2 weapon string to its canonical key."""
    if not name:
        return "_default"
    n = str(name).strip().lower().removeprefix("weapon_")
    while True:
        m = _SKIN_RE.search(n)
        if not m:
            break
        n = n[: m.start()]  # strip WMPVP skin suffixes: ak47_txz03 -> ak47
    hit = WEAPON_ALIASES.get(n)
    if hit:
        return hit
    # last resort: normalize separators ("dual-berettas" / "sawed off")
    stripped = n.replace("-", "_").replace(" ", "_")
    return WEAPON_ALIASES.get(stripped, "_default")


def label_zh(name: str | None) -> str:
    canon = canonical(name)
    return WEAPON_LABELS_ZH.get(canon, canon)


def category(name: str | None) -> str:
    return WEAPON_CATEGORY.get(canonical(name), "unknown")


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
