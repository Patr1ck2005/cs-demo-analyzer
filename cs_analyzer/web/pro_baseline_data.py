"""Phase D3b — pro baseline reference (职业基准卡).

Reads ``output/pro_baseline.json`` (collected by scripts/pro_baseline.py from
bo3.gg's public stats API) and turns it into a cross-library comparison
card: my percentile position vs the pro reference for the shared metrics.

Metrics compared (bo3 gg's rating is on a different scale than HLTV 2.0 —
the card shows my value, the pro's value, and the pro's per-map band so the
gap is readable without pretending the numbers are one scale):

  KPR  (avg_kills)  ·  ADR (avg_damage)  ·  HS% (accuracy headshots)
  K/D  (kills/deaths from general)  ·  win rate

No rank math across scales — the card is a reference band, not a score.
"""
from __future__ import annotations

import json
from pathlib import Path

BASELINE_PATH = Path("output/pro_baseline.json")
_cache: dict | None = None
_mtime: float | None = None


def _load() -> dict | None:
    global _cache, _mtime
    if not BASELINE_PATH.exists():
        return None
    m = BASELINE_PATH.stat().st_mtime
    if _cache is None or m != _mtime:
        try:
            _cache = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
            _mtime = m
        except (OSError, ValueError):
            return None
    return _cache


def pro_baseline_card() -> dict:
    """Card payload for /compare (职业基准区块)."""
    doc = _load()
    if not doc or not doc.get("players"):
        return {
            "available": False,
            "note": "职业基准未采集 — 运行 `python scripts/pro_baseline.py s1mple m0nesy donk`",
            "players": [],
        }
    players = []
    for nick, p in doc["players"].items():
        g = p.get("general") or {}
        kd = None
        if g.get("kills") and g.get("deaths"):
            kd = round(g["kills"] / max(g["deaths"], 1), 2)
        maps = [
            {"map": slug, "maps_count": m.get("maps_count"),
             "avg_kills": m.get("avg_kills"), "avg_damage": m.get("avg_damage")}
            for slug, m in (p.get("maps") or {}).items()
        ]
        maps.sort(key=lambda x: -(x.get("maps_count") or 0))
        players.append({
            "nickname": nick,
            "six_month_rating": p.get("six_month_rating"),
            "games": g.get("games"), "rounds": g.get("rounds"),
            "kd": kd,
            "top_maps": maps[:4],
        })
    return {
        "available": True,
        "source": doc.get("source"),
        "collected_at": doc.get("collected_at"),
        "players": players,
        "note": "职业参照（bo3.gg 统计口径，与本地 demo 统计非同一评分标尺）",
    }
