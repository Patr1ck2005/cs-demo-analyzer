"""Memoized per-map aggregation (Phase L3 地图分析).

Groups the library by map: play counts / round win rates (T and CT),
merged opening routes (per side, share-weighted across demos), bomb-plant
site distribution, and each map's strongest players (from the aggregate).

Phase X: per-demo payloads (routes/postplant/round outcomes) go through the
T3 shard cache (same pattern as ev_data/aggregate) — a new demo costs one
demo's module run + a cheap re-merge instead of a full-library rescan. The
merged report stays memoized + snapshotted exactly as before.
"""
from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()
_report: dict | None = None
_shards: list | None = None  # per-demo payloads (shard-backed scan)


def map_report() -> dict:
    """Return the memoized report, computing it on first use (single-flight).

    Shard memo warmed before the lock — see utilitylab_report (the cold
    _scan_all path takes the same non-reentrant lock _build holds)."""
    global _report
    if _report is None:
        _scan_all()
        with _lock:
            if _report is None:
                _report = _build()
    return _report


def invalidate_map_report() -> None:
    global _report, _shards
    with _lock:
        _report = None
        _shards = None


def _merge_routes(acc: dict, routes: list[dict], weight: float) -> None:
    """Merge another demo's opening routes into {side: [centroids, shares]}."""
    for r in routes:
        acc.append({"route": r["route"], "share": r.get("share", 0.0) * weight,
                    "rounds": r.get("rounds", [])})


def _pool_map_players(players: list) -> dict[str, dict[str, dict]]:
    """{map_name: {steamid: pooled cell}} from the aggregate's per-demo
    entries. Same-map multi-demo play must POOL (the old inline dict was
    overwritten per demo, keeping only the last demo's rating/rounds)."""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for p in players:
        for d in p.demos:
            cell = out[d["map_name"]].setdefault(p.steamid, {
                "steamid": p.steamid, "name": p.name,
                "rounds": 0, "_rw": 0.0, "demos": p.demo_count,
            })
            cell["rounds"] += d["rounds"]
            cell["_rw"] += d["Rating"] * d["rounds"]
    return out


def best_players_for_map(cells: dict[str, dict], min_rounds: int = 40,
                         k: int = 5) -> list[dict]:
    """本图最强选手：按回合加权 Rating（比率）排序。

    v5 口径审计：旧口径 rating×rounds 是绝对值乘积——打得越多乘积越大，
    违反"打得多≠数据好"总原则。门槛 min_rounds 只做样本可靠性过滤
    （S3 用户裁决：≥40 回合才纳入统计——约半张图的量，10 回合的"最强"
    噪声太大）。R1: Rating 非二元结果，Wilson 不适用——按均值类 EB 收缩
    挂 conf（n=回合数，k=64），`rating_shrunk` 仅展示不参与排序。
    """
    from cs_analyzer.analysis.stats import attach_conf

    rows = []
    for cell in cells.values():
        if cell["rounds"] < min_rounds:
            continue
        rows.append({
            "steamid": cell["steamid"], "name": cell["name"],
            "rounds": cell["rounds"], "demos": cell["demos"],
            "rating": round(cell["_rw"] / cell["rounds"], 3),
        })
    rows.sort(key=lambda x: -x["rating"])
    attach_conf(rows, "rating", "rounds", kind="mean", k=64, gate_n=min_rounds)
    for r in rows:
        r["rating_shrunk"] = r.pop("shrunk", None)
    return rows[:k]


def _demo_payload(demo) -> dict:
    """Per-demo shard payload: round outcomes + normalized routes + plants."""
    from cs_analyzer.web import runtime
    from cs_analyzer.web.utilitylab_data import _norm_spot

    routes = runtime.analyze_module(demo, "routes")
    try:
        postplant = runtime.analyze_module(demo, "postplant")
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
        "map_name": demo.metadata.map_name,
        "rounds": len(reg),
        "t_wins": t_wins,
        "ct_wins": len(reg) - t_wins,
        "t_routes": norm_routes(routes.routes),
        "ct_routes": norm_routes(routes.ct_routes),
        "plants": [r for r in (postplant.rounds if postplant else []) if r.get("site")],
    }


def _scan_all() -> list:
    """Whole-library scan with the T3 shard cache (memoized).

    Thread path via the per-demo module memo (shares results with other
    pages); routes/postplant are light modules, so the process pool's spawn
    overhead would dwarf the gain.
    """
    global _shards
    if _shards is not None:
        return _shards
    from cs_analyzer.web import runtime, snapshots

    cache_dir = runtime.cache().cache_dir
    hashes = snapshots._cached_demo_hashes(cache_dir)
    sharded, missing = snapshots.load_shards("map", runtime.out_dir(),
                                             cache_dir, hashes)
    if missing:
        from cs_analyzer.analysis.library import scan_hashes

        pairs = scan_hashes(cache_dir, missing, _demo_payload)
        for h, payload in pairs:
            snapshots.save_shard("map", runtime.out_dir(), cache_dir,
                                 h, payload)
            sharded[h] = payload
    entries = [sharded[h] for h in hashes if h in sharded]
    with _lock:
        _shards = entries
        return _shards


def _build() -> dict:
    from cs_analyzer.web.aggregation import aggregated

    agg = aggregated()
    per_player_map = _pool_map_players(agg.players)
    per_demo = _scan_all()

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
        best = best_players_for_map(per_player_map.get(m["map_name"], {}))
        # R1: 图级 T/CT 胜率挂 Wilson（n=该图回合数）
        from cs_analyzer.analysis.stats import wilson_interval

        tw_lo, tw_hi = wilson_interval(m["t_wins"], total) if total else (0.0, 0.0)
        out.append({
            "map_name": m["map_name"],
            "demos": m["demos"],
            "rounds": total,
            "t_win_rate": round(m["t_wins"] / total, 3) if total else 0.0,
            "ct_win_rate": round(m["ct_wins"] / total, 3) if total else 0.0,
            "t_win_conf": {"lo": round(tw_lo, 3), "hi": round(tw_hi, 3),
                           "n": total, "gated": total < 30},
            "routes": m["routes"],
            "sites": sites,
            "best_players": [
                {k: bp[k] for k in ("steamid", "name", "rating", "rounds",
                                    "demos", "conf", "rating_shrunk")}
                for bp in best[:5]
            ][:5],
        })
    out.sort(key=lambda m: -m["demos"])
    return {"maps": out, "generated": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat(timespec="seconds")}


# ---- T1 snapshot pair (called by web.snapshots under _lock) ----

def _snapshot_payload() -> dict | None:
    return _report


def restore_snapshot(payload: dict) -> None:
    global _report
    _report = payload
