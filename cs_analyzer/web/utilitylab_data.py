"""Memoized cross-demo utility report (Phase L2 道具专题).

Scans every cached demo through the ``utility_effect`` module (memoized
per-demo in app._module_cache) and merges per-player flash/smoke stats across
the library; smoke landing spots are normalized to image-space [0..1]² per
map (same convention as routes_payload) so the page can plot them over the
radar PNG. Invalidated together with the aggregate.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_report: dict | None = None


def utilitylab_report() -> dict:
    """Return the memoized report, computing it on first use (single-flight)."""
    global _report
    if _report is None:
        with _lock:
            if _report is None:
                _report = _build()
    return _report


def invalidate_utilitylab() -> None:
    global _report
    with _lock:
        _report = None


def _norm_spot(x: float, y: float, map_name: str, res_cache: dict) -> tuple[float, float] | None:
    """World (X, Y) -> image-space [0..1]² (y flipped), or None without map data."""
    from cs_analyzer.maps.loader import load_map

    try:
        res = res_cache[map_name]
    except KeyError:
        try:
            res = res_cache[map_name] = load_map(map_name)
        except Exception:  # noqa: BLE001 — unknown map -> skip its spots
            res = res_cache[map_name] = None
    if res is None:
        return None
    px, py = res.world_to_pixel(float(x), float(y))
    w = max(res.image_width, 1)
    h = max(res.image_height, 1)
    if not (0.0 <= px / w <= 1.0 and 0.0 <= py / h <= 1.0):
        return None
    return round(px / w, 4), round(py / h, 4)


def _build() -> dict:
    from cs_analyzer.analysis.library import scan_demos
    from cs_analyzer.web import runtime
    from cs_analyzer.web.store import list_demos
    from pathlib import Path

    cache_dir = runtime.cache().cache_dir
    meta = {d["demo_hash"]: d for d in list_demos(cache_dir)}

    def work(demo) -> dict:
        result = runtime.analyze_module(demo, "utility_effect")
        return {
            "demo_hash": demo.metadata.demo_hash,
            "map_name": demo.metadata.map_name,
            "flashers": result.flashers,
            "smoke": result.smoke,
            "smoke_events": result.smoke_events,
        }

    per_demo = scan_demos(cache_dir, work)

    # ---- merge flashers across demos ----
    flashers: dict[str, dict] = {}
    smoke: dict[str, dict] = {}
    spots_by_map: dict[str, list[dict]] = {}
    demos_with_flash = 0
    for entry in per_demo:
        if entry["flashers"]:
            demos_with_flash += 1
        for f in entry["flashers"]:
            sid = f["steamid"]
            agg = flashers.setdefault(sid, {
                "steamid": sid, "name": f.get("name") or sid, "demos": set(),
                "throws": 0, "enemy_blind_s": 0.0, "friendly_blind_s": 0.0,
                "value": 0.0, "flash_assists": 0,
            })
            agg["demos"].add(entry["demo_hash"])
            agg["throws"] += f.get("throws", 0)
            agg["enemy_blind_s"] += f.get("enemy_blind_s", 0.0)
            agg["friendly_blind_s"] += f.get("friendly_blind_s", 0.0)
            agg["value"] += f.get("value", 0.0)
            agg["flash_assists"] += f.get("flash_assists", 0)
        for s in entry["smoke"]:
            sid = s["steamid"]
            agg = smoke.setdefault(sid, {
                "steamid": sid, "name": s.get("name") or sid, "demos": set(),
                "smoke_kills": 0, "smoke_deaths": 0,
            })
            agg["demos"].add(entry["demo_hash"])
            agg["smoke_kills"] += s.get("smoke_kills", 0)
            agg["smoke_deaths"] += s.get("smoke_deaths", 0)
        res_cache: dict = {}
        for ev in entry["smoke_events"]:
            norm = _norm_spot(ev.get("x"), ev.get("y"), entry["map_name"], res_cache)
            if norm is None:
                continue
            spots_by_map.setdefault(entry["map_name"], []).append({
                "u": norm[0], "v": norm[1], "kind": ev.get("kind", "smoke"),
                "side": ev.get("side", ""), "round": ev.get("round", 0),
                "demo": Path(meta.get(entry["demo_hash"], {}).get("filename", "")).name,
            })

    flashers_out = []
    for agg in flashers.values():
        flashers_out.append({
            "steamid": agg["steamid"], "name": agg["name"],
            "demos": len(agg["demos"]), "throws": agg["throws"],
            "enemy_blind_s": round(agg["enemy_blind_s"], 1),
            "friendly_blind_s": round(agg["friendly_blind_s"], 1),
            "value": round(agg["value"], 1),
            "value_per_throw": round(agg["value"] / agg["throws"], 2) if agg["throws"] else 0.0,
            "flash_assists": agg["flash_assists"],
        })
    # v5 口径审计：闪光榜按「每次投掷价值」排序——总价值随场次线性膨胀，
    # 打得多不再天然登顶；绝对值保留在列中，投掷 <3 次的行前端标"少"。
    flashers_out.sort(key=lambda x: (-x["value_per_throw"], -x["value"]))

    # 烟中榜同改每场净值（v5）：kills×2−deaths 的绝对值随场次膨胀
    smoke_out = sorted(
        ({**v, "demos": len(v["demos"]),
          "net_per_demo": round((v["smoke_kills"] * 2 - v["smoke_deaths"])
                                / max(len(v["demos"]), 1), 2)}
         for v in smoke.values()),
        key=lambda x: -x["net_per_demo"],
    )

    return {
        "generated": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "totals": {
            "demos_scanned": len(per_demo),
            "demos_with_flash": demos_with_flash,
            "total_throws": sum(f["throws"] for f in flashers_out),
            "total_flash_assists": sum(f["flash_assists"] for f in flashers_out),
            "total_smoke_kills": sum(s["smoke_kills"] for s in smoke_out),
            "total_enemy_blind_s": round(sum(f["enemy_blind_s"] for f in flashers_out), 1),
        },
        "flashers": flashers_out,
        "smoke": smoke_out,
        "spots_by_map": spots_by_map,
        "maps": sorted(spots_by_map.keys()),
    }


# ---- T1 snapshot pair (called by web.snapshots under _lock) ----

def _snapshot_payload() -> dict | None:
    return _report


def restore_snapshot(payload: dict) -> None:
    global _report
    _report = payload
