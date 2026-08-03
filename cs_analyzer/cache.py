"""Content-addressed cache for parsed demos.

Cache layout under {cache_dir}/{demo_hash}/:
    model.json              - DemoData (metadata, players, rounds)
    ticks.parquet           - per-tick player state
    events/{type}.parquet   - one parquet per event type
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.model.io import load_parsed_demo, save_parsed_demo

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 65536


class DemoCache:
    """Hash-keyed cache for ParsedDemo instances."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)

    @staticmethod
    def hash_demo(dem_path: Path) -> str:
        """SHA256 of the .dem file content."""
        h = hashlib.sha256()
        with open(dem_path, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
                h.update(chunk)
        return h.hexdigest()

    def path_for(self, demo_hash: str) -> Path:
        return self.cache_dir / demo_hash

    def exists(self, demo_hash: str) -> bool:
        return (self.path_for(demo_hash) / "model.json").exists()

    def load(self, demo_hash: str) -> ParsedDemo | None:
        """Load a cached demo, or None if not present / corrupted."""
        if not self.exists(demo_hash):
            return None
        try:
            return load_parsed_demo(self.path_for(demo_hash))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache load failed for %s: %s", demo_hash, exc)
            return None

    def save(self, demo_hash: str, demo: ParsedDemo) -> None:
        """Persist a parsed demo to cache."""
        save_parsed_demo(demo, self.path_for(demo_hash))
