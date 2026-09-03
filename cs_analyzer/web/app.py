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
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Query, Request, UploadFile
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
#: L0: per-demo module results, LRU-capped so a large library can't grow
#: this unbounded (HANDOFF §9.5). 512 slots ≈ 25+ demos × all modules.
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
    from cs_analyzer.web.chart_data import RADAR_AXES

    result = aggregated()
    row = next((p for p in result.players if p.steamid == steamid), None)
    if row is None:
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": f"未找到选手 {steamid}"}
        )
    # B4: career radar must normalize with the same server-side ranges as the
    # per-demo radar (the old hardcoded template ranges were wrong).
    return TEMPLATES.TemplateResponse(
        request, "player_career.html",
        {"p": row, "radar_axes": RADAR_AXES},
    )


@app.get("/highlights", response_class=HTMLResponse)
def highlights_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "highlights.html", {})


# ---- Phase L1: favorites / tags / notes ----

@app.get("/favorites", response_class=HTMLResponse)
def favorites_page(request: Request):
    """收藏与标注：星标/标签/备注（列表由 favorites.js 从 /api/favorites 渲染）。"""
    return TEMPLATES.TemplateResponse(request, "favorites.html", {})


# ---- Phase L2: utility lab (道具专题) — must register BEFORE /{placeholder} ----

@app.get("/utility-lab", response_class=HTMLResponse)
def utility_lab_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "utility_lab.html", {})


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


@app.get("/report/{demo_hash}", response_class=HTMLResponse)
def report_match_page(request: Request, demo_hash: str):
    """Print-friendly single-match report (exported to PNG/PDF by playwright;
    also printable from the browser)."""
    from datetime import datetime, timezone

    from cs_analyzer.analysis import AnalysisRunner
    from cs_analyzer.config import AnalysisConfig

    demo = _load(demo_hash)
    if demo is None:
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": "未找到该对局"})
    runner = AnalysisRunner(AnalysisConfig(enabled_modules=["basic_stats", "ratings", "highlights"]))
    results = runner.run(demo)
    basic, ratings = results.get("basic_stats"), results.get("ratings")
    hl = results.get("highlights")
    reg = demo.regular_rounds
    t_wins = sum(1 for r in reg if r.winner_side == "T")
    team_of: dict[str, str] = {}
    for p in demo.players:
        team_of[p.steamid] = p.team
    side_of_team = {demo.metadata.team_a.name: demo.metadata.team_a.starting_side,
                    demo.metadata.team_b.name: demo.metadata.team_b.starting_side}
    players = []
    if basic is not None and ratings is not None:
        rt_by = {p.steamid: p for p in ratings.players}
        for b in sorted(basic.players, key=lambda x: -(rt_by[x.steamid].Rating if x.steamid in rt_by else 0)):
            rt = rt_by.get(b.steamid)
            players.append({
                "name": b.name,
                "side": side_of_team.get(team_of.get(b.steamid, ""), "?"),
                "kills": b.kills, "deaths": b.deaths,
                "adr": b.ADR, "kast": rt.KAST if rt else 0.0,
                "hs": (b.headshot_kills / b.kills * 100) if b.kills else 0.0,
                "rating": rt.Rating if rt else 0.0,
            })
    highlights = []
    if hl is not None:
        for h in hl.sorted():
            if h.tier in ("ace", "k4", "1v4", "k3", "1v3"):
                highlights.append({"tier": h.tier, "name": h.name, "round": h.round,
                                   "kills": h.kills, "side": h.side})
    meta = demo.metadata
    return TEMPLATES.TemplateResponse(request, "report_match.html", {
        "meta": {
            "map_name": meta.map_name,
            "filename": Path(meta.demo_path).name,
            "match_id": getattr(meta, "match_id", None),
            "demo_hash": meta.demo_hash,
        },
        "score": {
            "t": reg[-1].t_score if reg else 0,
            "ct": reg[-1].ct_score if reg else 0,
            "rounds": len(reg),
        },
        "t_wr": (t_wins / len(reg)) if reg else 0.0,
        "trend": [{"n": r.number, "w": r.winner_side} for r in reg],
        "players": players,
        "highlights": highlights,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    })


@app.get("/api/favorites")
def favorites_get():
    from cs_analyzer.web.favorites_store import load_favorites

    return JSONResponse(load_favorites(OUT_DIR))


@app.post("/api/favorites")
async def favorites_set(request: Request):
    """Merge one entry patch: {scope: "match"|"player", id, patch, meta?}."""
    from cs_analyzer.web.favorites_store import (
        apply_patch,
        empty_doc,
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


_PLACEHOLDER_PAGES: dict[str, tuple[str, str]] = {}


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


@app.get("/api/compare/teamplay.json")
def compare_teamplay():
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
    from cs_analyzer.web import feed_data

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
    # P5: kill-context badges straight off the player_death flag columns
    _BADGES = (
        ("penetrated", "穿", "穿墙击杀"),
        ("thrusmoke", "烟", "烟雾中击杀"),
        ("noscope", "盲", "未开镜击杀"),
        ("attackerinair", "空", "空中击杀"),
        ("headshot", "HS", "爆头"),
    )
    rows = []
    for _, r in df.iterrows():
        badges = []
        for col, label, title in _BADGES:
            try:
                hit = bool(r.get(col, False))
            except (TypeError, ValueError):
                hit = False
            if hit:
                badges.append({"code": col, "label": label, "title": title})
        rows.append(
            {
                "tick": int(r.get("tick", 0)),
                "round": _round_at_tick(demo, int(r.get("tick", 0))),
                "attacker": r.get("attacker_name", ""),
                "victim": r.get("user_name", ""),
                "weapon": r.get("weapon", ""),
                "badges": badges,
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


