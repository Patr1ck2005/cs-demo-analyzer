"""Memoized cross-demo aim-science aggregation (Phase R3 枪法科学).

Merges AimScienceModule per-demo per-player vectors across the library.
T3 shard cache (ev_data precedent): a new demo costs one demo's module run
+ a cheap re-merge. The merged memo is NOT T1-snapshotted — the per-demo
shards are the persistent layer, and the merge is cheap (35 small payloads).

IMPORTANT (X4b/U1 lesson): report-level access MUST warm the shard memo via
_aim_report() BEFORE any lock-taking request path; the /match and career
pages only *peek* at the warm memo and never trigger a cold scan
synchronously (warmup.wave2 materializes it in the background).
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_report: dict | None = None


def invalidate_aimsci() -> None:
    global _report
    with _lock:
        _report = None


def _demo_payload(demo) -> dict:
    """Per-demo shard payload via the shared single-source computation."""
    from cs_analyzer.analysis.aim_science import compute_aim_science

    result = compute_aim_science(demo)
    return {
        "demo_hash": demo.metadata.demo_hash,
        "map_name": demo.metadata.map_name,
        "players": result.players,
        "samples": result.samples,
        "notes": result.notes,
    }


def _scan_all() -> list:
    """Whole-library scan with the T3 shard cache (memoized, family aimsci)."""
    from cs_analyzer.analysis.library import scan_hashes
    from cs_analyzer.web import runtime, snapshots

    cache_dir = runtime.cache().cache_dir
    hashes = snapshots._cached_demo_hashes(cache_dir)
    sharded, missing = snapshots.load_shards("aimsci", runtime.out_dir(),
                                             cache_dir, hashes)
    if missing:
        pairs = scan_hashes(cache_dir, missing, _demo_payload)
        for h, payload in pairs:
            snapshots.save_shard("aimsci", runtime.out_dir(), cache_dir, h, payload)
            sharded[h] = payload
    return [sharded[h] for h in hashes if h in sharded]


def _merge(per_demo: list) -> dict:
    from collections import defaultdict

    from cs_analyzer.analysis.stats import wilson_interval

    agg: dict[str, dict] = {}
    demos_n: dict[str, set] = defaultdict(set)
    calibrations = []
    for entry in per_demo:
        if entry.get("notes", {}).get("calibration"):
            calibrations.append({
                "demo_hash": entry["demo_hash"],
                **entry["notes"]["calibration"],
            })
        for p in entry["players"]:
            sid = p["steamid"]
            a = agg.setdefault(sid, {
                "steamid": sid, "name": p["name"],
                "preaim": [], "preaim_pitch": [], "preaim_lt10": [],
                "aim_dmg": [], "counter_s": [], "counter_nofire": 0,
                "duels_stopped": [], "duels_moving": [],
                "shots": 0, "stopped_shots": 0, "dmg_shots": 0,
            })
            a["preaim"] += entry["samples"].get(sid, {}).get("preaim", [])
            a["preaim_pitch"] += entry["samples"].get(sid, {}).get("preaim_pitch", [])
            a["preaim_lt10"] += entry["samples"].get(sid, {}).get("preaim_lt10", [])
            a["aim_dmg"] += entry["samples"].get(sid, {}).get("aim_dmg", [])
            a["counter_s"] += entry["samples"].get(sid, {}).get("counter_s", [])
            a["counter_nofire"] += entry["samples"].get(sid, {}).get("counter_nofire", 0)
            a["duels_stopped"] += entry["samples"].get(sid, {}).get("duels_stopped", [])
            a["duels_moving"] += entry["samples"].get(sid, {}).get("duels_moving", [])
            a["shots"] += p.get("n_shots", 0) or 0
            a["stopped_shots"] += entry["samples"].get(sid, {}).get("stopped_shots", 0)
            a["dmg_shots"] += entry["samples"].get(sid, {}).get("dmg_shots", 0)
        for p in entry["players"]:
            demos_n[p["steamid"]].add(entry["demo_hash"])
    # fix demos_n (first pass computed it before the set was complete)
    for sid, a in agg.items():
        a["demos_n"] = len(demos_n[sid])

    import numpy as np

    def med(vals):
        return round(float(np.median(vals)), 2) if vals else None

    players_out = []
    for sid, a in agg.items():
        n_pre = len(a["preaim"])
        n_lt10 = sum(a["preaim_lt10"])
        n_cnt = len(a["counter_s"])
        n_counter = n_cnt + a["counter_nofire"]
        lt10_lo, lt10_hi = wilson_interval(n_lt10, n_pre) if n_pre else (0.0, 0.0)
        cf_lo, cf_hi = wilson_interval(
            sum(1 for s_ in a["counter_s"] if s_ <= 0.5), n_counter) if n_counter else (0.0, 0.0)
        row = {
            "steamid": sid, "name": a["name"], "demos": a["demos_n"],
            "n_shots": a["shots"],
            "preaim_n": n_pre,
            "preaim_med_deg": med(a["preaim"]),
            "preaim_pitch_med_deg": med(a["preaim_pitch"]),
            "preaim_lt10_rate": round(n_lt10 / n_pre, 3) if n_pre else None,
            "preaim_lt10_conf": {"lo": round(lt10_lo, 3), "hi": round(lt10_hi, 3),
                                 "n": n_pre, "gated": n_pre < 20},
            "aim_dmg_med_deg": med(a["aim_dmg"]),
            "counter_n": n_counter,
            "counter_med_s": med(a["counter_s"]),
            "counter_fast_rate": (round(sum(1 for s_ in a["counter_s"] if s_ <= 0.5) / n_counter, 3)
                                  if n_counter else None),
            "counter_fast_conf": {"lo": round(cf_lo, 3), "hi": round(cf_hi, 3),
                                  "n": n_counter, "gated": n_counter < 20},
            "duel_stopped_n": len(a["duels_stopped"]),
            "duel_stopped_wins": sum(a["duels_stopped"]),
            "duel_moving_n": len(a["duels_moving"]),
            "duel_moving_wins": sum(a["duels_moving"]),
            "stopped_fire_rate": (round(a["stopped_shots"] / a["shots"], 3)
                                  if a["shots"] else None),
            "fire_damage_rate": (round(a["dmg_shots"] / a["shots"], 3)
                                 if a["shots"] else None),
        }
        players_out.append(row)
    players_out.sort(key=lambda r: -r["preaim_n"])
    return {
        "players": players_out,
        "n_demos": len(per_demo),
        "calibrations": calibrations,
        "notes": {
            "preaim_def": "首次伤害前 24 tick（64tick≈0.375s）视角与目标方向夹角的中位数；越小说明预瞄越贴点",
            "counter_def": "本生命首次被伤害 → 自己下一枪的延迟中位数；≤0.5s 份额为'反击枪快'指标",
            "boundaries": "无地图几何（无视线/遮挡判定）；64tick 采样 ±1 tick=±15.6ms；aim_dmg_med_deg 为校准诊断（应≈0，偏大则 preaim 不可信）",
        },
    }


def aim_report() -> dict:
    """Merged cross-library aim-science report (memoized, single-flight)."""
    global _report
    if _report is None:
        per_demo = _scan_all()  # warm shard memo BEFORE the lock (X4 lesson)
        with _lock:
            if _report is None:
                _report = _merge(per_demo)
    return _report


def aim_peek() -> dict | None:
    """Read-only view of the warm memo (never triggers a cold scan)."""
    return _report
