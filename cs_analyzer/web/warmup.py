"""Background cold-start prewarm (Phase L0, T1 snapshot-aware).

The first dashboard hit used to pay the entire whole-library scan
synchronously (~70s white screen: aggregate ~17s + highlight feed ~50s).
The server now starts listening immediately; a daemon thread prewarms every
cross-demo memo in sequence, and the dashboard renders a skeleton that
long-polls /api/warmup.json until the data is ready.

Phase T1: the prewarm first tries to seed every memo from the disk
snapshots (web/snapshots.py). When the library fingerprint matches, the
expensive steps are skipped entirely and "ready" lands in well under a
second; only the missing memos are actually recomputed. After a real
rebuild the snapshots are re-written so the NEXT restart hits them.

Two warm-up waves: the dashboard-critical five memos must be ready before
"ready" flips true; the专题页 reports (map/lineups/style-map) fill in the
background right after, so the专题 pages never gate the dashboard.

Started from the FastAPI lifespan (real uvicorn runs it; a bare TestClient
does not, so tests stay deterministic). After an invalidate (new demo
parsed) memos simply recompute lazily on request — start_once never re-runs.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_thread: threading.Thread | None = None
_state: dict = {
    "phase": "idle",  # idle -> snapshots -> aggregate -> ... -> wave2 -> done | error
    "ready": False,
    "error": "",
    "t_started": 0.0,
    "t_done": 0.0,
    # T1 diagnostics for the /system performance panel
    "snapshot_hits": [],   # memo names seeded from disk
    "snapshot_saved": [],  # memo names persisted after the rebuild
}

#: /api/warmup.json?wait=1 long-poll ceiling per request (the dashboard JS
#: re-polls until ready, so the ceiling only bounds a single request).
POLL_WAIT_S = 20.0


def status() -> dict:
    return dict(_state)


def start_once() -> None:
    """Spawn the prewarm thread; at most once per process (idempotent)."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        if _state.get("done_once"):
            return
        _thread = threading.Thread(target=_run, name="csa-warmup", daemon=True)
        _thread.start()


def kick() -> None:
    """Re-prewarm after an invalidate (Phase S).

    start_once covers only the process-cold path; after an upload/sweep
    invalidates every memo, the dashboard used to rebuild ~70s of aggregate
    synchronously inside the first request (warm["ready"] stayed True).
    kick() resets the readiness flags and spawns a fresh prewarm thread —
    the skeleton/long-poll path covers the "cold again" state too. Safe to
    call from any thread, any number of times.
    """
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return  # already prewarming
        _state.update(phase="idle", ready=False, error="", t_done=0.0,
                      snapshot_hits=[], snapshot_saved=[])
        _state.pop("done_once", None)
        _thread = threading.Thread(target=_run, name="csa-warmup", daemon=True)
        _thread.start()


def wait_until_ready(timeout: float = POLL_WAIT_S) -> dict:
    """Long-poll: block until warm / failed / timeout, then return status.

    Returns immediately when no prewarm thread exists (idle — nothing will
    ever set ready; the caller's lazy path applies instead).
    """
    with _lock:
        alive = _thread is not None and _thread.is_alive()
    if not alive:
        return status()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _state["ready"] or _state["phase"] == "error":
            break
        time.sleep(0.25)
    return status()


def reset_for_tests() -> None:
    """Forget thread + state so a test can exercise start_once() itself."""
    global _thread
    with _lock:
        _thread = None
        _state.update(phase="idle", ready=False, error="", t_started=0.0, t_done=0.0,
                      snapshot_hits=[], snapshot_saved=[])
        _state.pop("done_once", None)


def _run() -> None:
    with _lock:
        if _state["phase"] not in ("idle", "error"):
            return  # another thread is already running (or already done)
        _state.update(phase="snapshots", ready=False, error="",
                      t_started=time.time(), t_done=0.0,
                      snapshot_hits=[], snapshot_saved=[])
    t0 = time.perf_counter()
    try:
        # ---- T1: try to seed everything from disk snapshots ----
        hits: list[str] = []
        try:
            from cs_analyzer.web import runtime, snapshots

            hits = snapshots.restore_all(runtime.out_dir(), runtime.cache().cache_dir)
        except Exception:  # noqa: BLE001 — snapshot IO must never kill warmup
            logger.exception("snapshot restore pass failed — full rebuild")
        with _lock:
            _state["snapshot_hits"] = hits
        logger.info("warmup: %d/%d memo(s) restored from snapshots",
                    len(hits), len(snapshots.SNAPSHOT_NAMES) if hits else 0)

        # ---- wave 1: dashboard-critical memos (skip the ones restored) ----
        for step_name, snap_name, step in (
            ("aggregate", "aggregate", _step_aggregate),
            ("highlights", "feed", _step_highlights),
            ("teamplay", "teamplay", _step_teamplay),
            ("utilitylab", "utilitylab", _step_utilitylab),
            ("funlab", "funlab_scan", _step_funlab),
        ):
            if snap_name in hits:
                continue  # snapshot already seeded this memo
            with _lock:
                _state["phase"] = step_name
            step()

        with _lock:
            _state.update(phase="done", ready=True, done_once=True,
                          t_done=time.time())
        logger.info("warmup done in %.1fs (%d snapshot hits)",
                    time.perf_counter() - t0, len(hits))

        # ---- T1: persist what we have so the NEXT restart hits ----
        # Only after a real rebuild: when every memo was restored the files
        # are already current. Run after ready=True — the dashboard must not
        # wait on disk IO.
        try:
            from cs_analyzer.web import runtime, snapshots

            saved = snapshots.save_all(runtime.out_dir(), runtime.cache().cache_dir)
            with _lock:
                _state["snapshot_saved"] = sorted(n for n, ok in saved.items() if ok)
        except Exception:  # noqa: BLE001
            logger.exception("snapshot save pass failed (fail-soft)")

        # ---- wave 2:专题页 memos (no dashboard gate; restored instantly when
        # their snapshots exist, recomputed here otherwise) ----
        with _lock:
            _state["phase"] = "wave2"
        for step_name, step in (
            ("map", _step_map),
            ("lineups", _step_lineups),
            ("stylemap", _step_stylemap),
        ):
            with _lock:
                _state["phase"] = f"wave2:{step_name}"
            try:
                step()
            except Exception:  # noqa: BLE001 — wave2 failures are not fatal
                logger.exception("warmup wave2 step %s failed", step_name)
        with _lock:
            _state["phase"] = "done"

        # second save: wave 2 just materialized map/lineups/style-map, so the
        # NEXT restart restores those too (no ~85s wave2 scan on a warm boot)
        try:
            from cs_analyzer.web import runtime, snapshots

            saved = snapshots.save_all(runtime.out_dir(), runtime.cache().cache_dir)
            with _lock:
                _state["snapshot_saved"] = sorted(n for n, ok in saved.items() if ok)
        except Exception:  # noqa: BLE001
            logger.exception("snapshot wave2 save pass failed (fail-soft)")
    except Exception:  # noqa: BLE001 — pages still work via lazy memos
        logger.exception("warmup failed")
        with _lock:
            _state.update(phase="error", error=traceback.format_exc(limit=3))


def _step_aggregate() -> None:
    from cs_analyzer.web import aggregation

    aggregation.aggregated()


def _step_highlights() -> None:
    from cs_analyzer.web import feed_data

    feed_data.all_highlights()


def _step_teamplay() -> None:
    from cs_analyzer.web import teamplay_data

    teamplay_data.teamplay_report()


def _step_utilitylab() -> None:
    from cs_analyzer.web import utilitylab_data

    utilitylab_data.utilitylab_report()


def _step_funlab() -> None:
    from cs_analyzer.web import funlab_data

    funlab_data.funlab_report()


def _step_map() -> None:
    from cs_analyzer.web import mapdata

    mapdata.map_report()


def _step_lineups() -> None:
    from cs_analyzer.web import lineups_data

    lineups_data.lineups_report()


def _step_stylemap() -> None:
    from cs_analyzer.web import style_map

    style_map.style_map_report()
