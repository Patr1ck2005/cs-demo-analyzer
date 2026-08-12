# CsDemoAnalyzer

Local-first CS2 demo analysis toolkit. Parses `.dem` files into typed intermediate data, computes statistics, and renders radar charts, 2D action maps, and T/CT overlap animations.

## Features

**P0 - Core**
- Multi-demo batch parsing with content-addressed cache (JSON + Parquet)
- Config-driven radar chart video (migrated from the original Manim scene)
- Provider abstraction: auto-detects Valve MM / Faceit / Perfect World demos

**P1 - Visualization**
- 2D action map: multi-round movement trajectories, T/CT colors, phase distinction
- T/CT overlap animation: player's T-side and CT-side trajectories animated over time

**P2 - Analysis**
- Basic stats: KPR, ADR, Survivals, HS%, First Kills Per Round
- Ratings: RWS (Round Win Shares), HLTV Rating 2.0 approximation, KAST, Impact
- Player preference: position heatmap data, utility placement, peek aggressiveness, crosshair placement

## Installation

```bash
# Requires Python 3.11+, ffmpeg (for video output)
pip install -e .

# Or with dev dependencies
pip install -e ".[dev]"
```

**ffmpeg**: Required for video export. Add to PATH or install via your package manager.

## Quick Start

```bash
# Show demo metadata (quick, no full parse)
csa info path/to/demo.dem

# Parse a demo (cached for reuse)
csa parse path/to/demo.dem

# Run analysis and show stats
csa analyze path/to/demo.dem

# Render radar chart video
csa render path/to/demo.dem --output output/radar.mov

# Render 2D action map
csa action-map path/to/demo.dem --player "PlayerName" --output output/action_map.png

# Render T/CT overlap animation
csa overlap-animation path/to/demo.dem --player "PlayerName" --output output/overlap.gif

# Full pipeline: parse + analyze + render + export
csa run path/to/demo.dem

# Batch process
csa batch configs/batch_example.yaml --parallel 4
```

## CLI Commands

| Command | Description |
| :--- | :--- |
| `csa info <demo>` | Show demo metadata (map, server, provider) |
| `csa parse <demo>` | Parse demo, cache result (JSON + Parquet) |
| `csa analyze <demo>` | Run analysis modules, print stats table |
| `csa render <demo>` | Render radar chart video (.mov) |
| `csa action-map <demo> --player <name>` | 2D movement trajectory map (PNG) |
| `csa overlap-animation <demo> --player <name>` | T/CT overlap animation (GIF/MP4) |
| `csa export <demo> --format video\|report` | Export final video or HTML report |
| `csa run <demo>` | Full pipeline (parse + analyze + render + export) |
| `csa batch <config.yaml>` | Batch process multiple demos |

Global options: `--config <path>`, `--verbose`, `--provider <valve|faceit|...>`

## Configuration

YAML config controls parsing, analysis, rendering, and export. See [configs/default.yaml](configs/default.yaml) for all options.

```yaml
parser:
  provider: null  # null = auto-detect

analysis:
  enabled_modules:
    - basic_stats
    - ratings
    - preference

render:
  radar_chart:
    title: "My Match"
    attributes: [KPR, Survivals, ADR, Headshot%, FirstKillsPerRound, Rating Pro]
    timing:
      entry_times: null  # null = auto-distribute by player count

export:
  video:
    background: bg/halloween.mp4
    music: music/thriller.mp3
    use_nvenc: true
```

**内容生产配置**：[configs/content_prod.yaml](configs/content_prod.yaml) 预设背景 + BGM + 标题，用于直接产出 `.dem` 全链路雷达视频成品：

```bash
csa run path/to/demo.dem --config configs/content_prod.yaml
```

## Demo 兼容性

已用以下类型的真实 `.dem` 端到端验证：
- **Valve SourceTV**（`tutorial/demoparser/.../test_demo.dem`）
- **完美世界平台 (WMPVP)** SourceTV：此类 demo 无 `player_info` 表和 `round_start/round_end` 事件列表项，引擎会自动从 `player_spawn` 事件重建玩家名单、从 `parse_event('round_end')` 获取回合与胜者（兼容字符串 "T"/"CT" winner）。

已知限制：个别 SourceTV demo 中某些玩家的 team_num 字段全空，会标记为 "Team 0"（不影响雷达图属性，仅 RWS 与 T/CT 着色受影响）。

## Architecture

Five-layer pipeline with provider abstraction and serializable intermediates.

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
[Analysis] ── pluggable modules ──> AnalysisResult (typed, JSON-serializable)
    │
    ▼
[Render] ── RadarChart / ActionMap / OverlapAnimation ──> RenderArtifact
    │
    ▼
[Export] ── ffmpeg / PIL / jinja2 ──> final output (mp4/png/html/json)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design document.

### Layers

| Layer | Responsibility | Key files |
| :--- | :--- | :--- |
| Parser | `.dem` -> typed data | `cs_analyzer/parser/` |
| Model | Pydantic models + serialization | `cs_analyzer/model/` |
| Analysis | Pluggable metric modules | `cs_analyzer/analysis/` |
| Render | Visualizations | `cs_analyzer/render/` |
| Export | Final output formats | `cs_analyzer/export/` |

### Analysis Modules

| Module | Output | Description |
| :--- | :--- | :--- |
| `basic_stats` | `BasicStatsResult` | K/D/A, KPR, ADR, HS%, FKPR |
| `ratings` | `RatingsResult` | RWS, Rating 2.0, KAST, Impact |
| `preference` | `PreferenceResult` | Position heatmap, utility, peek, crosshair |

Enable via `analysis.enabled_modules` in config. Modules can declare dependencies (`requires`); the runner resolves order automatically.

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
bounds:
  min_x: -2700.0
  max_x: 1500.0
  min_y: -2700.0
  max_y: 900.0
```

Place the radar PNG at `cs_analyzer/maps/data/de_mirage.png`. Action maps and animations overlay trajectories on this image. Without the PNG, trajectories render on a dark background.

## Provider Detection

Providers are auto-detected from the demo header (server name, client name):

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

External platforms (Faceit, Perfect World) may compute these differently. Values will be close but not identical.

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check cs_analyzer/
mypy cs_analyzer/
```

### Adding an Analysis Module

```python
from cs_analyzer.analysis.base import AnalysisModule, AnalysisResult, register_module

class MyResult(AnalysisResult):
    ...

@register_module
class MyModule(AnalysisModule):
    name = "my_module"
    requires = ("basic_stats",)  # optional dependencies

    def run(self, demo, ctx):
        return MyResult(module=self.name, ...)
```

Register it in `cs_analyzer/analysis/runner.py` imports, then enable via config.

## Project Structure

```
cs_analyzer/
├── parser/          # Layer 1: .dem parsing + provider abstraction
├── model/           # Layer 2: pydantic models + JSON/Parquet IO
├── analysis/        # Layer 3: pluggable metric modules
├── render/          # Layer 4: radar chart, action map, overlap animation
├── export/          # Layer 5: video (ffmpeg), report (HTML/JSON)
├── maps/            # map radar images + coordinate mappings
├── cli.py           # typer CLI
├── batch.py         # batch processing orchestration
├── cache.py         # content-addressed cache
└── config.py        # pydantic settings
```

## License

MIT
