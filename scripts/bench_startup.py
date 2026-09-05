# -*- coding: utf-8 -*-
"""Phase T1/T4 基准探针：冷启动三场景计时（uvicorn 真进程 + HTTP 轮询）。

场景：
  cold_snapshot   = 快照全命中重启（本基准的核心验收数字）
  recompute       = 快照作废后的全量重算（对照）
  incremental     = 新增 demo 后的增量重算（T3 后对照）

用法： python scripts/bench_startup.py [--wipe-snapshots] [--json out.json]
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SNAP_DIR = REPO / "output" / "web" / "snapshots"
PY = sys.executable
PORT = 8123  # dedicated bench port — never touch the dev server on 8000


def _wait_ready(timeout_s: float = 300.0) -> tuple[float, dict]:
    """(seconds_to_ready, final_status) from server start to warmup ready."""
    t0 = time.perf_counter()
    deadline = t0 + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{PORT}/api/warmup.json", timeout=5) as r:
                last = json.loads(r.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 — server not up yet
            time.sleep(0.5)
            continue
        if last.get("ready") or last.get("phase") == "error":
            return time.perf_counter() - t0, last
        time.sleep(0.5)
    return time.perf_counter() - t0, {"phase": "timeout", "detail": last}


def _start_server() -> subprocess.Popen:
    return subprocess.Popen(
        [PY, "-m", "uvicorn", "cs_analyzer.web.app:app", "--port", str(PORT),
         "--log-level", "warning"],
        cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_scene(label: str, wipe: bool = False) -> dict:
    if wipe and SNAP_DIR.exists():
        for p in SNAP_DIR.glob("*.json"):
            p.unlink()
    proc = _start_server()
    try:
        secs, status = _wait_ready()
        return {"scene": label, "ready_seconds": round(secs, 2),
                "phase": status.get("phase", ""),
                "snapshot_hits": status.get("snapshot_hits", []),
                "snapshot_saved": status.get("snapshot_saved", [])}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    out_path = None
    argv = list(sys.argv[1:])
    scenes: list[dict] = []
    if "--wipe-snapshots" in argv:
        # recompute scene: full rebuild with snapshots disabled
        scenes.append(run_scene("recompute_full", wipe=True))
        argv.remove("--wipe-snapshots")
    # cold_snapshot scene: whatever snapshots exist now (first ever run of
    # this bench may still recompute — read the phase/hits to know which)
    scenes.append(run_scene("cold_snapshot_or_recompute"))
    # second run MUST be a pure snapshot hit — the acceptance number
    scenes.append(run_scene("cold_snapshot"))
    out = {
        "bench": "bench_startup",
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "port": PORT,
        "scenes": scenes,
    }
    if "--json" in argv:
        out_path = Path(argv[argv.index("--json") + 1])
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
