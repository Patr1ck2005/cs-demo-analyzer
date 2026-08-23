# 交接文档 (HANDOFF)

> 给下一个开发 agent 的交接说明。目标：让接手者能在 10 分钟内了解项目状态、运行环境、验收缺口和下一步。

## 1. 项目状态摘要

CsDemoAnalyzer：本地优先 CS2 demo 分析工具。产品定位 = **CS2 demo 分析器**（非视频工作室），两个分析视角——定量（统计/ECharts 雷达/聚合）+ 空间-时间（**Canvas 实时回放器 v2**：相机缩放平移 + 高级覆盖层）。本地 Web 平台（FastAPI, `csa serve` → `http://127.0.0.1:8000`）是唯一主入口。

**当前形态（2026-08-24, Phase E 完成后）**：matplotlib/manim 视频管线已整体退役（能力归档见 `docs/video_pipeline_archive.md`），CLI 只剩 parse/analyze/coverage/serve/info 五个命令；定量图表全部 ECharts 本地 vendor 化（离线可用），matplotlib 依赖移除；全站深色分析风设计系统（token + 组件类）；97 测试全绿。

**主分支 commit 历史**（git log 倒序，Phase E 改动在工作区待提交，见 §7）：
```
a074731 docs: sync ARCHITECTURE/HANDOFF/README + dev_log for Phase C/D
c6ed497 feat: canvas real-time replay viewer + T/CT side fix + esports UI overhaul (Phase C/D)
6b41e58 feat: web demo analyzer (2D viewer + export studio) + load speedups
```

## 2. 已实现功能（对照验收指标）

| 验收指标 | 状态 | 说明 |
| :--- | :--- | :--- |
| 批量处理 5+ demo | ✅ 已实现 | 内容寻址缓存 + `store.list_demos` 扫描；批量视频流水线已随管线退役 |
| 雷达图视频 | 🗄️ 已归档 | matplotlib/manim 视频管线 Phase E 退役；ECharts 交互式雷达取代（`web/chart_data.py`） |
| 2D 行动 map | 🗄️ 已归档 | 由实时回放器 + 地图位置散点图取代 |
| 偏好分析报告 | ✅ 已实现 | `csa analyze` 含 preference 模块；web 端 ECharts 地图位置图 |
| 中间结果可序列化 | ✅ 已实现 | metadata → JSON，ticks/events → Parquet（`.cache/{hash}/`） |
| 性能：解析 < 30s | ✅ 已验证 | 60MB demo 解析 <5s（含缓存命中） |
| 单元测试 | ✅ 已补齐 | `tests/` 97 个测试全绿（model/parser/analysis/web/chart_data/viewer_data/timeline） |
| README / ARCHITECTURE | ✅ 已同步 | Phase E 同步后与代码一致（2026-08-24） |

## 3. 运行环境（关键！）

| 项 | 值 |
| :--- | :--- |
| OS | Windows 11 Pro 10.0.26200 |
| Python | **`D:\Program Files\Python311\python.exe`（3.11.9）** — 真正的工作环境 |
| demoparser2 | 0.41.4（0.41 系无弹药路由，见 §4 已知限制） |
| ffmpeg | 不再需要（无服务端渲染） |
| 虚拟环境 | `enve/` 是 **DELL 机器复制的旧 venv**，勿用；基 Python 已装全部依赖 |

**关键修正（vs 旧 HANDOFF）**：Python 在 `D:\Program Files\Python311`（不是 C:\）。bash PATH 里 `python` 会解析到 `enve/Scripts/python`（缺包）——跑本项目命令一律用显式路径。`PYTHONIOENCODING=utf-8` 用于 CJK 输出。

## 4. 已知问题 / 技术债务

1. **弹药数据缺失**：demoparser2 0.41.4 无 clip/reserve 路由（`scripts/probe_ammo.py` 已证），viewer 面板无弹药位。升级后重探 → bump `VIEWER_DATA_VERSION`。
2. **道具飞行轨迹为反推**：SourceTV 无道具轨迹实体；投掷起点由投掷者位置按飞行秒数反推（`timeline._reconstruct_throw`），区域时长为真实值（`*_expired` 实体匹配）。
3. **Team 0 玩家（pawn 未解析）**：某些 WMPVP SourceTV demo 个别玩家全位置 NaN 且不可重建（逐广播特定）。viewer/热力图跳过，统计完整。判定：`cs_analyzer/coverage.py`。
4. **RWS / Rating 是近似**：自实现 HLTV 公式，与平台数值有差异。
5. **队名为占位**："Team 2/3"；真实队名在 `begin_new_match`（viewer-data v2 已输出 `teams`，WMPVP demo 该事件常缺失 → 客户端回退 T/CT）。
6. **bomb 事件坐标三级回退**：事件坐标 → 下包者快照插值 → null（客户端画 site 徽章）。`scripts/probe_bomb_events.py` 尚未编写。
7. **孤儿产物目录**：`output/web/{hash}/radar|pref|aggregate`（matplotlib 时代 PNG）已无生产者，可手动删除。
8. **coverage.html 内联样式**：仍是 Phase D token 快照（调色板一致，未引入 v2 组件类）；后续可对齐。

## 5. 关键入口

```bash
"/d/Program Files/Python311/python.exe" -m pytest -q        # 97 全绿
PYTHONIOENCODING=utf-8 "/d/Program Files/Python311/python.exe" -m uvicorn cs_analyzer.web.app:app --port 8000
scripts/visual_check.py                                      # playwright 全页截图 + console 错误
```

核心文件：
- CLI: `cs_analyzer/cli.py`（parse/analyze/coverage/serve/info）
- 覆盖度: `cs_analyzer/coverage.py` + `scripts/probe_team0.py`
- 解析: `cs_analyzer/parser/backend.py`（demoparser2）, `providers.py`
- 模型/缓存: `cs_analyzer/model/`, `cache.py`（PARSER_VERSION 1.5.1）
- 分析: `cs_analyzer/analysis/`（basic_stats, ratings, preference, aggregate）
- 回放数据层: `cs_analyzer/replay/timeline.py`（PlayerTimeline/UTILITY_END_TABLES/_reconstruct_throw）
- Web: `cs_analyzer/web/`——`app.py` 路由、`viewer_data.py`（v2 数据包+layers）、`chart_data.py`（ECharts 载荷）、`store.py`、`tasks.py`、`templates/`、`static/`（viewer_canvas.js + js/viewer_camera.js + js/viewer_overlays.js + charts.js + vendor/echarts）
- 地图: `cs_analyzer/maps/loader.py` + `maps/data/`（mirage/ancient/inferno）

## 6. 下一步建议（按优先级）

1. **提交 Phase E 全部改动**（工作区待提交，provenance `ai:stealth/ox-alpha`，用户已确认）。
2. **弹药数据**：demoparser2 升级后重探 → `VIEWER_DATA_VERSION` bump → OB 面板弹药位。
3. **更多地图**：从 MurkyYT/cs2-map-icons 取 PNG + radar_info 校准 yaml。
4. **可选**：bomb 事件坐标探针脚本；coverage.html 样式对齐 v2 组件类；`_analysis_cache` 加上限或失效策略。

## 7. 已验证里程碑（本阶段成果）

- **Phase E 全站重设计 + 高级 2D 分析（ox-alpha, 2026-08-24，待提交）**：
  - M1 归档：`docs/video_pipeline_archive.md`（能力目录 + 参数/色板/时序移植规格 + 质量评估结论）。
  - M2 删除：matplotlib/manim 视频管线 ~3000 行（render 8 模块/recipe/batch/export/utils.ffmpeg/studio×3 页/7 CLI 命令/5 测试文件/素材），依赖清理（Pillow/manim extra/matplotlib），grep 门禁归零。
  - M3 viewer-data v2（VIEWER_DATA_VERSION=2）：击杀坐标+爆头、道具真实时长（timeline 复用）+投掷起点、闪光致盲对、炸弹事件（三级坐标回退）、真实队名、武器驻留+int 化（**raw 6.5→4.8MB，gzip 0.78MB 持平**）；重型分层 `viewer_layers.json`（shots 4253/economy 24 回合，gzip 40KB）+ `/api/demo/{h}/viewer-layers`。
  - M4 canvas 升级：`js/viewer_camera.js`（滚轮缩放至光标 1-8×、拖拽平移、R/双击复位、fit 哨兵 null 解析、防 0 尺寸图退化）；`js/viewer_overlays.js`（道具飞行弧+真实时长区域/多层烟雾云/8 火焰区/击杀连线+爆头环/枪线火花/闪光环/炸弹标记）；覆盖层开关工具条（localStorage）、击杀流挂件、炸弹倒计时、`?round=&t=` 深链、时间轴击杀点按凶手侧着色；修复 age<0 未来事件渲染 bug。
  - M5 设计系统：style.css v2（token 体系+组件类），导航重构（Demo 库/跨场聚合/覆盖度），index=Demo 库（dropzone+统计条+密集表）、demo_detail（比分 hero+可排序表+ECharts 雷达+回合深链徽章）、player_detail（stat tiles+个人雷达+地图位置图）、aggregate（矩阵/条形/趋势）、job/error 组件化；`table_sort.js`。
  - M6 ECharts：vendor 5.5.1 本地（Apache-2.0），暗色主题，`chart_data.py` 纯载荷装配（雷达归一化/地图位置归一点/聚合矩阵），3 个 charts.json 端点，render/ 包与 matplotlib 依赖整体删除。
  - M7 文档：ARCHITECTURE/HANDOFF/README/GOALS 同步；97 测试全绿；playwright 全页 console 零错误。
- **Phase D yaw 修复 + 排版/IA 收尾（已提交 a074731）**：
  - D1 yaw 朝向修复：demoparser2 yaw = Source 约定 0=+X（12613 移动样本圆周误差 -0.8° 实证），viewer_canvas.js 误按 0=+Y → 90° 漂移；修为 `(cos,-sin)`。
  - D2 字号 token / D3 击杀流分组 / D4 导航理顺 + coverage 接入 web。
- **Phase C Canvas 实时回放器（已提交 c6ed497）**：M1 T/CT 配色修复（PARSER_VERSION 1.5.1）、M2 viewer-data v1、M3+M4 canvas 前端+OB 面板、M5 电竞风 token、M6 验收清理。
- **Phase B 加速（已提交 6b41e58）**：详情页 54s→3.7s、viewer 预渲染 6min→3.5min。
- **LTG-2/LTG-3 及更早（已提交）**：Web 平台、覆盖度报告（Team 0 根因=demoparser2 pawn 库层限制）。
