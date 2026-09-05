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
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

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


def scan_demos_proc(cache_dir: Path,
                    worker: Callable[[tuple[str, str]], T | None],
                    *,
                    workers: int = DEFAULT_WORKERS,
                    fallback_fn: Callable[[ParsedDemo], T | None] | None = None) -> list[T]:
    """Process-pool sibling of scan_demos (Phase T2, bench ADOPT +53.5%).

    ``worker`` must be a MODULE-LEVEL function taking ``(cache_dir: str,
    demo_hash: str)`` — Windows spawn pickles it by qualified name, closures
    are unusable. Workers load AND analyze inside the child and return small
    payloads only: a ParsedDemo cannot cross the boundary (pickling ~30MB of
    ticks per demo OOMs the result queue — measured 2026-09-05). Results
    keep sorted-hash order like the thread path; per-demo failures are
    fail-soft when the worker swallows them (web workers do).

    ``fallback_fn`` (a demo-level thread-mode fn) is the degradation path:
    a hard child death (Rust panic → BrokenProcessPool, spawn restrictions)
    reruns the whole scan on the thread pool instead of failing the report.
    """
    from concurrent.futures import ProcessPoolExecutor

    hashes = cached_demo_hashes(cache_dir)
    if not hashes:
        return []
    args = [(str(cache_dir), h) for h in hashes]
    try:
        with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
            results = list(ex.map(worker, args))
    except Exception:  # noqa: BLE001 — degrade instead of failing the report
        logger.exception("process scan failed — falling back to thread pool")
        if fallback_fn is None:
            raise
        return scan_demos(cache_dir, fallback_fn, workers=workers)
    return [r for r in results if r is not None]


def scan_hashes(cache_dir: Path, hashes: list[str],
                fn: Callable[[ParsedDemo], T]) -> list[tuple[str, T]]:
    """Thread scan of an EXPLICIT hash subset (Phase T3 增量重算: only the
    demos missing a shard get loaded). Returns [(demo_hash, fn(demo))] in
    the given order; unloadable demos are dropped, per-demo exceptions are
    logged and dropped (fail-soft, same as scan_demos)."""
    cache = DemoCache(cache_dir)

    def safe(h: str) -> tuple[str, T] | None:
        try:
            demo = cache.load(h)
            if demo is None:
                return None
            return h, fn(demo)
        except Exception:  # noqa: BLE001
            logger.exception("subset scan failed for %s", h[:12])
            return None

    with ThreadPoolExecutor(max_workers=max(1, DEFAULT_WORKERS)) as ex:
        return [r for r in ex.map(safe, hashes) if r is not None]


def scan_hashes_proc(cache_dir: Path, hashes: list[str],
                     worker: Callable[[tuple[str, str]], T | None],
                     *,
                     fallback_fn: Callable[[ParsedDemo], T] | None = None,
                     workers: int = DEFAULT_WORKERS) -> list[tuple[str, T]]:
    """Process scan of an EXPLICIT hash subset (T3). Same contract as
    scan_demos_proc but only for the listed hashes, and results carry their
    demo_hash (shard association must survive)."""
    from concurrent.futures import ProcessPoolExecutor

    if not hashes:
        return []
    try:
        with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
            results = list(ex.map(worker, [(str(cache_dir), h) for h in hashes]))
    except Exception:  # noqa: BLE001 — degrade instead of failing the report
        logger.exception("process subset scan failed — falling back to threads")
        if fallback_fn is None:
            raise
        return scan_hashes(cache_dir, hashes, fallback_fn)
    return [(h, r) for h, r in zip(hashes, results, strict=True) if r is not None]
