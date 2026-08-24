"""Pure payload builders for the ECharts layer (Phase E M6).

Server-side dict assembly only — no rendering. The browser fetches these
payloads from /api/.../charts.json endpoints and feeds them to vendored
Apache ECharts with the dark CSA theme.
"""
from __future__ import annotations

from cs_analyzer.analysis.aggregate import AggregateResult
from cs_analyzer.analysis.basic_stats import BasicStatsResult
from cs_analyzer.analysis.preference import PreferenceResult
from cs_analyzer.analysis.ratings import RatingsResult
from cs_analyzer.maps.loader import MapResource
from cs_analyzer.model.parsed_demo import ParsedDemo

# Radar axes inherit the semantic ranges of the retired matplotlib radar
# (config RadarChartConfig.attribute_ranges); values normalize to 0-100.
RADAR_AXES: list[dict] = [
    {"key": "KPR", "label": "KPR", "min": 0.5, "max": 0.9},
    {"key": "Survivals", "label": "存活率", "min": 0.2, "max": 0.35},
    {"key": "ADR", "label": "ADR", "min": 50.0, "max": 90.0},
    {"key": "Headshot%", "label": "爆头率%", "min": 30.0, "max": 50.0},
    {"key": "FirstKillsPerRound", "label": "首杀/回合", "min": 0.0, "max": 0.15},
    {"key": "Rating_Pro", "label": "Rating", "min": 0.7, "max": 1.2},
]

_UTILITY_LABELS = {"smoke": "烟雾", "flash": "闪光", "he": "HE", "molly": "燃烧瓶"}


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _norm(v: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return round(_clamp((v - lo) / (hi - lo) * 100.0), 1)


def radar_payload(basic: BasicStatsResult, ratings: RatingsResult | None) -> dict:
    """Per-demo six-axis radar for every player (normalized 0-100)."""
    by_steamid = {r.steamid: r for r in ratings.players} if ratings else {}
    series = []
    for p in basic.players:
        rt = by_steamid.get(p.steamid)
        merged = {
            "KPR": p.KPR,
            "Survivals": p.Survivals,
            "ADR": p.ADR,
            "Headshot%": p.headshot_pct,
            "FirstKillsPerRound": p.FirstKillsPerRound,
            "Rating_Pro": (rt.Rating_Pro if rt else 0.0),
        }
        values = [_norm(merged[a["key"]], a["min"], a["max"]) for a in RADAR_AXES]
        series.append(
            {
                "name": p.name,
                "steamid": p.steamid,
                "team": p.team,
                "values": values,
                "raw": [round(merged[a["key"]], 2) for a in RADAR_AXES],
                "rating": round(rt.Rating, 2) if rt else 0.0,
            }
        )
    series.sort(key=lambda s: s["rating"], reverse=True)
    return {
        "indicators": [{"name": a["label"], "min": 0, "max": 100} for a in RADAR_AXES],
        "series": series,
    }


def _normalize_points(points: list[tuple[float, float]], map_res: MapResource) -> list[list[float]]:
    """World coords -> [0..1]² normalized against the map image box."""
    out = []
    for x, y in points:
        if x != x or y != y:  # NaN guard (Team 0)
            continue
        px, py = map_res.world_to_pixel(float(x), float(y))
        out.append([
            round(px / max(map_res.image_width, 1), 4),
            round(py / max(map_res.image_height, 1), 4),
        ])
    return out


def player_position_payload(pref: PreferenceResult | None, steamid: str,
                            demo: ParsedDemo) -> dict:
    """Heatmap points (normalized) for one player; empty when unavailable."""
    pp = next((p for p in pref.players if p.steamid == steamid), None) if pref else None
    if pp is None:
        return {"points": [], "has_map_image": False}
    from cs_analyzer.maps.loader import load_map_or_fallback

    map_res = load_map_or_fallback(demo.metadata.map_name, demo.ticks)
    return {
        "points": _normalize_points(pp.position_samples, map_res),
        "has_map_image": map_res.image_path is not None,
    }


def player_utility_payload(pref: PreferenceResult | None, steamid: str,
                           demo: ParsedDemo) -> dict:
    """Per-kind utility landing scatter (normalized points)."""
    pp = next((p for p in pref.players if p.steamid == steamid), None) if pref else None
    if pp is None:
        return {"kinds": [], "has_map_image": False}
    from cs_analyzer.maps.loader import load_map_or_fallback

    map_res = load_map_or_fallback(demo.metadata.map_name, demo.ticks)
    kinds = []
    for kind, pts in pp.utility_positions.items():
        kinds.append(
            {
                "kind": kind,
                "label": _UTILITY_LABELS.get(kind, kind),
                "points": _normalize_points(pts, map_res),
            }
        )
    return {"kinds": kinds, "has_map_image": map_res.image_path is not None}


def player_style_payload(pref: PreferenceResult | None, steamid: str) -> dict:
    pp = next((p for p in pref.players if p.steamid == steamid), None) if pref else None
    if pp is None:
        return {}
    return {
        "engagement_fraction": round(pp.avg_first_engagement_fraction, 2),
        "engagement_rounds": pp.engagement_rounds,
        "avg_pitch": round(pp.avg_pitch, 1),
        "pitch_samples": pp.pitch_samples,
        "utility_counts": pp.utility_counts,
    }


def aggregate_payload(result: AggregateResult) -> dict:
    """Cross-demo matrix (player × demo Rating) + bars + trends."""
    demo_names = [d.filename for d in result.demos]
    matrix_players = []
    values = []
    for p in result.players[:20]:  # keep the matrix readable
        matrix_players.append(p.name)
        by_demo = {d["demo"]: d.get("Rating", 0.0) for d in p.demos}
        values.append([round(by_demo.get(name, None), 2) if by_demo.get(name) is not None else None
                       for name in demo_names])
    top = result.players[:10]
    return {
        "matrix": {"players": matrix_players, "demos": demo_names, "values": values},
        "bars": {
            "names": [p.name for p in top],
            "kpr": [round(p.avg_kpr, 2) for p in top],
            "adr": [round(p.avg_adr, 1) for p in top],
            "rating": [round(p.avg_rating, 2) for p in top],
        },
        "trends": [
            {
                "name": d.filename,
                "map": d.map_name,
                "t_win_rate": round(d.t_win_rate, 3),
                "trend": d.trend,
            }
            for d in result.demos
        ],
    }


# ---- Phase F M7/M8: advanced analysis payloads ----


def duels_payload(result) -> dict:
    """Duel matrix -> ECharts heatmap (players × players win-rate cells)."""
    players = result.players
    names = [result.names.get(s, s[-4:]) for s in players]
    cells = []
    for i, a in enumerate(players):
        for j, b in enumerate(players):
            k = result.kills.get(a, {}).get(b, 0)
            d = result.kills.get(b, {}).get(a, 0)
            if k + d == 0 or i == j:
                continue
            cells.append([j, i, round(k / (k + d), 3), k, d, k + d >= result.min_duels])
    sides = [result.sides.get(s, "") for s in players]
    return {"players": names, "steamids": players, "sides": sides,
            "min_duels": result.min_duels, "cells": cells}


def economy_payload(result) -> dict:
    """Round buy classification -> combo chart (spend bars + buy-type line)."""
    rounds = sorted({r.round for r in result.rounds})
    series = {}
    for side in ("T", "CT"):
        rows = {r.round: r for r in result.rounds if r.side == side}
        series[side] = {
            "spend": [round(rows[r].spend) if r in rows else None for r in rounds],
            "buy": [rows[r].buy if r in rows else None for r in rounds],
        }
    return {
        "rounds": rounds,
        "series": series,
        "win_by_buy": result.win_by_buy,
        "loss_streaks": result.loss_streaks,
    }


def utility_payload(result) -> dict:
    """Flash value ranking + smoke denial counters."""
    return {
        "flashers": result.flashers,
        "smoke": result.smoke,
    }


def routes_payload(result, map_res: MapResource) -> dict:
    """Opening route centroids in image-space [0..1]² (same convention as the
    heatmap: world_to_pixel, y flipped — plot with yAxis inverse:true)."""
    def norm(pt: list[list[float]]) -> list[list[float]]:
        out = []
        for x, y in pt:
            px, py = map_res.world_to_pixel(float(x), float(y))
            out.append([round(px / max(map_res.image_width, 1), 4),
                        round(py / max(map_res.image_height, 1), 4)])
        return out

    return {
        "side": result.side,
        "k": result.k,
        "routes": [
            {"route": norm(r["route"]), "rounds": r["rounds"], "share": r["share"]}
            for r in result.routes
        ],
    }
