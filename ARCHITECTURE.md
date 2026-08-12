# CsDemoAnalyzer 架构设计

## 1. 概述

CsDemoAnalyzer 是一个本地优先的 CS2 demo 分析工具，将 `.dem` 文件转换为可序列化的中间数据，再产出统计指标、可视化（雷达图视频、2D 行动 map、T/CT 重叠动画）和分析报告。架构上预留 SaaS 化接口，便于未来包装为 Web 服务。

### 设计目标

| 目标 | 说明 |
| :--- | :--- |
| 本地优先 | CLI 驱动，单机即可完成全流程；不依赖外部服务 |
| SaaS 就绪 | 中间结果可序列化、可缓存、可并行；Provider 抽象隔离来源差异 |
| 现代化 | Python 3.11+，完整类型注解，pydantic 模型，分层清晰 |
| 高性能 | 多进程并行解析，结果缓存，避免重复计算 |
| 可扩展 | 分析模块、渲染器、导出器均为插件式，新增指标只需实现协议 |

### 非目标

- 不做 BSP 地图几何真实解析（使用预渲染的雷达图图片 + 坐标映射）
- 不做可见性/反应时间研究（架构预留接口，本期不实现）
- 不实现 SaaS Web 服务（仅预留接口）
- 不做用户系统/计费

### 实现状态（2026-08 与代码同步）

本文是设计文档，部分内容与实际代码有漂移。以代码为准：

| 设计项 | 状态 |
| :--- | :--- |
| 5 层架构 + 9 个 CLI 命令 | ✅ 已实现 |
| provider 链 | ✅ Valve / Faceit / PerfectWorld（单文件 `providers.py`，非子包） |
| analysis 模块 | ⚠️ 仅 `basic_stats` / `ratings` / `preference` 三个；economy/clutch/refrag/post_plant 未实现，positioning/utility/peek 合并进 `preference.py` |
| `export/image.py`、`render/styles.py` | ❌ 不存在（图像导出走 PIL 在渲染层，样式在 config） |
| maps 数据 | ⚠️ 仅 `de_mirage.yaml`，无 PNG 底图 |
| 解析稳健性 | ✅ 支持无 player_info / 无 round_start 事件的 SourceTV demo（从 spawns 重建玩家、兼容字符串 winner） |

---

## 2. 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI (typer)                          │
│   parse | analyze | render | export | run | batch          │
└──────────────┬──────────────────────────────────────────────┘
               │
   ┌───────────▼────────────┐
   │    Config (YAML +      │  跨层共享：配置、缓存、日志
   │    pydantic settings)  │
   └───────────┬────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│  Layer 1: Parser          .dem ──> raw DataFrames           │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  DemoParserBackend (demoparser2, Rust-backed)       │    │
│  └──────────────────┬──────────────────────────────────┘    │
│                     │                                       │
│  ┌──────────────────▼──────────────────────────────────┐    │
│  │  Provider 层                                         │    │
│  │  Valve | Faceit | ESEA | 5EPlay | PerfectWorld      │    │
│  │  (检测来源、归一化元数据、修正回合边界)              │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│  Layer 2: Model           raw ──> typed DemoData            │
│  pydantic models: DemoData, Match, Round, Player,           │
│                   PlayerState, GameEvent 子类型              │
│  序列化: JSON (元数据/事件) + Parquet (tick 级位置数据)     │
│  缓存: content-hash key, .cache/{hash}/model.json           │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│  Layer 3: Analysis        DemoData ──> AnalysisResult       │
│  可插拔模块 (AnalysisModule ABC):                            │
│   BasicStats | Ratings | Positioning | Utility | Peek |     │
│   Economy | Clutch | Refrag | PostPlant | TeamCoord         │
│  每个模块产出 typed result, 可独立缓存                       │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│  Layer 4: Render          metrics ──> RenderArtifact        │
│  RadarChartRenderer (Manim, 迁移自现有代码)                 │
│  ActionMapRenderer (2D 轨迹热图, matplotlib)                │
│  OverlapAnimationRenderer (T/CT 动画, Manim)                │
│  样式由 config 驱动 (颜色/字体/时机)                        │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│  Layer 5: Export          artifact ──> final output         │
│  VideoExporter (ffmpeg + NVENC, 背景叠加 + 音乐)            │
│  ImageExporter (PNG / SVG)                                  │
│  ReportExporter (JSON / HTML via jinja2)                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 数据流

### 单 demo 全流程

```
demo.dem
  │
  ├─[Parser]─> DemoParserBackend.parse(path) ──> raw DataFrames
  │                                                (events, ticks, players)
  │
  ├─[Provider.detect] ──> ProviderKind (Faceit/Valve/...)
  │
  ├─[Provider.normalize] ──> 修正回合边界、元数据
  │
  ├─[Model.build] ──> DemoData (pydantic, validated)
  │                      │
  │                      ├─> .cache/{hash}/model.json   (元数据 + 事件)
  │                      └─> .cache/{hash}/ticks.parquet (tick 级位置)
  │
  ├─[Analysis.run] ──> 各模块并行计算
  │                      │
  │                      └─> AnalysisResultSet (typed)
  │
  ├─[Render] ──> 选择 renderer, 输入 metrics + style config
  │                  │
  │                  └─> RenderArtifact (Manim scene / matplotlib fig)
  │
  └─[Export] ──> VideoExporter / ImageExporter / ReportExporter
                     │
                     └─> final mp4 / png / html / json
```

### 批量流程

```
configs/batch.yaml (列出多个 .dem 路径)
  │
  ▼
[BatchRunner]
  │
  ├─ multiprocessing.Pool(parser workers)
  │     每个 worker: parse ──> model ──> cache
  │
  ├─ 进度条 (rich.progress)
  │
  ├─ 分析阶段 (可并行, 每个 demo 独立)
  │
  ├─ 渲染阶段 (Manim 单进程, 避免资源竞争)
  │
  └─ 导出阶段
```

---

## 4. 关键设计决策

### 4.1 demoparser2 作为解析后端

**选择**：使用 [demoparser2](https://github.com/LaihoE/demoparser) 作为唯一解析后端。

**理由**：
- Rust 实现，性能极强（749 MB/s on gaming PC，4.6GB / 6.14s）
- 已在项目中使用（`first_donk.py`）
- 支持所有需要的字段：玩家位置 (X/Y/Z)、pitch/yaw、血量/护甲、武器、金钱、按钮状态、聚合统计 (kills_total, damage_total 等)
- 支持所有事件：player_hurt, player_death, weapon_fire, round_start, round_end, bomb_planted 等
- Python API 友好：返回 pandas DataFrame

**不自己写解析器**：CS2 demo 格式复杂，自写解析器投入产出比低。demoparser2 已覆盖所有 Valve demo 兼容格式（MM/Faceit/HLTV 等）。

### 4.2 Provider 抽象

所有平台（Valve MM / Faceit / ESEA / 5EPlay / 完美）的 `.dem` 文件都使用 Valve 标准 demo 格式，差异仅在元数据和约定：

| 差异点 | 例子 |
| :--- | :--- |
| match_id 格式 | Faceit 是 UUID，完美是数字串 |
| 队伍命名 | Faceit 用队名，MM 用 "Team X" |
| 回合边界 | 部分平台包含 warmup 回合，需识别并剔除 |
| 服务器信息 | 平台标识有时写入 game_phase 或 server name |

**Provider 职责**：
1. `detect(dem_path) -> bool`：根据元数据判断是否为该 provider 的 demo
2. `parse(dem_path) -> DemoData`：调用共享的 DemoParserBackend，再应用 provider 特定的归一化
3. `get_metadata(dem_path) -> MatchMetadata`：提取来源特定的元数据

```python
class DemoProvider(ABC):
    @abstractmethod
    def detect(self, dem_path: Path) -> bool: ...

    @abstractmethod
    def parse(self, dem_path: Path) -> DemoData: ...

    @abstractmethod
    def kind(self) -> ProviderKind: ...
```

**注册机制**：启动时遍历所有 provider，按优先级尝试 `detect`，首个匹配的负责解析。用户可通过 config 强制指定。

### 4.3 Pydantic 数据模型

所有中间数据使用 pydantic v2 模型：

- **类型安全**：字段类型完整标注，IDE 自动补全
- **验证**：解析时自动校验（如 tick 必须 >= 0，血量 0-100）
- **序列化**：原生支持 JSON dump/load，带 schema 版本
- **SaaS 友好**：FastAPI 等框架原生集成 pydantic

核心模型层级：

```
DemoData
├── metadata: MatchMetadata         (地图、时间、provider、match_id)
├── players: list[Player]           (steamid、name、team)
├── rounds: list[Round]             (每回合: 起始tick、结束tick、winner、bomb_site)
└── events: list[GameEvent]         (player_hurt, player_death, weapon_fire, ...)
    └── 每个 event 关联 tick, player, attacker, weapon, position, etc.

TickData (单独存储, Parquet)
├── tick: int
├── player_steamid: str
├── x, y, z: float                  (世界坐标)
├── pitch, yaw: float               (视角)
├── health, armor: int
├── velocity_x/y/z: float
├── active_weapon: str
└── is_alive: bool
```

### 4.4 Parquet 用于 tick 级数据

**问题**：一局 demo 的 tick 数据量巨大（5v5, ~100s 回合 × 64 tick/s × 10 玩家 ≈ 数十万行）。

**选择**：元数据和事件用 JSON（小、可读、便于调试）；tick 级位置数据用 Parquet（列式存储、高压缩、快速查询）。

**收益**：
- 缓存大小可控（Parquet 压缩比 JSON 高 5-10x）
- 按玩家/回合查询时列式扫描快
- pandas / polars 原生支持，无需额外依赖

### 4.5 可插拔分析模块

```python
class AnalysisModule(ABC):
    name: ClassVar[str]
    requires: ClassVar[list[str]]   # 依赖的其他模块名

    @abstractmethod
    def run(self, demo: DemoData, ctx: AnalysisContext) -> AnalysisResult: ...
```

**注册表**：`AnalysisRegistry` 启动时自动发现所有模块，按依赖拓扑排序。用户通过 config 启用/禁用模块。

**结果独立缓存**：每个模块的结果单独存为 `.cache/{demo_hash}/{module_name}.json`，修改某模块只重算该模块。

### 4.6 配置驱动的渲染

现有 `cs_radar_chart.py` 的所有硬编码（`entry_times`, `time_control`, `title_text`, `dataset_name`, `attribute_ranges`）全部移到 YAML config：

```yaml
# configs/radar_chart.yaml
render:
  radar_chart:
    title: "2024 9/22"
    subtitle: "群友数据图"
    attributes: [KPR, Survivals, ADR, Headshot%, FirstKillsPerRound, Rating Pro]
    attribute_ranges:
      KPR: [0.5, 0.9]
      Survivals: [0.2, 0.35]
      # ...
    style:
      highlight_color: "#FFD700"
      normal_color: "#FFFFFF"
      background_color: "#1A1A1A"
      radar_size: 2.4
    timing:
      show_title: 3
      show_ticks_def: 12
      # ...
      entry_times: [42, 50, 60, 68, 75, 82]
    assets:
      player_images_dir: "radar_data"
      default_image: "radar_data/default.jpg"
```

### 4.7 缓存策略

**缓存键**：`sha256(dem_file_content) + parser_version`

**目录结构**：
```
.cache/
├── {demo_hash}/
│   ├── model.json           (DemoData 元数据 + 事件)
│   ├── ticks.parquet        (tick 级位置数据)
│   ├── basic_stats.json     (各分析模块结果)
│   ├── positioning.json
│   └── ...
└── index.json               (全局索引: demo_hash -> 文件路径/解析时间/大小)
```

**失效条件**：
- demo 文件内容变更（hash 变化）
- parser 版本升级
- 用户强制 `--no-cache`

---

## 5. 项目结构

> 以下为**当前实际代码**布局（2026-08 与代码同步）。早期规划与实现的差异见 §1 的实现状态表。

```
CsDemoAnalyzer/
├── cs_analyzer/                       # 主包
│   ├── __init__.py
│   ├── __main__.py                    # python -m cs_analyzer
│   ├── cli.py                         # typer CLI 入口（9 个命令）
│   ├── config.py                      # pydantic settings
│   ├── cache.py                       # 哈希缓存 + parser_version 失效标记
│   ├── batch.py                       # BatchRunner 批处理编排
│   │
│   ├── parser/                        # Layer 1
│   │   ├── __init__.py
│   │   ├── backend.py                 # demoparser2 封装（事件/玩家/回合构建）
│   │   ├── manager.py                 # ParseManager: 缓存 + provider 检测编排
│   │   └── providers.py               # DemoProvider ABC + Valve/Faceit/PW + 检测链
│   │
│   ├── model/                         # Layer 2
│   │   ├── __init__.py
│   │   ├── types.py                   # DemoData, MatchMetadata, Player, Round, Team
│   │   ├── parsed_demo.py             # ParsedDemo 容器 + 查询辅助
│   │   └── io.py                      # JSON/Parquet 序列化
│   │
│   ├── analysis/                      # Layer 3
│   │   ├── __init__.py
│   │   ├── base.py                    # AnalysisModule ABC + 注册表
│   │   ├── runner.py                  # AnalysisRunner 模块执行/依赖排序
│   │   ├── basic_stats.py             # KPR/ADR/Survivals/HS%/FK
│   │   ├── ratings.py                 # RWS, HLTV Rating 2.0, KAST, Impact
│   │   └── preference.py              # 位置/道具/Peek/准星（合并自 4 个规划模块）
│   │
│   ├── render/                        # Layer 4
│   │   ├── __init__.py
│   │   ├── base.py                    # Renderer ABC + RadarPlayerData + merge
│   │   ├── image_utils.py             # 头像裁剪/透明度工具（迁移自 utils/image_pre.py）
│   │   ├── radar_chart.py             # PlayerRadarChart + RadarChartRenderer
│   │   ├── action_map.py              # 2D 行动 map
│   │   └── overlap_animation.py       # T/CT 重叠动画
│   │
│   ├── export/                        # Layer 5
│   │   ├── __init__.py
│   │   ├── base.py                    # Exporter ABC
│   │   ├── video.py                   # ffmpeg 合成 (bg + music, NVENC)
│   │   └── report.py                  # JSON/HTML 报告
│   │
│   └── maps/                          # 地图资源
│       ├── __init__.py
│       ├── loader.py                  # 雷达图加载、坐标映射
│       └── data/                      # 目前仅 de_mirage.yaml（无 PNG）
│
├── configs/                           # 示例配置
│   ├── default.yaml
│   ├── batch_example.yaml
│   └── content_prod.yaml              # 内容生产：背景 + BGM
│
├── tests/
│   ├── conftest.py                    # 合成 demo fixtures
│   ├── test_model.py
│   ├── test_parser.py
│   ├── test_analysis.py
│   ├── test_render.py
│   └── test_export.py
│
├── examples/
│   └── render_radar_from_csv.py       # CSV 适配器（旧流程兼容）
│
├── pyproject.toml
├── ARCHITECTURE.md
├── README.md
├── HANDOFF.md
└── dev_log.md
```

---

## 6. Provider 抽象详解

```python
from enum import Enum

class ProviderKind(str, Enum):
    VALVE = "valve"
    FACEIT = "faceit"
    ESEA = "esea"
    FIVEE = "5eplay"
    PERFECT_WORLD = "perfect_world"
    UNKNOWN = "unknown"


class DemoProvider(ABC):
    @abstractmethod
    def kind(self) -> ProviderKind: ...

    @abstractmethod
    def detect(self, dem_path: Path) -> bool:
        """根据 demo 元数据判断是否匹配本 provider。"""

    @abstractmethod
    def parse(self, dem_path: Path) -> DemoData:
        """解析 demo, 返回归一化后的 DemoData。"""

    def normalize(self, demo: DemoData) -> DemoData:
        """provider 特定的归一化 (默认无操作, 子类按需 override)。"""
        return demo


class ValveProvider(DemoProvider):
    def kind(self) -> ProviderKind:
        return ProviderKind.VALVE

    def detect(self, dem_path: Path) -> bool:
        # Valve MM demos: server name 含 "Valve", 或 game_type 标识
        ...

class FaceitProvider(DemoProvider):
    def kind(self) -> ProviderKind:
        return ProviderKind.FACEIT

    def detect(self, dem_path: Path) -> bool:
        # Faceit demos: match_id 是 UUID 格式, 或 team_clan_name 非空
        ...


# Provider 链：按优先级尝试, 首个 detect 成功的负责解析
DEFAULT_PROVIDER_CHAIN = [
    FaceitProvider(),
    PerfectWorldProvider(),
    FiveEProvider(),
    ESEAProvider(),
    ValveProvider(),      # 兜底
]
```

**设计要点**：
- 所有 provider 共享同一个 `DemoParserBackend`，差异只在元数据归一化
- `detect` 应快速（只读 header，不全量解析）
- 用户可在 config 中强制 `provider: faceit` 跳过自动检测

---

## 7. 配置系统

使用 YAML + pydantic settings，支持多级合并（默认 < 用户 < 命令行）。

```python
# cs_analyzer/config.py
from pydantic import BaseModel
from pydantic_settings import BaseSettings

class ParserConfig(BaseModel):
    provider: str | None = None        # None = 自动检测
    tick_rate: int = 64
    include_warmup: bool = False
    fields: list[str] = [              # 解析的 tick 字段
        "X", "Y", "Z", "pitch", "yaw",
        "health", "armor", "velocity",
        "active_weapon", "is_alive",
    ]

class AnalysisConfig(BaseModel):
    enabled_modules: list[str] = ["basic_stats", "ratings"]
    module_options: dict[str, dict] = {}

class RenderConfig(BaseModel):
    output_dir: Path = Path("output")
    radar_chart: RadarChartConfig | None = None
    action_map: ActionMapConfig | None = None
    overlap_animation: OverlapAnimationConfig | None = None

class ExportConfig(BaseModel):
    video: VideoExportConfig = VideoExportConfig()
    image: ImageExportConfig = ImageExportConfig()
    report: ReportExportConfig = ReportExportConfig()

class Settings(BaseSettings):
    parser: ParserConfig = ParserConfig()
    analysis: AnalysisConfig = AnalysisConfig()
    render: RenderConfig = RenderConfig()
    export: ExportConfig = ExportConfig()
    cache_dir: Path = Path(".cache")
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        yaml_file="configs/default.yaml",
        env_prefix="CSA_",
    )
```

**批量配置示例**：

```yaml
# configs/batch_example.yaml
batch:
  demos:
    - path: "demos/match1.dem"
    - path: "demos/match2.dem"
    - path: "demos/match3.dem"
      provider: faceit           # 强制指定
  parallel: 4                     # 并行 worker 数

parser:
  include_warmup: false

analysis:
  enabled_modules:
    - basic_stats
    - ratings
    - positioning
    - utility

render:
  radar_chart:
    title: "群友内战集锦"
    timing:
      entry_times: auto           # auto = 按选手数自动等距分布

export:
  video:
    background: "bg/halloween.mp4"
    music: "music/thriller.mp3"
    use_nvenc: true
```

---

## 8. 扩展点

新增能力只需实现对应协议，无需改动核心代码：

| 扩展类型 | 协议 | 注册方式 |
| :--- | :--- | :--- |
| 新 Provider | `DemoProvider` | 加入 provider chain |
| 新分析模块 | `AnalysisModule` | `@register_module` 装饰器 |
| 新渲染器 | `Renderer` | `@register_renderer` 装饰器 |
| 新导出器 | `Exporter` | `@register_exporter` 装饰器 |
| 新地图 | `maps/data/{map}.yaml + .png` | 文件即注册 |

---

## 9. 性能考量

| 操作 | 目标 | 实现方式 |
| :--- | :--- | :--- |
| 单 demo 解析 | < 30s | demoparser2 Rust 后端，4.6GB 仅需 6s |
| 单 demo 渲染 | < 60s | Manim 1080p60, 30s 场景约 30-50s |
| 批量 5 demo | < 5 min | 多进程并行解析，缓存复用 |
| 内存占用 | < 2GB | tick 数据流式处理，Parquet 列式加载 |
| 缓存命中 | < 1s | 直接读 `.cache/{hash}/model.json` |

**并行策略**：
- 解析阶段：`multiprocessing.Pool`，每个 worker 处理一个 demo
- 分析阶段：同 demo 内模块间有依赖，串行；不同 demo 间可并行
- 渲染阶段：Manim 使用 OpenGL，单进程串行（避免 GPU 资源竞争）
- 导出阶段：ffmpeg 可并行（每个 demo 独立进程）

---

## 10. SaaS 迁移路径

架构设计已为 SaaS 化预留：

| 本地 CLI 概念 | SaaS 对应 |
| :--- | :--- |
| `.dem` 文件路径 | 上传的文件对象 (S3 URL / blob storage) |
| `.cache/` 目录 | Redis / 对象存储 (键: demo_hash) |
| `multiprocessing.Pool` | Celery / task queue |
| `typer` CLI | FastAPI endpoint |
| `Settings` (YAML) | per-tenant config (DB / config service) |
| `AnalysisModule` | 微服务 / serverless function |

**关键约束**：所有中间结果可序列化（JSON/Parquet），无内存共享假设。Provider 无状态，可水平扩展。

---

## 11. 从现有代码迁移策略

### 雷达图迁移（P0）

现有 `cs_radar_chart.py` 的 `PlayerRadarChart` 类迁移为 `cs_analyzer/render/radar_chart.py` 的 `RadarChartRenderer`：

| 现有（硬编码） | 新架构（配置驱动） |
| :--- | :--- |
| `self.entry_times = [42, 50, ...]` | `config.render.radar_chart.timing.entry_times` |
| `self.title_text = "2024\n9/22?"` | `config.render.radar_chart.title` |
| `dataset_name = '0922'` | `config.input.dataset_name` 或自动从 demo metadata |
| `self.attribute_ranges = {...}` | `config.render.radar_chart.attribute_ranges` |
| `self.attributes = [...]` | `config.render.radar_chart.attributes` |
| `self.music` | `config.export.video.music` |

**迁移原则**：
- 保留所有 Manim 动画逻辑不变（用户对成品满意）
- 数据来源从 `player_statistics.csv` 改为 `AnalysisResultSet`（直接从 demo 算出）
- 静态资源（选手头像、队伍图标）路径可配置，默认沿用 `radar_data/` 目录
- `ffmpeg_out_put.py` 的逻辑迁移到 `cs_analyzer/export/video.py`

### 统计指标迁移

现有 `radar_data/statistics_script.py` 依赖外部 `match_data.json`（来自完美平台等）。新架构直接从 demo 计算：

| 指标 | 来源 | 实现方式 |
| :--- | :--- | :--- |
| KPR | demo | `kills_total / rounds` (demoparser2 聚合字段) |
| ADR | demo | `damage_total / rounds` |
| Survivals | demo | `(rounds - deaths_total) / rounds` |
| Headshot% | demo | `headshot_kills_total / kills_total` |
| FirstKillsPerRound | demo | 解析 `player_death` 事件, 每回合首个击杀 |
| RWS | demo | 自实现 (Round Win Shares 公式, 见 `analysis/ratings.py`) |
| Rating Pro | demo | 自实现 HLTV Rating 2.0 近似公式 |

**RWS / Rating 说明**：外部平台的 RWS 和 Rating Pro 是各自 proprietary 公式，新架构实现的版本可能与平台数值有差异。在报告中明确标注"自算 RWS (HLTV 公式)"以避免混淆。

---

## 12. 测试策略

| 层 | 测试重点 | 工具 |
| :--- | :--- | :--- |
| Parser | provider 检测准确性、字段完整性、边界 demo | pytest + 小样本 demo fixture |
| Model | 序列化往返、schema 版本兼容、验证规则 | pytest + pydantic 验证 |
| Analysis | 指标计算正确性（与已知 demo 手算对照） | pytest, 数值容差 |
| Render | 渲染产物存在性、关键元素存在（不验证像素） | pytest + 文件检查 |
| Export | ffmpeg 调用参数、输出文件有效性 | pytest + ffprobe 检查 |

**测试 demo**：在 `tests/fixtures/` 放一个小的 .dem 文件（或用 git-lfs），用于回归测试。

---

## 13. 依赖清单

```toml
[project]
dependencies = [
    "demoparser2>=2.0",        # demo 解析
    "pydantic>=2.0",           # 数据模型
    "pydantic-settings>=2.0",  # 配置
    "typer>=0.9",              # CLI
    "rich>=13.0",              # 终端输出 / 进度条
    "pandas>=2.0",             # 数据处理
    "pyarrow>=14.0",           # Parquet 支持
    "numpy>=1.24",
    "manim>=0.18",             # 动画渲染
    "Pillow>=10.0",            # 图像处理
    "matplotlib>=3.7",         # 2D 图表
    "jinja2>=3.1",             # HTML 报告模板
    "pyyaml>=6.0",             # YAML 配置
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "ruff>=0.1",               # linter + formatter
    "mypy>=1.5",               # 类型检查
]
```

---

## 14. 开放问题（待实现时决策）

1. **地图坐标映射**：每个地图需要一个"世界坐标 -> 雷达图像素"的映射表。是手动标定几个锚点然后仿射变换，还是从 BSP 文件提取？本期用手动标定（`maps/data/{map}.yaml`），预留 BSP 解析接口。

2. **RWS / Rating 公式精度**：自实现的公式与外部平台数值会有差异。是否提供"导入外部 JSON"作为后备？建议在 `analysis/ratings.py` 同时支持"从 demo 自算"和"从外部 JSON 读取"两种模式。

3. **Manim 渲染稳定性**：Manim OpenGL 渲染有时会崩。是否提供 Cairo renderer 后备？建议 `config.render.radar_chart.renderer = "opengl" | "cairo"`。

4. **大 demo 内存**：极长 demo（如 5 map BO5）的 tick 数据可能超 1GB。是否流式处理？Parquet 按回合分片可缓解。

5. **Provider 自动检测准确率**：需要收集各平台 demo 样本验证 `detect` 逻辑。本期先实现 Valve + Faceit + PerfectWorld 三个主要 provider。
