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
