"""复盘提升包 B2: demos/ watcher (auto_import) 单测.

The watcher is fully deterministic here: DEMOS_DIR/STATE_PATH are pointed
at tmp dirs, the task manager is a stub, and app._parse_job is patched at
the module attribute the lazy import resolves against.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from cs_analyzer.web import auto_import
from cs_analyzer.web import app as app_module


class _StubJobs:
    """Deterministic TaskManager stand-in."""

    def __init__(self) -> None:
        self.submitted: list[str] = []
        self.status = "error"  # what get_status reports for every job

    def submit(self, fn, *, label="", **kwargs):
        self.submitted.append(kwargs.get("path", ""))
        return f"job{len(self.submitted)}"

    def get_status(self, job_id: str):
        return SimpleNamespace(status=self.status, label="stub.dem")


@pytest.fixture()
def watcher(tmp_path, monkeypatch):
    demo_dir = tmp_path / "demos"
    demo_dir.mkdir()
    monkeypatch.setattr(auto_import, "DEMOS_DIR", demo_dir)
    monkeypatch.setattr(auto_import, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(auto_import, "_failed", set())
    monkeypatch.setattr(auto_import, "_pending", {})
    monkeypatch.setattr(auto_import, "_last_sig", {})
    stub = _StubJobs()
    import cs_analyzer.web.tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "tasks", stub)
    monkeypatch.setattr(app_module, "_parse_job", lambda path: "h" * 64)
    import cs_analyzer.web.aggregation as agg_mod

    monkeypatch.setattr(agg_mod, "invalidate_aggregate", lambda: None)
    return SimpleNamespace(dir=demo_dir, stub=stub)


def _drop_demo(demo_dir, name="new.dem", size=128, old=True):
    p = demo_dir / name
    p.write_bytes(b"CSDEMO-fake" * (size // 11))
    if old:  # backdate so the MIN_AGE_S gate passes immediately
    # (os.utime to 10 minutes ago)
        import os
        import time

        old_t = time.time() - 600
        os.utime(p, (old_t, old_t))
    return p


def test_first_poll_only_records_signature(watcher):
    _drop_demo(watcher.dir)
    assert auto_import._poll_once() == 0  # unstable on first sight
    assert auto_import._poll_once() == 1  # stable + old → submitted


def test_no_resubmit_while_pending(watcher):
    _drop_demo(watcher.dir)
    auto_import._poll_once()
    auto_import._poll_once()
    assert len(watcher.stub.submitted) == 1
    assert auto_import._poll_once() == 0
    assert len(watcher.stub.submitted) == 1  # pending job blocks resubmit


def test_failed_parse_never_retried(watcher):
    _drop_demo(watcher.dir)
    auto_import._poll_once()
    auto_import._poll_once()
    assert len(watcher.stub.submitted) == 1
    watcher.stub.status = "error"
    auto_import._reap_jobs()
    assert len(auto_import._failed) == 1
    watcher.stub.status = "error"
    auto_import._pending.clear()
    assert auto_import._poll_once() == 0  # failed hash is not resubmitted
    assert len(watcher.stub.submitted) == 1


def test_cached_file_skipped(watcher, monkeypatch):
    from cs_analyzer.cache import DemoCache

    _drop_demo(watcher.dir)
    monkeypatch.setattr(DemoCache, "exists", lambda self, h: True)
    auto_import._poll_once()
    assert auto_import._poll_once() == 0
    assert watcher.stub.submitted == []


def test_toggle_persists(watcher):
    auto_import.set_enabled(False)
    assert auto_import.status()["enabled"] is False
    import json

    assert json.loads(watcher.dir.parent.joinpath("state.json").read_text(
        encoding="utf-8"))["enabled"] is False
    auto_import.set_enabled(True)
    assert auto_import.status()["enabled"] is True


def test_auto_import_api_roundtrip(web_client):
    c, _, _ = web_client
    r = c.get("/api/system/auto-import.json")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["enabled"], bool)
    r2 = c.post("/api/system/auto-import.json", json={"enabled": False})
    assert r2.status_code == 200
    assert r2.json()["enabled"] is False
    c.post("/api/system/auto-import.json", json={"enabled": True})
    assert c.get("/api/system/auto-import.json").json()["enabled"] is True


def test_system_page_has_auto_import_toggle(web_client):
    c, _, _ = web_client
    r = c.get("/system")
    assert r.status_code == 200
    assert "sys-auto-import" in r.text


@pytest.mark.parametrize("mtime_age_s", [5])
def test_fresh_file_waits_for_stability(watcher, mtime_age_s):
    import os
    import time

    p = _drop_demo(watcher.dir, old=False)
    fresh = time.time() - mtime_age_s
    os.utime(p, (fresh, fresh))
    auto_import._poll_once()
    auto_import._poll_once()
    assert watcher.stub.submitted == []  # MIN_AGE_S guard holds
