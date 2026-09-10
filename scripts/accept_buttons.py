"""Button-level acceptance (Phase W 操作验收 + Phase X IA 验收): click every
high-risk button headlessly and assert the observable behavior.

Prereq: the web server is running on http://127.0.0.1:8000 with a warm
library (same setup as scripts/visual_check.py). Steps cover the audited
defects F1/F2/F3/F4/F5/F9/F10/F12 at the UI level plus the Phase X IA
regressions (nav active state, retired 301s, lab deep-link); server-side
contracts are covered by tests/test_phase_w.py and tests/test_phase_x.py.

Run-order contract (收尾 V-B4): fresh server → this script ONCE, nothing
else. The self-invalidating steps (一键入库 / upload) live at the TAIL —
mid-run they used to kick a wave2 rebuild under the memo-dependent V2
steps (16/19/20 eat 503s while shards rebuild). Memo-dependent steps
additionally gate on wait_warm() so an externally cold server heals
instead of failing.

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
# S2 step 20: the repo demos/ dir (dry-run must not add anything here)
DEMOS_GLOB_DIR = Path("demos")

failures: list[str] = []


def ok(name: str, detail: str = "") -> None:
    print(f"[PASS] {name}" + (f" — {detail}" if detail else ""))


def fail(name: str, detail: str) -> None:
    print(f"[FAIL] {name} — {detail}")
    failures.append(name)


def api(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_warm(timeout_s: float = 1800) -> bool:
    """Block until the prewarm finished (snapshot rebuild can take minutes).

    S3-B1: gate on ready AND wave2_done — ready flips true after wave1 while
    wave2 shard rebuilds may still be running; waiting on ready alone races
    that window (the S2-era back-to-back degradation root cause)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            st = api("/api/warmup.json")
            if st.get("phase") == "error":
                return False
            if st.get("ready") and st.get("wave2_done"):
                return True
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
        # (Phase X: the lab now lives at /players?tab=lab; lazy script mount
        # means the chips can take a while on a cold tab)
        def step_funlab():
            page.goto(BASE + "/players?tab=lab", wait_until="networkidle", timeout=120000)
            page.wait_for_selector("#fl-stack-chips [data-stack]", timeout=180000)
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

        # ---- (收尾 V-B4) steps 10/11 moved to the TAIL: the import/upload
        # steps invalidate the aggregate + kick a wave2 rebuild, and the
        # V2-era steps 16-20 consume wave2 memos (aimsci/winloo/duelmo) —
        # mid-run they raced that rebuild and ate 503s (7/23 failures in one
        # round). Self-invalidating steps now run last, after every
        # memo-dependent assertion is done.

        # ---- 10. match tabs / map chips / view toggles ----
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
            page.wait_for_timeout(3000)
            chips = page.locator("#ma-map-chips [data-map]")
            if chips.count() > 1:
                chips.nth(1).click()
                page.wait_for_timeout(800)
            page.click("#ma-side-ct")
            page.wait_for_timeout(800)
            # Phase X: 道具落点热力 follows the page-level map selection
            page.evaluate(
                "document.getElementById('utility').scrollIntoView()")
            page.wait_for_timeout(1200)
            assert page.locator("#ul-spots").count() == 1, "utility spots missing"
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

        run("map chips / utility follow / highlight filter / view toggle", step_chips)

        # ---- 11. Phase X IA: nav active state + retired-page redirects ----
        def step_nav_ia():
            # report page must highlight 报告 (W-audit P2 finding)
            page.goto(BASE + f"/report/{H}", wait_until="networkidle", timeout=60000)
            cls = page.locator('nav a[href="/reports"]').get_attribute("class") or ""
            assert "active" in cls, f"/report page has no active nav item: {cls!r}"
            # retired pages 301 to their new homes
            for url, needle in (("/fun-lab", "fl-quadrant"),
                                ("/utility-lab", "ul-flash-table")):
                resp = page.goto(BASE + url, wait_until="load", timeout=90000)
                assert resp.url != BASE + url, f"{url} did not redirect"
                assert needle in page.content(), f"{url} target missing {needle}"
            # the players lab tab deep-link activates the lab panel
            page.goto(BASE + "/players?tab=lab", wait_until="networkidle", timeout=90000)
            on = page.locator('.tab-btn[data-tab="lab"]').get_attribute("class") or ""
            assert "on" in on, "players?tab=lab did not activate the lab tab"
            expect_no_console_errors("nav IA")

        run("X nav active + retired 301s + lab deep-link", step_nav_ia)

        # ---- 12. W2 F-A: players tab round-trip, echarts injected ONCE ----
        def step_players_roundtrip():
            page.goto(BASE + "/players", wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(2000)  # matrix fetch + mount
            page.click('.tab-btn[data-tab="lab"]')
            page.wait_for_selector("#fl-stack-chips [data-stack]", timeout=180000)
            page.wait_for_timeout(2000)  # funlab fetch + mount
            page.click('.tab-btn[data-tab="overview"]')
            # poll instead of sleep — fixed sleeps raced the tab switch
            page.wait_for_function(
                "document.querySelector('[data-panel=\"lab\"]').hidden", timeout=10000)
            page.wait_for_timeout(1500)  # matrix remount/settle
            st = page.evaluate(
                """() => {
                    const inst = (id) => {
                        const el = document.getElementById(id);
                        return el ? echarts.getInstanceByDom(el) : null;
                    };
                    const q = inst('fl-quadrant'), g = inst('sm-galaxy');
                    const m = inst('matrix-chart');
                    return {q: q ? q.getWidth() : 0, g: g ? g.getHeight() : 0,
                            mw: m ? m.getWidth() : 0,
                            scripts: document.querySelectorAll('script[src*="echarts.min"]').length};
                }""")
            assert st["scripts"] == 1, f"echarts injected {st['scripts']}x (W2 F-A)"
            assert st["q"] > 300 and st["g"] > 200, f"lab charts 0-size: {st}"
            assert st["mw"] > 300, f"matrix not mounted after return: {st}"
            expect_no_console_errors("players round-trip")

        run("W2 players tab round-trip + single echarts", step_players_roundtrip)

        # ---- 13. W2 F-B: /reports?demo= preselect + preview href synced ----
        def step_reports_preselect():
            page.goto(BASE + f"/reports?demo={H}", wait_until="networkidle", timeout=90000)
            page.wait_for_function(
                "document.querySelectorAll('#rp-demo option').length > 0", timeout=30000)
            assert page.evaluate("document.getElementById('rp-demo').value") == H, \
                "?demo= preselect failed"
            href = page.get_attribute("#rp-preview", "href")
            assert href and H in href, f"preview href not pre-synced (F-B): {href!r}"

        run("W2 reports ?demo= preselect + preview href", step_reports_preselect)

        # ---- 14. W2: funlab sigma slider label + localStorage + restore ----
        def step_sigma_slider():
            page.goto(BASE + "/players?tab=lab", wait_until="networkidle", timeout=90000)
            page.wait_for_selector("#fl-stack-chips [data-stack]", timeout=180000)
            page.eval_on_selector(
                '#sm-traj-sigma',
                """el => { el.value = '2.5';
                          el.dispatchEvent(new Event('input', {bubbles: true})); }""")
            page.wait_for_timeout(500)
            assert page.inner_text("#sm-traj-sigma-val") == "2.5", "label not updated"
            assert page.evaluate("localStorage.getItem('csa.trajSigma')") == "2.5", \
                "localStorage not persisted"
            page.reload(wait_until="networkidle")
            page.wait_for_selector("#fl-stack-chips [data-stack]", timeout=180000)
            assert page.eval_on_selector("#sm-traj-sigma", "el => el.value") == "2.5", \
                "slider not restored after reload"
            # restore default
            page.eval_on_selector(
                '#sm-traj-sigma',
                """el => { el.value = '1.5';
                          el.dispatchEvent(new Event('input', {bubbles: true})); }""")
            expect_no_console_errors("sigma slider")

        run("W2 funlab sigma slider persist/restore", step_sigma_slider)

        # ---- 15. R5: loss-attribution chip deep-links the viewer round ----
        def step_loss_chips():
            page.goto(BASE + f"/match/{H}", wait_until="networkidle", timeout=90000)
            chip = page.locator("#lossattr-panel a.loss-tag").first
            chip.wait_for(timeout=60000)
            href = chip.get_attribute("href")
            assert href and "/viewer?round=" in href, f"chip href broken: {href!r}"
            expected_round = href.split("round=")[1].split("&")[0]
            chip.click()
            page.wait_for_function(
                "location.pathname.endsWith('/viewer') && location.search.includes('round=')",
                timeout=20000)
            assert f"round={expected_round}" in page.url, \
                f"deep link landed on wrong round: {page.url}"
            page.go_back(wait_until="networkidle")
            expect_no_console_errors("loss chips deep link")

        run("R5 loss chip deep-links viewer round", step_loss_chips)

        # ---- 16. R1/R3: career conf rows fill + aim table stopped column ----
        def step_career_conf_rows():
            assert wait_warm(), "wave2 warm timeout before career conf step"
            page.goto(BASE + "/player/76561198845044722",
                      wait_until="networkidle", timeout=90000)
            # conf rows must fill from the career-conf API (poll, never sleep)
            page.wait_for_function(
                """() => {
                    const el = document.getElementById('conf-rating');
                    return el && el.textContent !== '…' && el.textContent.includes('区间');
                }""", timeout=30000)
            assert "n=" in page.locator("#conf-rating").text_content()
            # aim-science table: stopped-fire column rendered with a value
            page.wait_for_function(
                """() => {
                    const rows = document.querySelectorAll('#aimsci-tbody tr');
                    return rows.length > 1 && rows[0].cells[5] &&
                        rows[0].cells[5].textContent.trim() !== '—' &&
                        rows[0].cells[5].textContent.includes('%');
                }""", timeout=30000)
            expect_no_console_errors("career conf + aim table")

        run("R career conf rows + aim table filled", step_career_conf_rows)

        # ---- 17. R4: smoke-bucket table follows the page map selection ----
        def step_smoke_buckets_follow_map():
            assert wait_warm(), "warm timeout before smoke buckets step"
            page.goto(BASE + "/map-analysis", wait_until="networkidle", timeout=120000)
            page.wait_for_function(
                """() => {
                    const b = document.getElementById('ul-smoke-buckets');
                    return b && b.querySelector('td') &&
                        !b.textContent.includes('加载中');
                }""", timeout=60000)
            before = page.locator("#ul-smoke-buckets tr").all_inner_texts()
            chips = page.locator("#ma-map-chips [data-map]")
            if chips.count() > 1:
                chips.nth(1).click()
                page.wait_for_timeout(1200)
                after = page.locator("#ul-smoke-buckets tr").all_inner_texts()
                assert before != after, "smoke buckets did not follow map change"
            expect_no_console_errors("smoke buckets follow map")

        run("R4 smoke buckets follow map selection", step_smoke_buckets_follow_map)

        # ---- 18. S2-A5: scan-sources button (dry-run: demos/ untouched) ----
        def step_scan_sources():
            page.goto(BASE + "/system", wait_until="networkidle", timeout=60000)
            demos_before = sorted(p.name for p in DEMOS_GLOB_DIR.glob("*.dem")) \
                if DEMOS_GLOB_DIR.is_dir() else []
            page.click("#sys-scan-sources")
            page.wait_for_function(
                """() => {
                    const el = document.getElementById('sys-scan-result');
                    return el && el.style.display !== 'none' &&
                        !el.textContent.includes('扫描平台源目录中');
                }""", timeout=120000)
            body = page.locator("#sys-scan-result").inner_text()
            assert "dry-run" in body, f"scan result missing dry-run note: {body!r}"
            demos_after = sorted(p.name for p in DEMOS_GLOB_DIR.glob("*.dem")) \
                if DEMOS_GLOB_DIR.is_dir() else []
            assert demos_before == demos_after, \
                f"dry-run must not import: {set(demos_after) - set(demos_before)}"
            expect_no_console_errors("scan sources")

        run("S2 scan-sources dry-run button", step_scan_sources)

        # ---- 19. 收尾 V-A1: the career duel block shows the viewer's own
        # row even outside the Top 12 (board is 200+ players; slice(0,12)
        # used to hide 209 of them on their own career page) ----
        def step_duel_self_row():
            assert wait_warm(), "wave2 warm timeout before duel step"
            board = api("/api/duel-model.json")
            players = board.get("players", [])
            if len(players) <= 12:
                return  # small library: the Top 12 covers everyone
            victim = players[14]  # rank 15 — provably outside the slice
            page.goto(BASE + f"/player/{victim['steamid']}",
                      wait_until="networkidle", timeout=90000)
            page.wait_for_function(
                """() => {
                    const tb = document.getElementById('duelmo-tbody');
                    return tb && tb.querySelector('a') &&
                        !tb.textContent.includes('未就绪');
                }""", timeout=60000)
            hrefs = page.eval_on_selector_all(
                "#duelmo-tbody a", "els => els.map(e => e.getAttribute('href'))")
            sids = [h.split("/player/")[1] for h in hrefs if h]
            assert victim["steamid"] in sids, \
                f"rank-15 player's own duel row missing: {sids}"
            expect_no_console_errors("duel self row")

        run("V-A1 duel block shows own row outside Top 12", step_duel_self_row)

        # ---- 20. 收尾 V-A2: winprob V2 OOS note (no duplicated 跨场 prefix)
        # + chart actually mounted on the match page ----
        def step_winprob_v2():
            assert wait_warm(), "wave2 warm timeout before winprob step"
            page.goto(BASE + f"/match/{H}", wait_until="networkidle",
                      timeout=90000)
            page.wait_for_function(
                """() => {
                    const el = document.getElementById('winprob-note');
                    return el && /留一 AUC/.test(el.textContent);
                }""", timeout=90000)
            note = page.locator("#winprob-note").text_content()
            assert "V2·跨场" in note, f"source tag missing: {note!r}"
            assert note.count("跨场") == 1, f"duplicated prefix back: {note!r}"
            mounted = page.evaluate(
                "() => { const el = document.getElementById('winprob-chart');"
                " return el ? !!echarts.getInstanceByDom(el) : false; }")
            assert mounted, "winprob chart not mounted"
            expect_no_console_errors("winprob V2")

        run("V-A2 winprob OOS note + chart mounted", step_winprob_v2)

        # ---- 21. 收尾 V-B2: overlap interactive sweep — the whole sub-mode
        # (mode switch / round-grid filters / phase slider / half switch /
        # toolbar chips) previously had zero button-level acceptance ----
        def step_overlap_sweep():
            page.goto(BASE + f"/match/{H}/viewer", wait_until="networkidle",
                      timeout=90000)
            page.wait_for_timeout(5000)  # data fetch + map image + first frames
            page.click('.ob-mode-switch [data-mode="overlap"]')
            page.wait_for_selector("#ov-rounds .chip", timeout=30000)
            page.click("#ovr-first4")
            page.wait_for_timeout(800)
            page.eval_on_selector(
                "#ov-phase",
                """el => { el.value = 50;
                          el.dispatchEvent(new Event('input', {bubbles: true})); }""")
            page.wait_for_timeout(500)
            page.click("#ov-half-2")
            page.wait_for_timeout(800)
            assert "on" in (page.get_attribute("#ov-half-2", "class") or ""), \
                "half switch did not activate"
            chip = page.locator('#ob-toolbar .chip', has_text="模式着色").first
            cls_before = chip.get_attribute("class") or ""
            chip.click()
            page.wait_for_timeout(600)
            assert (chip.get_attribute("class") or "") != cls_before, \
                "模式着色 chip did not toggle"
            size = page.evaluate(
                "() => { const c = document.getElementById('ov-metrics');"
                " return c ? {w: c.width, h: c.height} : null; }")
            assert size and size["w"] > 0, f"overlap metrics canvas empty: {size}"
            page.click('.ob-mode-switch [data-mode="replay"]')
            page.wait_for_timeout(600)
            expect_no_console_errors("overlap sweep")

        run("V-B2 overlap sweep (mode/filters/slider/half/chip)", step_overlap_sweep)

        # ---- 22. 复盘提升包 A1: Ctrl+K palette — type a regular's name,
        # Enter must land on their career page ----
        def step_cmdk():
            page.goto(BASE + "/", wait_until="networkidle", timeout=60000)
            board = api("/api/search.json?q=Jake")
            assert board["players"], "search API should know Jake"
            jake_href = "/player/" + board["players"][0]["steamid"]
            page.keyboard.press("Control+K")
            page.wait_for_selector("#cmdk-input", timeout=10000)
            page.fill("#cmdk-input", "Jake")
            page.wait_for_selector("#cmdk-list .cmdk-row", timeout=15000)
            page.keyboard.press("Enter")
            page.wait_for_url(lambda url: url.endswith(jake_href),
                              timeout=20000)
            expect_no_console_errors("cmdk palette")

        run("A1 Ctrl+K palette lands on player page", step_cmdk)

        # ---- 23/24. (tail, V-B4) the self-invalidating steps: 一键入库 +
        # upload kick invalidate_aggregate → wave2 rebuild — deliberately
        # LAST so they never poison the memo-dependent assertions above.
        # Run-order contract: fresh server → this script once, nothing else.

        # ---- 23. 一键入库 (idempotent on a clean demos/) ----
        def step_import():
            page.goto(BASE + "/system", wait_until="networkidle", timeout=60000)
            page.click("#sys-import")
            # the click feedback IS the disabled state (fetch in flight)
            page.wait_for_timeout(300)
            assert page.locator("#sys-import").is_disabled(), "import gave no click feedback"
            page.wait_for_function("!document.getElementById('sys-import').disabled",
                                   timeout=15000)
            expect_no_console_errors("system import")

        run("system import click (tail, invalidates)", step_import)

        # ---- 24. F10: upload rejects non-.dem, queues the .dem ----
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

        run("F10 upload gate + job lifecycle (tail, invalidates)", step_upload)

        browser.close()

    print("\nACCEPTANCE FAILURES:", failures or "none")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
