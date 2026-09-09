"""Visual acceptance: screenshot every web page headlessly (playwright).

Saves PNGs to output/.visual/ and prints console errors per page so the agent
can Read each image and verify layout/art before handing off to the user.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"


def wait_warm(timeout_s: float = 1800) -> bool:
    """Gate on ready AND wave2_done (S3-B1): ready flips true after wave1,
    but wave2 shard rebuilds (rating21/winloo/aimsci/lossattr/evcells) may
    still be running — waiting on ready alone races that window and the R/S2
    era acceptance runs degraded exactly there."""
    import time
    import urllib.request

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + "/api/warmup.json",
                                        timeout=10) as r:
                st = json.loads(r.read().decode("utf-8"))
            if st.get("phase") == "error":
                return False
            if st.get("ready") and st.get("wave2_done"):
                return True
        except Exception:
            pass
        time.sleep(2.0)
    return False


H = "769f7be048a28713ba1e09e8bce0b5f6d4d46f5a146bb8663256ea142aa65217"
OUT = Path("output/.visual")

PAGES = [
    ("dashboard", "/", None),
    ("matches", "/matches", 800),
    ("match_detail", f"/match/{H}", 800),
    ("tab_kills", f"/match/{H}?tab=kills", 1500),
    ("tab_economy", f"/match/{H}?tab=economy", 1500),
    ("tab_utility", f"/match/{H}?tab=utility", 1500),
    ("tab_routes", f"/match/{H}?tab=routes", 2000),
    ("tab_tactics", f"/match/{H}?tab=tactics", 1500),
    ("players", "/players", 1200),
    # Phase X: fun-lab merged into /players?tab=lab (lazy-mounted charts)
    ("players_lab", "/players?tab=lab", 2500),
    ("highlights", "/highlights", 1200),
    ("compare", "/compare", 1200),
    ("system", "/system", 800),
    # Phase L: the five former placeholder pages, now real
    ("favorites", "/favorites", 1200),
    # Phase X: utility-lab merged into /map-analysis (the #utility section)
    ("map_analysis", "/map-analysis", 2500),
    ("map_utility", "/map-analysis#utility", 2500),
    ("teams", "/teams", 1500),
    ("reports", "/reports", 1500),
    ("report_match", f"/report/{H}", 1200),
    # S2-V2: Jake = the 34-demo regular; the old sid played 1 demo so the
    # R3 aim-science panel rendered mostly "—" (poor visual coverage)
    ("player_career", "/player/76561198845044722", 1200),
    ("overlap", f"/match/{H}/overlap", None),
    ("viewer", f"/match/{H}/viewer", None),
]

# S2-V3: narrow-viewport pass over the pages R/S2 most recently touched
# (7-column aim table, conf badges, loss chips, scan button). GOTO + zero
# console errors + screenshot archive; art review is manual via read_image.
NARROW_PAGES = [
    ("narrow_matches", "/matches"),
    ("narrow_players_lab", "/players?tab=lab"),
    ("narrow_map_utility", "/map-analysis#utility"),
    ("narrow_player_career", "/player/76561198845044722"),
    ("narrow_match_detail", f"/match/{H}"),
    ("narrow_system", "/system"),
]


def main() -> int:
    if not wait_warm():
        print("warmup (incl. wave2) did not finish — aborting visual check")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    failures = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        for name, url, settle_ms in PAGES:
            errors.clear()
            # W2 F-D: 45s was too tight for the API storm on the 35-demo
            # library (4 transient GOTO timeouts in one run, all passing on
            # retry) — raise to 90s and retry each GOTO once before failing.
            ok_goto = False
            last_err = ""
            for attempt in (1, 2):
                try:
                    page.goto(BASE + url, wait_until="networkidle", timeout=90000)
                    ok_goto = True
                    break
                except Exception as e:
                    last_err = str(e)
                    print(f"[{name}] GOTO attempt {attempt} failed: {last_err[:120]}")
            if not ok_goto:
                print(f"[{name}] GOTO FAIL {last_err}")
                failures.append(name)
                continue
            if name == "viewer":
                page.wait_for_timeout(6000)  # data fetch + map image + first frames
                page.keyboard.press("Space")  # start playback for the shot
                page.wait_for_timeout(2500)
                page.keyboard.press("Space")
                page.wait_for_timeout(400)
            elif name == "overlap":
                page.wait_for_timeout(5000)  # data fetch + map image + first frames
            elif settle_ms:
                page.wait_for_timeout(settle_ms)
            else:
                page.wait_for_timeout(500)
            path = OUT / f"{name}.png"
            page.screenshot(path=str(path), full_page=(name != "viewer"))
            errs = [e[:200] for e in errors]
            status = "OK" if not errs else f"CONSOLE ERRORS ({len(errs)})"
            print(f"[{name}] shot -> {path}  {status}")
            for e in errs:
                print(f"    ! {e}")
            if errs:
                failures.append(name)

        # ---- S2-V3: narrow-viewport second pass (900px) ----
        page.set_viewport_size({"width": 900, "height": 900})
        for name, url in NARROW_PAGES:
            errors.clear()
            ok_goto = False
            last_err = ""
            for attempt in (1, 2):
                try:
                    page.goto(BASE + url, wait_until="networkidle", timeout=90000)
                    ok_goto = True
                    break
                except Exception as e:
                    last_err = str(e)
                    print(f"[{name}] GOTO attempt {attempt} failed: {last_err[:120]}")
            if not ok_goto:
                print(f"[{name}] GOTO FAIL {last_err}")
                failures.append(name)
                continue
            page.wait_for_timeout(2500)
            path = OUT / f"{name}.png"
            page.screenshot(path=str(path), full_page=True)
            errs = [e[:200] for e in errors]
            status = "OK" if not errs else f"CONSOLE ERRORS ({len(errs)})"
            print(f"[{name}] shot -> {path}  {status}")
            for e in errs:
                print(f"    ! {e}")
            if errs:
                failures.append(name)
        browser.close()
    print("\nFAILURES:", failures or "none")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
