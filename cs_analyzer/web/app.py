"""LTG-2: local web platform (FastAPI + Jinja2, all-Chinese).

Phase H information architecture: entity-centered three zones —
dashboard (/) / matches / players / highlights / compare / system.
Legacy /demo/... and /aggregate URLs 301-redirect to the new tree;
all /api/... paths are unchanged.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.gzip import GZipMiddleware

from cs_analyzer.analysis import AnalysisRunner
from cs_analyzer.cache import DemoCache
from cs_analyzer.config import AnalysisConfig, load_settings
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.web import store, tasks, weapons

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
TEMPLATES.env.filters["wicon"] = weapons.icon_url
TEMPLATES.env.filters["wlabel"] = weapons.label_zh
STATIC_DIR = BASE_DIR / "static"
OUT_DIR = Path("output") / "web"
DEMOS_DIR = Path("demos")


def _demos_dir() -> Path:
    """Upload target dir (module-level so tests can monkeypatch it)."""
    return DEMOS_DIR


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Phase L0: prewarm every cross-demo memo in a background thread right
    # after the server starts listening, so the first dashboard visit hits
    # warm memos (or a skeleton + long-poll fill) instead of a ~70s block.
    from cs_analyzer.web import warmup

    _stale_cache_sweep()
    warmup.start_once()
    yield


app = FastAPI(title="CsDemoAnalyzer 本地平台", version="0.1.0", lifespan=_lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# static asset cache-buster: server start time, so a restart always hands the
# browser fresh CSS/JS (root cause fix for the "styles didn't update" reports)
import time as _time

TEMPLATES.env.globals["static_v"] = str(int(_time.time()))

_analysis_cache: dict[str, dict] = {}
#: L0: per-demo module results, FIFO-capped so a large library can't grow
#: this unbounded (HANDOFF §9.5). Eviction is insertion-order (oldest demo
#: first) — access-order LRU was never implemented; 512 slots ≈ 25+ demos ×
#: all modules.
_MODULE_CACHE_CAP = 512
_module_cache: OrderedDict[str, dict] = OrderedDict()


def _settings():
    return load_settings(None)


def _cache() -> DemoCache:
    return DemoCache(_settings().cache_dir)


def _runner() -> AnalysisRunner:
    cfg = _settings().analysis
    modules = list(cfg.enabled_modules)
    if "preference" not in modules:
        modules.append("preference")
    return AnalysisRunner(AnalysisConfig(enabled_modules=modules, module_options=cfg.module_options))


def _analyze(demo: ParsedDemo) -> dict:
    """Run analysis once per demo and memoize the result dict."""
    key = demo.metadata.demo_hash
    if key in _analysis_cache:
        return _analysis_cache[key]
    runner = _runner()
    results = runner.run(demo)
    out = {
        "basic": results.get("basic_stats"),
        "ratings": results.get("ratings"),
        "preference": results.get("preference"),
    }
    _analysis_cache[key] = out
    return out


def _analyze_module(demo: ParsedDemo, module_name: str):
    """Lazy per-module memo: demo pages only pay for the modules they render."""
    key = demo.metadata.demo_hash
    slot = _module_cache.get(key)
    if slot is None:
        slot = {}
        _module_cache[key] = slot
        while len(_module_cache) > _MODULE_CACHE_CAP:
            _module_cache.popitem(last=False)
    if module_name in slot:
        return slot[module_name]
    result = _runner().run_one(demo, module_name)
    slot[module_name] = result
    return result


# ---- pages ----

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # L0: the heavy whole-library scans (aggregate, highlight feed) are
    # memoized + prewarmed at startup. First paint is instant: counts that
    # need the aggregate render "…" and fill in via /api/warmup.json polling
    # (static/js/warmup.js) when it is still computing.
    demos = store.list_demos(_cache().cache_dir)
    # "recent" = match-id order (B8: WMPVP filenames are chronological; the
    # old parsed_at sort was wall-clock parse time, i.e. upload order)
    recent = sorted(demos, key=store.match_key, reverse=True)[:8]
    from cs_analyzer.web import warmup

    warm = warmup.status()
    highlights = _top_highlights(6) if warm["ready"] else []
    player_count: int | str = "…"
    if warm["ready"]:
        from cs_analyzer.web.aggregation import aggregated

        player_count = aggregated().total_players
    return TEMPLATES.TemplateResponse(
        request, "index.html",
        {
            "demos": demos,
            "recent": recent,
            "highlights": highlights,
            "total": len(demos),
            "map_count": len({d["map_name"] for d in demos}),
            "round_count": sum(d["num_rounds"] for d in demos),
            "player_count": player_count,
            "warm_ready": warm["ready"],
            **_map_availability(sorted({d["map_name"] for d in demos})),
        },
    )


def _top_highlights(limit: int) -> list[dict]:
    """Global highlight feed, best-first (dashboard 精选). Memoized (L0),
    fails soft."""
    from cs_analyzer.web import feed_data

    try:
        return feed_data.top_highlights(limit)
    except Exception:  # noqa: BLE001
        logger.exception("dashboard highlights feed failed")
        return []


# ---- legacy URL 301 redirects (Phase H): query strings pass through ----

def _redirect(request: Request, target: str) -> RedirectResponse:
    qs = str(request.url.query)
    if not qs:
        return RedirectResponse(target, status_code=301)
    # target may already carry a query (e.g. /players?tab=lab) — join with &
    sep = "&" if "?" in target else "?"
    return RedirectResponse(target + sep + qs, status_code=301)


@app.get("/demo/{demo_hash}", response_class=HTMLResponse)
def demo_detail_redirect(request: Request, demo_hash: str):
    return _redirect(request, f"/match/{demo_hash}")


@app.get("/demo/{demo_hash}/viewer", response_class=HTMLResponse)
def demo_viewer_redirect(request: Request, demo_hash: str):
    return _redirect(request, f"/match/{demo_hash}/viewer")


@app.get("/demo/{demo_hash}/overlap", response_class=HTMLResponse)
def demo_overlap_redirect(request: Request, demo_hash: str):
    return _redirect(request, f"/match/{demo_hash}/overlap")


@app.get("/demo/{demo_hash}/player/{steamid}", response_class=HTMLResponse)
def player_redirect(request: Request, demo_hash: str, steamid: str):
    return _redirect(request, f"/player/{steamid}")


@app.get("/aggregate", response_class=HTMLResponse)
def aggregate_redirect(request: Request):
    return _redirect(request, "/players")


# ---- Phase H new pages (M1 skeleton: minimal shells, filled in M3+) ----

@app.get("/matches", response_class=HTMLResponse)
def matches_page(request: Request):
    _stale_cache_sweep()
    demos = store.list_demos(_cache().cache_dir)
    maps = sorted({d["map_name"] for d in demos})
    return TEMPLATES.TemplateResponse(
        request, "matches.html", {"demos": demos, "maps": maps, **_map_availability(maps)}
    )


@app.get("/players", response_class=HTMLResponse)
def players_page(request: Request):
    from cs_analyzer.web.aggregation import aggregated

    result = aggregated()
    return TEMPLATES.TemplateResponse(request, "players.html", {"result": result})


@app.get("/player/{steamid}", response_class=HTMLResponse)
def player_career(request: Request, steamid: str):
    from cs_analyzer.web.aggregation import aggregated
    from cs_analyzer.web.chart_data import RADAR_AXES
    from cs_analyzer.web.rating21_data import player_card as player_rating21

    result = aggregated()
    row = next((p for p in result.players if p.steamid == steamid), None)
    if row is None:
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": f"未找到选手 {steamid}"}, status_code=404
        )
    # U1: Rating 2.1 vs 2.0 side-by-side (round-weighted across demos).
    # S3-A2: shard layer lives in web/rating21_data.py (digest-covered
    # producer module — app.py must not hold shard payload code).
    r21 = player_rating21(steamid)
    # Round 2: duel board display gate (visible-greyed threshold)
    from cs_analyzer.web.duel_data import DUEL_GATE_N

    # B4: career radar must normalize with the same server-side ranges as the
    # per-demo radar (the old hardcoded template ranges were wrong).
    return TEMPLATES.TemplateResponse(
        request, "player_career.html",
        {"p": row, "radar_axes": RADAR_AXES, "r21": r21, "gate_duels": DUEL_GATE_N},
    )


@app.get("/api/player/{steamid}/career-conf.json")
def player_career_conf(steamid: str):
    """R1: 生涯卡置信区间（merge 层，shard 载荷零改动）。

    rating/KAST/hs/fkpr 的 Wilson（或 EB）区间 + 实际 n——把"打得多≠数据高"
    落到推断层：小样本选手的区间自然更宽。
    """
    from cs_analyzer.analysis.stats import K_PER_ROUND, wilson_interval
    from cs_analyzer.web.aggregation import aggregated

    row = next((p for p in aggregated().players if p.steamid == steamid), None)
    if row is None:
        raise HTTPException(status_code=404, detail="player not found")

    def w(pct_val: float, n: int, scale: float = 1.0) -> dict:
        lo, hi = wilson_interval(pct_val * scale * n, n)
        return {"lo": round(lo * scale, 3), "hi": round(hi * scale, 3),
                "n": n, "gated": n < 30}

    r_lo, r_hi = wilson_interval(0, 0)  # placeholder for EB below
    # Rating/KAST 是回合池化均值（非二元）→ EB 收缩带（n=回合数）
    from cs_analyzer.analysis.stats import shrunk_mean

    pool_rating = (sum(p.avg_rating * p.total_rounds for p in aggregated().players)
                   / max(sum(p.total_rounds for p in aggregated().players), 1))
    pool_kast = (sum(p.avg_kast * p.total_rounds for p in aggregated().players)
                 / max(sum(p.total_rounds for p in aggregated().players), 1))
    pool_adr = (sum(p.avg_adr * p.total_rounds for p in aggregated().players)
                / max(sum(p.total_rounds for p in aggregated().players), 1))
    pool_kpr = (sum(p.avg_kpr * p.total_rounds for p in aggregated().players)
                / max(sum(p.total_rounds for p in aggregated().players), 1))
    rating_shrunk = shrunk_mean(row.avg_rating, row.total_rounds, pool_rating, K_PER_ROUND)
    kast_shrunk = shrunk_mean(row.avg_kast, row.total_rounds, pool_kast, K_PER_ROUND)
    adr_shrunk = shrunk_mean(row.avg_adr, row.total_rounds, pool_adr, K_PER_ROUND)
    kpr_shrunk = shrunk_mean(row.avg_kpr, row.total_rounds, pool_kpr, K_PER_ROUND)
    del r_lo, r_hi

    def eb(value: float, shrunk: float, digits: int) -> dict:
        return {"value": round(value, digits), "shrunk": round(shrunk, digits),
                "lo": round(min(value, shrunk), digits),
                "hi": round(max(value, shrunk), digits),
                "n": row.total_rounds, "gated": row.total_rounds < 30}

    return {
        "steamid": steamid,
        "rating": eb(row.avg_rating, rating_shrunk, 3),
        "kast": eb(row.avg_kast, kast_shrunk, 3),
        "adr": eb(row.avg_adr, adr_shrunk, 1),
        "kpr": eb(row.avg_kpr, kpr_shrunk, 3),
        "hs": w(row.avg_hs_pct / 100.0, row.total_kills),
        "fkpr": w(row.avg_fkpr, row.total_rounds),
    }


@app.get("/highlights", response_class=HTMLResponse)
def highlights_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "highlights.html", {})


# ---- Phase L1: favorites / tags / notes ----

@app.get("/favorites", response_class=HTMLResponse)
def favorites_page(request: Request):
    """收藏与标注：星标/标签/备注（列表由 favorites.js 从 /api/favorites 渲染）。"""
    return TEMPLATES.TemplateResponse(request, "favorites.html", {})


# ---- Phase X: fun-lab merged into /players?tab=lab; utility-lab merged into
# /map-analysis (both 301, query strings pass through) — must register BEFORE
# /{placeholder} ----

@app.get("/fun-lab", response_class=HTMLResponse)
def fun_lab_redirect(request: Request):
    return _redirect(request, "/players?tab=lab")


@app.get("/utility-lab", response_class=HTMLResponse)
def utility_lab_redirect(request: Request):
    return _redirect(request, "/map-analysis#utility")


# ---- Phase L3: map analysis (地图分析) — must register BEFORE /{placeholder} ----

@app.get("/map-analysis", response_class=HTMLResponse)
def map_analysis_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "map_analysis.html", {})


# ---- Phase L4: lineups (队伍视图) — must register BEFORE /{placeholder} ----

@app.get("/teams", response_class=HTMLResponse)
def teams_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "teams.html", {})


# ---- Phase L5: report export (报告导出) — must register BEFORE /{placeholder} ----

@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "reports.html", {})


@app.get("/api/funlab.json")
def funlab_api(request: Request):
    """Fun metrics report; optional filters:

    stack=1,2,4 — keep only matches with that many library-regulars (排型)
    dates=20260902,20260903 — keep only matches played on those dates (5E only:
        perfect-world demos carry no date in the demo or the filename)
    platform=five_e|perfect_world — platform filter (Y2, filename-derived)
    """
    from cs_analyzer.web.funlab_data import funlab_report

    def _ints(param: str) -> tuple[int, ...] | None:
        vals = tuple(int(v) for v in param.split(",") if v.strip().isdigit())
        return vals or None

    stack_param = request.query_params.get("stack", "").strip()
    dates_param = request.query_params.get("dates", "").strip()
    platform_param = request.query_params.get("platform", "").strip()
    stack = _ints(stack_param) if stack_param else None
    dates = tuple(v for v in dates_param.split(",") if v.strip()) or None
    platform = platform_param if platform_param in ("five_e", "perfect_world") else None
    return JSONResponse(funlab_report(stack=stack, dates=dates, platform=platform))


@app.get("/api/style-map.json")
def style_map_api():
    """Phase N 风格星系：全 32 指标 · 稳健标准化 · 欧氏距离 · Ward 聚类。

    Derives from the memoized funlab vectors (≥3-demos gate shared); pure
    math on top, so no separate prewarm step is needed.
    """
    from cs_analyzer.web.style_map import style_map_report

    return JSONResponse(style_map_report())


@app.get("/report/{demo_hash}", response_class=HTMLResponse)
def report_match_page(request: Request, demo_hash: str):
    """Print-friendly single-match report (exported to PNG/PDF by playwright;
    also printable from the browser)."""
    from cs_analyzer.web.report_data import report_context

    demo = _load(demo_hash)
    if demo is None:
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": "未找到该对局"}, status_code=404)
    return TEMPLATES.TemplateResponse(
        request, "report_match.html", report_context(demo))


@app.get("/api/favorites")
def favorites_get():
    from cs_analyzer.web.favorites_store import load_favorites

    return JSONResponse(load_favorites(OUT_DIR))


@app.post("/api/favorites")
async def favorites_set(request: Request):
    """Merge one entry patch: {scope: "match"|"player", id, patch, meta?}."""
    from cs_analyzer.web.favorites_store import (
        apply_patch,
        load_favorites,
        save_favorites,
    )

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "invalid json"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "expected object"}, status_code=400)
    scope = body.get("scope")
    item_id = str(body.get("id", "") or "")
    patch = body.get("patch")
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else None
    if scope not in ("match", "player") or not item_id:
        return JSONResponse({"error": "scope must be match|player and id required"}, status_code=400)
    if not isinstance(patch, dict):
        return JSONResponse({"error": "patch object required"}, status_code=400)
    with _favorites_lock():
        doc = load_favorites(OUT_DIR)
        entry = apply_patch(doc, scope, item_id, patch, meta)
        save_favorites(OUT_DIR, doc)
    logger.info("favorites %s/%s updated", scope, item_id[:16])
    return JSONResponse({"ok": True, "entry": entry})


def _favorites_lock():
    """Single-process write lock (module-level; monkeypatch-friendly indirection)."""
    from cs_analyzer.web import favorites_store

    return favorites_store._lock


@app.get("/compare", response_class=HTMLResponse)
def compare_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "compare.html", {})


@app.get("/system", response_class=HTMLResponse)
def system_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "system.html", {})


@app.get("/{placeholder}", response_class=HTMLResponse)
def placeholder_page(request: Request, placeholder: str):
    """Catch-all for unknown single-segment paths (Phase S: the old
    _PLACEHOLDER_PAGES registry has been empty since Phase L made all five
    "placeholder" pages real — the mechanism was dead code)."""
    return TEMPLATES.TemplateResponse(request, "error.html", {"message": "页面不存在"}, status_code=404)


def _save_upload(file: UploadFile) -> Path:
    """Persist an uploaded .dem into demos/, resolving filename collisions.

    Same-name-same-size is treated as the same file (overwrite in place);
    otherwise a numeric suffix is appended. Non-.dem names are rejected by
    the route (server-side check — the dropzone's accept filter is advisory
    only and a crafted POST skips it).
    """
    demos_dir = _demos_dir()
    demos_dir.mkdir(exist_ok=True)
    name = Path(file.filename or "upload.dem").name or "upload.dem"
    if not name.lower().endswith(".dem"):
        raise ValueError(f"只支持 .dem 文件：{name}")
    dest = demos_dir / name
    if dest.exists():
        # compare sizes without loading either into memory; never close the
        # upload stream here — it is still read afterwards by copyfileobj
        file.file.seek(0, 2)
        same = file.file.tell() == dest.stat().st_size
        file.file.seek(0)
        if not same:
            stem, suffix = dest.stem, dest.suffix or ".dem"
            n = 2
            while (demos_dir / f"{stem}-{n}{suffix}").exists():
                n += 1
            dest = demos_dir / f"{stem}-{n}{suffix}"
            logger.info("upload name collision: %s -> %s", name, dest.name)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return dest


@app.post("/upload")
def upload(request: Request, files: list[UploadFile] = File(...)):
    """Multi-demo upload: save all, dedup by content hash, batch-parse the rest.

    Sync def on purpose (Phase S): file copies are blocking MBs-to-GBs IO —
    as async def they ran on the event loop and froze every other request
    for the whole upload; FastAPI runs sync handlers in its thread pool.
    """
    saved: list[tuple[str, Path]] = []
    for f in files:
        try:
            dest = _save_upload(f)
        except (OSError, ValueError) as exc:
            # ValueError = non-.dem name rejected before anything hit disk
            logger.info("upload rejected: %s (%s)", f.filename, exc)
            saved.append((f.filename or "?", exc))
            continue
        saved.append((Path(f.filename or dest.name).name, dest))

    rows = []  # batch_jobs.html rows: {label, job_id|None, state}
    cache = _cache()
    for label, dest in saved:
        if isinstance(dest, BaseException):
            # OSError = save failure; ValueError = non-.dem name rejected
            rows.append({"label": label, "job_id": None, "state": "error",
                         "error": str(dest), "demo_hash": None})
            continue
        try:
            demo_hash = DemoCache.hash_demo(dest)
        except OSError as exc:
            logger.exception("hash failed for %s", dest)
            rows.append({"label": label, "job_id": None, "state": "error",
                         "error": str(exc), "demo_hash": None})
            continue
        if cache.exists(demo_hash):
            logger.info("upload duplicate skipped: %s (%s)", label, demo_hash[:12])
            rows.append({"label": label, "job_id": None, "state": "duplicate",
                         "error": None, "demo_hash": demo_hash})
            continue
        job_id = tasks.tasks.submit(_parse_job, label=label, path=str(dest))
        rows.append({"label": label, "job_id": job_id, "state": "submitted",
                     "error": None, "demo_hash": demo_hash})

    return TEMPLATES.TemplateResponse(
        request, "batch_jobs.html", {"rows": rows, "action": "解析 demo"}
    )


# F7: per-demo-hash parse locks. Two jobs for the same demo (double-clicked
# 一键入库, upload + import racing, two tabs) must not parse concurrently —
# both would miss the cache and then write the same <hash>/ dir (model.json
# + parquet are plain writes, a torn interleaving corrupts the entry).
_parse_locks: dict[str, threading.Lock] = {}
_parse_locks_guard = threading.Lock()


def _parse_lock(demo_hash: str) -> threading.Lock:
    with _parse_locks_guard:
        lock = _parse_locks.get(demo_hash)
        if lock is None:
            lock = threading.Lock()
            _parse_locks[demo_hash] = lock
        return lock


def _parse_job(path: str) -> str:
    from cs_analyzer.web.aggregation import invalidate_aggregate

    try:
        from cs_analyzer.parser.manager import ParseManager

        demo_hash = DemoCache.hash_demo(Path(path))
        with _parse_lock(demo_hash):
            cache = _cache()
            if cache.exists(demo_hash):
                # another job for the same content finished while we waited
                demo = cache.load(demo_hash)
                if demo is not None:
                    return demo.metadata.demo_hash
            manager = ParseManager(cache=cache)
            demo = manager.parse(path, use_cache=True)
            return demo.metadata.demo_hash
    finally:
        # success or failure: the cache set may have changed (a failed parse
        # can still leave a partial cache dir) — drop the aggregate memo
        invalidate_aggregate()


@app.get("/api/jobs")
def job_list():
    """Recent jobs snapshot for the system-page monitor (newest first)."""
    return JSONResponse([j.as_dict() for j in tasks.tasks.recent(30)])


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = tasks.tasks.get_status(job_id)
    if job is None:
        return JSONResponse({"status": "unknown"})
    return JSONResponse(job.as_dict())


@app.get("/match/{demo_hash}", response_class=HTMLResponse)
def match_detail(request: Request, demo_hash: str):
    demo = _load(demo_hash)
    if demo is None:
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": f"未找到 demo {demo_hash[:12]}，请先上传/解析"}, status_code=404
        )
    analysis = _analyze(demo)
    ctx = _demo_context(demo, analysis)
    return TEMPLATES.TemplateResponse(request, "match_detail.html", ctx)


@app.get("/match/{demo_hash}/viewer", response_class=HTMLResponse)
def match_viewer(request: Request, demo_hash: str):
    demo = _load(demo_hash)
    if demo is None:
        # 收尾 V-B1: 404 分支必须真的返回 404 —— 漏 status_code 时 error.html
        # 会以 200 出去，与 /match、/player 的 404 分支不一致。
        return TEMPLATES.TemplateResponse(
            request, "error.html",
            {"message": f"未找到 demo {demo_hash[:12]}（缓存可能正在后台重解析，请稍后刷新重试）"},
            status_code=404,
        )
    meta = demo.metadata
    reg = demo.regular_rounds
    return TEMPLATES.TemplateResponse(
        request, "replay_viewer.html",
        {
            "demo": {
                "hash": meta.demo_hash,
                "filename": Path(meta.demo_path).name,
                "map_name": meta.map_name,
                "t_score": reg[-1].t_score if reg else 0,
                "ct_score": reg[-1].ct_score if reg else 0,
                "num_rounds": len(reg),
            },
        },
    )


@app.get("/match/{demo_hash}/overlap", response_class=HTMLResponse)
def match_overlap(request: Request, demo_hash: str):
    """Round-overlap (回合重叠) is a sub-mode of the replay viewer (Phase J).

    The standalone page is retired: this route now serves the replay viewer,
    whose JS auto-enters overlap mode for the /overlap path. Old bookmarks
    and deep links keep working with identical semantics.
    """
    return match_viewer(request, demo_hash)


# ---- chart data (ECharts payloads; rendering happens in the browser) ----

@app.get("/api/demo/{demo_hash}/charts.json")
def demo_charts(demo_hash: str):
    """Six-axis radar payload for every player in the demo."""
    from cs_analyzer.web.chart_data import radar_payload

    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    analysis = _analyze(demo)
    return JSONResponse(radar_payload(analysis["basic"], analysis["ratings"]))


@app.get("/api/demo/{demo_hash}/player/{steamid}/charts.json")
def player_charts(demo_hash: str, steamid: str):
    """Map-position heatmap / utility scatter / style metrics for one player."""
    from cs_analyzer.web.chart_data import (
        player_position_payload,
        player_style_payload,
        player_utility_payload,
    )

    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    analysis = _analyze(demo)
    pref = analysis["preference"]
    return JSONResponse(
        {
            "heatmap": player_position_payload(pref, steamid, demo),
            "utility": player_utility_payload(pref, steamid, demo),
            "style": player_style_payload(pref, steamid),
            "map_image": f"/maps/{demo.metadata.map_name}.png",
        }
    )


@app.get("/api/aggregate/charts.json")
def aggregate_charts():
    """Cross-demo matrix / bars / trends payload."""
    from cs_analyzer.web.aggregation import aggregated
    from cs_analyzer.web.chart_data import aggregate_payload

    result = aggregated()
    return JSONResponse(aggregate_payload(result))


# ---- Phase F M7/M8: advanced analysis payloads ----

@app.get("/api/demo/{demo_hash}/analysis/duels.json")
def duels_charts(demo_hash: str):
    """Duel matrix heatmap payload (对枪矩阵)."""
    from cs_analyzer.web.chart_data import duels_payload

    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    result = _analyze_module(demo, "duels")
    return JSONResponse(duels_payload(result))


@app.get("/api/demo/{demo_hash}/analysis/economy.json")
def economy_charts(demo_hash: str):
    """Per-round buy classification + win-by-buy payload (经济分析)."""
    from cs_analyzer.web.chart_data import economy_payload

    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    result = _analyze_module(demo, "economy")
    return JSONResponse(economy_payload(result))


@app.get("/api/demo/{demo_hash}/analysis/utility.json")
def utility_charts(demo_hash: str):
    """Flash value ranking + smoke denial payload (道具效用)."""
    from cs_analyzer.web.chart_data import utility_payload

    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    result = _analyze_module(demo, "utility_effect")
    return JSONResponse(utility_payload(result))


@app.get("/api/demo/{demo_hash}/analysis/routes.json")
def routes_charts(demo_hash: str):
    """Opening route clusters over the map image (开局路线)."""
    from cs_analyzer.maps.loader import load_map_or_fallback
    from cs_analyzer.web.chart_data import routes_payload

    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    result = _analyze_module(demo, "routes")
    map_res = load_map_or_fallback(demo.metadata.map_name, demo.ticks)
    payload = routes_payload(result, map_res)
    payload["map_image"] = f"/maps/{demo.metadata.map_name}.png"
    payload["has_map_image"] = map_res.image_path is not None
    return JSONResponse(payload)


# ---- Phase I: deepening-module endpoints ----


@app.get("/api/demo/{demo_hash}/analysis/kill_context.json")
def kill_context_charts(demo_hash: str):
    """Kill-context badges + MVP/pickups + weapon mix (击杀情境)."""
    from cs_analyzer.web.chart_data import kill_context_payload

    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    return JSONResponse(kill_context_payload(_analyze_module(demo, "kill_context")))


@app.get("/api/demo/{demo_hash}/analysis/hitgroups.json")
def hitgroups_charts(demo_hash: str):
    """Hitgroup damage distribution + armor efficiency (部位伤害)."""
    from cs_analyzer.web.chart_data import hitgroups_payload

    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    return JSONResponse(hitgroups_payload(_analyze_module(demo, "hitgroups")))


@app.get("/api/demo/{demo_hash}/analysis/aim.json")
def aim_charts(demo_hash: str):
    """Fire->kill conversion + movement-state fire shares (枪法纪律)."""
    from cs_analyzer.web.chart_data import aim_payload

    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    return JSONResponse(aim_payload(_analyze_module(demo, "aim")))


@app.get("/api/demo/{demo_hash}/analysis/postplant.json")
def postplant_charts(demo_hash: str):
    """Post-plant hold/retake/defuse analytics (下包后分析)."""
    from cs_analyzer.web.chart_data import postplant_payload

    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    return JSONResponse(postplant_payload(_analyze_module(demo, "postplant")))


@app.get("/api/demo/{demo_hash}/analysis/weapons.json")
def weapons_splits_charts(demo_hash: str):
    """Per-player kill/death splits by weapon category (武器拆分)."""
    from cs_analyzer.web.chart_data import weapon_splits_payload

    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    return JSONResponse(weapon_splits_payload(_analyze_module(demo, "weapon_splits")))


@app.get("/api/demo/{demo_hash}/analysis/weapon_timeline.json")
def weapon_timeline_charts(demo_hash: str):
    """Per-player weapon hold segments + round equips (U2 武器时间线)."""
    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    result = _analyze_module(demo, "weapon_timeline")
    tick_rate = demo.metadata.tick_rate or 64
    players = []
    for p in result.players:
        players.append({
            "steamid": p.steamid, "name": p.name, "team": p.team,
            "holds": [{"weapon": h.weapon, "seconds": round(h.ticks / tick_rate, 1),
                       "segments": h.segments, "kills": h.kills} for h in p.holds],
            "round_equips": p.round_equips,
        })
    return JSONResponse({"players": players, "rounds": result.rounds_total,
                         "tick_rate": tick_rate})


@app.get("/api/demo/{demo_hash}/analysis/win_probability.json")
def win_probability_charts(demo_hash: str):
    """Round win-probability curve (V2) + cross-demo LOO metrics.

    Curve source: the OOS curve from the LOO memo (trained on every OTHER
    demo — the honest generalization number) when the memo is warm; the
    per-demo in-sample fit is the cold fallback, labeled in `note`.
    loo_memo_peek reads the WARM memo only: a cold first visit must not pay
    the whole-library scan synchronously (U1 lesson); warmup wave2
    materializes it in the background.
    """
    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    result = _analyze_module(demo, "win_probability")
    from cs_analyzer.web.winprob_loo import loo_memo_peek

    memo = loo_memo_peek()
    entry = (memo or {}).get("demos", {}).get(demo_hash)
    loo_auc = entry.get("auc") if entry else None

    # OOS merge: the T-view snapshots' p_win is replaced by the leave-one-out
    # prediction at the same (round, tick). Band fields go None — this round
    # ships no per-point band on the OOS curve (35 pooled bootstrap refits
    # were judged not worth it; docs/research-ledger.md). Snapshots without
    # an OOS point keep the in-sample value.
    oos_t: dict[tuple[int, int], float] = {}
    if entry:
        by_pos = (memo or {}).get("oos_curves", {}).get(demo_hash, {}).get("by_pos", {})
        for key, p in by_pos.items():
            rn_s, tk_s, s_s = key.split(":")
            if int(s_s) == 1:  # T-view only — the page curve's perspective
                oos_t[(int(rn_s), int(tk_s))] = float(p)
    curve_source = "oos" if oos_t else "insample"

    rounds_out = []
    for rnd in result.rounds:
        rows = []
        for s in rnd:
            d = {"round": s.round, "tick": s.tick, "side": s.side,
                 "alive_diff": s.alive_diff, "buy_diff": round(s.buy_diff, 2),
                 "planted": s.planted, "p_win": s.p_win,
                 "p_lo": s.p_lo, "p_hi": s.p_hi, "outcome": s.outcome}
            if oos_t:
                p = oos_t.get((s.round, s.tick))
                if p is not None:
                    d["p_win"], d["p_lo"], d["p_hi"] = round(p, 3), None, None
            rows.append(d)
        rounds_out.append(rows)

    note = result.sample_note
    if curve_source == "oos" and loo_auc is not None:
        n_demos = (memo or {}).get("n_demos")
        brier = (memo or {}).get("brier")
        # 收尾 V-A2: 页面已加 "V2·跨场" 来源标——note 里不再重复"跨场诚实曲线"前缀
        note = (f"其余 {n_demos - 1} 场训练 · 本场留一 AUC {loo_auc:.2f}"
                + (f" · 库级 Brier {brier:.3f}" if brier is not None else ""))

    return JSONResponse({
        "rounds": rounds_out,
        "auc": result.model_auc, "n_train_rounds": result.n_train_rounds,
        "model": result.model_version, "curve_source": curve_source,
        "loo_auc": loo_auc,
        "brier": (memo or {}).get("brier"),
        "calibration": (memo or {}).get("calibration"),
        "note": note,
    })


# S3-C1: the per-demo economy_ev endpoint is gone — the economy tab
# deliberately consumes the cross-library /api/ev/table.json (pooled cells;
# per-demo EV tables are all grey under the n>=5 gate). The analysis module
# and the ev_cells shard family remain in service via ev_data.


@app.get("/api/ev/table.json")
def economy_ev_table():
    """Cross-library decision-EV query table (V2 决策 EV)."""
    from cs_analyzer.web.ev_data import ev_table

    return JSONResponse(ev_table())


# ---- Phase R: research panels (枪法科学 / 失利归因) — routes registered
# BEFORE the /{placeholder} catch-all (铁律 5) ----

@app.get("/api/aim-science.json")
def aim_science_cross():
    """R3: cross-library aim-science report (peek-only, S3-B2).

    Cold shards + a missed wave2 window used to block this request on a
    whole-library scan (the U1 landmine shape). Serve the warm memo or 503 —
    the career panel already renders 预热中 on failure. Tests warm explicitly
    via aim_data.aim_report() per the documented report-level contract."""
    from cs_analyzer.web.aim_data import aim_peek

    memo = aim_peek()
    if memo is None:
        return JSONResponse({"status": "warming"}, status_code=503)
    return JSONResponse(memo)


@app.get("/api/demo/{demo_hash}/loss-attribution.json")
def loss_attribution_demo(demo_hash: str):
    """R5: per-round loss tags for one demo (both teams, no 'our side' guess)."""
    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    result = _analyze_module(demo, "loss_attribution")
    return JSONResponse({
        "rounds": result.rounds,
        "teams": result.teams,
        "notes": result.notes,
    })


@app.get("/api/duel-model.json")
def duel_model_cross(player: str | None = None):
    """Round 2: cross-library duel-model board (peek-only, S3-B2 precedent).

    503 {"status": "warming"} until wave2 materialized the duelmo memo —
    request paths must never trigger a whole-library scan (U1 lesson).
    ?player= narrows to one player's 对枪实力 row."""
    from cs_analyzer.web import duel_data

    if duel_data.duel_peek() is None:
        return JSONResponse({"status": "warming"}, status_code=503)
    if player:
        p = duel_data.duel_for(player)
        if p is None:
            raise HTTPException(status_code=404, detail="player has no duel data")
        return JSONResponse(p)
    return JSONResponse(duel_data.duel_report())


@app.get("/api/loss-patterns.json")
def loss_patterns_cross(player: str | None = None):
    """R5: cross-library loss-mode distribution (per team, or ?player= per player).

    S3-B2: peek-only — 503 {"status": "warming"} until wave2 materialized the
    memo (request paths must never trigger a whole-library scan; same U1
    lesson as aim-science above)."""
    from cs_analyzer.analysis.stats import wilson_interval
    from cs_analyzer.web import loss_data

    if loss_data.loss_peek() is None:
        return JSONResponse({"status": "warming"}, status_code=503)

    if player:
        p = loss_data.loss_patterns_for(player)
        if p is None:
            raise HTTPException(status_code=404, detail="player has no loss data")
        return JSONResponse(p)
    report = loss_data.loss_report()
    out = []
    for t in report["teams"]:
        n = t["lost_rounds"]
        tags = []
        for tag, c in t["tags"].items():
            lo, hi = wilson_interval(c, n) if n else (0.0, 0.0)
            tags.append({
                "tag": tag, "count": c, "share": round(c / n, 3) if n else 0.0,
                "conf": {"lo": round(lo, 3), "hi": round(hi, 3), "n": n,
                         "gated": n < 30},
            })
        out.append({"team": t["team"], "lost_rounds": n, "tags": tags})
    return JSONResponse({"teams": out, "demos": report["demos"],
                         "tag_defs": report["tag_defs"]})


# ---- Phase H: highlights / compare / system payloads ----

@app.get("/api/demo/{demo_hash}/highlights.json")
def demo_highlights(demo_hash: str):
    """Single-demo highlight moments (多杀/残局/ACE), best-first."""
    from cs_analyzer.web.chart_data import highlights_payload

    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    result = _analyze_module(demo, "highlights")
    return JSONResponse(highlights_payload(result))


@app.get("/api/highlights.json")
def all_highlights():
    """Global highlight feed across every cached demo, best-first."""
    return JSONResponse({"highlights": _top_highlights(200)})


@app.get("/api/compare/charts.json")
def compare_charts():
    """Big-sample leaderboard + percentile ranks + career radar overlay."""
    from cs_analyzer.web.chart_data import compare_payload
    from cs_analyzer.web.aggregation import aggregated

    return JSONResponse(compare_payload(aggregated()))


@app.get("/api/pro-baseline.json")
def pro_baseline_card():
    """D3b: pro reference card (bo3.gg stats layer; demo layer needs FACEIT key)."""
    from cs_analyzer.web.pro_baseline_data import pro_baseline_card as card

    return JSONResponse(card())


@app.get("/api/compare/teamplay.json")
def compare_teamplay_legacy():
    """Phase X alias: the section moved to /teams; keep old bookmarks working."""
    from cs_analyzer.web.teamplay_data import teamplay_report

    return JSONResponse(teamplay_report())


@app.get("/api/teams/teamplay.json")
def teams_teamplay():
    """K5: five-stack link network + stack-vs-mixed + portraits (5E set)."""
    from cs_analyzer.web.teamplay_data import teamplay_report

    return JSONResponse(teamplay_report())


@app.get("/api/warmup.json")
def warmup_status(request: Request):
    """Cold-start prewarm progress (L0).

    ?wait=1 long-polls up to ~20s for readiness; the dashboard skeleton JS
    re-polls until {phase: "done", ready: true} and then fills the counts +
    highlight feed that the server rendered as placeholders.
    """
    from cs_analyzer.web import warmup

    if request.query_params.get("wait"):
        return JSONResponse(warmup.wait_until_ready())
    return JSONResponse(warmup.status())


@app.get("/api/warmup/dashboard.json")
def warmup_dashboard_payload():
    """Dashboard hydration payload (L0): player count + server-rendered
    highlight-card fragment (single source of truth: _highlight_card.html)."""

    highlights = _top_highlights(6)
    highlights_html = ""
    if highlights:
        tpl = TEMPLATES.env.get_template("_highlight_card.html")
        cards = "".join(tpl.render(h=h) for h in highlights)
        highlights_html = f'<div class="grid hl-grid" id="dash-highlights">{cards}</div>'
    from cs_analyzer.web.aggregation import aggregated

    return JSONResponse({
        "player_count": aggregated().total_players,
        "highlights_html": highlights_html,
    })


# ---- Phase L2: utility lab (道具专题) ----

@app.get("/api/utilitylab.json")
def utilitylab_api():
    from cs_analyzer.web.utilitylab_data import utilitylab_report

    return JSONResponse(utilitylab_report())


@app.get("/api/map-analysis.json")
def map_analysis_api():
    from cs_analyzer.web.mapdata import map_report

    return JSONResponse(map_report())


@app.get("/api/lineups.json")
def lineups_api():
    from cs_analyzer.web.lineups_data import lineups_report

    return JSONResponse(lineups_report())


# ---- Phase L5: report export APIs ----

def _report_out_dir() -> Path:
    return Path("output") / "reports"


@app.post("/api/report/{demo_hash}/export")
async def report_export(demo_hash: str, request: Request):
    """Export the print report as PNG (full-page) or PDF via playwright.

    501 with guidance when playwright/chromium is missing; 404 unknown demo.
    """
    from cs_analyzer.web.report_export import (
        ReportUnavailableError,
        export_match_report,
    )

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    fmt = str(body.get("format", "png")).lower() if isinstance(body, dict) else "png"
    if fmt not in ("png", "pdf"):
        return JSONResponse({"error": "format must be png|pdf"}, status_code=400)
    if _load(demo_hash) is None:
        return JSONResponse({"error": "未找到该对局"}, status_code=404)
    base = str(request.base_url).rstrip("/")
    import asyncio

    try:
        # playwright's sync API cannot run inside the event loop — offload
        target = await asyncio.to_thread(
            export_match_report, base, demo_hash, fmt, _report_out_dir())
    except ReportUnavailableError as exc:
        return JSONResponse({"error": str(exc)}, status_code=501)
    except Exception:  # noqa: BLE001
        logger.exception("report export failed for %s", demo_hash[:12])
        return JSONResponse({"error": "导出失败，见服务端日志"}, status_code=500)
    return JSONResponse({"ok": True, "file": target.name,
                         "url": f"/report-exports/{target.name}"})


@app.get("/api/report/exports.json")
def report_exports():
    from cs_analyzer.web.report_export import list_exports

    return JSONResponse({"exports": list_exports(_report_out_dir())})


@app.get("/api/report/demos.json")
def report_demos():
    """Dropdown source: one row per cached demo (hash/map/filename)."""
    demos = store.list_demos(_cache().cache_dir)
    return JSONResponse({"demos": [
        {"demo_hash": d["demo_hash"], "map_name": d["map_name"], "filename": d["filename"]}
        for d in demos
    ]})


@app.get("/report-exports/{filename}")
def report_export_file(filename: str):
    """Serve an exported report file (name-validated, no traversal)."""
    from cs_analyzer.web.report_export import list_exports

    allowed = {e["file"]: e for e in list_exports(_report_out_dir())}
    entry = allowed.get(filename)
    if entry is None:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(_report_out_dir() / filename, filename=filename)


@app.get("/api/system/status.json")
def system_status():
    """Cache size + pipeline version constants for the system page."""
    import os

    from cs_analyzer.cache import PARSER_VERSION
    from cs_analyzer.web import viewer_data

    cache_dir = _cache().cache_dir
    entries = [d for d in cache_dir.glob("*") if d.is_dir()]
    total = 0
    for root, _dirs, files in os.walk(cache_dir):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                continue

    return JSONResponse(
        {
            "cache_entries": len(entries),
            "cache_size_mb": round(total / 1e6, 1),
            "parser_version": PARSER_VERSION,
            "viewer_data_version": viewer_data.VIEWER_DATA_VERSION,
            "layer_version": viewer_data.LAYER_VERSION,
            # T1: disk snapshot inventory for the performance panel
            "snapshots": _snapshots_status(),
            "warmup": _warmup_status_public(),
        }
    )


def _warmup_status_public() -> dict:
    from cs_analyzer.web import warmup

    st = warmup.status()
    st.pop("error", "")  # the traceback is noise in the panel
    return st


def _snapshots_status() -> dict:
    from cs_analyzer.web import snapshots

    return snapshots.status(OUT_DIR, _cache().cache_dir)


@app.get("/api/system/unparsed.json")
def system_unparsed():
    """.dem files in demos/ that have no cache entry yet."""
    cache = _cache()
    demos_dir = _demos_dir()
    files: list[str] = []
    if demos_dir.is_dir():
        for dem in sorted(demos_dir.glob("*.dem")):
            try:
                if not cache.exists(DemoCache.hash_demo(dem)):
                    files.append(dem.name)
            except OSError:
                continue
    return JSONResponse({"files": files})


@app.post("/system/import")
def system_import():
    """Submit parse jobs for every unparsed .dem, then return to /system.

    Invalidate once AFTER the loop (Phase S): each parse job invalidates in
    its own finally anyway; N invalidates here just re-armed warmup N times.
    """
    cache = _cache()
    demos_dir = _demos_dir()
    submitted = 0
    if demos_dir.is_dir():
        for dem in sorted(demos_dir.glob("*.dem")):
            try:
                if cache.exists(DemoCache.hash_demo(dem)):
                    continue
            except OSError:
                continue
            tasks.tasks.submit(_parse_job, label=dem.name, path=str(dem))
            submitted += 1
    if submitted:
        from cs_analyzer.web.aggregation import invalidate_aggregate

        invalidate_aggregate()
    return RedirectResponse("/system", status_code=303)


@app.get("/api/system/scan-sources.json")
def system_scan_sources():
    """S2-A5: dry-run scan of the platform source dirs (configs/demo_sources.yaml).

    Reuses the Phase Y import semantics (zip inner-.dem CONTENT hash vs
    demos/) but NEVER writes: this endpoint only reports what a real import
    would do (new / duplicate / corrupt per platform). Imports stay on the
    existing one-click path (POST /system/import after a manual copy) or the
    CLI script with its explicit --dry-run flag.
    """
    import hashlib
    import zipfile

    def _sha_stream(fh) -> str:
        h = hashlib.sha256()
        for part in iter(lambda: fh.read(1 << 20), b""):
            h.update(part)
        return h.hexdigest()

    demos_dir = _demos_dir()
    known: set[str] = set()
    if demos_dir.is_dir():
        for dem in demos_dir.glob("*.dem"):
            try:
                known.add(_sha_stream(dem.open("rb")))
            except OSError:
                continue

    import yaml

    cfg_path = Path("configs/demo_sources.yaml")
    if not cfg_path.exists():
        raise HTTPException(status_code=404, detail="configs/demo_sources.yaml 不存在")
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    sources = []
    total_new = 0
    for name, cfg in raw.items():
        if not isinstance(cfg, dict) or not cfg.get("enabled"):
            continue
        src_path = Path(cfg.get("path", ""))
        pattern = cfg.get("pattern", "*.zip")
        entry = {"name": name, "path": str(src_path), "exists": src_path.is_dir(),
                 "zips": 0, "new": 0, "duplicates": 0, "corrupt": 0,
                 "new_files": []}
        if src_path.is_dir():
            for zp in sorted(src_path.glob(pattern)):
                entry["zips"] += 1
                try:
                    with zipfile.ZipFile(zp) as zf:
                        inners = [n for n in zf.namelist()
                                  if n.lower().endswith(".dem")]
                except Exception:  # noqa: BLE001 — truncated EOCD etc.
                    entry["corrupt"] += 1
                    continue
                for inner in inners:
                    try:
                        with zipfile.ZipFile(zp) as zf, zf.open(inner) as fh:
                            digest = _sha_stream(fh)
                    except Exception:  # noqa: BLE001
                        entry["corrupt"] += 1
                        continue
                    if digest in known or (demos_dir / Path(inner).name).exists():
                        entry["duplicates"] += 1
                    else:
                        entry["new"] += 1
                        entry["new_files"].append(Path(inner).name)
        total_new += entry["new"]
        sources.append(entry)

    return JSONResponse({
        "sources": sources, "total_new": total_new,
        "known_demos": len(known),
        "note": "dry-run 只报告，不导入；导入请将新 demo 复制到 demos/ 后用一键入库",
    })


# ---- 2D map replay viewer (B2) ----

# ---- real-time canvas viewer data (Phase C) ----

@app.get("/api/demo/{demo_hash}/viewer-data")
def get_viewer_data(demo_hash: str):
    """Per-player snapshot payload for the canvas viewer. Serves the cached
    artifact when version-fresh; otherwise builds it inline (<10s)."""
    import time as _time

    from cs_analyzer.web import viewer_data

    cached = viewer_data.load_viewer_data(demo_hash, OUT_DIR)
    if cached is not None:
        return FileResponse(
            viewer_data.viewer_data_path(demo_hash, OUT_DIR),
            media_type="application/json",
            headers={"Cache-Control": "no-cache"},
        )
    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    t0 = _time.time()
    path, size = viewer_data.build_and_save(demo, OUT_DIR)
    logger.info("viewer-data built in %.1fs (%.2f MB)", _time.time() - t0, size / 1e6)
    return FileResponse(path, media_type="application/json",
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/demo/{demo_hash}/viewer-layers")
def get_viewer_layers(demo_hash: str, with_layers: str = Query("shots,economy", alias="with")):
    """Heavy overlay layers (shots/economy), lazy-loaded after first paint.

    Built as ONE artifact covering every known layer key: at the <=250KB-gzip
    budget, splitting per key would multiply cache artifacts for no gain.
    Unknown `with=` keys are ignored with a warning.
    """
    import time as _time

    from cs_analyzer.web import viewer_data

    requested = [k.strip() for k in with_layers.split(",") if k.strip()]
    dropped = [k for k in requested if k not in viewer_data.LAYER_KEYS]
    if dropped:
        logger.warning("viewer-layers: ignoring unknown layer keys %s", dropped)

    cached = viewer_data.load_viewer_layers(demo_hash, OUT_DIR)
    if cached is not None:
        path = viewer_data.viewer_layers_path(demo_hash, OUT_DIR)
    else:
        demo = _load(demo_hash)
        if demo is None:
            return JSONResponse({"error": "demo 未找到"}, status_code=404)
        t0 = _time.time()
        path, size = viewer_data.build_and_save_layers(demo, OUT_DIR)
        logger.info("viewer-layers built in %.1fs (%.2f MB)", _time.time() - t0, size / 1e6)
    return FileResponse(path, media_type="application/json",
                        headers={"Cache-Control": "no-cache"})


# ---- Phase H+: user-tunable viewer visual preferences ----

def _ui_prefs_path() -> Path:
    return OUT_DIR / "ui_prefs.json"


@app.get("/api/ui-prefs")
def ui_prefs_get():
    """Persisted viewer visual preferences (empty object when never saved)."""
    p = _ui_prefs_path()
    if not p.exists():
        return JSONResponse({})
    try:
        return JSONResponse(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return JSONResponse({})


@app.post("/api/ui-prefs")
async def ui_prefs_set(request: Request):
    """Save viewer visual preferences from the tuning panel (atomic write,
    same lock discipline as favorites — two concurrent POSTs must not be
    able to interleave into a half-written file)."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "invalid json"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "expected object"}, status_code=400)
    import os

    from cs_analyzer.web import favorites_store

    p = _ui_prefs_path()
    with favorites_store._lock:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    logger.info("ui-prefs saved (%d keys)", len(body))
    return JSONResponse({"ok": True, "count": len(body)})


@app.get("/maps/{map_name}")
def map_image(map_name: str):
    """Serve official radar PNGs (immutable: images are content-pinned by name)."""
    from cs_analyzer.maps.loader import MAPS_DATA_DIR

    allowed = {p.stem: p for p in MAPS_DATA_DIR.glob("*.png")}
    p = allowed.get(map_name.removesuffix(".png"))
    if p is None:
        return JSONResponse({"error": "unknown map"}, status_code=404)
    return FileResponse(p, headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ---- helpers ----

def _map_availability(maps: list[str]) -> dict:
    """Which maps have a radar PNG (missing ones render a flat placeholder)."""
    from cs_analyzer.maps.loader import MAPS_DATA_DIR

    available = {p.stem for p in MAPS_DATA_DIR.glob("*.png")}
    return {"map_images": {m: f"/maps/{m}.png" for m in maps if m in available}}


def _load(demo_hash: str) -> ParsedDemo | None:
    return store.load_demo(demo_hash, _cache().cache_dir)


_sweep_started = False


def _stale_cache_sweep() -> None:
    """Reconcile the parse cache with demos/ (once per process, cheap hashing).

    Two directions:
    - stale: a cached demo whose .dem re-hashed differently (e.g.
      PARSER_VERSION bump re-creates the cache dir) is re-parsed in the
      background task pool;
    - orphan: a cache entry whose source .dem is gone (deleted after a test
      upload, manual cleanup) is GC'd — otherwise it keeps masquerading as a
      real match in every whole-library report forever.

    Without this, a version bump leaves every demo 404 until manually
    re-parsed, and deleted sources leave zombie matches polluting aggregates.
    """
    global _sweep_started
    if _sweep_started:
        return
    _sweep_started = True
    cache = _cache()
    demos_dir = _demos_dir()
    if not demos_dir.is_dir():
        return
    from cs_analyzer.analysis.library import cached_demo_hashes
    from cs_analyzer.web.aggregation import invalidate_aggregate

    known: set[str] = set()
    for dem in sorted(demos_dir.glob("*.dem")):
        try:
            demo_hash = DemoCache.hash_demo(dem)
        except OSError:
            logger.exception("sweep: hash failed for %s", dem)
            continue
        known.add(demo_hash)
        if cache.exists(demo_hash):
            continue
        logger.info("sweep: re-parsing stale demo %s (%s)", dem.name, demo_hash[:12])
        invalidate_aggregate()
        tasks.tasks.submit(_parse_job, label=dem.name, path=str(dem))
    # orphan GC: only when demos/ is non-empty (an emptied/moved demos dir
    # must not wipe the whole cache). Runs from lifespan before the server
    # accepts requests, so no parse job can be in flight here.
    if known:
        for demo_hash in cached_demo_hashes(cache.cache_dir):
            if demo_hash in known:
                continue
            logger.info("sweep: GC orphan cache %s (no source .dem)", demo_hash[:12])
            shutil.rmtree(Path(cache.cache_dir) / demo_hash, ignore_errors=True)
            invalidate_aggregate()


def _demo_context(demo: ParsedDemo, analysis: dict) -> dict:
    from cs_analyzer.web.match_data import demo_context

    return demo_context(demo, analysis)
