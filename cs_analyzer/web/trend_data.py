"""C3 趋势对比 (车队趋势): recent-half vs earlier-half per-player means.

Presentation layer only — every number is an already-shipped metric from
the T1 aggregate memo's per-demo entries (Rating/ADR/KAST); the library is
split at the chronological median demo (aggregated().demos is match_key
sorted = chronological). Δ values are DISPLAY conventions, not statistical
tests; players with <3 demos in either window are honestly greyed out.
Request-safe: aggregated() is snapshot-backed, never scans.
"""
from __future__ import annotations

MIN_PER_WINDOW = 3


def trend_report(agg=None) -> dict:
    from cs_analyzer.web.aggregation import aggregated

    agg = agg if agg is not None else aggregated()
    demos = list(agg.demos)
    n = len(demos)
    split = n // 2
    recent_hashes = {d.demo_hash for d in demos[split:]}

    def mean(rows: list[dict], key: str) -> float:
        return sum(r[key] for r in rows) / len(rows)

    out: list[dict] = []
    for p in agg.players:
        before = [e for e in p.demos if e["demo_hash"] not in recent_hashes]
        recent = [e for e in p.demos if e["demo_hash"] in recent_hashes]
        if len(before) < MIN_PER_WINDOW or len(recent) < MIN_PER_WINDOW:
            continue
        row = {
            "steamid": p.steamid, "name": p.name,
            "n_before": len(before), "n_recent": len(recent),
            "rating_before": round(mean(before, "Rating"), 3),
            "rating_recent": round(mean(recent, "Rating"), 3),
            "adr_before": round(mean(before, "ADR"), 1),
            "adr_recent": round(mean(recent, "ADR"), 1),
            "kast_before": round(mean(before, "KAST"), 1),
            "kast_recent": round(mean(recent, "KAST"), 1),
        }
        row["d_rating"] = round(row["rating_recent"] - row["rating_before"], 3)
        row["d_adr"] = round(row["adr_recent"] - row["adr_before"], 1)
        row["d_kast"] = round(row["kast_recent"] - row["kast_before"], 1)
        out.append(row)
    out.sort(key=lambda r: -r["d_rating"])
    return {
        "split": {"before": split, "recent": n - split},
        "players": out,
        "note": ("切分=比赛时间序中位数；Δ 为展示值非显著性检验；"
                 f"任一窗口 <{MIN_PER_WINDOW} 场灰显"),
    }
