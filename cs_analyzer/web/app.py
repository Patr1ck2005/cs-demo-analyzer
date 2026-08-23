"""LTG-2: local web platform (FastAPI + Jinja2, all-Chinese).

Stage 1: single-match review (upload -> stats / radar / replay / preference).
Stage 2: cross-match aggregation (player matrix, team comparison, trends).
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.gzip import GZipMiddleware

from cs_analyzer.analysis import AnalysisRunner
from cs_analyzer.analysis.aggregate import compute_aggregate
from cs_analyzer import cache
from cs_analyzer.cache import DemoCache
from cs_analyzer.config import AnalysisConfig, RadarChartConfig, load_settings
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.web import replay_map, store, tasks

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
STATIC_DIR = BASE_DIR / "static"
OUT_DIR = Path("output") / "web"
DEMOS_DIR = Path("demos")

app = FastAPI(title="CsDemoAnalyzer 本地平台", version="0.1.0")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_analysis_cache: dict[str, dict] = {}


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


def _radar_config() -> RadarChartConfig:
    rc = _settings().render.radar_chart
    return rc if rc is not None else RadarChartConfig()


# ---- pages ----

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    demos = store.list_demos(_cache().cache_dir)
    return TEMPLATES.TemplateResponse(
        request, "index.html", {"demos": demos, "total": len(demos)}
    )


@app.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    DEMOS_DIR.mkdir(exist_ok=True)
    dest = DEMOS_DIR / Path(file.filename).name
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    job_id = tasks.tasks.submit(_parse_job, path=str(dest))
    return TEMPLATES.TemplateResponse(
        request, "job.html", {"job_id": job_id, "action": "解析 demo"}
    )


def _parse_job(path: str) -> str:
    from cs_analyzer.parser.manager import ParseManager

    manager = ParseManager(cache=_cache())
    demo = manager.parse(path, use_cache=True)
    return demo.metadata.demo_hash


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str):
    return TEMPLATES.TemplateResponse(
        request, "job.html", {"job_id": job_id, "action": "任务"}
    )


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = tasks.tasks.get_status(job_id)
    if job is None:
        return JSONResponse({"status": "unknown"})
    return JSONResponse(
        {
            "id": job.id,
            "status": job.status,
            "progress": job.progress,
            "result": job.result,
            "error": job.error,
        }
    )


@app.get("/demo/{demo_hash}", response_class=HTMLResponse)
def demo_detail(request: Request, demo_hash: str):
    demo = _load(demo_hash)
    if demo is None:
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": f"未找到 demo {demo_hash[:12]}，请先上传/解析"}
        )
    analysis = _analyze(demo)
    ctx = _demo_context(demo, analysis)
    return TEMPLATES.TemplateResponse(request, "demo_detail.html", ctx)


@app.get("/demo/{demo_hash}/player/{steamid}", response_class=HTMLResponse)
def player_detail(request: Request, demo_hash: str, steamid: str):
    demo = _load(demo_hash)
    if demo is None:
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": f"未找到 demo {demo_hash[:12]}"}
        )
    analysis = _analyze(demo)
    ctx = _player_context(demo, analysis, steamid)
    if ctx is None:
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": f"未找到玩家 {steamid}"}
        )
    return TEMPLATES.TemplateResponse(request, "player_detail.html", ctx)


@app.get("/aggregate", response_class=HTMLResponse)
def aggregate(request: Request):
    result = compute_aggregate(_cache().cache_dir, _settings().analysis)
    charts = _aggregate_charts(result)
    return TEMPLATES.TemplateResponse(
        request, "aggregate.html", {"result": result, "charts": charts}
    )


@app.get("/coverage", response_class=HTMLResponse)
def coverage_page(request: Request):
    """Serve the CLI-generated coverage report; explain how to build it if absent."""
    report = Path("output") / "coverage" / "coverage.html"
    if report.exists():
        return FileResponse(report, media_type="text/html",
                            headers={"Cache-Control": "no-cache"})
    return TEMPLATES.TemplateResponse(
        request, "error.html",
        {"message": "覆盖度报告尚未生成。请先运行: csa coverage \"demos/*.dem\" --out output/coverage/coverage.html"}
    )


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


@app.get("/maps/{map_name}")
def map_image(map_name: str):
    """Serve official radar PNGs (immutable: images are content-pinned by name)."""
    from cs_analyzer.maps.loader import MAPS_DATA_DIR

    allowed = {p.stem: p for p in MAPS_DATA_DIR.glob("*.png")}
    p = allowed.get(map_name.removesuffix(".png"))
    if p is None:
        return JSONResponse({"error": "unknown map"}, status_code=404)
    return FileResponse(p, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/demo/{demo_hash}/viewer", response_class=HTMLResponse)
def demo_viewer(request: Request, demo_hash: str):
    demo = _load(demo_hash)
    if demo is None:
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": f"未找到 demo {demo_hash[:12]}"}
        )
    meta = demo.metadata
    reg = demo.regular_rounds
    from cs_analyzer.web import viewer_data

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
            "data_ready": viewer_data.is_ready(demo_hash, OUT_DIR),
        },
    )


@app.get("/api/demo/{demo_hash}/replay-map")
def replay_map_status(demo_hash: str):
    if not replay_map.is_ready(demo_hash, OUT_DIR):
        return JSONResponse({"status": "missing"})
    data = replay_map.load_map(demo_hash, OUT_DIR)
    data["status"] = "ready"
    data["video_url"] = f"/media/{demo_hash}/viewer/replay.mp4?v={replay_map.RENDER_VERSION}"
    return JSONResponse(data)


@app.post("/api/demo/{demo_hash}/replay-map")
def start_replay_map(demo_hash: str, speed: float = Form(10.0)):
    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    if speed <= 0 or speed > 60:
        return JSONResponse({"error": "speed 应在 1-60 之间"}, status_code=400)
    job_id = tasks.tasks.submit(
        replay_map.render_viewer_job, demo_hash=demo_hash, demo=demo,
        out_dir=OUT_DIR, speed=speed,
    )
    return JSONResponse({"job_id": job_id})


# ---- video export studio (B3) ----

@app.get("/studio", response_class=HTMLResponse)
def studio(request: Request):
    demos = store.list_demos(_cache().cache_dir)
    return TEMPLATES.TemplateResponse(request, "studio.html", {"demos": demos})


@app.get("/studio/replay/{demo_hash}", response_class=HTMLResponse)
def studio_replay_page(request: Request, demo_hash: str):
    demo = _load(demo_hash)
    if demo is None:
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": f"未找到 demo {demo_hash[:12]}"}
        )
    from cs_analyzer.recipe import load_recipes

    recipes = load_recipes(Path("configs/recipes.yaml"))
    recs = [{"name": n, "title": r.title, "kind": r.kind} for n, r in recipes.items()]
    analysis = _analyze(demo)
    from cs_analyzer.coverage import _player_position_stats

    pos = _player_position_stats(demo)
    plist = [
        {"steamid": bs.steamid, "name": bs.name, "replayable": pos.get(bs.steamid, (False, 0.0))[0]}
        for bs in analysis["basic"].players
    ]
    return TEMPLATES.TemplateResponse(
        request, "studio_replay.html",
        {"demo": _demo_meta(demo), "recipes": recs, "players": plist},
    )


@app.get("/studio/radar/{demo_hash}", response_class=HTMLResponse)
def studio_radar_page(request: Request, demo_hash: str):
    demo = _load(demo_hash)
    if demo is None:
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": f"未找到 demo {demo_hash[:12]}"}
        )
    return TEMPLATES.TemplateResponse(request, "studio_radar.html", {"demo": _demo_meta(demo)})


@app.post("/api/studio/replay")
async def api_studio_replay(payload: dict = Body(...)):
    demo_hash = payload.get("demo_hash", "")
    recipe = payload.get("recipe", "")
    player = payload.get("player", "") or ""
    override = payload.get("override") or {}
    if not demo_hash or not recipe:
        return JSONResponse({"error": "缺少 demo 或配方"}, status_code=400)
    if _load(demo_hash) is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    job_id = tasks.tasks.submit(
        _studio_replay_job, demo_hash=demo_hash, recipe=recipe, player=player, override=override
    )
    return JSONResponse({"job_id": job_id})


@app.post("/api/studio/radar")
async def api_studio_radar(payload: dict = Body(...)):
    demo_hash = payload.get("demo_hash", "")
    if not demo_hash or _load(demo_hash) is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    quality = payload.get("quality") or "medium_quality"
    job_id = tasks.tasks.submit(
        _studio_radar_job, demo_hash=demo_hash, radar=payload.get("radar") or {}, quality=quality
    )
    return JSONResponse({"job_id": job_id})


def _studio_replay_job(demo_hash: str, recipe: str, player: str, override: dict) -> str:
    demo = _load(demo_hash)
    if demo is None:
        raise ValueError("demo not found")
    from cs_analyzer.recipe import load_recipes, render_recipe
    from cs_analyzer.web.replay_map import RENDER_VERSION

    recipes = load_recipes(Path("configs/recipes.yaml"))
    rec = recipes[recipe]
    # RENDER_VERSION in the filename invalidates stale (pre-basemap) artifacts
    out = OUT_DIR / demo_hash / "studio" / f"v{RENDER_VERSION}_{recipe}_{player or 'team'}.mp4"
    render_recipe(demo, rec, out, player=player, overrides=override or None)
    return f"/media/{demo_hash}/studio/{out.name}"


def _studio_radar_job(demo_hash: str, radar: dict, quality: str) -> str:
    demo = _load(demo_hash)
    if demo is None:
        raise ValueError("demo not found")
    analysis = _analyze(demo)
    from cs_analyzer.render.base import merge_for_radar
    from cs_analyzer.render.radar_chart import RadarChartRenderer

    base_cfg = _radar_config()
    known = {k: v for k, v in radar.items() if v not in (None, "")}
    if "attributes" in known and isinstance(known["attributes"], str):
        known["attributes"] = [a.strip() for a in known["attributes"].split(",") if a.strip()]
    cfg = base_cfg.model_copy(update=known)
    players = merge_for_radar(analysis["basic"], analysis["ratings"], cfg.attributes)
    out = OUT_DIR / demo_hash / "studio" / "radar.mp4"
    produced = RadarChartRenderer(cfg, players).render(
        out, quality=quality, transparent=False, format="mp4"
    )
    target = OUT_DIR / demo_hash / "studio" / "radar.mp4"
    if Path(produced) != target:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(produced, target)
    return f"/media/{demo_hash}/studio/radar.mp4"


def _demo_meta(demo: ParsedDemo) -> dict:
    meta = demo.metadata
    reg = demo.regular_rounds
    return {
        "hash": meta.demo_hash,
        "filename": Path(meta.demo_path).name,
        "map_name": meta.map_name,
        "t_score": reg[-1].t_score if reg else 0,
        "ct_score": reg[-1].ct_score if reg else 0,
        "num_rounds": len(reg),
    }


# ---- replay ----

REPLAY_RECIPES = {
    "s-openings": ("single", "开局重叠 30s"),
    "s-overlap-full": ("single", "全场重叠"),
    "s-highlights": ("single", "高光回合"),
    "t-full": ("team", "10人全场记录"),
    "t-highlights": ("team", "10人高光"),
    "t-overlap-round": ("team", "10人逐回合重叠"),
}


@app.post("/api/demo/{demo_hash}/replay")
def start_replay(demo_hash: str, recipe: str = Form(...), player: str = Form("")):
    if recipe not in REPLAY_RECIPES:
        return JSONResponse({"error": f"未知配方 {recipe}"}, status_code=400)
    demo = _load(demo_hash)
    if demo is None:
        return JSONResponse({"error": "demo 未找到"}, status_code=404)
    job_id = tasks.tasks.submit(
        _render_recipe_job, demo_hash=demo_hash, recipe=recipe, player=player
    )
    return JSONResponse({"job_id": job_id})


def _render_recipe_job(demo_hash: str, recipe: str, player: str) -> str:
    demo = _load(demo_hash)
    if demo is None:
        raise ValueError("demo not found")
    from cs_analyzer.recipe import load_recipes, render_recipe
    from cs_analyzer.web.replay_map import RENDER_VERSION

    recipes = load_recipes(Path("configs/recipes.yaml"))
    rec = recipes[recipe]
    pid = player or "team"
    out = OUT_DIR / demo_hash / f"v{RENDER_VERSION}_replay_{recipe}_{pid}.mp4"
    result = render_recipe(demo, rec, out, player=player)
    return str(result)


@app.get("/media/{demo_hash}/{rest:path}")
def media(demo_hash: str, rest: str):
    path = OUT_DIR / demo_hash / rest
    if not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    # revalidate every time: renders regenerate under the same URLs, and a
    # heuristically-cached old video would hide newly rendered basemaps
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


# ---- helpers ----

def _load(demo_hash: str) -> ParsedDemo | None:
    return store.load_demo(demo_hash, _cache().cache_dir)


def _demo_context(demo: ParsedDemo, analysis: dict) -> dict:
    meta = demo.metadata
    reg = demo.regular_rounds
    t_score = reg[-1].t_score if reg else 0
    ct_score = reg[-1].ct_score if reg else 0

    basic = analysis["basic"]
    ratings = analysis["ratings"]
    radar_cfg = _radar_config()
    from cs_analyzer.coverage import _player_position_stats

    pos_stats = _player_position_stats(demo)  # one pass, not once per player
    players = []
    for bs in basic.players:
        rt = ratings.by_steamid(bs.steamid) if ratings else None
        radar_img = _player_radar_png(demo, bs.steamid, basic, ratings, radar_cfg)
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
                "radar_img": radar_img,
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
    radar_cfg = _radar_config()
    radar_img = _player_radar_png(demo, steamid, basic, ratings, radar_cfg)
    pref_imgs = _preference_pngs(demo, pref, steamid)
    from cs_analyzer.analysis.preference import PlayerPreference

    pp = None
    if pref is not None:
        pp = next((p for p in pref.players if p.steamid == steamid), None)

    replayable = _replayable(demo, steamid)
    from cs_analyzer.web.replay_map import RENDER_VERSION

    replays = []
    for recipe, (kind, label) in REPLAY_RECIPES.items():
        pid = steamid if kind == "single" else "team"
        vpath = OUT_DIR / meta.demo_hash / f"v{RENDER_VERSION}_replay_{recipe}_{pid}.mp4"
        # single-player recipes are impossible without position data; say why
        disabled = kind == "single" and not replayable
        replays.append(
            {
                "recipe": recipe,
                "label": label,
                "kind": kind,
                "disabled": disabled,
                "exists": vpath.exists(),
                "url": f"/media/{meta.demo_hash}/{vpath.name}" if vpath.exists() else None,
            }
        )

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
        "radar_img": radar_img,
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
        "charts": pref_imgs,
        "replays": replays,
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


def _player_radar_png(demo, steamid, basic, ratings, radar_cfg) -> str:
    from cs_analyzer.render.base import merge_for_radar
    from cs_analyzer.render.radar_static import render_radar_static

    players = merge_for_radar(basic, ratings, radar_cfg.attributes)
    p = next((p for p in players if p.ID == (basic.by_steamid(steamid).name)), None)
    if p is None:
        return ""
    out = OUT_DIR / demo.metadata.demo_hash / "radar" / f"v{cache.PARSER_VERSION}_{steamid}.png"
    if not out.exists():  # render once per parser version, then reuse on disk
        render_radar_static(p, radar_cfg, out)
    return f"/media/{demo.metadata.demo_hash}/radar/{out.name}"


def _preference_pngs(demo, pref, steamid) -> dict:
    from cs_analyzer.maps import load_map_or_fallback
    from cs_analyzer.render.preference_charts import (
        render_heatmap,
        render_style_panel,
        render_utility_map,
    )

    if pref is None:
        return {}
    pp = next((p for p in pref.players if p.steamid == steamid), None)
    if pp is None:
        return {}
    map_res = load_map_or_fallback(demo.metadata.map_name, demo.ticks)
    pv = f"v{cache.PARSER_VERSION}"
    h = OUT_DIR / demo.metadata.demo_hash / "pref" / f"{pv}_{steamid}_heatmap.png"
    u = OUT_DIR / demo.metadata.demo_hash / "pref" / f"{pv}_{steamid}_utility.png"
    s = OUT_DIR / demo.metadata.demo_hash / "pref" / f"{pv}_{steamid}_style.png"
    if not h.exists():
        render_heatmap(pp, map_res, h)
    if not u.exists():
        render_utility_map(pp, map_res, u)
    if not s.exists():
        render_style_panel(pp, s)
    base = f"/media/{demo.metadata.demo_hash}/pref/{pv}_{steamid}"
    return {"heatmap": f"{base}_heatmap.png", "utility": f"{base}_utility.png", "style": f"{base}_style.png"}


def _aggregate_charts(result):
    from cs_analyzer.render.aggregate_charts import render_aggregate_charts

    charts = render_aggregate_charts(result, OUT_DIR / "aggregate")
    return {
        "player_matrix": charts.get("player_matrix", ""),
        "team_win": charts.get("team_win", ""),
        "trends": charts.get("trends", ""),
    }
