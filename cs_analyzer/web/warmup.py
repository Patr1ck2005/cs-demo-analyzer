"""Background cold-start prewarm (Phase L0).

The first dashboard hit used to pay the entire whole-library scan
synchronously (~70s white screen: aggregate ~17s + highlight feed ~50s).
The server now starts listening immediately; a daemon thread prewarms every
cross-demo memo in sequence, and the dashboard renders a skeleton that
long-polls /api/warmup.json until the data is ready.

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
    "phase": "idle",  # idle -> aggregate -> highlights -> teamplay -> done | error
    "ready": False,
    "error": "",
    "t_started": 0.0,
    "t_done": 0.0,
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
        _state.update(phase="idle", ready=False, error="", t_done=0.0)
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
        _state.update(phase="idle", ready=False, error="", t_started=0.0, t_done=0.0)
        _state.pop("done_once", None)


def _run() -> None:
    with _lock:
        if _state["phase"] not in ("idle", "error"):
            return  # another thread is already running (or already done)
        _state.update(phase="aggregate", ready=False, error="",
                      t_started=time.time(), t_done=0.0)
    t0 = time.perf_counter()
    try:
        for step_name, step in (
            ("aggregate", _step_aggregate),
            ("highlights", _step_highlights),
            ("teamplay", _step_teamplay),
            ("utilitylab", _step_utilitylab),
            ("funlab", _step_funlab),
        ):
            with _lock:
                _state["phase"] = step_name
            step()
        with _lock:
            _state.update(phase="done", ready=True, done_once=True,
                          t_done=time.time())
        logger.info("warmup done in %.1fs", time.perf_counter() - t0)
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
