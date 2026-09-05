"""Match-page context builders (Phase S: moved verbatim out of app.py).

app.py keeps routes; this module owns the data transforms behind
/match/{hash}: the player table, the kill feed grouped by round. The kill
feed is computed ONCE per render — the old code walked every player_death
row twice (a dead `_kill_feed` call whose result was discarded, then
`_kill_groups` internally recomputing it).
"""
from __future__ import annotations

from pathlib import Path

from cs_analyzer.model.parsed_demo import ParsedDemo


def kill_feed(demo: ParsedDemo) -> list[dict]:
    df = demo.events.get("player_death")
    if df is None or df.empty:
        return []
    # P5: kill-context badges straight off the player_death flag columns
    _BADGES = (
        ("penetrated", "穿", "穿墙击杀"),
        ("thrusmoke", "烟", "烟雾中击杀"),
        ("noscope", "盲", "未开镜击杀"),
        ("attackerinair", "空", "空中击杀"),
        ("headshot", "HS", "爆头"),
    )
    rows = []
    for _, r in df.iterrows():
        badges = []
        for col, label, title in _BADGES:
            try:
                hit = bool(r.get(col, False))
            except (TypeError, ValueError):
                hit = False
            if hit:
                badges.append({"code": col, "label": label, "title": title})
        rows.append(
            {
                "tick": int(r.get("tick", 0)),
                "round": _round_at_tick(demo, int(r.get("tick", 0))),
                "attacker": r.get("attacker_name", ""),
                "victim": r.get("user_name", ""),
                "weapon": r.get("weapon", ""),
                "badges": badges,
            }
        )
    rows.sort(key=lambda x: x["tick"])
    return rows


def kill_groups(demo: ParsedDemo, rounds: list[dict]) -> list[dict]:
    """Kill feed grouped by round (D3): [{round, winner_side, kills: [...]}].

    Keeps every kill (no truncation) but collapses each round group in the UI.
    """
    kills = kill_feed(demo)
    if not kills:
        return []
    winner = {r["number"]: r["winner_side"] for r in rounds}
    groups: dict[int, list[dict]] = {}
    for k in kills:
        groups.setdefault(k["round"], []).append(k)
    return [
        {
            "round": rnd,
            "winner_side": winner.get(rnd, ""),
            "kills": groups[rnd],
        }
        for rnd in sorted(groups)
    ]


def round_at_tick(demo: ParsedDemo, tick: int) -> int:
    rnd = demo.data.round_at_tick(tick)
    return rnd.number if rnd else 0


def demo_context(demo: ParsedDemo, analysis: dict) -> dict:
    meta = demo.metadata
    reg = demo.regular_rounds
    t_score = reg[-1].t_score if reg else 0
    ct_score = reg[-1].ct_score if reg else 0

    basic = analysis["basic"]
    ratings = analysis["ratings"]
    from cs_analyzer.coverage import _player_position_stats

    pos_stats = _player_position_stats(demo)  # one pass, not once per player
    players = []
    for bs in basic.players:
        rt = ratings.by_steamid(bs.steamid) if ratings else None
        players.append(
            {
                "steamid": bs.steamid,
                "name": bs.name,
                "team": bs.team,
                "team_label": {"Team 2": "T", "Team 3": "CT"}.get(bs.team, "Team 0"),
                "K": bs.kills,
                "D": bs.deaths,
                "A": bs.assists,
                "ADR": round(bs.ADR, 1),
                "KPR": round(bs.KPR, 2),
                "Rating": round(rt.Rating, 2) if rt else 0.0,
                "RWS": round(rt.RWS, 1) if rt else 0.0,
                "KAST": round(rt.KAST, 0) if rt else 0,
                "replayable": pos_stats.get(bs.steamid, (False, 0.0))[0],
            }
        )
    players.sort(key=lambda p: p["Rating"], reverse=True)

    rounds = [
        {"number": r.number, "winner_side": r.winner_side, "t_score": r.t_score, "ct_score": r.ct_score}
        for r in reg
    ]

    return {
        "demo": {
            "hash": meta.demo_hash,
            "filename": Path(meta.demo_path).name,
            "map_name": meta.map_name,
            "provider": meta.provider.value,
            "t_score": t_score,
            "ct_score": ct_score,
            "num_rounds": len(reg),
        },
        "players": players,
        "rounds": rounds,
        "kills": kill_groups(demo, rounds),
        "has_preference": analysis["preference"] is not None,
    }


def _round_at_tick(demo: ParsedDemo, tick: int) -> int:
    return round_at_tick(demo, tick)
