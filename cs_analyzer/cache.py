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

# Bump this when parser logic changes (new fields, bug fixes) so cached
# parses produced by an older parser are invalidated.
PARSER_VERSION = "1.1.3"


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

    @staticmethod
    def _version_file(demo_dir: Path) -> Path:
        return demo_dir / "parser_version"

    def exists(self, demo_hash: str) -> bool:
        demo_dir = self.path_for(demo_hash)
        vfile = self._version_file(demo_dir)
        if not (demo_dir / "model.json").exists():
            return False
        # Treat caches without a matching parser_version as stale.
        try:
            return vfile.exists() and vfile.read_text(encoding="utf-8").strip() == PARSER_VERSION
        except OSError:
            return False

    def load(self, demo_hash: str) -> ParsedDemo | None:
        """Load a cached demo, or None if not present / corrupted / stale."""
        if not self.exists(demo_hash):
            return None
        try:
            return load_parsed_demo(self.path_for(demo_hash))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache load failed for %s: %s", demo_hash, exc)
            return None

    def save(self, demo_hash: str, demo: ParsedDemo) -> None:
        """Persist a parsed demo to cache."""
        demo_dir = self.path_for(demo_hash)
        save_parsed_demo(demo, demo_dir)
        self._version_file(demo_dir).write_text(PARSER_VERSION, encoding="utf-8")
