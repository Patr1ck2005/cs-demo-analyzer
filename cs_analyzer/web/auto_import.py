"""demos/ 监视自动入库 (复盘提升包 B2, 2026-09-10).

A daemon thread polls demos/ (root level only — demos/pro is the separate
D2b pro-library flow and is NOT watched) every POLL_SEC. A new .dem is
submitted to the existing task queue (app._parse_job, same single-flight
parse lock as upload/一键入库) once it is stable: unchanged size+mtime
across two consecutive polls AND at least MIN_AGE_S old — a partially
copied file must never enter the queue. invalidate_aggregate() runs once
per submitted batch (same contract as /system/import).

Failure policy (口径): a file whose parse job ends in "error" is recorded
(persisted to the state file — survives restarts, R3-F2) and NEVER retried
(dead-loop guard); failed files stay visible in /system's 自动入库 status
line until removed manually. State (enabled flag + failed hashes) persists
to output/web/auto_import_state.json; default is ON.

Everything here reuses existing building blocks — no new parse path.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEMOS_DIR = Path("demos")
STATE_PATH = Path("output/web/auto_import_state.json")
POLL_SEC = 30.0
MIN_AGE_S = 20.0

_lock = threading.Lock()
_enabled = True
_started = False
_last_sig: dict[str, tuple[int, int]] = {}  # filename -> (size, mtime int)
_failed: set[str] = set()                   # content hashes that failed (no retry)
_failed_names: dict[str, str] = {}          # content hash -> filename (display)
_FAILED_CAP = 200                           # persisted-failure list cap (oldest dropped)
_pending: dict[str, str] = {}               # content hash -> job id
_last_action = "尚未扫描"


def _load_state() -> None:
    global _enabled
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        _enabled = bool(data.get("enabled", True))
        for entry in data.get("failed", []):
            try:
                h, name = entry
            except (TypeError, ValueError):
                continue
            _failed.add(str(h))
            _failed_names[str(h)] = str(name)
    except (OSError, ValueError):
        pass  # missing/corrupt state → default ON, empty failure memory


def _save_state() -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        failed = [[h, _failed_names.get(h, "")] for h in list(_failed)[- _FAILED_CAP:]]
        STATE_PATH.write_text(
            json.dumps({"enabled": _enabled, "failed": failed}, ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        logger.warning("auto_import: cannot persist state", exc_info=True)


def set_enabled(value: bool) -> None:
    global _enabled
    with _lock:
        _enabled = bool(value)
        _save_state()
        _set_action("自动入库已开启" if _enabled else "自动入库已关闭")


def status() -> dict:
    with _lock:
        return {
            "enabled": _enabled,
            "watched": str(DEMOS_DIR),
            "poll_sec": POLL_SEC,
            "last_action": _last_action,
            "failed_n": len(_failed),
            "failed": [{"hash": h[:12], "name": _failed_names.get(h, "")}
                       for h in list(_failed)[-10:]],
        }


def _set_action(msg: str) -> None:
    global _last_action
    _last_action = f"{time.strftime('%H:%M:%S')} {msg}"


def start_once() -> None:
    """Idempotent daemon start (lifespan calls this after warmup.start_once)."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
        _load_state()
    t = threading.Thread(target=_loop, name="csa-auto-import", daemon=True)
    t.start()
    logger.info("auto_import: watching %s every %.0fs (enabled=%s)",
                DEMOS_DIR, POLL_SEC, _enabled)


def _poll_once() -> int:
    """One scan → submit stable, unseen, unparsed .dem files. Returns count."""
    from cs_analyzer.cache import DemoCache
    from cs_analyzer.config import load_settings

    if not DEMOS_DIR.is_dir():
        return 0
    cache = DemoCache(load_settings(None).cache_dir)
    now = time.time()
    submit: list[Path] = []
    seen_names: set[str] = set()
    for dem in sorted(DEMOS_DIR.glob("*.dem")):
        seen_names.add(dem.name)
        try:
            st = dem.stat()
        except OSError:
            continue
        sig = (st.st_size, int(st.st_mtime))
        prev = _last_sig.get(dem.name)
        _last_sig[dem.name] = sig
        if prev != sig or now - st.st_mtime < MIN_AGE_S:
            continue  # still copying / just landed — wait for stability
        try:
            demo_hash = DemoCache.hash_demo(dem)
        except OSError:
            continue
        if demo_hash in _failed or demo_hash in _pending:
            continue
        if cache.exists(demo_hash):
            continue
        submit.append(dem)
        _pending[demo_hash] = ""  # job id filled below
    for name in [n for n in _last_sig if n not in seen_names]:
        _last_sig.pop(name, None)

    if not submit:
        # reap finished jobs so failures land in _failed and successes unblock
        _reap_jobs()
        return 0

    from cs_analyzer.web.aggregation import invalidate_aggregate
    from cs_analyzer.web.app import _parse_job  # lazy: app imports this module
    from cs_analyzer.web import tasks

    for dem in submit:
        demo_hash = DemoCache.hash_demo(dem)
        job_id = tasks.tasks.submit(_parse_job, label=f"[自动] {dem.name}",
                                    path=str(dem), dedupe_key=str(dem))
        _pending[demo_hash] = job_id
    invalidate_aggregate()  # once per batch (same as /system/import)
    _set_action(f"自动入库 {len(submit)} 个新 demo："
                + "、".join(d.name for d in submit[:3])
                + ("…" if len(submit) > 3 else ""))
    logger.info("auto_import: submitted %d new demo(s)", len(submit))
    return len(submit)


def _reap_jobs() -> None:
    """Check pending parse jobs; failed ones enter _failed (never retried)."""
    from cs_analyzer.web import tasks

    for demo_hash, job_id in list(_pending.items()):
        if not job_id:
            continue
        job = tasks.tasks.get_status(job_id)
        if job is None:
            _pending.pop(demo_hash, None)  # evicted (F11 cap) — treat as done
            continue
        if job.status == "error":
            _failed.add(demo_hash)
            _failed_names[demo_hash] = job.label.replace("[自动] ", "")
            _pending.pop(demo_hash, None)
            _set_action(f"自动入库失败（不再重试）：{job.label}")
            logger.warning("auto_import: parse failed for %s — no retry", job.label)
            with _lock:
                _save_state()
        elif job.status == "done":
            _pending.pop(demo_hash, None)


def _loop() -> None:
    while True:
        time.sleep(POLL_SEC)
        try:
            with _lock:
                enabled = _enabled
            if enabled:
                if _poll_once() == 0:
                    _reap_jobs()
        except Exception:  # noqa: BLE001 — the watcher must never die
            logger.exception("auto_import: poll cycle failed")
