"""Batch processing: run the full pipeline on multiple demos.

Phases:
  1. Parallel parse + analyze (multiprocessing, CPU-bound)
  2. Serial render (Manim OpenGL, not parallelizable)
  3. Parallel export (ffmpeg subprocesses)
"""
from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from cs_analyzer.analysis import AnalysisRunner
from cs_analyzer.cache import DemoCache
from cs_analyzer.config import Settings
from cs_analyzer.export import ReportExporter, VideoExporter
from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.parser import ParseManager
from cs_analyzer.render import merge_for_radar
from cs_analyzer.render.radar_chart import RadarChartRenderer

logger = logging.getLogger(__name__)
console = Console()


@dataclass
class BatchResult:
    demo_path: Path
    success: bool
    output_paths: list[Path]
    error: str | None = None


def _parse_and_analyze(
    dem_path: str,
    cache_dir: str,
    provider: str | None,
    modules: list[str],
) -> tuple[str, ParsedDemo, dict]:
    """Worker function for parallel parsing. Must be top-level for pickling."""
    from cs_analyzer.analysis import AnalysisRunner
    from cs_analyzer.cache import DemoCache
    from cs_analyzer.parser import ParseManager

    manager = ParseManager(cache=DemoCache(Path(cache_dir)))
    demo = manager.parse(dem_path, force_provider=provider)
    runner = AnalysisRunner()
    results = runner.run(demo, modules=modules)
    return dem_path, demo, results


class BatchRunner:
    """Orchestrates batch processing of multiple demos."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cache = DemoCache(settings.cache_dir)

    def run(
        self,
        demo_paths: list[Path],
        render_radar: bool = True,
        export_video: bool = True,
        export_report: bool = True,
        parallel: int = 1,
    ) -> list[BatchResult]:
        """Process multiple demos: parse+analyze in parallel, render serial, export parallel."""
        results: list[BatchResult] = []

        # Phase 1: parallel parse + analyze
        parsed: dict[str, tuple[ParsedDemo, dict]] = {}
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Parsing demos...", total=len(demo_paths))

            if parallel <= 1:
                for path in demo_paths:
                    try:
                        manager = ParseManager(cache=self.cache)
                        demo = manager.parse(path)
                        runner = AnalysisRunner(self.settings.analysis)
                        results_dict = runner.run(demo)
                        parsed[str(path)] = (demo, results_dict)
                    except Exception as exc:  # noqa: BLE001
                        results.append(BatchResult(path, False, [], str(exc)))
                    progress.advance(task)
            else:
                with ProcessPoolExecutor(max_workers=parallel) as pool:
                    futures = {
                        pool.submit(
                            _parse_and_analyze,
                            str(path),
                            str(self.settings.cache_dir),
                            None,
                            list(self.settings.analysis.enabled_modules),
                        ): path
                        for path in demo_paths
                    }
                    for future in as_completed(futures):
                        path = futures[future]
                        try:
                            dem_path, demo, results_dict = future.result()
                            parsed[dem_path] = (demo, results_dict)
                        except Exception as exc:  # noqa: BLE001
                            results.append(BatchResult(path, False, [], str(exc)))
                        progress.advance(task)

        # Phase 2: serial render (Manim can't parallelize OpenGL)
        rendered: dict[str, Path] = {}
        for path_str, (demo, results_dict) in parsed.items():
            path = Path(path_str)
            output_paths: list[Path] = []
            try:
                if render_radar and self.settings.render.radar_chart is not None:
                    video_path = self._render_radar(demo, results_dict, path)
                    rendered[path_str] = video_path
                    output_paths.append(video_path)
                if export_report:
                    report_path = self._export_report(demo, results_dict, path)
                    output_paths.append(report_path)
                results.append(BatchResult(path, True, output_paths))
            except Exception as exc:  # noqa: BLE001
                logger.exception("render failed for %s", path)
                results.append(BatchResult(path, False, [], str(exc)))

        # Phase 3: export video (ffmpeg) - can be parallel but keep serial for simplicity
        for path_str, video_path in rendered.items():
            path = Path(path_str)
            if not export_video:
                continue
            try:
                final_path = self._export_video(video_path, path)
                for r in results:
                    if r.demo_path == path:
                        r.output_paths.append(final_path)
                        break
            except Exception as exc:  # noqa: BLE001
                logger.warning("video export failed for %s: %s", path, exc)

        return results

    def _render_radar(self, demo: ParsedDemo, results: dict, demo_path: Path) -> Path:
        cfg = self.settings.render.radar_chart
        assert cfg is not None
        basic = results.get("basic_stats")
        ratings = results.get("ratings")
        if basic is None or ratings is None:
            raise RuntimeError("radar chart requires basic_stats + ratings modules")

        players = merge_for_radar(basic, ratings, cfg.attributes)
        output_dir = self.settings.render.output_dir / demo_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "radar_chart.mov"

        renderer = RadarChartRenderer(cfg, players)
        return renderer.render(output_path)

    def _export_video(self, fg_video: Path, demo_path: Path) -> Path:
        output_dir = self.settings.render.output_dir / demo_path.stem
        output_path = output_dir / "final.mp4"
        exporter = VideoExporter(self.settings.export.video)
        return exporter.export(fg_video, output_path)

    def _export_report(self, demo: ParsedDemo, results: dict, demo_path: Path) -> Path:
        output_dir = self.settings.render.output_dir / demo_path.stem
        output_path = output_dir / "report.html"
        basic = results.get("basic_stats")
        ratings = results.get("ratings")
        exporter = ReportExporter(basic, ratings)
        return exporter.export(None, output_path)
