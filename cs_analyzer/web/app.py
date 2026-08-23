"""LTG-2: local web platform (FastAPI + Jinja2, all-Chinese).

Stage 1: single-match review (upload -> stats / radar / replay / preference).
Stage 2: cross-match aggregation (player matrix, team comparison, trends).
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.gzip import GZipMiddleware

from cs_analyzer.analysis import AnalysisRunner
from cs_analyzer.analysis.aggregate import compute_aggregate
from cs_analyzer.cache import DemoCache
from cs_analyzer.config import AnalysisConfig, load_settings
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.web import store, tasks

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


# ---- pages ----

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    demos = store.list_demos(_cache().cache_dir)
    return TEMPLATES.TemplateResponse(
        request, "index.html",
        {
            "demos": demos,
            "total": len(demos),
            "map_count": len({d["map_name"] for d in demos}),
            "round_count": sum(d["num_rounds"] for d in demos),
        },
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
    return TEMPLATES.TemplateResponse(request, "aggregate.html", {"result": result})


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


