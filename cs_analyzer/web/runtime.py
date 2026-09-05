"""Web runtime facade — the data layer's dependency contract.

Phase S: every cross-demo data module (aggregation, feed_data, funlab_data,
mapdata, teamplay_data, utilitylab_data, lineups_data, report_export) used
to import private functions from web.app directly — an app ↔ data-layer
cycle held together only by lazy function-local imports. They now import
this facade instead; the concrete implementations (and the test
monkeypatching surface on ``web_app`` attributes) stay in app.py.

Moving the real implementations here later means touching exactly this
file plus the tests' patch target — data modules keep importing runtime.
"""
from __future__ import annotations


def _web_app():
    """Late-bound app module (the cycle-break: app imports data modules at
    request time, data modules import runtime which resolves app lazily)."""
    from cs_analyzer.web import app as _app

    return _app


def settings():
    return _web_app()._settings()


def cache():
    return _web_app()._cache()


def out_dir():
    """App OUT_DIR (output/web) — snapshot/ui stores hang off it; tests
    monkeypatch web_app.OUT_DIR and this picks the patch up dynamically."""
    return _web_app().OUT_DIR


def load_demo(demo_hash: str):
    return _web_app()._load(demo_hash)


def analyze_module(demo, module_name: str):
    return _web_app()._analyze_module(demo, module_name)
