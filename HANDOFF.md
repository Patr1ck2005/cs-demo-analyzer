# 交接文档 (HANDOFF)

> 给下一个开发 agent 的交接说明。目标：让接手者能在 10 分钟内了解项目状态、运行环境、验收缺口和下一步。

## 1. 项目状态摘要

CsDemoAnalyzer：本地优先 CS2 demo 分析工具。5 层架构（parser → model → analysis → render → export）已全部落地，9 个 CLI 命令入口保留，雷达图视频成品已验证产出。

**当前形态（2026-08-23, Phase C 完成后）**：产品定位 = **CS2 demo 分析器**（非视频工作室），两个分析视角——定量（统计/雷达/聚合）+ 空间-时间（**Canvas 实时回放器**，电竞 OB 观赛布局）。本地 Web 平台（FastAPI, `csa serve` → `http://127.0.0.1:8000`）是主入口；matplotlib 视频管线冻结迭代（studio 导出仍可用）。149 测试全绿。

**主分支 commit 历史**（git log，倒序，最新 3 条）：
```
6b41e58 feat: web demo analyzer (2D viewer + export studio) + load speedups
395edb3 feat: web demo analyzer platform + replay/video polish checkpoint
dcb9d4f feat: add parse coverage scanner + report (LTG-3)
```
（Phase B 加速 + Phase C canvas 实时回放器改动在工作区待提交，见 §7。）

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
8. **个别玩家 tick 位置缺失（Team 0 / pawn 未解析）**：某些 WMPVP SourceTV demo 中个别玩家（如 de_ancient 的 庄小葵/陈平安4，de_inferno 的 斯文酱qaq 等）demoparser2 完全无法解析其 pawn 实体——ticks 表有行但 X/Y/team_num 全 NaN，且**所有事件的位置字段同样全 NaN**（事件计数正常）。这是 demoparser2 库层限制、逐广播特定（同一 steamid 在另一 demo 可正常回放），无法从事件重建位置。`csa replay` 对这类玩家拒绝并提示换人；事件类统计仍完整。判定逻辑：`cs_analyzer/coverage.py` + `scripts/probe_team0.py`；完整结论见 `output/coverage/coverage.html`。

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
- CLI: `cs_analyzer/cli.py`（replay/recipe/coverage/serve 等命令）
- 配方: `cs_analyzer/recipe.py` + `configs/recipes.yaml`（声明式配方 + 细粒度样式覆盖）
- 覆盖度: `cs_analyzer/coverage.py`（DemoCoverage/scan_demo/render_coverage_report）+ `scripts/probe_team0.py`（Team 0 探针）
- 解析: `cs_analyzer/parser/backend.py` (demoparser2), `providers.py`
- 模型: `cs_analyzer/model/types.py`, `io.py`
- 分析: `cs_analyzer/analysis/`（basic_stats, ratings, preference, **aggregate** 跨场聚合）
- 回放: `cs_analyzer/replay/timeline.py`（PlayerTimeline + round_freeze_ends + 存活窗口）
- 渲染: `cs_analyzer/render/`（radar_chart, action_map, **replay_animation**, **team_animation**, effects, hud, fonts, **radar_static**, **preference_charts**, **aggregate_charts**）
- Web: `cs_analyzer/web/`（app.py FastAPI 路由, store.py demo 索引, tasks.py 后台任务, **viewer_data.py** canvas 数据包, replay_map.py 视频预渲染, templates/, static/**viewer_canvas.js**）
- 地图: `cs_analyzer/maps/loader.py` + `maps/data/`（mirage/ancient/inferno 官方雷达 PNG + yaml bounds）
- 导出: `cs_analyzer/export/video.py` (ffmpeg), `report.py`
- 缓存: `cs_analyzer/cache.py`, `batch.py`

## 7. 下一步建议（按优先级）

1. **提交 Phase B 加速 + Phase C + Phase D 全部改动**（当前阶段）：工作区含 canvas 实时回放器（viewer_data.py/viewer_canvas.js/replay_viewer.html 重写/全站电竞风 CSS/T/CT 配色修复 PARSER_VERSION 1.5.1/yaw 朝向修复/字号 token 体系/击杀流分组/coverage 接入 web/测试 150 绿），用户验收后按 provenance 规则提交。
2. **弹药数据**：demoparser2 0.41.4 无 clip/reserve 路由（`scripts/probe_ammo.py` 已证）。升级 demoparser2 后重探，viewer-data `VIEWER_DATA_VERSION` bump + OB 面板加弹药位。
3. **更多地图**：`maps/data/` 目前 mirage/ancient/inferno 三图（官方雷达 PNG + radar_info 校准 bounds）。新图从 MurkyYT/cs2-map-icons 取 PNG + radar_info 元数据校准 yaml。
4. **可选**：装 ffprobe 根治探测、provider 补充真实队名映射、player_detail 旧雷达 PNG 版本键重生成（当前 v1.5.1 键已生效，旧文件自然失效）。

## 8. 已验证里程碑（本阶段成果）

- **Phase D yaw 修复 + 排版/IA 收尾（ox-alpha-free 本轮，待提交）**：
  - D1 yaw 朝向修复：demoparser2 yaw = Source 约定 0=+X（12613 移动样本圆周误差 -0.8° 实证），viewer_canvas.js 误按 0=+Y → 90° 漂移；修为 `(cos,-sin)`；parquet/JSON 双源 + 窗口长度对照验证闭环（2-tick med 5.6° vs 旧约定 89.9° 对照）。
  - D2 字号 token：style.css `:root` 建 `--fs-xs 12px`（下限）~ `--fs-xl 30px` + 行高 token，全站硬编码替换（11px 全升 12px），coverage.html 同步。
  - D3 击杀流重组：按回合 `<details>` 分组默认折叠（全量不截断），回合时间线徽章锚点跳转。
  - D4 导航理顺：顶栏 active 态 + 覆盖度入口；`GET /coverage` 路由（产物存在即服务/缺失给 csa coverage 提示）；studio 子页补返回链接；demo_detail 补 h1；player_detail 徽章移出 h1；index "查看" 改按钮样式。150 测试全绿，playwright 9 页 console 零错误。
- **Phase C Canvas 实时回放器（ox-alpha-free 本轮，待提交）**：
  - M1 T/CT 配色修复：WMPVP player_info/spawns 快照阵营错/过期 → 以正式局逐 tick team_num 多数派为真值（`backend._apply_live_majority`），PARSER_VERSION 1.5.0，探针 0 MISMATCH。
  - M2 viewer-data 数据包：`web/viewer_data.py`（VIEWER_DATA_VERSION=1）8Hz 向量化快照 + tick 域 segments + 扩展事件 + 地图 meta；`GET /api/demo/{hash}/viewer-data` 现算 <2s、gzip ~0.78MB；弹药 V1=null（0.41.4 无路由，`scripts/probe_ammo.py` 已证）。
  - M3+M4 canvas 前端：`static/viewer_canvas.js` 三层画布（map/fx/main）+ 单 rAF + 二分插值 + yaw 扇形 + 轨迹渐变 + 特效 + tick 域时间轴（拖拽/倍速/键盘）+ DOM OB 面板（100ms 节流/换边自动换列/HP 三色条）+ 记分条。
  - M5 全站美术：style.css 电竞观赛风 token（--bg #0b0e14/--accent #4da3ff/--t #ffb02e/--ct #3d9bff/glow），h2 大写字距/tabular-nums/按钮描边+hover glow；matplotlib 胜者横幅 fontsize 52→18（冻结管线一行修）。
  - M6 验收+清理：playwright 8 页截图 console 零错误；根治 viewer 坐标 bug（世界坐标需经 worldToPixel 两级变换）；删 replay_viewer.js/.viewer-wrap 死代码；index 徽章统一"实时回放 ▶"（无预渲染门槛）；149 测试全绿。
- **Phase B 加速（deepseek-v4-pro, 已提交 6b41e58）**：详情页 54s→3.7s（PNG 落盘跳过重渲染 + searchsorted 向量化）、viewer 预渲染 6min→3.5min、studio 表单默认全开。
- **LTG-2 本地 Web 平台（deepseek-v4-pro, 已提交）**：FastAPI + Jinja2 全中文服务端渲染，`csa serve` 命令，单场复盘 + 跨场聚合 + 视频导出工作室（studio）。
- **STG-1 回放打磨（deepseek-v4-pro 本轮）**：重叠类回合/结束淡出（ReplayConfig 加 `overlay_fade_seconds`，单player overlay + 团队 _fade_hold + alpha 重置），射击标记 z-order 降到轨迹下（3），HUD 侧别徽章 T黄/CT蓝 反馈。ffmpeg 帧分析验证淡出（单player 22k→12.8k 亮像素，团队逐回合边界升-降-升）。**已 git reset --soft 撤下提交，改动保留待审核**。
- **LTG-3 解析覆盖度报告（deepseek-v4-pro 本轮）**：`cs_analyzer/coverage.py` + `csa coverage` → `output/coverage/coverage.html`（总览矩阵/逐 demo 明细/调查结论/已知限制）。Team 0 根因查明：demoparser2 库层 pawn 解析限制（全位置 NaN、逐广播特定、不可重建），7/60 玩家位次。**已提交 dcb9d4f**。
- **统一渲染配方框架（deepseek-v4-pro 本轮）**：`cs_analyzer/recipe.py`（Recipe 模型 + flatten_style/apply_style/render_recipe）+ `configs/recipes.yaml`（8 个声明式配方）+ `csa recipe <demo> <名> [--override style.yaml]` 统一入口。`ReplayConfig` 细粒度化（特效逐项开关 show_*/各类颜色/半径/时长、轨迹、HUD 元素、选手标记/光环、团队色板 t_palette/ct_palette），渲染器全部读配置（effects.py 去掉硬编码颜色）。样式覆盖：`canvas/trail/marker/hud/team/effects`。
- **团队回放渲染器（deepseek-v4-pro 本轮）**：`cs_analyzer/render/team_animation.py`——10 人同时回放，分色（**T 黄系 / CT 蓝系**）、尸体 ☠、击杀连线、全员投掷物；支持 team/team-highlights/team-highlight(高亮单人白环★)/team-overlap-round/team-overlap-full。重叠类全部时间驱动 + 真实特效（抛掷物/烟雾/击杀动画），openings 用本地偏移对齐。
- **回放通用处理**：`round_freeze_end` 去准备时间；单人存活窗口裁剪去死亡时间；团队尸体☠继续播；死亡 ☠ 标记（mathtext）。PARSER_VERSION 已至 1.4.0。
- **2D 回放系统（deepseek-v4-pro 早轮）**：`cs_analyzer/replay/`（PlayerTimeline 数据层）+ `cs_analyzer/render/replay_animation.py`（手动帧循环 + FFMpegWriter）+ `effects.py`/`hud.py`/`fonts.py`。轨迹用 LineCollection，归位出生点自动断线。深色底图 + 专业 HUD + 行动特效。
- **真实对局成品（deepseek-v4-pro 本轮）**：`output/real_demo_1/final.mp4`（30.8MB，1分49秒，1080p，h264 + AAC(Thriller)，halloween 背景）。输入为用户真实 WMPVP 对局（`demos/real_demo_1.dem`，de_ancient，24 回合 14-10，10 玩家），走 .dem 全链路。修复了 WMPVP SourceTV 无 player_info/round_start 的解析问题（§5.7）。
- **.dem 全链路成品（deepseek-v4-pro 本轮）**：`output/test_demo/final_content.mp4`（31MB，1分50秒，1080p，h264 + AAC(Thriller)，halloween 背景）。输入为测试 .dem（`tutorial/demoparser/src/parser/test_demo.dem`）。
- **雷达图成品（GLM5.2 上轮，CSV 路径）**：`output/0922_final.mp4`（28.7MB，1分46秒，720p30，6 选手轮播 + halloween 背景 + Thriller 音乐）。data 来自 `radar_data/0922/player_statistics.csv`。
- **单元测试**：`tests/` 45 个测试全绿。
- 修复：enve venv 跨机失效（pyvenv.cfg 指向本机基 Python）、HANDOFF 中 Python 路径错误、新增 `configs/content_prod.yaml`。
