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
from pathlib import Path

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.gzip import GZipMiddleware

from cs_analyzer.analysis import AnalysisRunner
from cs_analyzer.analysis.aggregate import compute_aggregate
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

app = FastAPI(title="CsDemoAnalyzer 本地平台", version="0.1.0")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# static asset cache-buster: server start time, so a restart always hands the
# browser fresh CSS/JS (root cause fix for the "styles didn't update" reports)
import time as _time

TEMPLATES.env.globals["static_v"] = str(int(_time.time()))

_analysis_cache: dict[str, dict] = {}
_module_cache: dict[str, dict] = {}


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
    slot = _module_cache.setdefault(key, {})
    if module_name in slot:
        return slot[module_name]
    result = _runner().run_one(demo, module_name)
    slot[module_name] = result
    return result


# ---- pages ----

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    _stale_cache_sweep()  # no-op after the first call
    demos = store.list_demos(_cache().cache_dir)
    # "recent" = parsed_at desc (fallback: filename order already applied)
    recent = sorted(demos, key=lambda d: d.get("parsed_at") or "", reverse=True)[:8]
    from cs_analyzer.web.aggregation import aggregated

    agg = aggregated()
    highlights = _top_highlights(6)
    return TEMPLATES.TemplateResponse(
        request, "index.html",
        {
            "demos": demos,
            "recent": recent,
            "highlights": highlights,
            "total": len(demos),
            "map_count": len({d["map_name"] for d in demos}),
            "round_count": sum(d["num_rounds"] for d in demos),
            "player_count": agg.total_players,
            **_map_availability(sorted({d["map_name"] for d in demos})),
        },
    )


def _top_highlights(limit: int) -> list[dict]:
    """Global highlight feed, best-first (dashboard 精选). Fails soft."""
    from cs_analyzer.web.chart_data import highlights_payload

    merged: list[dict] = []
    try:
        for entry in store.list_demos(_cache().cache_dir):
            demo = _load(entry["demo_hash"])
            if demo is None:
                continue
            try:
                result = _analyze_module(demo, "highlights")
            except Exception:  # noqa: BLE001 — one bad demo must not kill the feed
                logger.exception("highlights failed for %s", entry["demo_hash"][:12])
                continue
            merged.extend(highlights_payload(result)["highlights"])
    except Exception:  # noqa: BLE001
        logger.exception("dashboard highlights feed failed")
        return []
    rank = {"ace": 0, "k4": 1, "1v4": 2, "k3": 3, "1v3": 4, "k2": 5, "1v2": 6}
    merged.sort(key=lambda h: (rank.get(h["tier"], 99), h["round"]))
    return merged[:limit]


# ---- legacy URL 301 redirects (Phase H): query strings pass through ----

def _redirect(request: Request, target: str) -> RedirectResponse:
    qs = str(request.url.query)
    return RedirectResponse(target + ("?" + qs if qs else ""), status_code=301)


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

    result = aggregated()
    row = next((p for p in result.players if p.steamid == steamid), None)
    if row is None:
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": f"未找到选手 {steamid}"}
        )
    return TEMPLATES.TemplateResponse(request, "player_career.html", {"p": row})


@app.get("/highlights", response_class=HTMLResponse)
def highlights_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "highlights.html", {})


@app.get("/compare", response_class=HTMLResponse)
def compare_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "compare.html", {})


@app.get("/system", response_class=HTMLResponse)
def system_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "system.html", {})


_PLACEHOLDER_PAGES = {
    "favorites": ("收藏与标注", "对局/选手打标签、收藏与备注，库页按标签筛选。"),
    "teams": ("队伍视图", "按队伍聚合：胜率/地图池/选手轮换，服务教练场景。"),
    "map-analysis": ("地图分析", "按地图聚合：胜率/常用路线/点位热力，地图池理解。"),
    "utility-lab": ("道具专题", "全库道具使用画像：闪光价值榜/烟中击杀/道具协同。"),
    "reports": ("报告导出", "单场报告一键导出 PDF/长图，或生成只读分享链接。"),
}


@app.get("/{placeholder}", response_class=HTMLResponse)
def placeholder_page(request: Request, placeholder: str):
    # /coverage retired from the web (CLI-only now) — 404, not a placeholder
    if placeholder in ("coverage",) or placeholder not in _PLACEHOLDER_PAGES:
        return TEMPLATES.TemplateResponse(request, "error.html", {"message": "页面不存在"})
    title, blurb = _PLACEHOLDER_PAGES[placeholder]
    return TEMPLATES.TemplateResponse(
        request, "placeholder.html", {"title": title, "blurb": blurb}
    )


def _save_upload(file: UploadFile) -> Path:
    """Persist an uploaded .dem into demos/, resolving filename collisions.

    Same-name-same-size is treated as the same file (overwrite in place);
    otherwise a numeric suffix is appended.
    """
    demos_dir = _demos_dir()
    demos_dir.mkdir(exist_ok=True)
    name = Path(file.filename or "upload.dem").name or "upload.dem"
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
async def upload(request: Request, files: list[UploadFile] = File(...)):
    """Multi-demo upload: save all, dedup by content hash, batch-parse the rest."""
    saved: list[tuple[str, Path]] = []
    for f in files:
        try:
            dest = _save_upload(f)
        except OSError as exc:
            logger.exception("failed to save upload %s", f.filename)
            saved.append((f.filename or "?", exc))
            continue
        saved.append((Path(f.filename or dest.name).name, dest))

    rows = []  # batch_jobs.html rows: {label, job_id|None, state}
    cache = _cache()
    for label, dest in saved:
        if isinstance(dest, OSError):
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


def _parse_job(path: str) -> str:
    from cs_analyzer.web.aggregation import invalidate_aggregate

    try:
        from cs_analyzer.parser.manager import ParseManager

        manager = ParseManager(cache=_cache())
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
            request, "error.html", {"message": f"未找到 demo {demo_hash[:12]}，请先上传/解析"}
        )
    analysis = _analyze(demo)
    ctx = _demo_context(demo, analysis)
    return TEMPLATES.TemplateResponse(request, "match_detail.html", ctx)


@app.get("/match/{demo_hash}/viewer", response_class=HTMLResponse)
def match_viewer(request: Request, demo_hash: str):
    demo = _load(demo_hash)
    if demo is None:
        return TEMPLATES.TemplateResponse(
            request, "error.html",
            {"message": f"未找到 demo {demo_hash[:12]}（缓存可能正在后台重解析，请稍后刷新重试）"},
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
    """Round-overlap analysis page (回合重叠): dedicated layout."""
    demo = _load(demo_hash)
    if demo is None:
        return TEMPLATES.TemplateResponse(
            request, "error.html",
            {"message": f"未找到 demo {demo_hash[:12]}（缓存可能正在后台重解析，请稍后刷新重试）"},
        )
    meta = demo.metadata
    return TEMPLATES.TemplateResponse(
        request, "overlap_viewer.html",
        {
            "demo": {
                "hash": meta.demo_hash,
                "filename": Path(meta.demo_path).name,
                "map_name": meta.map_name,
            },
        },
    )


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
    from cs_analyzer.web.chart_data import aggregate_payload

    result = compute_aggregate(_cache().cache_dir, _settings().analysis)
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
        }
    )


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
    """Submit parse jobs for every unparsed .dem, then return to /system."""
    cache = _cache()
    demos_dir = _demos_dir()
    if demos_dir.is_dir():
        for dem in sorted(demos_dir.glob("*.dem")):
            try:
                if cache.exists(DemoCache.hash_demo(dem)):
                    continue
            except OSError:
                continue
            from cs_analyzer.web.aggregation import invalidate_aggregate

            invalidate_aggregate()
            tasks.tasks.submit(_parse_job, label=dem.name, path=str(dem))
    return RedirectResponse("/system", status_code=303)


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


@app.get("/api/meta/weapons.json")
def weapons_meta():
    """Weapon alias/label/category table (mirror: static/js/weapon_meta.js)."""
    return JSONResponse(weapons.payload())


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
    """Save viewer visual preferences from the tuning panel."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "invalid json"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "expected object"}, status_code=400)
    p = _ui_prefs_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
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
    """Re-parse demos whose cache went stale (e.g. PARSER_VERSION bump).

    Runs once per process, on the first library page render: hashing is cheap,
    stale entries re-parse in the background task pool (~10s each). Without
    this, a version bump leaves every demo 404 until manually re-parsed.
    """
    global _sweep_started
    if _sweep_started:
        return
    _sweep_started = True
    cache = _cache()
    demos_dir = _demos_dir()
    if not demos_dir.is_dir():
        return
    for dem in sorted(demos_dir.glob("*.dem")):
        try:
            demo_hash = DemoCache.hash_demo(dem)
        except OSError:
            logger.exception("sweep: hash failed for %s", dem)
            continue
        if cache.exists(demo_hash):
            continue
        logger.info("sweep: re-parsing stale demo %s (%s)", dem.name, demo_hash[:12])
        from cs_analyzer.web.aggregation import invalidate_aggregate

        invalidate_aggregate()
        tasks.tasks.submit(_parse_job, label=dem.name, path=str(dem))


def _demo_context(demo: ParsedDemo, analysis: dict) -> dict:
    meta = demo.metadata
    reg = demo.regular_rounds
    t_score = reg[-1].t_score if reg else 0
    ct_score = reg[-1].ct_score if reg else 0

    basic = analysis["basic"]
    ratings = analysis["ratings"]
    from cs_analyzer.coverage import _player_position_stats

    pos_stats = _player_position_stats(demo)  # one pass, not once per player
    players = []
    for bs in basic.players:
        rt = ratings.by_steamid(bs.steamid) if ratings else None
        players.append(
            {
                "steamid": bs.steamid,
                "name": bs.name,
                "team": bs.team,
                "team_label": {"Team 2": "T", "Team 3": "CT"}.get(bs.team, "Team 0"),
                "K": bs.kills,
                "D": bs.deaths,
                "A": bs.assists,
                "ADR": round(bs.ADR, 1),
                "KPR": round(bs.KPR, 2),
                "Rating": round(rt.Rating, 2) if rt else 0.0,
                "RWS": round(rt.RWS, 1) if rt else 0.0,
                "KAST": round(rt.KAST, 0) if rt else 0,
                "replayable": pos_stats.get(bs.steamid, (False, 0.0))[0],
            }
        )
    players.sort(key=lambda p: p["Rating"], reverse=True)

    rounds = [
        {"number": r.number, "winner_side": r.winner_side, "t_score": r.t_score, "ct_score": r.ct_score}
        for r in reg
    ]
    kills = _kill_feed(demo)

    return {
        "demo": {
            "hash": meta.demo_hash,
            "filename": Path(meta.demo_path).name,
            "map_name": meta.map_name,
            "provider": meta.provider.value,
            "t_score": t_score,
            "ct_score": ct_score,
            "num_rounds": len(reg),
        },
        "players": players,
        "rounds": rounds,
        "kills": _kill_groups(demo, rounds),
        "has_preference": analysis["preference"] is not None,
    }


def _player_context(demo: ParsedDemo, analysis: dict, steamid: str) -> dict | None:
    meta = demo.metadata
    basic = analysis["basic"]
    ratings = analysis["ratings"]
    pref = analysis["preference"]
    bs = basic.by_steamid(steamid) if basic else None
    if bs is None:
        return None
    rt = ratings.by_steamid(steamid) if ratings else None
    from cs_analyzer.analysis.preference import PlayerPreference

    pp = None
    if pref is not None:
        pp = next((p for p in pref.players if p.steamid == steamid), None)

    replayable = _replayable(demo, steamid)

    player = {
        "steamid": steamid,
        "name": bs.name,
        "team": bs.team,
        "team_label": {"Team 2": "T", "Team 3": "CT"}.get(bs.team, "Team 0"),
        "K": bs.kills,
        "D": bs.deaths,
        "A": bs.assists,
        "ADR": round(bs.ADR, 1),
        "KPR": round(bs.KPR, 2),
        "HS%": round(bs.headshot_pct, 1),
        "Rating": round(rt.Rating, 2) if rt else 0.0,
        "RWS": round(rt.RWS, 1) if rt else 0.0,
        "KAST": round(rt.KAST, 0) if rt else 0,
        "replayable": replayable,
    }
    pref_data = None
    if pp is not None:
        pref_data = {
            "utility_counts": pp.utility_counts,
            "engagement_fraction": round(pp.avg_first_engagement_fraction, 2),
            "engagement_rounds": pp.engagement_rounds,
            "avg_pitch": round(pp.avg_pitch, 1),
            "pitch_samples": pp.pitch_samples,
            "position_count": len(pp.position_samples),
        }
    return {
        "demo": {
            "hash": meta.demo_hash,
            "filename": Path(meta.demo_path).name,
            "map_name": meta.map_name,
        },
        "player": player,
        "pref": pref_data,
    }


def _replayable(demo: ParsedDemo, steamid: str) -> bool:
    from cs_analyzer.coverage import _player_position_stats

    stats = _player_position_stats(demo)
    return stats.get(steamid, (False, 0.0))[0]


def _kill_feed(demo: ParsedDemo) -> list[dict]:
    df = demo.events.get("player_death")
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        rows.append(
            {
                "tick": int(r.get("tick", 0)),
                "round": _round_at_tick(demo, int(r.get("tick", 0))),
                "attacker": r.get("attacker_name", ""),
                "victim": r.get("user_name", ""),
                "weapon": r.get("weapon", ""),
            }
        )
    rows.sort(key=lambda x: x["tick"])
    return rows


def _kill_groups(demo: ParsedDemo, rounds: list[dict]) -> list[dict]:
    """Kill feed grouped by round (D3): [{round, winner_side, kills: [...]}].

    Keeps every kill (no truncation) but collapses each round group in the UI.
    """
    kills = _kill_feed(demo)
    if not kills:
        return []
    winner = {r["number"]: r["winner_side"] for r in rounds}
    groups: dict[int, list[dict]] = {}
    for k in kills:
        groups.setdefault(k["round"], []).append(k)
    return [
        {
            "round": rnd,
            "winner_side": winner.get(rnd, ""),
            "kills": groups[rnd],
        }
        for rnd in sorted(groups)
    ]


def _round_at_tick(demo: ParsedDemo, tick: int) -> int:
    rnd = demo.data.round_at_tick(tick)
    return rnd.number if rnd else 0


