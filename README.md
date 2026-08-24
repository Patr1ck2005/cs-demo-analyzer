# CsDemoAnalyzer

Local-first CS2 demo analysis toolkit. Parses `.dem` files into typed intermediate data, computes quantitative stats, and serves a dark analytics web platform with an interactive real-time 2D replay viewer.

## Features

**P0 - Core**
- Multi-demo parsing with content-addressed cache (JSON + Parquet)
- Provider abstraction: auto-detects Valve MM / Faceit / Perfect World demos
- Robust SourceTV handling: roster rebuilt from spawns when `player_info` is absent; T/CT sides from live per-tick `team_num` majority
- Multi-file upload with content-hash dedup + batch job progress page

**P1 - Quantitative Analysis**
- Basic stats: K/D/A, KPR, ADR, Survivals, HS%, First Kills Per Round
- Ratings: RWS, HLTV Rating 2.0 approximation, KAST, Impact
- Player preference: position heatmap, utility placement, peek aggressiveness, crosshair placement
- Advanced: duel matrix (pairwise win rates), economy buy classification (eco/force/full + win rates), utility effectiveness (flash value, smoke kills), opening route clustering (seeded k-means)
- Cross-demo aggregation matched by SteamID

**P2 - Local Web Platform**
- FastAPI + Jinja2 all-Chinese SSR UI (`csa serve`), no node toolchain
- Demo 库: drag-drop upload, stat strip, dense demo table
- Demo detail: score hero, sortable player table, ECharts six-axis radar, round timeline deep-linking into the viewer, per-round kill feed
- Player detail: stat tiles, personal radar, map-position heatmap + utility scatter (ECharts over the official radar PNG)
- Cross-match aggregation: player×demo Rating matrix, per-player bars, T-side score trends, sortable detail table
- Charts are pure JSON payloads (`web/chart_data.py`) rendered by vendored Apache ECharts — fully offline, no matplotlib

**P3 - Real-Time 2D Replay Viewer (Phase C/E/F)**
- Esports OB layout: 2D map center, T/CT 5-player panels (name/weapon icon/ammo/HP/armor/reload badge), scoreboard + round clock + bomb countdown
- Zero prerender wait: viewer-data v3 snapshot pack (8Hz, ~0.73MB gzip) built on first open (<3s)
- Per-tick ammo + reload windows from demoparser2 0.42 (`active_weapon_ammo`/`is_in_reload`/`weapon_reload`)
- Camera: mouse-wheel zoom-to-cursor, drag pan, R/double-click reset
- Advanced overlays (ported from the archived video pipeline): grenade flight arcs + real-duration smoke/fire zones, kill connection lines with headshot accent, muzzle flash + gold tracers (shot yaw from layers v2), blind rings, bomb plant/defuse/explode markers, kill feed widget with weapon icons
- **Map control (控图)**: real-time territory tinting (Gaussian influence kernels + EMA smoothing) with a switchable pseudo-3D extrusion view, football pitch-control style
- Zoom LOD: HP ring, ammo counter, weapon-icon badges fade in as you zoom (≥2.5×/≥3×)
- Overlay toggle toolbar (persisted), tick-domain timeline with side-colored kill dots
- Round deep links `?round=N&t=S`; real team names from the demo header when present

## Installation

```bash
# Requires Python 3.11+ (no ffmpeg needed — there is no server-side rendering)
pip install -e .

# Or with dev dependencies
pip install -e ".[dev]"
```

## Quick Start

最省事的方式：双击仓库根目录的 **`start_web.bat`**（自动起服务 + 打开浏览器；重复点击只开浏览器不会重复起进程），**`stop_web.bat`** 一键关闭。

```bash
# Show demo metadata (quick, no full parse)
csa info path/to/demo.dem

# Parse a demo (cached for reuse)
csa parse path/to/demo.dem

# Run analysis and show stats tables
csa analyze path/to/demo.dem

# Parse-coverage HTML report (which demos/players are fully replayable)
csa coverage "demos/*.dem" --out output/coverage/coverage.html

# Run the local web platform (open http://127.0.0.1:8000 in a browser)
csa serve
```

## CLI Commands

| Command | Description |
| :--- | :--- |
| `csa info <demo>` | Show demo metadata (map, server, provider) |
| `csa parse <demo>` | Parse demo, cache result (JSON + Parquet) |
| `csa analyze <demo>` | Run analysis modules, print stats tables |
| `csa coverage [DEMOS...] [--out html]` | Scan parse coverage -> HTML report (Team 0 / replayability) |
| `csa serve [--host X --port Y]` | Run the local web platform (FastAPI, browser UI) |

Global options: `--config <path>`, `--verbose`, `--provider <valve|faceit|...>`

The legacy matplotlib/manim video pipeline (replay videos, radar video, ffmpeg compositing, recipes, /studio) was retired in Phase E. Its capability catalog and the overlay porting spec live in [docs/video_pipeline_archive.md](docs/video_pipeline_archive.md).

## Configuration

```yaml
parser:
  provider: null  # null = auto-detect

analysis:
  enabled_modules:
    - basic_stats
    - ratings
```

See [configs/default.yaml](configs/default.yaml) for all options.

## Demo 兼容性

已用以下类型的真实 `.dem` 端到端验证：
- **Valve SourceTV**（`tutorial/` 内测试 demo，勿删——测试 fixture 依赖）
- **完美世界平台 (WMPVP)** SourceTV：此类 demo 无 `player_info` 表和 `round_start/round_end` 事件列表项，引擎自动从 `player_spawn` 重建名单、兼容字符串 winner。

已知限制：个别 SourceTV demo 中某些玩家的 pawn 实体无法解析（Team 0）——位置类分析跳过该玩家，统计与击杀数据仍完整。

## Architecture

```
.dem file
    │
    ▼
[Parser] ── demoparser2 + Provider ──> ParsedDemo (DemoData + DataFrames)
    │                                      │
    │                                      ▼
    │                            .cache/{hash}/ (JSON + Parquet)
    │
    ▼
[Analysis] ── pluggable modules ──> typed AnalysisResult (JSON-serializable)
    │
    ▼
[Web] ── FastAPI + Jinja2 SSR ──> browser rendering
    ├── viewer-data v2 JSON  ──> canvas replay viewer (camera + overlays)
    └── charts.json payloads ──> vendored Apache ECharts (dark theme)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design document.

### Layers

| Layer | Responsibility | Key files |
| :--- | :--- | :--- |
| Parser | `.dem` -> typed data | `cs_analyzer/parser/` |
| Model | Pydantic models + serialization | `cs_analyzer/model/` |
| Analysis | Pluggable metric modules | `cs_analyzer/analysis/` |
| Web | SSR pages + JSON data endpoints | `cs_analyzer/web/` |

### Analysis Modules

| Module | Output | Description |
| :--- | :--- | :--- |
| `basic_stats` | `BasicStatsResult` | K/D/A, KPR, ADR, HS%, FKPR |
| `ratings` | `RatingsResult` | RWS, Rating 2.0, KAST, Impact |
| `preference` | `PreferenceResult` | Position heatmap, utility, peek, crosshair |
| `duels` | `DuelMatrixResult` | Pairwise attacker-vs-victim kill matrix |
| `economy` | `EconomyResult` | Per-round eco/force/full buy classification + win rates |
| `utility_effect` | `UtilityEffectResult` | Flash value (enemy/friendly blind seconds), smoke kills |
| `routes` | `OpeningRouteResult` | Opening path clustering (seeded k-means, T side) |

## Caching

Parsed demos are cached by content hash under `.cache/{demo_hash}/`:

```
.cache/
├── {hash}/
│   ├── model.json          # DemoData (metadata, players, rounds)
│   ├── ticks.parquet       # per-tick player state
│   └── events/
│       ├── player_death.parquet
│       ├── player_hurt.parquet
│       └── ...
```

Re-running analysis on the same demo hits cache (< 1s). Use `--no-cache` to force re-parse.

## Map Resources

Each map needs a radar image + coordinate bounds in `cs_analyzer/maps/data/`:

```yaml
# de_mirage.yaml
map_name: de_mirage
image_width: 1024
image_height: 1024
bounds: {min_x: -3230, max_x: 1890, min_y: -3407, max_y: 1713}
```

The PNG backs the viewer basemap and the ECharts map-position charts. Without it, the viewer falls back to a dark canvas with percentile-derived bounds.

## Provider Detection

| Provider | Detection hint |
| :--- | :--- |
| Faceit | "faceit" in server/client name |
| Perfect World | "perfect" / "完美" / "5eplay" in header |
| Valve | "valve" in server/client name (fallback) |

Override with `--provider faceit` or `parser.provider` in config.

## RWS and Rating Notes

RWS and Rating are approximations of proprietary metrics:
- **RWS**: Round Win Shares computed as damage share in won rounds (ESEA-style formula)
- **Rating**: HLTV Rating 2.0 approximation using KAST, KPR, DPR, Impact, ADR

External platforms compute these differently; values are close but not identical.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check cs_analyzer/
```

## Project Structure

```
cs_analyzer/
├── parser/          # .dem parsing + provider abstraction
├── model/           # pydantic models + JSON/Parquet IO
├── analysis/        # pluggable metric modules
├── replay/          # PlayerTimeline (real utility durations, throw reconstruction)
├── maps/            # radar images + coordinate mappings
├── web/             # FastAPI app, templates, static (canvas viewer + ECharts)
├── coverage.py      # parse-coverage scanner + HTML report
├── cli.py           # typer CLI (parse/analyze/coverage/serve/info)
├── cache.py         # content-addressed cache
└── config.py        # pydantic settings
```

## License

MIT
