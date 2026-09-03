"""Whole-library scan helpers (Phase L0).

Every cross-demo report (aggregate, dashboard highlight feed, teamplay, the
Phase L utility/map/lineup pages) walks the entire parse cache. Loading a
demo — parquet read + pydantic validation — dominates the cost (~0.7s/demo)
and releases the GIL inside pyarrow, so a small thread pool gives a real
speedup over the old serial glob loops.

Thread-safety notes:
- DemoCache is stateless (just a path); concurrent load() calls read
  separate files.
- AnalysisRunner is safe to share: modules are instantiated per run and
  every run() gets its own AnalysisContext; config is read-only.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, TypeVar

from cs_analyzer.cache import DemoCache
from cs_analyzer.model.parsed_demo import ParsedDemo

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Parallel workers for whole-library scans. 4 keeps disk contention sane
#: while still overlapping the parquet reads.
DEFAULT_WORKERS = 4


def cached_demo_hashes(cache_dir: Path) -> list[str]:
    """Parse-cache subdirectory names (demo hashes), sorted for determinism."""
    return sorted(d.name for d in Path(cache_dir).glob("*") if d.is_dir())


def demo_filenames(cache_dir: Path) -> dict[str, str]:
    """{demo_hash: basename} from each cache dir's model.json.

    Cheap on purpose: model.json is a small JSON blob — no parquet load.
    Lets prefix-based filters (teamplay's g161- 5E marker) pick their demo
    subset before paying for full loads.
    """
    import json

    out: dict[str, str] = {}
    for demo_hash in cached_demo_hashes(cache_dir):
        p = Path(cache_dir) / demo_hash / "model.json"
        try:
            md = json.loads(p.read_text(encoding="utf-8")).get("metadata", {})
        except (OSError, ValueError):
            continue
        out[demo_hash] = Path(str(md.get("demo_path", ""))).name
    return out


def load_all_demos(cache_dir: Path, *, workers: int = DEFAULT_WORKERS) -> list[ParsedDemo]:
    """Load every cached demo in parallel, sorted by demo hash.

    Stale/corrupt entries (cache.load -> None) are skipped, mirroring the
    serial glob loops this replaces.
    """
    return scan_demos(cache_dir, lambda demo: demo, workers=workers)


def scan_demos(
    cache_dir: Path,
    fn: Callable[[ParsedDemo], T],
    *,
    workers: int = DEFAULT_WORKERS,
    strict: bool = False,
) -> list[T]:
    """Load every cached demo and apply ``fn`` concurrently (one per demo).

    Results keep sorted-hash order so downstream merges stay deterministic.
    Unloadable demos (stale/corrupt cache) are dropped, matching the serial
    loops this replaces. ``fn`` exceptions are logged and yield a skipped
    slot (fail-soft — one broken demo must not kill a whole-library report);
    pass ``strict=True`` to propagate instead. ``fn`` returning ``None`` also
    marks the slot skipped.
    """
    cache = DemoCache(cache_dir)
    hashes = cached_demo_hashes(cache_dir)

    def work(demo_hash: str) -> T | None:
        demo = cache.load(demo_hash)
        if demo is None:
            return None
        return fn(demo)

    def safe(demo_hash: str) -> T | None:
        try:
            return work(demo_hash)
        except Exception:  # noqa: BLE001
            logger.exception("library scan failed for %s", demo_hash[:12])
            return None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        mapper = ex.map(work if strict else safe, hashes)
        results = list(mapper)
    return [r for r in results if r is not None]
