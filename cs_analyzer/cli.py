"""CsDemoAnalyzer CLI.

Commands:
  parse    - parse a .dem file (with cache)
  analyze  - run analysis modules
  coverage - scan parse coverage, write HTML report
  serve    - run the local web platform (analysis + real-time 2D replay)
  info     - show demo metadata

(The legacy matplotlib/manim video pipeline was retired in Phase E; see
docs/video_pipeline_archive.md.)
"""
from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from cs_analyzer.cache import DemoCache
from cs_analyzer.config import Settings, load_settings
from cs_analyzer.parser import ParseManager
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
def coverage(
    demos: list[Path] = typer.Argument(
        None, help=".dem files or glob patterns to scan (default: demos/*.dem)"
    ),
    out: Path | None = typer.Option(None, "--out", help="Output HTML path"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Force re-parse (bypass cache)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Scan parse coverage of demos and write an HTML report."""
    _setup_logging(verbose)
    from cs_analyzer.coverage import render_coverage_report, scan_demos

    import glob as _glob

    def expand(arg: Path) -> list[Path]:
        if any(ch in str(arg) for ch in "*?["):
            return [Path(p) for p in sorted(_glob.glob(str(arg)))]
        return [arg]

    if demos:
        paths: list[Path] = []
        for arg in demos:
            paths.extend(expand(arg))
    else:
        paths = [Path(p) for p in sorted(_glob.glob("demos/*.dem"))]
    if not paths:
        console.print("[red]No demos matched. Pass .dem files/globs or run from the repo root.[/red]")
        raise typer.Exit(1)
    console.print(f"Scanning {len(paths)} demos ...")
    demo_rows = scan_demos(paths, use_cache=not no_cache)
    for d in demo_rows:
        status = "[green]OK[/green]" if d.status == "ok" else "[red]ERR[/red]"
        console.print(
            f"  {status} {d.path.split(chr(92))[-1]:40s} {d.map_name:12s} "
            f"{len(d.players):2d}p T0={len(d.team_zero_players)} "
            f"replayable={len(d.replayable_players)}"
        )
    output_path = out or (Path("output") / "coverage" / "coverage.html")
    result = render_coverage_report(demo_rows, output_path)
    console.print(f"[green]Coverage report[/green] -> {result}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8000, "--port", help="Bind port"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the local web platform (FastAPI + Jinja2)."""
    _setup_logging(verbose)
    import uvicorn

    from cs_analyzer.web.app import app as web_app

    console.print(f"[green]CsDemoAnalyzer web[/green] http://{host}:{port}")
    uvicorn.run(web_app, host=host, port=port)


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
