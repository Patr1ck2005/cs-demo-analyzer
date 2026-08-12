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
| 性能：解析 < 30s | ✅ 已验证 | `test_demo.dem`（60MB）解析 <5s（含缓存命中） |
| 性能：渲染 < 60s | ⚠️ 视质量而定 | 1080p60（high_quality）约 5.5min；仅低质量/短场景可达 <60s，见 §3.5 |
| 单元测试 | ✅ 已补齐 | `tests/` 45 个测试全绿（model/parser/analysis/export/render） |
| README / ARCHITECTURE | ⚠️ 有漂移 | [ARCHITECTURE.md](ARCHITECTURE.md) 与代码结构不一致（见 §5.6） |

## 3. 验收缺口（下一 agent 首要任务）

1. **~~单元测试缺失~~ → 已补齐**：`tests/` 45 个测试全绿。覆盖 model 序列化往返、parser 字段映射/回合构建、provider 检测、analysis 指标（basic_stats/ratings/preference 手算对照）、export ffmpeg 探测 fallback、render 雷达数据合并。
2. **~~真实 .dem 端到端~~ → 已验证**：`tutorial/demoparser/src/parser/test_demo.dem`（60MB，demoparser2 自带，gitignore 但仓库内存在）跑通 `csa run`：parse→analyze→radar_chart.mov（59 动画）→report.html→final.mp4。`configs/content_prod.yaml` 产出带 bg+BGM 的 `final_content.mp4`（31MB 1080p）。
3. **地图 PNG 底图缺失**：`cs_analyzer/maps/data/` 只有 `de_mirage.yaml` 无 PNG。**仅影响 2D map / T/CT 动画（B/C 通道），不阻塞雷达图（A 通道）**。
4. **用户真实对局 .dem 缺失**：群友对局（0922/0925 等）原始 .dem 未提供；当前成品用的是测试 demo。产出真正商业价值内容需用户提供自己的 .dem。
5. **渲染性能**：high_quality(1080p60) 110s 场景约 5.5min。若需 <60s 需低质量或短场景；内容生产建议 medium_quality 或降低 fps。

## 4. 运行环境（关键！）

| 项 | 值 |
| :--- | :--- |
| OS | Windows 11 Pro 10.0.26200 |
| Python | **`D:\Program Files\Python311\python.exe`（3.11.9）** — 真正的工作环境 |
| manim | 0.20.1（代码已适配 `Write(scale=...)`/`Write(shift=...)` 移除） |
| demoparser2 | 已安装，import 正常 |
| ffmpeg | `D:\ProgramData\oopz\ffmpeg.exe`（支持 NVENC h264/hevc） |
| ffprobe | **缺失** → `VideoExporter` 已实现 `ffmpeg -i` stderr 解析 fallback |
| 虚拟环境 | `enve/` 是 **DELL 机器复制的旧 venv**（manim 0.18.1），已修 pyvenv.cfg 指向本机，但**不建议使用**；基 Python 已装全部依赖 |

**关键修正（vs 旧 HANDOFF）**：Python 在 `D:\Program Files\Python311`（不是 C:\），旧路径 `C:\Program Files\Python311` 不存在。`enve/` 是陈旧环境。ffmpeg 不在 PATH，`VideoExporter._find_executable()` 硬编码搜索 `C:/ProgramData/oopz`、`D:/ProgramData/oopz`、`C:/ffmpeg/bin`（当前命中 `D:/ProgramData/oopz`）。若迁移机器需更新该列表。

## 5. 已知问题 / 技术债务

1. **ffprobe 缺失**：已用 `_probe_with_ffmpeg()` fallback（正则解析 `Duration:` 和分辨率），但不是所有编码都可靠。装 ffprobe 可根治。
2. **Manim 0.20 兼容**：已修 `Write` 的 `scale`/`shift` 参数。原版 `cs_radar_chart.py` 仍用旧 API，若重新渲染需用新架构的 `RadarChartRenderer`。
3. **RWS / Rating 是近似**：自实现 HLTV 公式，与 Faceit/完美平台 proprietary 数值有差异，README 已标注。
4. **Player team 名**：`_build_players` 用 `team_number` 生成 `Team 2`/`Team 3` 而非真实队名（Valve MM demo 无队名），provider 层可后续补充。
5. **`statistics_script.py` 遗留**：`radar_data/statistics_script.py` 依赖外部 `match_data.json` 的老流程仍在，新架构从 .dem 直接算，两者并存。`examples/render_radar_from_csv.py` 是 CSV 输入的兼容适配层。
6. **ARCHITECTURE.md 与代码漂移**：ARCHITECTURE 是早期规划，代码演进后未同步。实际：`parser/` 是单文件 `providers.py`+`manager.py`（非 `providers/` 5 子文件）；model 是 `types.py`+`parsed_demo.py`+`io.py`（非 demo/player/events/ticks.py）；analysis 只有 `basic_stats/ratings/preference` 三个模块（economy/clutch/refrag 等未实现）；无 `export/image.py`、`render/styles.py`。以代码为准，ARCHITECTURE 仅作意图参考。已更新 §1 实现状态表 + §5 结构树。
7. **WMPVP/完美平台 SourceTV demo 解析**（已修复）：此类 demo 无 `player_info` 表、`list_game_events()` 不列 `round_start/round_end`。backend 已改为全事件尝试 + 从 `player_spawn` 重建玩家 + 兼容字符串 winner（"T"/"CT"）+ round_start 精确边界。**已知限制**：个别玩家 team_num 全空 → 标记 "Team 0"（RWS=0，不影响雷达图属性）。缓存加了 `parser_version` 失效标记，改解析逻辑需同步 bump `cache.PARSER_VERSION`。
8. **个别玩家 tick 位置缺失**（2D 回放）：real_demo_1 中 2 名玩家（庄小蔥、陈平啦4）demoparser2 未跟踪其 per-tick 位置/队伍（同 §7 的 Team 0 玩家），`csa replay` 会拒绝并提示换人。其余 8 名玩家数据完整。若需回放此类玩家，需调查 demoparser2 对该 demo 实体的跟踪问题。

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

1. **提供群友真实 .dem** → 放入仓库（gitignore 已排除，放 `demos/` 即可），跑 `csa run <你的.dem> --config configs/content_prod.yaml` 产出有真实价值的雷达视频
2. **验证 batch 5+ demo** → 用 5+ 个真实 .dem 跑 `csa batch configs/batch_example.yaml --parallel 4`
3. **补地图底图** → `cs_analyzer/maps/data/de_mirage.png` + yaml 坐标映射（B/C 通道需要）
4. **同步 ARCHITECTURE.md** → 对齐实际代码结构（§5.6 列出的漂移点）
5. **可选**：装 ffprobe 根治探测、provider 补充真实队名映射、content 渲染质量可调（当前硬编码 high_quality）

## 8. 已验证里程碑（本阶段成果）

- **2D 回放系统（deepseek-v4-pro 本轮）**：`cs_analyzer/replay/`（PlayerTimeline 数据层）+ `cs_analyzer/render/replay_animation.py`（手动帧循环 + FFMpegWriter）+ `effects.py`/`hud.py`/`fonts.py`。`csa replay` 模式：全场15x / 高光 / **开局 montage**（每回合开局顺序剪辑）/ **重叠 openings**（多回合开局路径同图叠绘、每回合一色）。**注意：开局（opening）与重叠（overlap）是独立概念**（用户明确）：开局 = 每回合开局段；重叠 = 多路径同图叠绘（含既有 `overlap-animation` 的 T/CT 重叠）。轨迹用 LineCollection，归位出生点自动断线。深色底图 + 专业 HUD + 行动特效（跳跃/射击/击杀/道具）。成品：`output/replay_Jake_15x.mp4`（2:03，720p30）、`replay_Jake_highlights.mp4`、`replay_Jake_openings.mp4`。
- **真实对局成品（deepseek-v4-pro 本轮）**：`output/real_demo_1/final.mp4`（30.8MB，1分49秒，1080p，h264 + AAC(Thriller)，halloween 背景）。输入为用户真实 WMPVP 对局（`demos/real_demo_1.dem`，de_ancient，24 回合 14-10，10 玩家），走 .dem 全链路。修复了 WMPVP SourceTV 无 player_info/round_start 的解析问题（§5.7）。
- **.dem 全链路成品（deepseek-v4-pro 本轮）**：`output/test_demo/final_content.mp4`（31MB，1分50秒，1080p，h264 + AAC(Thriller)，halloween 背景）。输入为测试 .dem（`tutorial/demoparser/src/parser/test_demo.dem`）。
- **雷达图成品（GLM5.2 上轮，CSV 路径）**：`output/0922_final.mp4`（28.7MB，1分46秒，720p30，6 选手轮播 + halloween 背景 + Thriller 音乐）。data 来自 `radar_data/0922/player_statistics.csv`。
- **单元测试**：`tests/` 45 个测试全绿。
- 修复：enve venv 跨机失效（pyvenv.cfg 指向本机基 Python）、HANDOFF 中 Python 路径错误、新增 `configs/content_prod.yaml`。
