# 交接文档 (HANDOFF)

> 给下一个开发 agent 的交接说明。目标：让接手者能在 10 分钟内了解项目状态、运行环境、验收缺口和下一步。

## 1. 项目状态摘要

CsDemoAnalyzer：本地优先 CS2 demo 分析工具。5 层架构（parser → model → analysis → render → export）已全部落地，9 个 CLI 命令可用，包可导入（`cs_analyzer` 0.1.0），雷达图视频成品已验证产出。

**主分支 commit 历史**（git log，倒序）：
```
37a678d feat: add CSV-to-radar adapter + ffmpeg fallback when ffprobe unavailable
88f95fc chore: gitignore generated artifacts and update dev_log with completion
54ade02 docs: add README with usage examples and architecture overview
0962ba5 feat: add player preference analysis (positioning, utility, peek, crosshair)
7109dbb feat: add T/CT overlap animation renderer + fix steamid type mismatch
7b55c20 feat: add 2D action map renderer with multi-round trajectory overlay
4061e02 feat: add export layer (video + report), batch framework, and typer CLI
57220ef feat: migrate radar chart to config-driven architecture (Layer 4 render)
2b97779 feat: add analysis layer (basic_stats + ratings) and fix CS2 winner/team-side mapping
941de35 feat: add model + parser layers (pydantic models, demoparser2 backend, provider abstraction)
bd80ec1 docs: add ARCHITECTURE.md with layered design and migration plan
51a1af4 archive: pre-agent era final state with radar chart work
```

## 2. 已实现功能（对照验收指标）

| 验收指标 | 状态 | 说明 |
| :--- | :--- | :--- |
| 批量处理 5+ demo | ✅ 已实现 | `csa batch configs/batch_example.yaml --parallel 4`，多进程 + 内容寻址缓存 |
| 雷达图视频 | ✅ 已验证 | `examples/render_radar_from_csv.py` → `output/0922_final.mp4` (28.7MB, 720p, NVENC H.264 + AAC) |
| 2D 行动 map | ✅ 已实现 | `csa action-map <demo> --player <name>`，多回合轨迹重叠、T/CT 分色、阶段区分 |
| T/CT 重叠动画 | ✅ 已实现 | `csa overlap-animation <demo> --player <name>`，MP4/GIF 输出 |
| 偏好分析报告 | ✅ 已实现 | `csa analyze <demo>` 含 `preference` 模块（position/utility/peek/crosshair） |
| 中间结果可序列化 | ✅ 已实现 | metadata → JSON，ticks/events → Parquet（`.cache/{hash}/`） |
| 性能 < 30s 解析 / < 60s 渲染 | ⚠️ 未验证 | demoparser2 Rust 后端理论达标，但无真实 .dem 端到端验证 |
| 类型注解 + 单元测试 | ❌ **缺口** | 类型注解完整，但 `tests/` 目录不存在，零测试 |
| README / ARCHITECTURE | ✅ 完整 | [README.md](README.md) 257 行 + [ARCHITECTURE.md](ARCHITECTURE.md) 681 行 |

## 3. 验收缺口（下一 agent 首要任务）

1. **单元测试缺失**：`tests/` 目录不存在。pyproject.toml 已配置 `[tool.pytest.ini_options]`（testpaths=["tests"]），需补 core 逻辑测试：model 序列化往返、parser 字段映射、analysis 指标数值正确性（对照已知 demo 手算）、export ffmpeg 调用参数。
2. **真实 .dem 端到端验证**：`.dem` 文件被 gitignore（`*.dem`），仓库无测试 demo。性能指标（解析 <30s / 渲染 <60s）和 batch 5+ demo 均未用真实文件验证。
3. **地图 PNG 底图缺失**：`cs_analyzer/maps/data/` 无 `de_mirage.png` + 坐标映射 yaml。当前 2D map / T/CT 动画在黑底渲染轨迹。用户提到雷达图 PNG 因 agent 无法读图而暂缺，需人工放入。

## 4. 运行环境（关键！）

| 项 | 值 |
| :--- | :--- |
| OS | Windows 11 Pro 10.0.26200 |
| Python | `C:\Program Files\Python311\python.exe`（3.11） |
| manim | 0.20.1（注意：`Write(scale=...)` / `Write(shift=...)` 已移除，代码已适配） |
| demoparser2 | 已安装，import 正常 |
| ffmpeg | `D:\ProgramData\oopz\ffmpeg.exe`（2022-10-30 版，支持 NVENC） |
| ffprobe | **缺失** → `VideoExporter` 已实现 `ffmpeg -i` stderr 解析 fallback |
| 虚拟环境 | `enve/`（旧 venv，含 demoparser2） |

**注意**：ffmpeg 不在 PATH，`VideoExporter._find_executable()` 硬编码搜索 `C:/ProgramData/oopz`、`D:/ProgramData/oopz`、`C:/ffmpeg/bin`。若迁移机器需更新该列表。

## 5. 已知问题 / 技术债务

1. **ffprobe 缺失**：已用 `_probe_with_ffmpeg()` fallback（正则解析 `Duration:` 和分辨率），但不是所有编码都可靠。装 ffprobe 可根治。
2. **Manim 0.20 兼容**：已修 `Write` 的 `scale`/`shift` 参数。原版 `cs_radar_chart.py` 仍用旧 API，若重新渲染需用新架构的 `RadarChartRenderer`。
3. **RWS / Rating 是近似**：自实现 HLTV 公式，与 Faceit/完美平台 proprietary 数值有差异，README 已标注。
4. **Player team 名**：`_build_players` 用 `team_number` 生成 `Team 2`/`Team 3` 而非真实队名（Valve MM demo 无队名），provider 层可后续补充。
5. **`statistics_script.py` 遗留**：`radar_data/statistics_script.py` 依赖外部 `match_data.json` 的老流程仍在，新架构从 .dem 直接算，两者并存。`examples/render_radar_from_csv.py` 是 CSV 输入的兼容适配层。

## 6. 关键入口

```bash
# 已验证：雷达图成品（CSV 输入，无需 .dem）
python examples/render_radar_from_csv.py \
  --csv radar_data/0922/player_statistics.csv \
  --title "2024 9/22" \
  --bg bg/halloween_shadows_in_window.mp4 \
  --music "music/Michael Jackson - Thriller.mp3" \
  --output output/0922_final.mp4

# 未验证（需 .dem）：完整管线
python -m cs_analyzer --help          # 9 个命令
python -m cs_analyzer run path/to/demo.dem
python -m cs_analyzer batch configs/batch_example.yaml --parallel 4
```

核心文件：
- CLI: `cs_analyzer/cli.py`
- 解析: `cs_analyzer/parser/backend.py` (demoparser2), `providers.py`
- 模型: `cs_analyzer/model/types.py`, `io.py`
- 分析: `cs_analyzer/analysis/`（basic_stats, ratings, preference）
- 渲染: `cs_analyzer/render/`（radar_chart, action_map, overlap_animation）
- 导出: `cs_analyzer/export/video.py` (ffmpeg), `report.py`
- 缓存: `cs_analyzer/cache.py`, `batch.py`

## 7. 下一步建议（按优先级）

1. **补单元测试**（验收硬缺口）→ `tests/` + fixtures，覆盖 model/parser/analysis/export
2. **准备测试 demo** → 放一个真实 .dem 到 `tests/fixtures/` 或 `demo/`，验证 `csa run` 端到端 + 性能指标
3. **补地图底图** → `cs_analyzer/maps/data/de_mirage.png` + yaml 坐标映射
4. **验证 batch 5+ demo** → 用真实文件跑 `csa batch`
5. **可选**：装 ffprobe 根治探测、provider 补充真实队名映射

## 8. 已验证里程碑（本阶段成果）

- **雷达图成品**：`output/0922_final.mp4`（28.7MB，1分46秒，720p30，6 选手轮播 + halloween 背景 + Thriller 音乐，NVENC 硬件编码）。用 0922 群友内战数据（6 选手），data 来自 `radar_data/0922/player_statistics.csv`。
- 修复：Manim 0.20 API 变更、ffprobe 缺失 fallback、CSV→RadarPlayerData 适配。
