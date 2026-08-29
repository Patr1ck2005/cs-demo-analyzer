"""Visual acceptance: screenshot every web page headlessly (playwright).

Saves PNGs to output/.visual/ and prints console errors per page so the agent
can Read each image and verify layout/art before handing off to the user.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
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
    ("highlights", "/highlights", 1200),
    ("compare", "/compare", 1200),
    ("system", "/system", 800),
    ("placeholder", "/favorites", 500),
    ("player_career", "/player/76561199829611601", 1200),
    ("overlap", f"/match/{H}/overlap", None),
    ("viewer", f"/match/{H}/viewer", None),
]


def main() -> int:
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
            try:
                page.goto(BASE + url, wait_until="networkidle", timeout=45000)
            except Exception as e:
                print(f"[{name}] GOTO FAIL {e}")
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
        browser.close()
    print("\nFAILURES:", failures or "none")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
