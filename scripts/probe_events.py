"""Probe: which demoparser2 events parse cleanly across our demos?

Each candidate event runs in an ISOLATED SUBPROCESS — unknown event names can
hard-panic demoparser2 (pyo3 abort, verified live on parse_convars with real
WMPVP demos), killing the whole process.

Phase I (2026-08-25) results committed to output/.event_probe.json:
  available: bomb_begindefuse (with haskit), bomb_abortdefuse*, bomb_dropped,
             bomb_pickup, weapon_zoom, cs_win_panel_match
  absent on WMPVP broadcasts (empty list): bullet_impact, *_thrown family,
             smokegrenade_tag, decoy_started, player_falldamage,
             round_announced, bomb_abortdefuse on some demos
Events absent here still belong in WANTED_EVENT_TYPES — the parser's
try/except skips missing types silently, and Valve/FACEIT demos get them.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANDIDATES = [
    "smokegrenade_tag",
    "decoy_started",
    "hegrenade_thrown",
    "smokegrenade_thrown",
    "flashbang_thrown",
    "molotov_thrown",
    "decoy_detonate",
    "weapon_zoom",
    "player_falldamage",
    "round_announced",
    "bomb_begindefuse",
    "bomb_abortdefuse",
    "bomb_dropped",
    "bomb_pickup",
    "cs_win_panel_match",
    "player_given_c4",
    "switch_round",
    "hostage_rescued",
    "bullet_impact",
]
DEMOS = sorted((REPO / "demos").glob("*.dem"))


def run_one(event: str, demo: Path) -> str:
    """Returns OK(nrows, cols...) | MISSING | PANIC | ERR(msg)."""
    code = f"""
import sys
sys.path.insert(0, r"{REPO}")
from demoparser2 import DemoParser
p = DemoParser(r"{demo}")
r = p.parse_event("{event}", player=["X", "Y"], other=["is_warmup_period"])
if isinstance(r, list):
    print("MISSING", len(r))  # demoparser2 returns [] for unknown/absent events
else:
    print("OK", len(r), sorted(r.columns.tolist())[:8])
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=300,
        )
        out = (proc.stdout or "").strip()
        if proc.returncode != 0:
            if proc.returncode < 0 or "panic" in (proc.stderr or "").lower():
                return "PANIC"
            return f"RC{proc.returncode}: {(proc.stderr or '').strip()[-60:]}"
        return out.splitlines()[-1] if out else "EMPTY"
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def main() -> None:
    if not DEMOS:
        print("no demos found")
        return
    results: dict[str, list[str]] = {}
    for event in CANDIDATES:
        row = []
        for d in DEMOS:
            row.append(f"{d.stem[:12]}:{run_one(event, d)}")
            print(f"  {event} @ {d.stem[:12]} -> {row[-1]}", flush=True)
        results[event] = row
        print(f"{event} -> {row}", flush=True)
    (REPO / "output").mkdir(exist_ok=True)
    (REPO / "output" / ".event_probe.json").write_text(
        json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print("saved -> output/.event_probe.json")


if __name__ == "__main__":
    main()
