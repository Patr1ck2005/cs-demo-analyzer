"""Per-demo dimension series for focus progress (复盘教练线 M3).

Reads the persistent per-demo layers DIRECTLY — per-demo shard files via
``snapshots.load_shards`` plus the funlab scan via the public
``snapshots.load_snapshot`` — so this module holds no merge code that
belongs to a producer and never edits a _SNAPSHOT_SOURCES member. Zero
ParsedDemo loads: missing shards simply don't contribute, and the funlab
snapshot returns None on a fingerprint mismatch (eco series -> honest
数据未就绪). Request-safe by construction.

Series metric per dim = the suggestion card's own evidence metric:
  duel -> duel win rate from the player's perspective (duelmo duels list;
          y = attacker won, so a victim "wins the duel" when y == 0)
  aim  -> stopped_fire_rate (aimsci samples[sid].stopped_shots / n_shots)
  loss -> untraded_rate (lossattr untraded_deaths / lost_deaths)
  eco  -> eco_hard_rate (funlab scan eco_frag_self / max(eco_rounds_played,1))
  utility -> unsupported: no per-demo layer exists for flash value, so it
          is excluded from FOCUSABLE_DIMS (the career button renders
          disabled with an honest tooltip).

Windows follow the C3 trend convention (MIN_PER_WINDOW = 3, honest grey
below) over the BEFORE/AFTER split defined by the focus's base_hashes
(the library snapshot at focus time — wall-clock demo dates are
unreliable, Y2).
"""
from __future__ import annotations

FOCUSABLE_DIMS: dict[str, str] = {
    "duel": "对枪", "aim": "枪法纪律", "loss": "失利模式", "eco": "eco 局表现",
}
DIM_UNITS: dict[str, str] = {
    "duel": "对枪胜率", "aim": "急停下开火率", "loss": "无贸易死占败死比",
    "eco": "神仙率（杀/eco回合）",
}
MIN_PER_WINDOW = 3


def dim_series(dim: str, sid: str, chron_hashes: list[str],
               out_dir, cache_dir) -> dict | None:
    """Per-demo values for one player+dim in chronological order.

    Returns {"points": [{demo_hash, seq, value, n}], "unit": str} or None
    when the dim's persistent layer is unavailable (eco on a fingerprint
    mismatch).
    """
    from cs_analyzer.web import snapshots

    if dim == "eco":
        return _eco_series(sid, chron_hashes, out_dir, cache_dir)

    family = {"duel": "duelmo", "aim": "aimsci", "loss": "lossattr"}.get(dim)
    if family is None:
        return None
    sharded, _missing = snapshots.load_shards(family, out_dir, cache_dir,
                                              chron_hashes)
    points: list[dict] = []
    for seq, h in enumerate(chron_hashes):
        entry = sharded.get(h)
        if entry is None:
            continue
        made = _point_for(dim, sid, entry)
        if made is not None:
            value, n = made
            points.append({"demo_hash": h, "seq": seq,
                           "value": round(value, 3), "n": n})
    if not points:
        return None
    return {"points": points, "unit": DIM_UNITS[dim]}


def _point_for(dim: str, sid: str, entry: dict) -> tuple[float, int] | None:
    """(value, n) for one demo entry, or None when the player is absent."""
    if dim == "duel":
        n = wins = 0
        for d in entry.get("duels", []):
            if d.get("att") == sid:
                n += 1
                wins += 1 if d.get("y") == 1 else 0
            elif d.get("vic") == sid:
                n += 1
                wins += 1 if d.get("y") == 0 else 0
        return (wins / n, n) if n else None
    if dim == "aim":
        samples = (entry.get("samples") or {}).get(sid) or {}
        stopped = samples.get("stopped_shots") or 0
        shots = next((p.get("n_shots") or 0
                      for p in entry.get("players", [])
                      if p.get("steamid") == sid), 0)
        return (stopped / shots, shots) if shots else None
    if dim == "loss":
        row = next((p for p in entry.get("players", [])
                    if p.get("steamid") == sid), None)
        if not row:
            return None
        lost = int(row.get("lost_deaths") or 0)
        untraded = int(row.get("untraded_deaths") or 0)
        return (untraded / lost, lost) if lost else None
    return None


def _eco_series(sid: str, chron_hashes: list[str],
                out_dir, cache_dir) -> dict | None:
    from cs_analyzer.web import snapshots

    fp = snapshots.library_fingerprint(cache_dir)
    payload = snapshots.load_snapshot("funlab_scan", fp, out_dir)
    if not payload:
        return None
    by_hash = {e.get("demo_hash"): e for e in payload.get("entries", [])}
    points: list[dict] = []
    for seq, h in enumerate(chron_hashes):
        entry = by_hash.get(h)
        if entry is None:
            continue
        row = next((p for p in entry.get("players", [])
                    if p.get("steamid") == sid), None)
        if not row:
            continue
        rounds = int(row.get("eco_rounds_played") or 0)
        frags = int(row.get("eco_frag_self") or 0)
        if rounds:
            points.append({"demo_hash": h, "seq": seq,
                           "value": round(frags / rounds, 3), "n": rounds})
    if not points:
        return None
    return {"points": points, "unit": DIM_UNITS["eco"]}


def progress(series: dict, base_hashes: list[str],
             min_per_window: int = MIN_PER_WINDOW) -> dict:
    """BEFORE (in base_hashes) vs AFTER (new demos) window means.

    A window with fewer than min_per_window points is gated to
    mean=None (honest grey, trend precedent); delta only when both means
    exist.
    """
    base = set(base_hashes)
    before = [p for p in series["points"] if p["demo_hash"] in base]
    after = [p for p in series["points"] if p["demo_hash"] not in base]

    def win(rows: list[dict]) -> dict:
        n = len(rows)
        return {"n": n,
                "mean": (round(sum(r["value"] for r in rows) / n, 3)
                         if n >= min_per_window else None)}

    w_before, w_after = win(before), win(after)
    delta = (round(w_after["mean"] - w_before["mean"], 3)
             if w_before["mean"] is not None and w_after["mean"] is not None
             else None)
    return {"before": w_before, "after": w_after, "delta": delta,
            "points": series["points"], "unit": series["unit"],
            "min_per_window": min_per_window}
