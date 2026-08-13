# CsDemoAnalyzer

Local-first CS2 demo analysis toolkit. Parses `.dem` files into typed intermediate data, computes statistics, and renders radar charts, 2D action maps, and 2D replay videos (single-player action timelines + 10-player team replays).

## Features

**P0 - Core**
- Multi-demo batch parsing with content-addressed cache (JSON + Parquet)
- Config-driven radar chart video (migrated from the original Manim scene)
- Provider abstraction: auto-detects Valve MM / Faceit / Perfect World demos

**P1 - Visualization**
- 2D action map: multi-round movement trajectories, T/CT colors, phase distinction
- 2D replay videos: single-player action timeline + 10-player team replay (time-driven overlays, utilities/kills/deaths animated)

**P2 - Analysis**
- Basic stats: KPR, ADR, Survivals, HS%, First Kills Per Round
- Ratings: RWS (Round Win Shares), HLTV Rating 2.0 approximation, KAST, Impact
- Player preference: position heatmap data, utility placement, peek aggressiveness, crosshair placement

**P3 - Local Web Platform (LTG-2)**
- FastAPI + Jinja2 all-Chinese server-rendered UI (`csa serve`)
- Single-match review: upload demo -> stats / static radar / preference charts / on-demand replay
- Cross-match aggregation: player rating matrix, T/CT win rates, score trends (matched by steamid)
- Parse-coverage report (`csa coverage`): which demos/players are fully replayable + Team 0 investigation

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

# Render a 2D replay recipe (e.g. 10-player full record)
csa recipe path/to/demo.dem t-full

# Parse-coverage HTML report (which demos/players are fully replayable)
csa coverage "demos/*.dem" --out output/coverage/coverage.html

# Run the local web platform (open http://127.0.0.1:8000 in a browser)
csa serve

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
| `csa replay <demo> [--player X] [--mode overlap-full\|openings\|highlights\|team\|team-highlight\|team-overlap-round\|team-overlap-full] [--speed N] [--rounds a,b] [--composite]` | 2D replay video (single or 10-player) |
| `csa recipe <demo> <name> [--player X] [--override style.yaml] [--list]` | Render a declarative recipe (fine-grained customization) |
| `csa export <demo> --format video\|report` | Export final video or HTML report |
| `csa coverage [DEMOS...] [--out html]` | Scan parse coverage -> HTML report (Team 0 / replayability) |
| `csa serve [--host X --port Y]` | Run the local web platform (FastAPI, browser UI) |
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

## 2D Replay（行动回放 · 常用配方）

俯视地图上动画展示行动：走位轨迹（归位断线）、跳跃、射击、击杀（受害者连线）、投掷道具（**抛掷物飞行 → 落点爆开 → 持续消散**，烟雾真实 ~22s / 燃烧弹 ~7s 时长）、死亡 ☠ 标记、专业 HUD。所有配方**自动去掉准备时间（round_freeze_end 起播）与死亡时间**（单人存活窗口裁剪；团队死者变尸体☠继续播）。带投掷物是标配，无投掷物版本不做。

### 单人（S，`--player <名字或steamid>`）

| 配方 | 成品 | 制备 |
| :-- | :-- | :-- |
| S-全场重叠 | 每回合完整存活路径重叠一图，每回合一色 | `--mode overlap-full` |
| S-开局重叠 | 每回合开局 **30s** 路径重叠，每回合一色 | `--mode openings`（默认 30s，`--opening N` 可调） |
| S-高光 | 指定回合正常速度 | `--mode highlights --rounds 3,5,12 --speed 2` |

### 10人（T，团队，无需 `--player`）

| 配方 | 成品 | 制备 |
| :-- | :-- | :-- |
| T-全场记录(不重叠) | 全员同时连续回放：分色轨迹、尸体☠、击杀连线、全员投掷物 | `--mode team --speed 10` |
| T-高光 | 击杀最多的 3 回合全员回放 | `--mode team-highlights --speed 2` |
| T-高亮单人 | 全员回放但只高亮一名选手（白环+加粗轨迹+★） | `--mode team-highlight --player <steamid>` |
| T-逐回合重叠 | 每回合 10 人路径重叠，逐回合切换 | `--mode team-overlap-round --speed 12` |
| T-全场重叠 | 全场 10 人路径一次性重叠 | `--mode team-overlap-full` |

**团队配色**：T 用黄色系、CT 用蓝色系（队内不同深浅区分个人），一眼分清阵营。所有配方（含重叠类）均带完整动作渲染（抛掷物飞行动画/烟雾/击杀连线）。

## 统一渲染配方框架

所有配方在 `configs/recipes.yaml` 声明式定义（目标 + 模式 + 细粒度样式），用统一入口渲染，任何视觉参数可自定义覆盖：

```bash
# 列出全部配方
csa recipe demo.dem --list

# 按配方渲染（单人配方需 --player）
csa recipe demo.dem t-full
csa recipe demo.dem s-openings --player "PlayerName"

# 细粒度自定义：额外样式覆盖，不动默认配方
csa recipe demo.dem t-full --override my_style.yaml
```

`my_style.yaml` 例子（只写想改的项，其余用配方默认）：

```yaml
canvas:   {width: 1920, height: 1080, fps: 60, bg: "#0a0a0a"}   # 画布/分辨率/帧率
effects:  {show_smoke: true, smoke_color: "#AAAAAA", smoke_max_radius: 150,
           show_flash: false, show_he: true, he_radius: 100}    # 特效逐项开关+颜色+半径
trail:    {seconds: 2.0, width_min: 1.0, width_max: 5.0}       # 轨迹
marker:   {size: 10, halo: true, halo_size: 24}                # 选手标记/光环
hud:      {show_score: true, show_feed: false}                 # HUD 元素
team:     {t_palette: ["#FFD54F","#FFB300"], ct_palette: ["#29B6F6","#0288D1"]}  # 阵营色板
```

样式分层：`canvas / trail / marker / hud / team / effects`，`effects` 里任意细粒度项（`show_*` 开关、各类颜色/半径/时长、投掷物飞行秒数）都可改。低层命令 `csa replay --mode` 仍可用。

```bash
# 单人开局重叠 30s
csa replay demo.dem --player "PlayerName" --mode openings

# 团队全场记录
csa replay demo.dem --mode team --speed 10

# 团队高光
csa replay demo.dem --mode team-highlights
```

`--player` 接受名字或 steamid。默认深色底图（无地图 PNG 时从 tick 数据推导坐标边界）；放地图 PNG 到 `cs_analyzer/maps/data/` 后可显示底图。

已知限制：个别 SourceTV demo 中某些玩家的 tick 位置数据缺失（如 team_num 全空的玩家），单人回放会拒绝并提示换人；团队模式自动跳过该玩家（N 人参与）。

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
[Render] ── RadarChart / ActionMap / ReplayAnimation / TeamReplay ──> RenderArtifact
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
├── render/          # Layer 4: radar chart, action map, replay/team replay
├── export/          # Layer 5: video (ffmpeg), report (HTML/JSON)
├── maps/            # map radar images + coordinate mappings
├── cli.py           # typer CLI
├── batch.py         # batch processing orchestration
├── cache.py         # content-addressed cache
└── config.py        # pydantic settings
```

## License

MIT
