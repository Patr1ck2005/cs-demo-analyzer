"""Memoized cross-demo loss-attribution aggregation (Phase R5 失利归因).

Merges LossAttributionModule per-demo payloads across the library into a
per-team loss-mode distribution (which failure mode dominates losses).
T3 shard family ``lossattr`` (ev_data precedent); merge is cheap, so — like
aim_data — no T1 whole-report snapshot (the shards are the persistent layer).

X4b/U1 lesson: report-level consumers must warm the shard memo through
loss_report() (which warms BEFORE locking); the request path only peeks.
"""
from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()
_report: dict | None = None

TAG_DEFS: dict[str, str] = {
    "lost_opening": "掉首口：回合首杀归敌",
    "untraded": "无贸易死：≥2 次死亡在贸易窗（2s）内无人击杀凶手",
    "lost_force": "强起失利：败方 force 买法",
    "lost_eco": "eco 失利：败方 eco 买法",
    "utility_deficit": "道具劣势：敌 utility 伤害 > 1.5×己方（且 ≥20）",
    "lost_clutch": "残局失守：败方进入 1vX 仍输",
}


def invalidate_lossattr() -> None:
    global _report
    with _lock:
        _report = None


def _demo_payload(demo) -> dict:
    """Per-demo shard payload via the shared single-source computation."""
    from cs_analyzer.analysis.loss_attribution import LossAttributionModule

    result = LossAttributionModule().run(demo, _EconCtx(demo))
    return {
        "demo_hash": demo.metadata.demo_hash,
        "rounds": result.rounds,
        "teams": [{"team": t["team"], "lost_rounds": t["lost_rounds"],
                   "tags": t["tags"]} for t in result.teams],
        # C2-H2: per-player death granularity in lost rounds (rate metric)
        "players": [{"steamid": p["steamid"],
                     "lost_deaths": p["lost_deaths"],
                     "untraded_deaths": p["untraded_deaths"]}
                    for p in result.players],
        "roster": result.roster,
    }


class _EconCtx:
    """Minimal AnalysisContext stand-in providing only the economy result."""

    def __init__(self, demo) -> None:
        self._demo = demo

    def require(self, name: str):
        if name != "economy":
            raise KeyError(name)
        from cs_analyzer.analysis.economy import EconomyModule
        from cs_analyzer.analysis.base import AnalysisContext, AnalysisConfig

        return EconomyModule().run(self._demo, AnalysisContext(AnalysisConfig()))


def _scan_all() -> list:
    from cs_analyzer.analysis.library import scan_hashes
    from cs_analyzer.web import runtime, snapshots

    cache_dir = runtime.cache().cache_dir
    hashes = snapshots._cached_demo_hashes(cache_dir)
    sharded, missing = snapshots.load_shards("lossattr", runtime.out_dir(),
                                             cache_dir, hashes)
    if missing:
        pairs = scan_hashes(cache_dir, missing, _demo_payload)
        for h, payload in pairs:
            snapshots.save_shard("lossattr", runtime.out_dir(), cache_dir, h, payload)
            sharded[h] = payload
    return [sharded[h] for h in hashes if h in sharded]


def loss_report() -> dict:
    """Cross-library per-team loss-mode counts (memoized, single-flight)."""
    global _report
    if _report is None:
        per_demo = _scan_all()  # warm shard memo BEFORE the lock (X4 lesson)
        with _lock:
            if _report is None:
                _report = _merge(per_demo)
    return _report


def loss_peek() -> dict | None:
    """Read-only view of the warm memo (never triggers a cold scan)."""
    return _report


def _merge(per_demo: list) -> dict:
    teams: dict[str, dict] = {}
    players: dict[str, dict] = {}
    pdeaths: dict[str, list] = {}  # C2-H2: sid -> [lost_deaths, untraded]
    for entry in per_demo:
        for t in entry["teams"]:
            a = teams.setdefault(t["team"], {"team": t["team"], "lost_rounds": 0,
                                             "tags": defaultdict(int)})
            a["lost_rounds"] += t["lost_rounds"]
            for tag, c in t["tags"].items():
                a["tags"][tag] += c
        # per-player: only rounds where the player's side actually lost
        for r in entry["rounds"]:
            for sid in r.get("loser_sids", []):
                p = players.setdefault(sid, {"steamid": sid, "demos": set(),
                                             "lost_rounds": 0,
                                             "tags": defaultdict(int)})
                p["demos"].add(entry["demo_hash"])
                p["lost_rounds"] += 1
                for tag in r["tags"]:
                    p["tags"][tag] += 1
        for pd in entry.get("players") or []:
            cell = pdeaths.setdefault(pd["steamid"], [0, 0])
            cell[0] += int(pd.get("lost_deaths") or 0)
            cell[1] += int(pd.get("untraded_deaths") or 0)
    return {
        "teams": [
            {"team": a["team"], "lost_rounds": a["lost_rounds"],
             "tags": dict(sorted(a["tags"].items(), key=lambda kv: -kv[1]))}
            for a in teams.values()
        ],
        "players": [
            {"steamid": p["steamid"], "lost_rounds": p["lost_rounds"],
             "demos": len(p["demos"]),
             "tags": dict(sorted(p["tags"].items(), key=lambda kv: -kv[1])),
             "lost_deaths": pdeaths.get(p["steamid"], [0, 0])[0],
             "untraded_deaths": pdeaths.get(p["steamid"], [0, 0])[1],
             "untraded_rate": (round(pdeaths[p["steamid"]][1] / pdeaths[p["steamid"]][0], 3)
                               if pdeaths.get(p["steamid"], [0, 0])[0] else None)}
            for p in players.values()
        ],
        "demos": len(per_demo),
        "tag_defs": TAG_DEFS,
    }


def loss_patterns_for(steamid: str) -> dict | None:
    """R5 生涯卡数据：一名选手参战队伍的败回合标签分布（含 Wilson conf）。"""
    from cs_analyzer.analysis.stats import wilson_interval

    report = loss_report()
    p = next((x for x in report.get("players", []) if x["steamid"] == steamid), None)
    if p is None:
        return None
    n = p["lost_rounds"]
    tags = []
    for tag, c in p["tags"].items():
        lo, hi = wilson_interval(c, n) if n else (0.0, 0.0)
        tags.append({
            "tag": tag, "count": c, "share": round(c / n, 3) if n else 0.0,
            "conf": {"lo": round(lo, 3), "hi": round(hi, 3), "n": n,
                     "gated": n < 30},
        })
    return {"steamid": steamid, "lost_rounds": n, "demos": p["demos"],
            "tags": tags, "tag_defs": TAG_DEFS}
