"""Single-match report payload (Phase S: moved out of app.py).

/report/{hash} used to build an AnalysisRunner inline on every request,
re-running basic_stats + ratings + highlights each time and bypassing the
per-module memo entirely. The payload builder lives here and reads through
runtime.analyze_module so repeat renders (the PNG/PDF exporter reloads the
page) hit the memo.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cs_analyzer.model.parsed_demo import ParsedDemo


def report_context(demo: ParsedDemo) -> dict:
    from cs_analyzer.web import runtime

    basic = runtime.analyze_module(demo, "basic_stats")
    ratings = runtime.analyze_module(demo, "ratings")
    hl = runtime.analyze_module(demo, "highlights")

    reg = demo.regular_rounds
    t_wins = sum(1 for r in reg if r.winner_side == "T")
    team_of: dict[str, str] = {}
    for p in demo.players:
        team_of[p.steamid] = p.team
    side_of_team = {demo.metadata.team_a.name: demo.metadata.team_a.starting_side,
                    demo.metadata.team_b.name: demo.metadata.team_b.starting_side}
    players = []
    if basic is not None and ratings is not None:
        rt_by = {p.steamid: p for p in ratings.players}
        for b in sorted(basic.players, key=lambda x: -(rt_by[x.steamid].Rating if x.steamid in rt_by else 0)):
            rt = rt_by.get(b.steamid)
            players.append({
                "name": b.name,
                "side": side_of_team.get(team_of.get(b.steamid, ""), "?"),
                "kills": b.kills, "deaths": b.deaths,
                "adr": b.ADR, "kast": rt.KAST if rt else 0.0,
                "hs": (b.headshot_kills / b.kills * 100) if b.kills else 0.0,
                "rating": rt.Rating if rt else 0.0,
            })
    highlights = []
    if hl is not None:
        for h in hl.sorted():
            if h.tier in ("ace", "k4", "1v4", "k3", "1v3"):
                highlights.append({"tier": h.tier, "name": h.name, "round": h.round,
                                   "kills": h.kills, "side": h.side})
    meta = demo.metadata
    # 复盘提升包 B1: rule-based conclusions (loser perspective) — reads the
    # lazy per-module memos via runtime; never scans (peek-only layers).
    from cs_analyzer.web.conclusions import match_conclusions

    return {
        "meta": {
            "map_name": meta.map_name,
            "filename": Path(meta.demo_path).name,
            "match_id": getattr(meta, "match_id", None),
            "demo_hash": meta.demo_hash,
        },
        "score": {
            "t": reg[-1].t_score if reg else 0,
            "ct": reg[-1].ct_score if reg else 0,
            "rounds": len(reg),
        },
        "t_wr": (t_wins / len(reg)) if reg else 0.0,
        "trend": [{"n": r.number, "w": r.winner_side} for r in reg],
        "players": players,
        "highlights": highlights,
        "conclusions": match_conclusions(demo),
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
