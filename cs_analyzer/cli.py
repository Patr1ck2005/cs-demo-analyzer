"""CsDemoAnalyzer CLI.

Commands:
  parse   - parse a .dem file (with cache)
  analyze - run analysis modules
  render  - render radar chart
  export  - export video / report
  run     - full pipeline (parse + analyze + render + export)
  batch   - batch process multiple demos
  info    - show demo metadata
"""
from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from cs_analyzer.batch import BatchRunner
from cs_analyzer.cache import DemoCache
from cs_analyzer.config import ActionMapConfig, Settings, load_settings
from cs_analyzer.export import ReportExporter, VideoExporter
from cs_analyzer.parser import ParseManager
from cs_analyzer.render import ActionMapRenderer, merge_for_radar
from cs_analyzer.render.radar_chart import RadarChartRenderer
from cs_analyzer.analysis import AnalysisRunner

app = typer.Typer(
    name="csa",
    help="CsDemoAnalyzer: local-first CS2 demo analysis toolkit.",
    no_args_is_help=True,
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _load_settings(config: Path | None) -> Settings:
    return load_settings(config) if config else load_settings()


@app.command()
def parse(
    demo: Path = typer.Argument(..., help="Path to .dem file"),
    config: Path | None = typer.Option(None, "--config", "-c", help="Config YAML file"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="Force provider (valve/faceit/...)"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable cache"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Parse a .dem file and cache the result."""
    _setup_logging(verbose)
    settings = _load_settings(config)
    manager = ParseManager(cache=DemoCache(settings.cache_dir))
    demo_data = manager.parse(demo, use_cache=not no_cache, force_provider=provider)
    console.print(f"[green]Parsed[/green] {demo.name}")
    console.print(f"  map: {demo_data.metadata.map_name}")
    console.print(f"  provider: {demo_data.metadata.provider.value}")
    console.print(f"  players: {len(demo_data.players)}")
    console.print(f"  rounds: {len(demo_data.rounds)} (regular: {len(demo_data.regular_rounds)})")
    console.print(f"  events: {len(demo_data.events)} types")
    console.print(f"  ticks: {len(demo_data.ticks)} rows")


@app.command()
def analyze(
    demo: Path = typer.Argument(..., help="Path to .dem file"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    modules: str | None = typer.Option(None, "--modules", "-m", help="Comma-separated module names"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run analysis modules on a parsed demo."""
    _setup_logging(verbose)
    settings = _load_settings(config)
    manager = ParseManager(cache=DemoCache(settings.cache_dir))
    demo_data = manager.parse(demo)

    module_list = modules.split(",") if modules else None
    runner = AnalysisRunner(settings.analysis)
    results = runner.run(demo_data, modules=module_list)

    for name, result in results.items():
        if not hasattr(result, "players") or not result.players:
            console.print(f"\n[bold]{name}[/bold] (no player data)")
            continue
        console.print(f"\n[bold]{name}[/bold] ({len(result.players)} players)")
        if name == "basic_stats":
            table = Table(show_header=True, header_style="bold")
            for col in ("Name", "Team", "K", "D", "A", "KPR", "ADR", "HS%"):
                table.add_column(col)
            for p in result.players[:10]:
                table.add_row(
                    p.name[:20], p.team,
                    str(p.kills), str(p.deaths), str(p.assists),
                    f"{p.KPR:.2f}", f"{p.ADR:.0f}", f"{p.headshot_pct:.0f}",
                )
            console.print(table)
        elif name == "ratings":
            table = Table(show_header=True, header_style="bold")
            for col in ("Name", "Team", "RWS", "Rating", "KAST%", "Impact"):
                table.add_column(col)
            for p in result.players[:10]:
                table.add_row(
                    p.name[:20], p.team,
                    f"{p.RWS:.1f}", f"{p.Rating:.2f}", f"{p.KAST:.0f}", f"{p.Impact:.2f}",
                )
            console.print(table)


@app.command()
def render(
    demo: Path = typer.Argument(..., help="Path to .dem file"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Render radar chart from a demo."""
    _setup_logging(verbose)
    settings = _load_settings(config)
    if settings.render.radar_chart is None:
        console.print("[red]No radar_chart config. Set render.radar_chart in config.[/red]")
        raise typer.Exit(1)

    manager = ParseManager(cache=DemoCache(settings.cache_dir))
    demo_data = manager.parse(demo)
    runner = AnalysisRunner(settings.analysis)
    results = runner.run(demo_data)

    basic = results.get("basic_stats")
    ratings = results.get("ratings")
    if basic is None or ratings is None:
        console.print("[red]basic_stats and ratings modules are required for radar chart.[/red]")
        raise typer.Exit(1)

    players = merge_for_radar(basic, ratings, settings.render.radar_chart.attributes)
    output_path = output or (settings.render.output_dir / demo.stem / "radar_chart.mov")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    renderer = RadarChartRenderer(settings.render.radar_chart, players)
    produced = renderer.render(output_path)
    console.print(f"[green]Rendered[/green] -> {produced}")


@app.command()
def export(
    demo: Path = typer.Argument(..., help="Path to .dem file"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    fmt: str = typer.Option("video", "--format", "-f", help="video | report | json"),
    input_video: Path | None = typer.Option(None, "--input", help="Input video for video export"),
    output: Path | None = typer.Option(None, "--output", "-o"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Export final video or analysis report."""
    _setup_logging(verbose)
    settings = _load_settings(config)

    if fmt == "video":
        if input_video is None:
            console.print("[red]--input required for video export[/red]")
            raise typer.Exit(1)
        output_path = output or (settings.render.output_dir / demo.stem / "final.mp4")
        exporter = VideoExporter(settings.export.video)
        result = exporter.export(input_video, output_path)
        console.print(f"[green]Exported[/green] -> {result}")
    elif fmt in ("report", "json"):
        manager = ParseManager(cache=DemoCache(settings.cache_dir))
        demo_data = manager.parse(demo)
        runner = AnalysisRunner(settings.analysis)
        results = runner.run(demo_data)
        ext = ".html" if fmt == "report" else ".json"
        output_path = output or (settings.render.output_dir / demo.stem / f"report{ext}")
        exporter = ReportExporter(results.get("basic_stats"), results.get("ratings"))
        result = exporter.export(None, output_path)
        console.print(f"[green]Exported[/green] -> {result}")


@app.command()
def run(
    demo: Path = typer.Argument(..., help="Path to .dem file"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    skip_video: bool = typer.Option(False, "--skip-video", help="Skip ffmpeg video export"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Full pipeline: parse + analyze + render + export."""
    _setup_logging(verbose)
    settings = _load_settings(config)
    runner = BatchRunner(settings)
    results = runner.run([demo], render_radar=True, export_video=not skip_video, export_report=True, parallel=1)
    for r in results:
        if r.success:
            console.print(f"[green]Done[/green] {r.demo_path.name}:")
            for p in r.output_paths:
                console.print(f"  -> {p}")
        else:
            console.print(f"[red]Failed[/red] {r.demo_path.name}: {r.error}")


@app.command()
def batch(
    config_file: Path = typer.Argument(..., help="Batch config YAML file"),
    config: Path | None = typer.Option(None, "--config", "-c", help="Global settings config"),
    parallel: int = typer.Option(1, "--parallel", "-n", help="Number of parallel parse workers"),
    skip_video: bool = typer.Option(False, "--skip-video"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Batch process multiple demos listed in a YAML config."""
    _setup_logging(verbose)
    settings = _load_settings(config)

    import yaml
    with open(config_file, encoding="utf-8") as f:
        batch_data = yaml.safe_load(f) or {}
    demos = [Path(d["path"]) for d in batch_data.get("demos", [])]

    if not demos:
        console.print("[red]No demos found in batch config.[/red]")
        raise typer.Exit(1)

    console.print(f"Processing {len(demos)} demos (parallel={parallel})")
    runner = BatchRunner(settings)
    results = runner.run(demos, render_radar=True, export_video=not skip_video, export_report=True, parallel=parallel)

    succeeded = sum(1 for r in results if r.success)
    console.print(f"\n[bold]Summary: {succeeded}/{len(results)} succeeded[/bold]")
    for r in results:
        status = "[green]OK[/green]" if r.success else "[red]FAIL[/red]"
        console.print(f"  {status} {r.demo_path.name}")


@app.command("action-map")
def action_map(
    demo: Path = typer.Argument(..., help="Path to .dem file"),
    player: str = typer.Option(..., "--player", help="Player name or steamid"),
    rounds: str | None = typer.Option(None, "--rounds", help="Comma-separated round numbers (default: all)"),
    output: Path | None = typer.Option(None, "--output", "-o"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Render 2D action map (player movement trajectories across rounds)."""
    _setup_logging(verbose)
    settings = _load_settings(config)
    manager = ParseManager(cache=DemoCache(settings.cache_dir))
    demo_data = manager.parse(demo)

    player_obj = demo_data.player(player)
    if player_obj is None:
        console.print(f"[red]Player '{player}' not found. Available: {[p.name for p in demo_data.players]}[/red]")
        raise typer.Exit(1)

    round_list = [int(r) for r in rounds.split(",")] if rounds else None
    cfg = settings.render.action_map or ActionMapConfig()
    renderer = ActionMapRenderer(cfg, demo_data)
    output_path = output or (settings.render.output_dir / demo.stem / f"action_map_{player_obj.name}.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = renderer.render_player(player_obj.steamid, round_list, output_path)
    console.print(f"[green]Action map[/green] -> {result}")


@app.command()
def info(
    demo: Path = typer.Argument(..., help="Path to .dem file"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Show demo metadata without full analysis."""
    _setup_logging(verbose)
    from cs_analyzer.parser.backend import DemoParserBackend

    backend = DemoParserBackend(tick_fields=[])
    header = backend.read_header(demo)
    console.print(f"[bold]{demo.name}[/bold]")
    console.print(f"  map: {header.get('map_name')}")
    console.print(f"  server: {header.get('server_name')}")
    console.print(f"  client: {header.get('client_name')}")
    console.print(f"  demo_version: {header.get('demo_version_name')}")


if __name__ == "__main__":
    app()
