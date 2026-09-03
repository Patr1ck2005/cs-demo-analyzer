"""Favorites / tags / notes store (Phase L1).

Local-first persistence at ``output/favorites.json``, same pattern as the
ui-prefs store (whole-document read/merge/write under a lock; a corrupt or
missing file degrades to an empty doc, never a 500).

Document shape (entries are denormalized on write — the starring page knows
the display name, so the favorites page never needs the heavy aggregate):
{
  "matches": {"<demo_hash>": {"starred": true, "tags": [...], "note": "...",
                              "saved_at": iso, "meta": {...}}},
  "players": {"<steamid>":  {...}}
}
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def favorites_path(out_dir: Path) -> Path:
    return Path(out_dir) / "favorites.json"


def empty_doc() -> dict:
    return {"matches": {}, "players": {}}


def load_favorites(out_dir: Path) -> dict:
    """Whole doc; missing/corrupt file -> empty doc (fail-soft)."""
    p = favorites_path(out_dir)
    if not p.exists():
        return empty_doc()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("favorites.json unreadable — starting from empty")
        return empty_doc()
    if not isinstance(doc, dict):
        return empty_doc()
    doc.setdefault("matches", {})
    doc.setdefault("players", {})
    return doc


def save_favorites(out_dir: Path, doc: dict) -> None:
    p = favorites_path(out_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def apply_patch(doc: dict, scope: str, item_id: str, patch: dict, meta: dict | None = None) -> dict:
    """Merge ``patch`` into doc[scope][item_id], creating/updating as needed.

    Returns the updated entry. Caller holds no lock — this is a pure helper.
    """
    book = doc.setdefault("matches" if scope == "match" else "players", {})
    entry = book.setdefault(item_id, {"starred": False, "tags": [], "note": "",
                                      "saved_at": "", "meta": {}})
    if "starred" in patch:
        entry["starred"] = bool(patch["starred"])
    if "tags" in patch:
        tags = patch["tags"]
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        entry["tags"] = [str(t)[:40] for t in (tags or [])][:20]
    if "note" in patch:
        entry["note"] = str(patch["note"])[:2000]
    if meta:
        # denormalized display snapshot; only fills blanks unless starred flips on
        clean = {k: str(v)[:200] for k, v in meta.items() if v}
        entry.setdefault("meta", {}).update(clean)
    if patch:
        entry["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return entry
