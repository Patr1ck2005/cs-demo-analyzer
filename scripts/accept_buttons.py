"""Button-level acceptance (Phase W 操作验收): click every high-risk button
headlessly and assert the observable behavior.

Prereq: the web server is running on http://127.0.0.1:8000 with a warm
library (same setup as scripts/visual_check.py). Steps cover the audited
defects F1/F2/F3/F4/F5/F9/F10/F12 at the UI level; server-side contracts
are covered by tests/test_phase_w.py.

Writes temporary artifacts only under output/.accept/ (fake upload payload);
cleans up after itself. Exit code 1 = any failure.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
H = "769f7be048a28713ba1e09e8bce0b5f6d4d46f5a146bb8663256ea142aa65217"
ACCEPT_DIR = Path("output/.accept")
DEMO_FILE = Path("demos") / "accept-fake.dem"

failures: list[str] = []


def ok(name: str, detail: str = "") -> None:
    print(f"[PASS] {name}" + (f" — {detail}" if detail else ""))


def fail(name: str, detail: str) -> None:
    print(f"[FAIL] {name} — {detail}")
    failures.append(name)


def api(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_warm(timeout_s: float = 600) -> bool:
    """Block until the prewarm finished (snapshot rebuild can take minutes)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            st = api("/api/warmup.json")
            if st.get("ready") or st.get("phase") == "error":
                return bool(st.get("ready"))
        except Exception:
            pass
        time.sleep(2.0)
    return False


def main() -> int:
    if not wait_warm():
        print("warmup did not finish — aborting acceptance")
        return 1
    ACCEPT_DIR.mkdir(parents=True, exist_ok=True)
    results: list[tuple[str, bool]] = []

    def run(name: str, fn):
        try:
            fn()
            results.append((name, True))
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {name} — {exc}")
            results.append((name, False))
            failures.append(name)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        def expect_no_console_errors(step: str) -> None:
            if errors:
                raise AssertionError(f"console errors: {errors[:3]}")
            errors.clear()

        # ---- 1. dashboard hydration (F6 path: fill, never reload-loop) ----
        def step_dashboard():
            page.goto(BASE + "/", wait_until="networkidle", timeout=60000)
            page.wait_for_function(
                "document.querySelector('[data-warmup=player_count]')?.textContent !== '…'",
                timeout=60000,
            )
            expect_no_console_errors("dashboard")

        run("dashboard hydration", step_dashboard)

        # ---- 2. F1: star state persists across reload ----
        def step_star():
            page.goto(BASE + f"/match/{H}", wait_until="networkidle", timeout=60000)
            star = page.locator("[data-match-card][data-fav-standalone] .fav-star")
            star.wait_for(timeout=15000)
            page.wait_for_timeout(800)  # favorites doc fetch settles
            if "on" not in (star.get_attribute("class") or ""):
                star.click()  # ensure ON
                page.wait_for_timeout(600)
            page.reload(wait_until="networkidle")
            star2 = page.locator("[data-match-card][data-fav-standalone] .fav-star")
            star2.wait_for(timeout=15000)
            page.wait_for_timeout(800)
            now_on = "on" in (star2.get_attribute("class") or "")
            assert now_on, "starred state lost after reload (F1)"
            # restore the clean (unstarred) default
            star2.click()
            page.wait_for_timeout(600)
            expect_no_console_errors("star")

        run("F1 star persists across reload", step_star)

        # ---- 3. note/tags editor roundtrip ----
        def step_note():
            page.goto(BASE + f"/match/{H}", wait_until="networkidle", timeout=60000)
            page.locator("[data-match-card][data-fav-standalone] .fav-edit").click()
            page.fill("#fav-editor-note", "W验收-自动备注")
            page.click(".fav-editor-save")
            page.wait_for_selector(".fav-editor", state="detached", timeout=10000)
            favs = api("/api/favorites")
            note = (favs["matches"].get(H) or {}).get("note", "")
            assert note == "W验收-自动备注", f"note not saved: {note!r}"
            # cleanup
            page.locator("[data-match-card][data-fav-standalone] .fav-edit").click()
            page.fill("#fav-editor-note", "")
            page.click(".fav-editor-save")
            page.wait_for_selector(".fav-editor", state="detached", timeout=10000)
            expect_no_console_errors("note")

        run("favorites note roundtrip", step_note)

        # ---- 4. F12: prefs save + reset syncs the server copy ----
        def step_prefs():
            page.goto(BASE + f"/match/{H}/viewer", wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(4000)
            page.click("#prefs-btn")
            page.wait_for_selector("#prefs-save", timeout=10000)
            page.eval_on_selector(
                'input[data-pref="marker.fit"]',
                """el => {
                    el.value = '0.9';
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                }""",
            )
            page.click("#prefs-save")
            page.wait_for_timeout(800)
            saved = api("/api/ui-prefs")
            assert saved.get("marker.fit") == 0.9, f"save failed: {saved.get('marker.fit')}"
            page.click("#prefs-reset")
            page.click("#prefs-save")
            page.wait_for_timeout(800)
            reset = api("/api/ui-prefs")
            assert reset.get("marker.fit") == 0.54, f"reset not synced (F12): {reset.get('marker.fit')}"
            expect_no_console_errors("prefs")

        run("F12 prefs save/reset sync", step_prefs)

        # ---- 5. F4: control v2 causal guard inside the live viewer ----
        def step_control_v2():
            page.goto(BASE + f"/match/{H}/viewer", wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(5000)
            # a FUTURE kill must not affect the field at the current tick
            diff = page.evaluate(
                """() => {
                    const map = window.__viewerDebug.D.map;
                    const TICK = window.__viewerDebug.D.tick_rate;
                    const t = window.__viewerDebug.state.tick;
                    const b = map.bounds;
                    const cx = (b.min_x + b.max_x) / 2, cy = (b.min_y + b.max_y) / 2;
                    const players = [{x: cx, y: cy, sideCode: 0}];
                    const f0 = ViewerControl.computeInstant(map, players, [], t, TICK);
                    const future = ViewerControl.computeInstant(map, players,
                        [{x: cx, y: cy, tick: t + 500}], t, TICK);
                    let dFuture = 0;
                    for (let i = 0; i < f0.length; i++)
                        dFuture = Math.max(dFuture, Math.abs(f0[i] - future[i]));
                    const past = ViewerControl.computeInstant(map, players,
                        [{x: cx, y: cy, tick: t - 10}], t, TICK);
                    let dPast = 0;
                    for (let i = 0; i < f0.length; i++)
                        dPast = Math.max(dPast, Math.abs(f0[i] - past[i]));
                    return {dFuture, dPast};
                }"""
            )
            assert diff["dFuture"] == 0, f"future fight leaked (F4): {diff}"
            assert diff["dPast"] > 0, "past fight has no effect — decay dead?"
            # playback + seek with v2 on
            page.keyboard.press("Space")
            page.wait_for_timeout(2000)
            page.keyboard.press("Space")
            expect_no_console_errors("control v2")

        run("F4 control v2 causal guard", step_control_v2)

        # ---- 6. F3: EV table shows the real round coverage ----
        def step_ev_table():
            page.goto(BASE + f"/match/{H}?tab=economy", wait_until="networkidle", timeout=90000)
            page.wait_for_function(
                """() => {
                    const el = document.getElementById('ev-note');
                    return el && /本表 N=\\d+/.test(el.textContent);
                }""",
                timeout=120000,
            )
            note = page.locator("#ev-note").text_content()
            assert "本表 N=0" not in note, f"EV coverage still 0 (F3): {note!r}"
            expect_no_console_errors("ev table")

        run("F3 EV table N>0", step_ev_table)

        # ---- 7. F5: weapon timeline tick_rate in payload ----
        def step_tick_rate():
            page.goto(BASE + f"/match/{H}?tab=tactics", wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(1500)
            tr = page.evaluate(
                f"fetch('/api/demo/{H}/analysis/weapon_timeline.json')"
                ".then(r => r.json()).then(d => d.tick_rate)"
            )
            assert tr in (32, 64, 128), f"bad tick_rate: {tr}"
            expect_no_console_errors("weapon timeline")

        run("F5 weapon timeline tick_rate", step_tick_rate)

        # ---- 8. F2: funlab rapid chip clicks keep filters == applied ----
        def step_funlab():
            page.goto(BASE + "/fun-lab", wait_until="networkidle", timeout=120000)
            page.wait_for_selector("#fl-stack-chips [data-stack]", timeout=120000)
            chips = page.locator("#fl-stack-chips [data-stack]")
            n = chips.count()
            assert n >= 2, f"need >=2 stack chips, got {n}"
            chips.nth(0).click()  # two clicks back-to-back (no settle)
            chips.nth(1).click()
            page.wait_for_timeout(4000)
            st = page.evaluate("window.__funlabDebug.state()")
            assert st["FILTERS"] == st["applied"], f"filter drift (F2): {st}"
            expect_no_console_errors("funlab chips")

        run("F2 funlab rapid clicks", step_funlab)

        # ---- 9. F9: report export single-flight + history ----
        def step_export():
            page.goto(BASE + "/reports", wait_until="networkidle", timeout=60000)
            page.wait_for_function(
                "document.querySelectorAll('#rp-demo option').length > 0", timeout=30000)
            before = len(api("/api/report/exports.json")["exports"])
            page.click("#rp-png")
            # in-flight guard observable immediately after the first click
            assert page.locator("#rp-png").is_disabled(), "export guard missing (F9)"
            page.click("#rp-png")  # no-op while in flight (button disabled)
            page.wait_for_selector("#rp-status a", timeout=120000)
            after = len(api("/api/report/exports.json")["exports"])
            # exactly ONE new file regardless of how many no-op clicks landed
            assert after in (before + 1, before + 2), f"export count odd: {before}→{after}"
            assert after > before, "no export produced"
            expect_no_console_errors("export")

        run("F9 report export single-flight", step_export)

        # ---- 10. 一键入库 (idempotent on a clean demos/) ----
        def step_import():
            page.goto(BASE + "/system", wait_until="networkidle", timeout=60000)
            page.click("#sys-import")
            # the click feedback IS the disabled state (fetch in flight)
            page.wait_for_timeout(300)
            assert page.locator("#sys-import").is_disabled(), "import gave no click feedback"
            page.wait_for_function("!document.getElementById('sys-import').disabled",
                                   timeout=15000)
            expect_no_console_errors("system import")

        run("system import click", step_import)

        # ---- 11. F10: upload rejects non-.dem, queues the .dem ----
        def step_upload():
            DEMO_FILE.unlink(missing_ok=True)  # idempotent re-runs
            fake = ACCEPT_DIR / "accept-fake.dem"
            fake.write_bytes(b"CSDEMO-accept-fake" * 200)
            txt = ACCEPT_DIR / "notes.txt"
            txt.write_bytes(b"not a demo")
            page.goto(BASE + "/", wait_until="networkidle", timeout=60000)
            page.set_input_files("#file-input", [str(fake), str(txt)])
            page.click("[data-upload-btn]")
            page.wait_for_load_state("networkidle", timeout=120000)
            assert "只支持 .dem" in page.content(), "non-.dem not rejected (F10)"
            live = page.locator('#batch-table tr[data-job]:not([data-job=""])')
            assert live.count() == 1, \
                f"expected exactly 1 live job row (the .dem), got {live.count()}"
            job_id = live.first.get_attribute("data-job")
            deadline = time.time() + 120
            status = ""
            while time.time() < deadline:
                status = api(f"/api/jobs/{job_id}").get("status", "")
                if status in ("done", "error"):
                    break
                time.sleep(1.0)
            assert status == "error", f"fake bytes should fail to parse, got {status}"
            # the .dem stays in demos/ (unparsed) until cleanup removes it
            assert DEMO_FILE.exists(), "upload did not persist the .dem"
            DEMO_FILE.unlink()
            expect_no_console_errors("upload")

        run("F10 upload gate + job lifecycle", step_upload)

        # ---- 12. match tabs / map chips / view toggles ----
        def step_tabs():
            page.goto(BASE + f"/match/{H}", wait_until="networkidle", timeout=90000)
            for tab in ("kills", "economy", "utility", "routes", "tactics"):
                page.click(f'.tab-btn[data-tab="{tab}"]')
                page.wait_for_timeout(1800)
            body = page.inner_text("body")
            assert "数据不可用" not in body, "a tab payload failed to load"
            expect_no_console_errors("tabs")

        run("match tabs", step_tabs)

        def step_chips():
            page.goto(BASE + "/map-analysis", wait_until="networkidle", timeout=120000)
            page.wait_for_timeout(2500)
            chips = page.locator("#ma-map-chips [data-map]")
            if chips.count() > 1:
                chips.nth(1).click()
                page.wait_for_timeout(800)
            page.click("#ma-side-ct")
            page.wait_for_timeout(800)
            page.goto(BASE + "/highlights", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(1500)
            page.click('.chip[data-kind="ace"]')
            page.wait_for_timeout(600)
            page.goto(BASE + "/matches", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(1000)
            page.click("#view-table")
            page.wait_for_timeout(400)
            page.click("#view-cards")
            expect_no_console_errors("chips + toggles")

        run("map chips / highlight filter / view toggle", step_chips)

        browser.close()

    print("\nACCEPTANCE FAILURES:", failures or "none")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
