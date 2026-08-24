"""Probe: which demoparser2 per-tick props parse cleanly across our demos?

Each candidate prop list runs in an ISOLATED SUBPROCESS because unknown props
can hard-panic demoparser2 (pyo3 abort), killing the whole process.

Decision rule: ship ammo in viewer-data only if >=1 candidate parses OK on ALL
demos; otherwise V1 ships "ammo": null.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANDIDATES = [
    ["active_weapon_ammo"],
    ["is_in_reload"],
    ["active_weapon_ammo", "is_in_reload"],
    ["clip"],
    ["reserve"],
    ["clip", "reserve"],
    ["money"],
    ["inventory"],
    ["weapons"],
    ["active_weapon_name"],
    ["current_ammo"],
]
DEMOS = sorted((REPO / "demos").glob("*.dem"))


def run_one(props: list[str], demo: Path) -> str:
    """Returns OK | UnknownProp | PANIC | ERROR(msg)."""
    code = f"""
import sys
sys.path.insert(0, r"{REPO}")
from demoparser2 import DemoParser
p = DemoParser(r"{demo}")
try:
    df = p.parse_ticks({props!r})
    cols = sorted(df.columns.tolist())
    # a prop "parses" only if its column actually materializes (0.41 silently
    # dropped unknown props, returning just name/steamid/tick)
    missing = [c for c in {props!r} if c not in cols]
    if missing:
        print("MISSING", missing)
    else:
        print("OK", len(df), cols[:8])
except Exception as e:
    print("ERR", type(e).__name__, str(e)[:80])
"""
    try:
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=180,
        )
        out = (r.stdout or "").strip()
        if r.returncode != 0:
            return "PANIC" if r.returncode < 0 or "panic" in (r.stderr or "").lower() else f"RC{r.returncode}"
        return out.splitlines()[-1] if out else "EMPTY"
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def main() -> None:
    if not DEMOS:
        print("no demos found")
        return
    results = {}
    # ammo candidates first (the decision-relevant ones), then legacy extras
    for props in CANDIDATES:
        row = []
        for d in DEMOS:
            row.append(f"{d.stem[:12]}:{run_one(props, d)}")
        results["+".join(props)] = row
        print(props, "->", ", ".join(row), flush=True)
    # weapon_reload event materialization (per-demo, isolated too)
    reload_row = []
    for d in DEMOS:
        code = f"""
import sys
sys.path.insert(0, r"{REPO}")
from demoparser2 import DemoParser
p = DemoParser(r"{d}")
try:
    df = p.parse_event("weapon_reload", player=["X", "Y"])
    print("OK", 0 if df is None else len(df), sorted(df.columns.tolist())[:6] if df is not None else [])
except Exception as e:
    print("ERR", type(e).__name__, str(e)[:80])
"""
        try:
            r = subprocess.run([sys.executable, "-c", code],
                               capture_output=True, text=True, timeout=180)
            out = (r.stdout or "").strip()
            reload_row.append(f"{d.stem[:12]}:{'PANIC' if r.returncode != 0 else (out.splitlines()[-1] if out else 'EMPTY')}")
        except subprocess.TimeoutExpired:
            reload_row.append(f"{d.stem[:12]}:TIMEOUT")
    results["event:weapon_reload"] = reload_row
    print("event:weapon_reload ->", ", ".join(reload_row), flush=True)
    (REPO / "output").mkdir(exist_ok=True)
    (REPO / "output" / ".ammo_probe.json").write_text(
        json.dumps(results, indent=1), encoding="utf-8"
    )
    print("saved -> output/.ammo_probe.json")


if __name__ == "__main__":
    main()
