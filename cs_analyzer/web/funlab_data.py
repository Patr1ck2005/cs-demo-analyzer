"""Memoized cross-demo fun-metrics report (Phase M 趣味数据实验室).

Merges FunLabModule per-demo results across the library into per-player
vectors, enforces the appearance gate (>= MIN_DEMOS demos — user-set at 3),
and derives the USER-APPROVED metric pool (docs/funlab-metrics.md v2).

Axes are ratios/means only (never "played more -> bigger number");
absolute values live in tooltips and the money boards only.

Filters (user request): lineup size (单排/双排/3排/4排/5排 — count of library
regulars in the match) and match date (from the 5E filename's embedded date).
The expensive whole-library scan is cached separately; filters re-merge
cheaply per request.
"""
from __future__ import annotations

import re
import threading
from collections import defaultdict

_lock = threading.Lock()
_scan: dict | None = None      # expensive whole-library per-demo vectors
_report: dict | None = None    # last merged report (any filter combo)
_report_key: tuple | None = None

#: chart gate — players with fewer appearances never enter /fun-lab
MIN_DEMOS = 3

_DATE_RE = re.compile(r"(\d{8})")


def funlab_report(stack: tuple[int, ...] | None = None,
                  dates: tuple[str, ...] | None = None) -> dict:
    """Return the merged report for the given filters (memoized per key)."""
    global _report, _report_key
    scan = _scan_all()
    key = (tuple(sorted(stack)) if stack else (), tuple(sorted(dates)) if dates else ())
    with _lock:
        if _report is None or _report_key != key:
            _report = _merge(scan, stack, dates)
            _report_key = key
    return _report


def invalidate_funlab() -> None:
    global _report, _report_key, _scan
    with _lock:
        _report = None
        _report_key = None
        _scan = None


def _demo_date(filename: str) -> str | None:
    """YYYYMMDD from the 5E filename (g161-20260902… / g161-n-20260902…).
    WMPVP numeric filenames (92069433…) match \d{8} too but carry no date —
    only trust g161-prefixed names."""
    if not filename.startswith("g161"):
        return None
    m = _DATE_RE.search(filename)
    return m.group(1) if m else None


def _scan_all() -> dict:
    """Expensive pass: per-demo per-player vectors + lineup/date metadata."""
    global _scan
    if _scan is not None:
        return _scan
    from cs_analyzer.analysis.library import scan_demos
    from cs_analyzer.web.app import _analyze_module, _cache
    from cs_analyzer.web.store import list_demos

    cache_dir = _cache().cache_dir
    meta = {d["demo_hash"]: d for d in list_demos(cache_dir)}

    def work(demo) -> dict:
        result = _analyze_module(demo, "funlab")
        return {
            "demo_hash": demo.metadata.demo_hash,
            "players": result.players,
        }

    per_demo = scan_demos(cache_dir, work)

    # date + five_e flag per demo, from the filename
    entries: list[dict] = []
    five_e_player_sets: list[tuple[str, set[str]]] = []
    for e in per_demo:
        fn = meta.get(e["demo_hash"], {}).get("filename", "")
        date = _demo_date(fn)
        sids = {p["steamid"] for p in e["players"]}
        entry = {
            "demo_hash": e["demo_hash"], "players": e["players"],
            "filename": fn, "date": date,
            "is_five_e": fn.startswith("g161-"),
            "player_ids": sids,
        }
        entries.append(entry)
        if entry["is_five_e"]:
            five_e_player_sets.append((e["demo_hash"], sids))

    # regulars: >=3 appearances across the 5E set (teamplay definition)
    appear: dict[str, int] = defaultdict(int)
    for _, sids in five_e_player_sets:
        for sid in sids:
            appear[sid] += 1
    regulars = {sid for sid, n in appear.items() if n >= 3}

    # lineup size per demo = how many regulars were in the match
    for e in entries:
        e["lineup_n"] = len(e["player_ids"] & regulars)

    dates = sorted({e["date"] for e in entries if e["date"]})
    out = {"entries": entries, "regulars": regulars, "dates": dates}
    with _lock:
        _scan = out
    return out


_SUM_FIELDS = [
    ("kills", "kills"), ("lives", "lives"), ("rounds", "rounds"),
    ("snipe_kills", "snipe_kills"), ("stolen_from", "stolen_from"),
    ("eco_frag_opponent", "eco_frags"), ("eco_rounds_played", "eco_rounds_played"),
    ("eco_frag_self", "eco_frag_self"),
    ("whiff_lives", "whiff_lives"), ("traded_deaths", "traded_deaths"),
    ("avenges", "avenges"), ("teammate_deaths", "teammate_deaths"),
    ("wallbang", "wallbang"), ("thrusmoke", "thrusmoke"),
    ("noscope", "noscope"), ("blind", "blind"), ("air", "air"),
    ("knife", "knife"), ("taser", "taser"),
    ("clutch_kills", "clutch_kills"),
    ("drops_made", "drops_made"), ("drops_value", "drops_value"),
    ("drops_poor", "drops_poor"), ("drops_received", "drops_received"),
    ("drops_value_received", "drops_value_received"),
    ("drops_wasted", "drops_wasted"), ("drops_profitable", "drops_profitable"),
    ("free_pickups", "free_pickups"), ("awp_kills", "awp_kills"),
    ("own_spend", "own_spend"), ("team_lost_rounds", "team_lost_rounds"),
    ("survived_losses", "survived_losses"), ("multi_rounds", "multi_rounds"),
    ("rebel_rounds", "rebel_rounds"), ("rebel_wins", "rebel_wins"),
    ("rebel_kills", "rebel_kills"), ("dist_n", "dist_n"),
    ("showoff_rounds", "showoff_rounds"), ("pure_eco_rounds", "pure_eco_rounds"),
]


def _merge(scan: dict, stack: tuple[int, ...] | None, dates: tuple[str, ...] | None) -> dict:
    selected = []
    for e in scan["entries"]:
        if stack and e["lineup_n"] not in stack:
            continue
        if dates and e["date"] not in dates:
            continue
        selected.append(e)

    merged: dict[str, dict] = {}
    for e in selected:
        for p in e["players"]:
            sid = p["steamid"]
            m = merged.setdefault(sid, {"steamid": sid, "name": p["name"],
                                        "demos": set(),
                                        "team_dmg": 0.0, "dist_sum": 0.0,
                                        "max_dist_m": 0.0, "dist_n": 0})
            m["demos"].add(e["demo_hash"])
            for src, dst in _SUM_FIELDS:
                m[dst] = m.get(dst, 0) + p.get(src, 0)
            m["team_dmg"] += p.get("team_dmg", 0.0)
            m["dist_sum"] += p.get("dist_sum", 0.0)
            m["dist_n"] += p.get("dist_n", 0)
            m["max_dist_m"] = max(m["max_dist_m"], p.get("max_dist_m", 0.0))

    players_out = []
    gated = 0
    for m in merged.values():
        m["demos_n"] = len(m["demos"])
        del m["demos"]
        if m["demos_n"] < MIN_DEMOS:
            gated += 1
            continue
        k = max(m["kills"], 1)
        lv = max(m["lives"], 1)
        eco_r = max(m["eco_rounds_played"], 1)
        rounds = max(m["rounds"], 1)
        flags_total = sum(m[x] for x in ("wallbang", "thrusmoke", "noscope",
                                         "blind", "air", "knife", "taser"))
        players_out.append({
            "steamid": m["steamid"], "name": m["name"], "demos": m["demos_n"],
            "kills": m["kills"], "lives": m["lives"], "rounds": m["rounds"],
            "drops_made": m["drops_made"], "drops_value": m["drops_value"],
            "drop_generosity": round(m["drops_value"] / max(m["own_spend"], 1), 3),
            "drop_poor_share": round(m["drops_poor"] / max(m["drops_made"], 1), 3),
            "drop_profit_rate": round(m["drops_profitable"] / max(m["drops_made"], 1), 3),
            "drops_received": m["drops_received"],
            "drops_value_received": m["drops_value_received"],
            "vulture_rate": round(m["drops_value_received"] /
                                  max(m["own_spend"] + m["drops_value_received"], 1), 3),
            "drop_waste_rate": round(m["drops_wasted"] / max(m["drops_received"], 1), 3),
            "free_pickups": m["free_pickups"],
            "free_pickup_rate": round(m["free_pickups"] /
                                      max(m["drops_received"] + m["free_pickups"], 1), 3),
            "eco_frag_rate": round(m["eco_frags"] / k, 3),
            "eco_hard_rate": round(m["eco_frag_self"] / eco_r, 3),
            "whiff_rate": round(m["whiff_lives"] / lv, 3),
            "snipe_rate": round(m["snipe_kills"] / k, 3),
            "stolen_rate": round(m["stolen_from"] / max(m["kills"] + m["stolen_from"], 1), 3),
            "clutch_freq": round(m["clutch_kills"] / rounds, 3),
            "multi_rate": round(m["multi_rounds"] / rounds, 3),
            "avg_dist_m": round(m["dist_sum"] / max(m["dist_n"], 1), 1),
            "max_dist_m": m["max_dist_m"],
            "awp_rate": round(m["awp_kills"] / k, 3),
            "wallbang_rate": round(m["wallbang"] / k, 3),
            "thrusmoke_rate": round(m["thrusmoke"] / k, 3),
            "noscope_rate": round(m["noscope"] / k, 3),
            "blind_rate": round(m["blind"] / k, 3),
            "air_rate": round(m["air"] / k, 3),
            "knife_rate": round(m["knife"] / k, 3),
            "flags_total": flags_total,
            "flags_rate": round(flags_total / k, 3),
            "team_dmg_rpr": round(m["team_dmg"] / rounds, 2),
            "avenged_rate": round(m["traded_deaths"] / lv, 3),
            "revenge_rate": round(m["avenges"] / max(m["teammate_deaths"], 1), 3),
            "trade_balance": m["avenges"] - m["traded_deaths"],
            "jame_index": round(m["survived_losses"] / max(m["team_lost_rounds"], 1), 3),
            "rebel_rate": round(m["rebel_rounds"] / eco_r, 3),
            "rebel_win_rate": round(m["rebel_wins"] / max(m["rebel_rounds"], 1), 3),
            "rebel_kills": m["rebel_kills"],
            "rebel_rounds": m["rebel_rounds"],
            "showoff_rate": round(m["showoff_rounds"] / eco_r, 3),
            "showoff_rounds": m["showoff_rounds"],
            "pure_eco_rate": round(m["pure_eco_rounds"] / eco_r, 3),
        })
    players_out.sort(key=lambda p: -p["kills"])

    def by(key):
        rows = [p for p in players_out if p["kills"] >= 10]
        return sorted(rows, key=lambda x: x[key], reverse=True)[:10]

    # lineup distribution of the selected demos (for the filter chips)
    lineup_counts: dict[int, int] = defaultdict(int)
    for e in selected:
        lineup_counts[e["lineup_n"]] += 1

    return {
        "generated": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "gate": {"min_demos": MIN_DEMOS, "players_total": len(merged), "gated": gated},
        "selected_demos": len(selected),
        "lineup_counts": {str(k): v for k, v in sorted(lineup_counts.items())},
        "dates": scan["dates"],
        "players": players_out,
        "boards": {
            "donor": by("drops_value"),
            "vulture": by("vulture_rate"),
            "generous": by("drop_generosity"),
            "poor_hero": by("drop_poor_share"),
            "whiff": by("whiff_rate"),
            "eco": by("eco_frag_rate"),
            "snipe": by("snipe_rate"),
            "stolen": by("stolen_rate"),
            "team_dmg": by("team_dmg_rpr"),
            "clutch": by("clutch_freq"),
            "flags": by("flags_rate"),
            "jame": by("jame_index"),
            "rebel": by("rebel_rate"),
            "free_pickup": by("free_pickups"),
            "showoff": by("showoff_rate"),
            "pure_eco": by("pure_eco_rate"),
        },
    }
