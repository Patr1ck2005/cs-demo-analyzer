"""Demo store: index parsed demos from the cache for the web UI.

Scans `.cache/*/model.json` into a searchable index and loads ParsedDemo
objects on demand. The cache is content-addressed (demo_hash -> dir); the
`demo_path` inside each model.json maps back to the original .dem file.
"""
from __future__ import annotations

import json
from pathlib import Path

from cs_analyzer.cache import DemoCache
from cs_analyzer.model.parsed_demo import ParsedDemo

CACHE_DIR = Path(".cache")
DEMOS_DIR = Path("demos")


def _load_model(demo_dir: Path) -> dict | None:
    model_path = demo_dir / "model.json"
    if not model_path.exists():
        return None
    try:
        return json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_demos(cache_dir: Path = CACHE_DIR) -> list[dict]:
    """Index entries for every cached demo, sorted by filename."""
    entries: list[dict] = []
    for demo_dir in sorted(cache_dir.glob("*")):
        if not demo_dir.is_dir():
            continue
        model = _load_model(demo_dir)
        if model is None:
            continue
        meta = model.get("metadata", {})
        players = model.get("players", [])
        rounds = model.get("rounds", [])
        path = meta.get("demo_path", "")
        entries.append(
            {
                "demo_hash": meta.get("demo_hash", demo_dir.name),
                "filename": Path(path).name if path else demo_dir.name,
                "map_name": meta.get("map_name", "?"),
                "provider": meta.get("provider", "?"),
                "demo_path": path,
                "num_rounds": len([r for r in rounds if not r.get("is_warmup")]),
                "players": players,
            }
        )
    entries.sort(key=lambda e: e["filename"])
    return entries


def load_demo(demo_hash: str, cache_dir: Path = CACHE_DIR) -> ParsedDemo | None:
    """Load a ParsedDemo from cache by hash, or None."""
    cache = DemoCache(cache_dir)
    return cache.load(demo_hash)


def player_lookup(cache_dir: Path = CACHE_DIR) -> dict[str, list[dict]]:
    """steamid -> [{demo_filename, name, replayable? via ticks?}] across demos."""
    from cs_analyzer.coverage import scan_demos

    out: dict[str, list[dict]] = {}
    paths = sorted(DEMOS_DIR.glob("*.dem")) if DEMOS_DIR.is_dir() else []
    if not paths:
        return out
    for cov in scan_demos(paths, cache=DemoCache(cache_dir)):
        for p in cov.players:
            out.setdefault(p.steamid, []).append(
                {
                    "demo_filename": Path(cov.path).name,
                    "demo_hash": cov.demo_hash,
                    "name": p.name,
                    "replayable": p.replayable,
                    "team": p.team_label,
                }
            )
    return out
