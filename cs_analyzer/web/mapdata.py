"""Memoized per-map aggregation (Phase L3 地图分析).

Groups the library by map: play counts / round win rates (T and CT),
merged opening routes (per side, share-weighted across demos), bomb-plant
site distribution, and each map's strongest players (from the aggregate).
All heavy per-demo work (routes/postplant modules) reuses the per-demo
module memo; whole-library iteration uses the L0 thread-pool scan.
"""
from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()
_report: dict | None = None


def map_report() -> dict:
    """Return the memoized report, computing it on first use (single-flight)."""
    global _report
    if _report is None:
        with _lock:
            if _report is None:
                _report = _build()
    return _report


def invalidate_map_report() -> None:
    global _report
    with _lock:
        _report = None


def _merge_routes(acc: dict, routes: list[dict], weight: float) -> None:
    """Merge another demo's opening routes into {side: [centroids, shares]}."""
    for r in routes:
        acc.append({"route": r["route"], "share": r.get("share", 0.0) * weight,
                    "rounds": r.get("rounds", [])})


def _build() -> dict:
    from cs_analyzer.analysis.library import scan_demos
    from cs_analyzer.web.aggregation import aggregated
    from cs_analyzer.web.app import _analyze_module, _cache
    from cs_analyzer.web.store import list_demos
    from cs_analyzer.web.utilitylab_data import _norm_spot

    cache_dir = _cache().cache_dir
    meta = {d["demo_hash"]: d for d in list_demos(cache_dir)}
    agg = aggregated()
    per_player_map: dict[str, dict[str, dict]] = defaultdict(dict)
    for p in agg.players:
        for d in p.demos:
            per_player_map[d["map_name"]][p.steamid] = {
                "steamid": p.steamid, "name": p.name, "rating": d["Rating"],
                "rounds": d["rounds"], "demos": p.demo_count,
            }

    def work(demo) -> dict:
        routes = _analyze_module(demo, "routes")
        try:
            postplant = _analyze_module(demo, "postplant")
        except Exception:  # noqa: BLE001 — postplant optional per demo
            postplant = None
        reg = demo.regular_rounds
        t_wins = sum(1 for r in reg if r.winner_side == "T")
        res_cache: dict = {}

        def norm_routes(rs):
            out = []
            for r in rs:
                pts = [_norm_spot(x, y, demo.metadata.map_name, res_cache)
                       for x, y in r.get("route", [])]
                pts = [p for p in pts if p is not None]
                if len(pts) >= 2:
                    out.append({"route": [[u, v] for u, v in pts],
                                "share": r.get("share", 0.0),
                                "rounds": r.get("rounds", [])})
            return out

        return {
            "demo_hash": demo.metadata.demo_hash,
            "map_name": demo.metadata.map_name,
            "rounds": len(reg),
            "t_wins": t_wins,
            "ct_wins": len(reg) - t_wins,
            "t_routes": norm_routes(routes.routes),
            "ct_routes": norm_routes(routes.ct_routes),
            "plants": [r for r in (postplant.rounds if postplant else []) if r.get("site")],
        }

    per_demo = scan_demos(cache_dir, work)

    maps: dict[str, dict] = {}
    for entry in per_demo:
        m = maps.setdefault(entry["map_name"], {
            "map_name": entry["map_name"], "demos": 0, "rounds": 0,
            "t_wins": 0, "ct_wins": 0,
            "routes": {"T": [], "CT": []},
            "sites": defaultdict(int),
        })
        m["demos"] += 1
        m["rounds"] += entry["rounds"]
        m["t_wins"] += entry["t_wins"]
        m["ct_wins"] += entry["ct_wins"]
        w = 1.0 / max(entry["rounds"], 1)
        _merge_routes(m["routes"]["T"], entry["t_routes"], w)
        _merge_routes(m["routes"]["CT"], entry["ct_routes"], w)
        for pl in entry["plants"]:
            m["sites"][pl.get("site") or "?"] += 1

    out = []
    for m in maps.values():
        total = m["t_wins"] + m["ct_wins"]
        # keep only recognizable sites (A/B); the module's numeric fallback
        # codes (demoparser2 place ids) are noise for the distribution bars
        sites = {k: v for k, v in m["sites"].items() if k in ("A", "B")}
        best = sorted(
            per_player_map.get(m["map_name"], {}).values(),
            key=lambda x: -(x["rating"] * x["rounds"]),
        )
        out.append({
            "map_name": m["map_name"],
            "demos": m["demos"],
            "rounds": total,
            "t_win_rate": round(m["t_wins"] / total, 3) if total else 0.0,
            "ct_win_rate": round(m["ct_wins"] / total, 3) if total else 0.0,
            "routes": m["routes"],
            "sites": sites,
            "best_players": [
                {k: bp[k] for k in ("steamid", "name", "rating", "rounds", "demos")}
                for bp in best[:5]
                if bp["rounds"] >= 10
            ][:5],
        })
    out.sort(key=lambda m: -m["demos"])
    return {"maps": out, "generated": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat(timespec="seconds")}
