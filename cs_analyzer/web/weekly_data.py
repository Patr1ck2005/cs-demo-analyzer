"""周期报告 (复盘教练线 M4): windowed aggregate + focus digest.

The window boundary follows the M3 decision: wall-clock demo dates are
unreliable (WMPVP numeric filenames carry none — Y2), so the report covers
demos NOT in the last baseline (``output/web/weekly_state.json``, set via
POST /api/weekly/baseline) versus that baseline cohort. No baseline yet →
fallback split = the last 10 demos vs the 10 before them (C3 trend gates).

Request-safe: everything derives from the aggregate memo (snapshot-backed)
plus the focus store / persistent per-demo layers (M3). Nothing here scans.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

WINDOW_FALLBACK = 10
MIN_PER_WINDOW = 3

_lock = threading.Lock()


# ---- baseline state (focus_store pattern, smaller) ----

def state_path(out_dir: Path) -> Path:
    return Path(out_dir) / "web" / "weekly_state.json"


def load_state(out_dir: Path) -> dict:
    p = state_path(out_dir)
    if not p.exists():
        return {"version": 1, "generated_at": "", "base_hashes": []}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("weekly_state.json unreadable — starting empty")
        return {"version": 1, "generated_at": "", "base_hashes": []}
    if not isinstance(doc, dict):
        return {"version": 1, "generated_at": "", "base_hashes": []}
    doc.setdefault("base_hashes", [])
    return doc


def save_state(out_dir: Path, doc: dict) -> None:
    p = state_path(out_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, p)


def set_baseline(out_dir: Path, base_hashes: list[str]) -> dict:
    doc = {"version": 1,
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "base_hashes": list(dict.fromkeys(base_hashes))}
    with _lock:
        save_state(out_dir, doc)
    return doc


# ---- windows ----

def _mean(rows: list[dict], key: str) -> float | None:
    return round(sum(r[key] for r in rows) / len(rows), 3) if rows else None


def _window(rows: list[dict], min_n: int = MIN_PER_WINDOW) -> dict:
    return {"n": len(rows), "rating": _mean(rows, "Rating"),
            "adr": (round(_mean(rows, "ADR"), 1) if rows else None),
            "kast": (round(_mean(rows, "KAST"), 1) if rows else None),
            "gated": len(rows) < min_n}


def weekly_report(agg=None, out_dir=None, cache_dir=None) -> dict:
    from cs_analyzer.web.aggregation import aggregated

    agg = agg if agg is not None else aggregated()
    out_dir = Path(out_dir) if out_dir is not None else None
    demos = list(agg.demos)  # match_key sorted = chronological (C3)
    hashes = {d.demo_hash for d in demos}

    state = load_state(out_dir) if out_dir is not None else {
        "base_hashes": [], "generated_at": ""}
    base = [h for h in state.get("base_hashes", []) if h in hashes]
    has_baseline = bool(state.get("generated_at"))
    if base:
        before_demos = [d for d in demos if d.demo_hash in set(base)]
        after_demos = [d for d in demos if d.demo_hash not in set(base)]
        split_note = "基线 = 上次标记已读时的库"
    else:
        split = max(0, len(demos) - WINDOW_FALLBACK)
        before_demos = demos[max(0, split - WINDOW_FALLBACK):split]
        after_demos = demos[split:]
        split_note = f"无基线 — 回退窗口：最近 {WINDOW_FALLBACK} 场 vs 再前 {WINDOW_FALLBACK} 场"

    before_set = {d.demo_hash for d in before_demos}
    after_set = {d.demo_hash for d in after_demos}

    players = []
    for p in agg.players:
        before = [e for e in p.demos if e["demo_hash"] in before_set]
        after = [e for e in p.demos if e["demo_hash"] in after_set]
        if not before and not after:
            continue
        w_before, w_after = _window(before), _window(after)
        row = {"steamid": p.steamid, "name": p.name,
               "n_before": w_before["n"], "n_after": w_after["n"],
               "gated": w_before["gated"] or w_after["gated"],
               "before": w_before, "after": w_after}
        row["d_rating"] = (round(w_after["rating"] - w_before["rating"], 3)
                           if not row["gated"] else None)
        players.append(row)
    players.sort(key=lambda r: (r["gated"], -(r["d_rating"] or 0)))

    matches = [{"demo_hash": d.demo_hash, "filename": d.filename,
                "map_name": d.map_name,
                "t_score": d.t_score, "ct_score": d.ct_score}
               for d in after_demos]
    t_wins = sum(1 for d in after_demos if d.t_score > d.ct_score)
    ct_wins = sum(1 for d in after_demos if d.ct_score > d.t_score)

    focus_rows = _focus_digest(agg, out_dir, cache_dir)
    return {
        "has_baseline": has_baseline,
        "generated_at": state.get("generated_at", ""),
        "split_note": split_note,
        "matches": matches,
        "n_new": len(matches),
        "t_wins": t_wins, "ct_wins": ct_wins,
        "players": players,
        "focus_rows": focus_rows,
        "min_per_window": MIN_PER_WINDOW,
    }


def _focus_digest(agg, out_dir, cache_dir) -> list[dict]:
    """Active focuses with their M3 progress + current weak items."""
    if out_dir is None:
        return []
    from cs_analyzer.web import focus_data, focus_store
    from cs_analyzer.web.conclusions import player_profile

    names = {p.steamid: p.name for p in agg.players}
    chron = [d.demo_hash for d in agg.demos]
    fdoc = focus_store.load_focus(out_dir)
    rows = []
    for sid, active in fdoc["active"].items():
        dim = active.get("dim")
        if dim not in focus_data.FOCUSABLE_DIMS:
            continue
        entry = {"steamid": sid, "name": names.get(sid, sid),
                 "dim": dim, "dim_label": focus_data.FOCUSABLE_DIMS[dim],
                 "set_at": active.get("set_at", "")}
        series = focus_data.dim_series(dim, sid, chron, out_dir, cache_dir)
        if series is not None:
            prog = focus_data.progress(series, active.get("base_hashes", []))
            entry.update({"before": prog["before"], "after": prog["after"],
                          "delta": prog["delta"], "unit": prog["unit"]})
        prof = player_profile(sid, name=names.get(sid))
        entry["weak_items"] = prof["weak_items"][:2]
        rows.append(entry)
    return rows
