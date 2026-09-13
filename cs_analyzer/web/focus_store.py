"""Focus store (复盘教练线 M3): one active focus per player, history kept.

Local-first persistence at ``output/web/focus.json`` (favorites_store
pattern: whole-document read/write under a lock; a corrupt or missing file
degrades to an empty doc, never a 500; atomic tmp+os.replace writes).

Single-active rule (M3 开工门槛, user-confirmed): a player has at most one
active focus — 真实练习一次练一样. Setting a new focus moves the previous
one to ``history`` with ``cleared_at``; explicit deletes do the same.

Document shape:
{
  "version": 1,
  "active": {"<steamid>": {"dim": "aim", "set_at": iso,
                           "base_hashes": ["<demo_hash>", ...]}},
  "history": [{"steamid": ..., "dim": ..., "set_at": ..., "cleared_at": ...}]
}

``base_hashes`` = the demo cache set at focus time — the BEFORE cohort.
The AFTER cohort is "demos not in base_hashes": wall-clock demo dates are
unreliable (WMPVP numeric filenames carry none — Y2), so the focus
boundary is the library snapshot taken when the focus was set.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_MAX_BASE = 500  # safety cap — the cache set is small, but bound the doc


def focus_path(out_dir: Path) -> Path:
    return Path(out_dir) / "web" / "focus.json"


def empty_doc() -> dict:
    return {"version": 1, "active": {}, "history": []}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_focus(out_dir: Path) -> dict:
    """Whole doc; missing/corrupt file -> empty doc (fail-soft)."""
    p = focus_path(out_dir)
    if not p.exists():
        return empty_doc()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("focus.json unreadable — starting from empty")
        return empty_doc()
    if not isinstance(doc, dict):
        return empty_doc()
    doc.setdefault("version", 1)
    doc.setdefault("active", {})
    doc.setdefault("history", [])
    return doc


def save_focus(out_dir: Path, doc: dict) -> None:
    """Atomic write (tmp + os.replace) — favorites_store rationale."""
    p = focus_path(out_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, p)


def set_focus(doc: dict, steamid: str, dim: str, base_hashes: list[str]) -> dict:
    """Activate (or replace) the focus for one player. Returns the entry.

    Caller holds no lock — pure helper. Replacing moves the old entry to
    history; base_hashes beyond _MAX_BASE are truncated (set order is
    stable enough for a cohort boundary).
    """
    prev = doc["active"].pop(steamid, None)
    if prev:
        doc["history"].append({**prev, "steamid": steamid,
                               "cleared_at": _now()})
    entry = {"dim": str(dim)[:20], "set_at": _now(),
             "base_hashes": list(dict.fromkeys(base_hashes))[:_MAX_BASE]}
    doc["active"][steamid] = entry
    return entry


def clear_focus(doc: dict, steamid: str) -> dict | None:
    """Deactivate the player's focus (moves it to history). Returns the
    cleared entry or None when there was nothing active."""
    prev = doc["active"].pop(steamid, None)
    if prev:
        doc["history"].append({**prev, "steamid": steamid,
                               "cleared_at": _now()})
    return prev
