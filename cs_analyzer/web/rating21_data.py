"""Memoized Rating 2.1 career card (Phase U1), extracted from app.py (S3-A2).

Per-demo shard payloads (T3 pattern) + the round-weighted per-player card.
A career-page visit reads 35 tiny JSON shards instead of loading 35 parquet
demos (~15s per visit before; <1s after). The shard family is ``rating21``;
the merged card is computed per request from the shards (cheap, ~35 dict
lookups) so there is no separate memo layer to invalidate.

IMPORTANT (X4b/U1 lesson): the career page is a REQUEST path consumer. It is
covered by the warmup wave2 ``rating21`` step, which materializes the shards
in the background; the request path itself only reads shards (never scans
synchronously unless the wave2 window was missed).
"""
from __future__ import annotations

from cs_analyzer.model.parsed_demo import ParsedDemo


def _shard_payload(demo: ParsedDemo) -> dict:
    """Per-demo ratings21 shard payload: round count + a small per-player
    metrics dict, enough for round-weighted career aggregation."""
    from cs_analyzer.web import runtime

    result = runtime.analyze_module(demo, "ratings21")
    if result is None:
        return {"rounds": 0, "players": {}}
    return {
        "rounds": result.rounds_total,
        "players": {
            p.steamid: {"r21": p.Rating21, "r20": p.Rating,
                        "kast": p.KAST21, "saves": p.save_rounds}
            for p in result.players
        },
    }


def shards() -> list[tuple[str, dict]]:
    """All demo rating21 payloads via the T3 shard cache (memo family
    ``rating21``; same pattern as ev_data/winprob_loo)."""
    from cs_analyzer.analysis.library import scan_hashes
    from cs_analyzer.web import runtime, snapshots

    cache_dir = runtime.cache().cache_dir
    hashes = snapshots._cached_demo_hashes(cache_dir)
    sharded, missing = snapshots.load_shards("rating21", runtime.out_dir(),
                                             cache_dir, hashes)
    if missing:
        pairs = scan_hashes(cache_dir, missing, _shard_payload)
        for h, payload in pairs:
            snapshots.save_shard("rating21", runtime.out_dir(), cache_dir, h, payload)
            sharded[h] = payload
    return [(h, sharded[h]) for h in hashes if h in sharded]


def player_card(steamid: str) -> dict | None:
    """Round-weighted Rating 2.1 / 2.0 / KAST21 / saves for one player.

    Never raises (fail-soft): the U1 card must never 500 the career page."""
    try:
        num21 = num20 = den = kast = saves = 0
        for _h, payload in shards():
            p = payload["players"].get(steamid)
            n = payload["rounds"]
            if p is None or n <= 0:
                continue
            num21 += p["r21"] * n
            num20 += p["r20"] * n
            kast += p["kast"] * n
            saves += p["saves"]
            den += n
        if den == 0:
            return None
        return {
            "rating21": round(num21 / den, 2),
            "rating20": round(num20 / den, 2),
            "kast21": round(kast / den),
            "save_rounds": saves,
        }
    except Exception:  # noqa: BLE001 — U1 card must never 500 the page
        return None
