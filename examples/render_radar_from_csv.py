"""Render radar chart from a pre-existing player_statistics.csv.

Adapter for the legacy workflow where stats come from an external CSV
(match_data.json -> statistics_script.py) instead of from .dem parsing.

Usage:
    python examples/render_radar_from_csv.py \\
        --csv radar_data/0922/player_statistics.csv \\
        --title "2024 9/22" \\
        --bg bg/halloween_shadows_in_window.mp4 \\
        --music "music/Michael Jackson - Thriller.mp3" \\
        --output output/0922_final.mp4
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

# Allow running from repo root without install
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cs_analyzer.config import RadarChartConfig, RadarChartTiming, VideoExportConfig
from cs_analyzer.export.video import VideoExporter
from cs_analyzer.render import merge_for_radar_from_csv
from cs_analyzer.render.radar_chart import RadarChartRenderer


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", required=True, help="player_statistics.csv path")
    p.add_argument("--title", default="", help="Title text")
    p.add_argument("--subtitle", default="群友数据图", help="Subtitle text")
    p.add_argument("--bg", help="Background video path")
    p.add_argument("--music", help="Music path")
    p.add_argument("--output", default="output/final.mp4", help="Final output path")
    p.add_argument("--entry-times", help="Comma-separated entry times, or 'auto'")
    p.add_argument("--quality", default="high_quality",
                   choices=["low_quality", "medium_quality", "high_quality", "production_quality"])
    p.add_argument("--no-nvenc", action="store_true", help="Disable NVENC GPU acceleration")
    p.add_argument("--radar-only", action="store_true", help="Skip ffmpeg compositing")
    p.add_argument("--composit-only", help="Skip radar render; use existing .mov at this path")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    # Load CSV
    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} players from {csv_path}")

    # Build radar config
    entry_times: list[float] | None
    if args.entry_times and args.entry_times != "auto":
        entry_times = [float(t) for t in args.entry_times.split(",")]
    else:
        entry_times = None  # auto-distribute

    timing = RadarChartTiming(entry_times=entry_times)
    config = RadarChartConfig(
        title=args.title,
        subtitle=args.subtitle,
        timing=timing,
    )

    # Merge CSV -> RadarPlayerData with ranks/is_top
    players = merge_for_radar_from_csv(df, config.attributes)
    print(f"Prepared {len(players)} players for radar chart")
    for p in players:
        tops = [a for a in config.attributes if p.attribute_rank(a) == 1]
        print(f"  {p.ID:30s} team={p.team:5s} is_top={p.is_top}  best_in={tops}")

    # Render radar chart (.mov)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    radar_path = output_path.parent / f"{output_path.stem}_radar.mov"

    if args.composit_only:
        produced = Path(args.composit_only)
        print(f"Skipping radar render; using existing {produced}")
    else:
        renderer = RadarChartRenderer(config, players)
        produced = renderer.render(radar_path, quality=args.quality, transparent=True, format="mov")
        print(f"Radar chart rendered -> {produced}")

    if args.radar_only:
        print(f"Skipping ffmpeg compositing (--radar-only)")
        return 0

    # Composite video: foreground + background + music
    video_cfg = VideoExportConfig(
        background=args.bg,
        music=args.music,
        use_nvenc=not args.no_nvenc,
    )
    exporter = VideoExporter(video_cfg)
    final = exporter.export(produced, output_path)
    print(f"Final video -> {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
