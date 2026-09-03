"""Single-match report export (Phase L5 报告导出).

Renders the print-friendly /report/{hash} page headlessly via Playwright
Chromium and writes a PNG (full page) or PDF. Playwright is an optional
dependency (``pip install cs-demo-analyzer[reports]``); without it the route
answers 501 with install guidance instead of failing.

This module is imported lazily so the web app works without playwright.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class ReportUnavailableError(RuntimeError):
    """playwright (or its chromium) is not installed."""


def export_match_report(base_url: str, demo_hash: str, fmt: str, out_dir: Path) -> Path:
    """Render /report/{demo_hash} and save {fmt} to out_dir; returns the file.

    fmt: "png" (full-page screenshot) or "pdf" (chromium print-to-pdf).
    """
    from cs_analyzer.web.app import _cache, _load

    demo = _load(demo_hash)
    if demo is None:
        raise LookupError(f"unknown demo {demo_hash[:12]}")
    meta = demo.metadata
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    from cs_analyzer.web.store import match_key as _mk

    mk = _mk({"match_id": getattr(meta, "match_id", None),
              "filename": Path(meta.demo_path).name})
    prefix = mk[1] if mk[0] == 0 else Path(meta.demo_path).stem
    safe = f"{prefix}_{meta.map_name}_{stamp}".replace("/", "_")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{safe}.{fmt}"
    url = f"{base_url.rstrip('/')}/report/{demo_hash}"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ReportUnavailableError(
            "未安装 playwright — 运行: pip install playwright && playwright install chromium"
        ) from exc

    t0 = datetime.now()
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # browsers not downloaded
            raise ReportUnavailableError(
                "playwright 浏览器未安装 — 运行: playwright install chromium") from exc
        try:
            page = browser.new_page(viewport={"width": 900, "height": 1200})
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(600)
            if fmt == "pdf":
                page.pdf(path=str(target), format="A4",
                         print_background=True,
                         margin={"top": "12mm", "bottom": "12mm",
                                 "left": "10mm", "right": "10mm"})
            else:
                page.screenshot(path=str(target), full_page=True)
        finally:
            browser.close()
    logger.info("report export %s -> %s (%.1fs)", demo_hash[:12], target.name,
                (datetime.now() - t0).total_seconds())
    return target


def list_exports(out_dir: Path) -> list[dict]:
    """Existing exports, newest first."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    items = []
    for f in sorted(out_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix.lower() in (".png", ".pdf") and f.is_file():
            items.append({
                "file": f.name,
                "url": f"/report-exports/{f.name}",
                "size_kb": round(f.stat().st_size / 1024, 1),
                "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
            })
    return items
