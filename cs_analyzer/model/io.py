"""Serialization for ParsedDemo.

Layout under {cache_dir}/{demo_hash}/:
    model.json              - DemoData (metadata, players, rounds)
    ticks.parquet           - per-tick player state
    events/{type}.parquet   - one parquet per event type
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from cs_analyzer.model.parsed_demo import ParsedDemo
from cs_analyzer.model.types import DemoData

MODEL_FILENAME = "model.json"
TICKS_FILENAME = "ticks.parquet"
EVENTS_DIRNAME = "events"


def save_parsed_demo(demo: ParsedDemo, dest_dir: Path) -> None:
    """Write DemoData to JSON and DataFrames to Parquet under dest_dir."""
    dest_dir.mkdir(parents=True, exist_ok=True)

    # metadata + players + rounds -> JSON
    (dest_dir / MODEL_FILENAME).write_text(
        demo.data.model_dump_json(indent=2), encoding="utf-8"
    )

    # ticks -> parquet
    if not demo.ticks.empty:
        demo.ticks.to_parquet(dest_dir / TICKS_FILENAME, index=False)
    else:
        # write empty parquet so loaders know there's no tick data
        demo.ticks.to_parquet(dest_dir / TICKS_FILENAME, index=False)

    # events -> one parquet per type
    events_dir = dest_dir / EVENTS_DIRNAME
    events_dir.mkdir(parents=True, exist_ok=True)
    for event_type, df in demo.events.items():
        if df is None or df.empty:
            continue
        df.to_parquet(events_dir / f"{event_type}.parquet", index=False)


def load_parsed_demo(src_dir: Path) -> ParsedDemo:
    """Reconstruct ParsedDemo from JSON + Parquet files written by save_parsed_demo."""
    model_path = src_dir / MODEL_FILENAME
    if not model_path.exists():
        raise FileNotFoundError(f"No {MODEL_FILENAME} in {src_dir}")

    data = DemoData.model_validate_json(model_path.read_text(encoding="utf-8"))

    ticks_path = src_dir / TICKS_FILENAME
    ticks = pd.read_parquet(ticks_path) if ticks_path.exists() else pd.DataFrame()

    events: dict[str, pd.DataFrame] = {}
    events_dir = src_dir / EVENTS_DIRNAME
    if events_dir.exists():
        for parquet_path in events_dir.glob("*.parquet"):
            events[parquet_path.stem] = pd.read_parquet(parquet_path)

    return ParsedDemo(data=data, events=events, ticks=ticks)


def cache_key(demo_hash: str, parser_version: str = "1.0.0") -> str:
    """Combine demo content hash with parser version for cache invalidation."""
    return f"{demo_hash}_v{parser_version}"
