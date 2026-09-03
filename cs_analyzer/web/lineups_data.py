"""Memoized lineup grouping (Phase L4 队伍视图).

Data reality (probed, HANDOFF §7.9): matchmaking demos carry no clan names —
team_a/team_b are "Team 3/Team 2" placeholders on every demo in the library.
So grouping is by STARTING LINEUP FINGERPRINT instead of by name, reusing
teamplay's regulars notion (>=3 appearances across the g161- 5E set): a match
where >=3 regulars queued together is a 车队局 (stack); the rest are 单排局
(solo). The "our side" perspective for win rates = the side holding the
majority of the regulars in each round (round_player_sides, swap-safe).
"""
from __future__ import annotations

import threading
from collections import Counter

_lock = threading.Lock()
_report: dict | None = None


def lineups_report() -> dict:
    """Return the memoized report, computing it on first use (single-flight)."""
    global _report
    if _report is None:
        with _lock:
            if _report is None:
                _report = _build()
    return _report


def invalidate_lineups() -> None:
    global _report
    with _lock:
        _report = None


def _start_lineups(demo) -> dict[str, list[dict]]:
    """{side: [players]} from each team's starting_side."""
    out: dict[str, list[dict]] = {"T": [], "CT": []}
    meta = demo.metadata
    for p in demo.players:
        if meta.team_a.starting_side in ("T", "CT") and p.team == meta.team_a.name:
            out[meta.team_a.starting_side].append({"steamid": p.steamid, "name": p.name})
        elif meta.team_b.starting_side in ("T", "CT") and p.team == meta.team_b.name:
            out[meta.team_b.starting_side].append({"steamid": p.steamid, "name": p.name})
    return out


def _build() -> dict:
    from cs_analyzer.analysis.library import demo_filenames, scan_demos
    from cs_analyzer.analysis.teamplay import FIVE_E_PREFIX
    from cs_analyzer.analysis.util import round_player_sides
    from cs_analyzer.web.aggregation import aggregated
    from cs_analyzer.web.app import _cache

    cache_dir = _cache().cache_dir
    names = demo_filenames(cache_dir)
    five_e_hashes = {h for h, fn in names.items() if fn.startswith(FIVE_E_PREFIX)}
    agg = aggregated()
    demo_ratings: dict[str, dict[str, float]] = {}
    for p in agg.players:
        for d in p.demos:
            demo_ratings.setdefault(d["demo_hash"], {})[p.steamid] = d["Rating"]

    def work(demo) -> dict | None:
        if demo.metadata.demo_hash not in five_e_hashes:
            return None  # lineups view covers the 5E five-stack library
        rounds = demo.regular_rounds
        return {
            "demo_hash": demo.metadata.demo_hash,
            "filename": demo.metadata.demo_path.replace("\\", "/").split("/")[-1],
            "map": demo.metadata.map_name,
            "match_id": getattr(demo.metadata, "match_id", None),
            "lineups": _start_lineups(demo),
            "rounds": len(rounds),
            "round_sides": round_player_sides(demo),
            "winners": [{"n": r.number, "w": r.winner_side} for r in rounds],
        }

    per_demo = [d for d in scan_demos(cache_dir, work) if d]

    # regulars: >=3 appearances in the 5E set (teamplay threshold)
    appear: Counter = Counter()
    reg_names: dict[str, str] = {}
    for d in per_demo:
        for side_players in d["lineups"].values():
            for pl in side_players:
                appear[pl["steamid"]] += 1
                reg_names.setdefault(pl["steamid"], pl["name"])
    regulars = {sid for sid, n in appear.items() if n >= 3}

    matches = []
    for d in per_demo:
        in_match = sorted({pl["steamid"] for side in d["lineups"].values()
                           for pl in side if pl["steamid"] in regulars})
        is_stack = len(in_match) >= 3
        # "our side" = majority-regular side per round; only clean splits count
        won = total = 0
        for w in d["winners"]:
            smap = d["round_sides"].get(w["n"], {})
            present = [smap.get(s, "") for s in in_match if smap.get(s)]
            if not present:
                continue
            t_n, ct_n = present.count("T"), present.count("CT")
            if (t_n > 0) != (ct_n > 0):
                total += 1
                if w["w"] == ("T" if t_n > 0 else "CT"):
                    won += 1
        rmap = demo_ratings.get(d["demo_hash"], {})
        matches.append({
            "demo_hash": d["demo_hash"], "filename": d["filename"], "map": d["map"],
            "match_id": d["match_id"], "rounds": d["rounds"],
            "is_stack": is_stack, "stack_size": len(in_match),
            "regulars": [reg_names.get(s, s) for s in in_match],
            "our_win_rate": round(won / total, 3) if total else None,
            "our_rounds": total,
            "lineups": {side: [{"steamid": pl["steamid"], "name": pl["name"],
                                "rating": rmap.get(pl["steamid"])}
                               for pl in side_players]
                        for side, side_players in d["lineups"].items()},
        })
    matches.sort(key=lambda m: m["match_id"] or m["filename"])

    stacks = [m for m in matches if m["is_stack"]]
    solos = [m for m in matches if not m["is_stack"]]

    def group(ms: list[dict]) -> dict:
        if not ms:
            return {"matches": 0, "avg_our_win_rate": None, "maps": []}
        wrs = [m["our_win_rate"] for m in ms if m["our_win_rate"] is not None]
        return {
            "matches": len(ms),
            "avg_our_win_rate": round(sum(wrs) / len(wrs), 3) if wrs else None,
            "maps": sorted({m["map"] for m in ms}),
        }

    return {
        "generated": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "note": "匹配匹 demo 无战队名（Team 2/3 占位）——按首发阵容指纹分组",
        "regulars": [{"steamid": s, "name": reg_names.get(s, s), "appearances": appear[s]}
                     for s in sorted(regulars, key=lambda x: -appear[x])],
        "groups": {"stack": group(stacks), "solo": group(solos)},
        "matches": matches,
    }
