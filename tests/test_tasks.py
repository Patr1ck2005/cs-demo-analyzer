"""Tests for the web platform's background task manager."""
from __future__ import annotations

import time

from cs_analyzer.web.tasks import TaskManager


def _wait(m, job_id, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = m.get_status(job_id)
        if st.status in ("done", "error"):
            return st
        time.sleep(0.01)
    return m.get_status(job_id)


def test_task_runs_and_reports_result() -> None:
    m = TaskManager(max_workers=1)
    job_id = m.submit(lambda: "ok42")
    st = _wait(m, job_id)
    assert st.status == "done"
    assert st.result == "ok42"
    assert st.progress == 1.0


def test_task_error_captured() -> None:
    m = TaskManager(max_workers=1)

    def boom():
        raise ValueError("boom")

    job_id = m.submit(boom)
    st = _wait(m, job_id)
    assert st.status == "error"
    assert "boom" in st.error


def test_unknown_job_is_none() -> None:
    m = TaskManager()
    assert m.get_status("nope") is None


def test_job_label_propagates() -> None:
    m = TaskManager(max_workers=1)
    job_id = m.submit(lambda: "ok", label="my_demo.dem")
    st = m.get_status(job_id)
    assert st.label == "my_demo.dem"
    assert st.as_dict()["label"] == "my_demo.dem"
    assert st.as_dict()["status"] in ("pending", "done")


def test_dedupe_key_collapses_pending_duplicates() -> None:
    """R3-F1: same dedupe_key while pending/running returns the existing id."""
    import threading

    m = TaskManager(max_workers=1)
    release = threading.Event()
    calls: list[str] = []

    def slow():
        calls.append("run")
        release.wait(timeout=2.0)
        return "ok"

    first = m.submit(slow, dedupe_key="demos/a.dem")
    second = m.submit(slow, dedupe_key="demos/a.dem")
    assert second == first  # collapsed, not enqueued
    release.set()
    assert _wait(m, first).status == "done"
    assert calls == ["run"]  # fn ran exactly once


def test_dedupe_key_released_after_finish() -> None:
    """A finished (done/error) job no longer blocks a same-key resubmit."""
    m = TaskManager(max_workers=1)

    def boom():
        raise ValueError("x")

    first = m.submit(boom, dedupe_key="demos/b.dem")
    _wait(m, first)
    second = m.submit(lambda: "ok", dedupe_key="demos/b.dem")
    assert second != first
    assert _wait(m, second).status == "done"


def test_no_dedupe_key_behavior_unchanged() -> None:
    """Regression lock: callers without dedupe_key enqueue independently."""
    m = TaskManager(max_workers=1)
    a = m.submit(lambda: 1)
    b = m.submit(lambda: 2)
    assert a != b
