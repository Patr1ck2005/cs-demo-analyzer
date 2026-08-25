# 交接文档 (HANDOFF)

> 给下一个开发 agent 的交接说明。目标：让接手者能在 10 分钟内了解项目状态、运行环境、验收缺口和下一步。

## 1. 项目状态摘要

CsDemoAnalyzer：本地优先 CS2 demo 分析工具。产品定位 = **CS2 demo 分析器**（非视频工作室），两个分析视角——定量（统计/ECharts 雷达/聚合）+ 空间-时间（**Canvas 实时回放器 v3**：相机缩放平移 + 高级覆盖层 + 弹药/换弹 + 控图染色）。本地 Web 平台（FastAPI, `csa serve` → `http://127.0.0.1:8000`）是唯一主入口。

**当前形态（2026-08-24, Phase F 完成后）**：Phase E 基础上新增——多 demo 上传+批量任务页、武器图标系统（49 个 MIT SVG vendor + 三命名体系归一）、demoparser2 0.42 升级（弹药/换弹真数据）、战斗反馈（枪口焰/曳光/换弹弧/缩放 LOD：血量环+弹药+武器徽章）、**控图实时染色+伪 3D**（客户端逐帧高斯核 EMA，p95 0.2ms）、四项高级分析（对枪矩阵/经济/道具效用/开局路线聚类，demo 详情页四个新区块）。123 测试全绿。

**主分支 commit 历史**（git log 倒序，Phase F 改动在工作区待提交，见 §7）：
```
f5a922f feat: one-click start/stop scripts for the local web platform
933e9b1 feat: Phase E full site redesign + advanced 2D analysis (video pipeline retired)
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
| demoparser2 | **0.42.0**（pyproject 锁 `>=0.42,<0.43`；0.42 起提供 `active_weapon_ammo`/`is_in_reload`/`weapon_reload`，探针结果 `output/.ammo_probe.json`） |
| ffmpeg | 不再需要（无服务端渲染） |
| 虚拟环境 | `enve/` 是 **DELL 机器复制的旧 venv**，勿用；基 Python 已装全部依赖 |

**关键修正（vs 旧 HANDOFF）**：Python 在 `D:\Program Files\Python311`（不是 C:\）。bash PATH 里 `python` 会解析到 `enve/Scripts/python`（缺包）——跑本项目命令一律用显式路径。`PYTHONIOENCODING=utf-8` 用于 CJK 输出。

## 4. 已知问题 / 技术债务

1. **~~弹药数据缺失~~（Phase F 已解决）**：0.42.0 提供逐 tick `active_weapon_ammo`/`is_in_reload`；viewer-data **v3** 快照带 `am`/`rl` 数组 + 顶层 `ammo` 特性标志；`rl` 用 prop ∪ `weapon_reload` 事件运行段并集（prop 对个别 WMPVP 选手漏报，0762 案例：1 span vs 3 event runs；prop span 97% 经弹药回填验证）。
2. **道具飞行轨迹为反推**：SourceTV 无道具轨迹实体；投掷起点由投掷者位置按飞行秒数反推（`timeline._reconstruct_throw`），区域时长为真实值（`*_expired` 实体匹配）。
3. **Team 0 玩家（pawn 未解析）**：某些 WMPVP SourceTV demo 个别玩家全位置 NaN 且不可重建（逐广播特定）。viewer/热力图跳过，统计完整。判定：`cs_analyzer/coverage.py`。
4. **RWS / Rating 是近似**：自实现 HLTV 公式，与平台数值有差异。
5. **队名为占位**："Team 2/3"；真实队名在 `begin_new_match`（viewer-data 已输出 `teams`，WMPVP demo 该事件常缺失 → 客户端回退 T/CT）。
6. **bomb 事件坐标三级回退**：事件坐标 → 下包者快照插值 → null（客户端画 site 徽章）。`scripts/probe_bomb_events.py` 尚未编写。
7. **孤儿产物目录**：`output/web/{hash}/radar|pref|aggregate`（matplotlib 时代 PNG）已无生产者，可手动删除。
8. **coverage.html 内联样式**：仍是 Phase D token 快照（调色板一致，未引入 v2 组件类）；后续可对齐。
9. **PARSER_VERSION 1.6.0 缓存失效**：Phase F bump 后旧缓存全部懒重解析（每 demo ~8-14s）；首次访问各页会慢一次。
10. **开局路线 V1 只出 T 方**：CT 结果已算好挂在 ctx（`OpeningRouteModule.run` 里 `ctx.put(results["CT"])`），未来页面可直接取用。

## 5. 关键入口

```bash
"/d/Program Files/Python311/python.exe" -m pytest -q        # 123 全绿
PYTHONIOENCODING=utf-8 "/d/Program Files/Python311/python.exe" -m uvicorn cs_analyzer.web.app:app --port 8000
scripts/visual_check.py                                      # playwright 全页截图 + console 错误
scripts/probe_ammo.py                                        # 弹药字段探针（隔离子进程）
```

核心文件：
- CLI: `cs_analyzer/cli.py`（parse/analyze/coverage/serve/info）
- 覆盖度: `cs_analyzer/coverage.py` + `scripts/probe_team0.py`
- 解析: `cs_analyzer/parser/backend.py`（demoparser2；`_parse_ticks` 带 legacy 字段降级重试）, `providers.py`
- 模型/缓存: `cs_analyzer/model/`, `cache.py`（PARSER_VERSION 1.6.0）
- 分析: `cs_analyzer/analysis/`（basic_stats, ratings, preference, aggregate + **duels, economy, utility_effect, routes**）
- 回放数据层: `cs_analyzer/replay/timeline.py`（PlayerTimeline/UTILITY_END_TABLES/_reconstruct_throw）
- Web: `cs_analyzer/web/`——`app.py` 路由（含 `/analysis/{duels,economy,utility,routes}.json` + 惰性 `_analyze_module` memo）、`viewer_data.py`（**v3** 数据包+layers v2）、`chart_data.py`（ECharts 载荷+4 个高级分析载荷）、`weapons.py`（**武器单一事实源**）、`store.py`、`tasks.py`（Job.label）、`templates/`（含 batch_jobs.html）、`static/`（viewer_canvas.js + js/viewer_camera.js + viewer_overlays.js + **viewer_control.js** + **weapon_meta.js** + charts.js + img/weapons/ + vendor/echarts）
- 地图: `cs_analyzer/maps/loader.py` + `maps/data/`（mirage/ancient/inferno）

## 6. 下一步建议（按优先级）

1. **提交 Phase G 全部改动**（工作区待提交，provenance 待用户确认）。
2. **更多地图**：从 MurkyYT/cs2-map-icons 取 PNG + radar_info 校准 yaml（控图/路线/热力图都吃地图资源）。
3. **CT 开局路线页**：数据已算好（ctx 里），加个 UI 切换即可。
4. **控图算法升级**（用户暂缓）：位置存在性 → 含视线/交战/时间权重。
5. **可选**：bomb 事件坐标探针脚本；`_module_cache` 加上限或失效策略；经济模块接 `is_warmup` 过滤。

## 7. 已验证里程碑（本阶段成果）

- **Phase G 全站美术重设计 "Violet Observatory"（ox-alpha, 2026-08-25，待提交）**：
  - 用户对美术完全不满意后 AskUserQuestion 定案：电竞数据平台风（Leetify/scope.gg 观感）、**紫罗兰主强调**（`#a78bfa`，渐变 `#c4b5fd→#8b5cf6`；T 橙/CT 蓝阵营语义色保留）、**三字体体系**、顶栏升级、**拉满展示级动效**、纯暗色、一步到位。
  - M1 字体地基：vendor 9 个 woff2（Inter 400-700 / Rajdhani 500-700 / JetBrains Mono 400+600，fontsource CDN 下载，三份 OFL 许可随包）+ `static/fonts.css`；display 字体用于 h1/h2/stat 值/比分/计时器/半场 tab，mono 用于表格数字/弹药/时间戳。
  - M2 外壳：base.html 品牌**准星 SVG 标记**（14s 慢旋转）+ **氛围双光晕**（紫/蓝 blur 漂移，body::before/::after）+ `static_v`（服务启动时间戳，模板 `?v=` 防缓存——根治"浏览器缓存问题"）；`body.wide`（回放器/重叠页版心 1600px）；10 个模板全部重皮，**id 与 JS 消费类名零改动**。
  - M3 动效库（全部 `prefers-reduced-motion` 关停）：区块依次入场（main>* nth-child 延迟封顶）、表格行 stagger（`--i` 变量）、卡片 hover 浮起+顶部渐变条、按钮**光泽扫过**（::after 斜切高光）+按压 scale、chips 紫光、**count-up 数字动画**（app.js，纯数字才动 600ms ease-out）、图表骨架 shimmer（`.chart-loading`，`CSACharts.mount()` 自动移除）、dropzone 蚂蚁线、导航玻璃拟态+发光下划线 scaleX、低时间红脉冲（`.ob-timer.low-time`，viewer_canvas 20s 阈值接线）、View Transitions API 渐进增强、暗色细滚动条（紫 thumb）。
  - M4 图表系统：echarts-theme-csa 紫色板重写（`['#a78bfa','#ffb02e','#3d9bff','#3ddc97','#ff4d5e','#22d3ee','#f472b6','#facc15',...]`）、charts.js TOKENS 对齐、viewer_canvas/viewer_overlap 仅 UI 色同步（**canvas 实体色不动**：T/CT 调色板、烟/火/闪、击杀金）；coverage.html 独立样式同步新 token。
  - 验证：123 测试全绿（**零测试改动**——文本 token 契约全部保住）；playwright 7 页（新增 overlap）console 零错误；逐页截图人工检查。
- **Phase F 密度/武器语义/控图/进阶分析（已提交 03c9eb4）**：
  - M1 回放器交互修复：工具条按钮"点不动"根因=拖拽 `setPointerCapture` 无条件劫持（双层修复：`.ob-toolbar` 内跳过 + 4px 阈值后才捕获）；`轨迹` 开关接活；模板补复位视图按钮；dblclick 工具条守卫；速度下拉补齐 3/5/6/7 与数字键同步。
  - M2 多 demo 上传：`list[UploadFile]` + multiple 表单 + 内容哈希去重（重复跳过）+ 文件名冲突后缀；`Job.label`；`batch_jobs.html` 批量结果页（逐行轮询）；测试隔离 `_demos_dir` monkeypatch（不再污染真实 demos/）。
  - M3 武器图标系统：49 个 MIT SVG vendor（akiver/cs-demo-manager，LICENSE.txt 附 provenance）；`weapons.py` 单一事实源（三命名体系归一：事件短名 `ak47` / WMPVP 皮肤 `ak47_txz03` / tick 显示名 `ak-47`，200 真实名全覆盖）；Jinja 过滤器 + `/api/meta/weapons.json` + `weapon_meta.js` 镜像（含异步 Image 缓存）；OB 面板/击杀流/战报页击杀行三路消费。
  - M4 demoparser2 0.42 升级：升级后 111 测试全绿 + 两类真实 demo 重解析回归；探针全 8 demo 物化（all-or-nothing 通过）；tick 字段 += ammo/reload（backend legacy 重试降级）；`PARSER_VERSION` 1.6.0；viewer-data **v3**（`am`/`rl` 数组 + `ammo` 标志，gzip 0.73MB 预算内）；`rl` = prop ∪ 事件运行段并集（数据质量实测：弹药 16→换弹→20 轨迹、97% prop span 经回填验证）。
  - M5 战斗反馈+LOD：shots 层 v2 补发射者 yaw（np.interp）；枪口焰 60ms 径向渐变 + 900u 曳光线（WeaponMeta.isGun 过滤投掷物/刀）；换弹琥珀虚线旋转弧 + 面板"换弹"徽标 + 弹药数字；缩放 LOD（zoom≥2.5：血量环/弹药数字；zoom≥3：武器贴图徽章，异步加载失败退级 console.warn）。playwright 实测环/数字/曳光全部渲染。
  - M6 控图旗舰（`js/viewer_control.js`）：客户端逐帧计算（10 人 × ±4 格截断高斯核 σ=170u/480u，CELL 128u）；τ=2s EMA + seek 回溯 4s 重建；2D 快路径 offscreen ImageData 单次 drawImage；**伪 3D 斜投影挤出**（顶面+双侧面、画家算法 depth=sy_top+sx、900 格封顶+视口剔除）；`控图`/`3D` 开关互斥 + T←→CT 图例；超帧预算自动降级 3D→平面。**性能实测 p50 0.1ms / p95 0.2ms（预算 4ms）**。
  - M7 对枪矩阵+经济：`analysis/duels.py`（方向性 kills 矩阵，<3 次灰显）；`analysis/economy.py`（eco<2000/force<3700/full 分类 + 各买法胜率 + 连败 streak；`build_purchase_log` 抽为 viewer layers 共享源——重构完成，layers 字节不变）；`app._analyze_module` 惰性 per-module memo。
  - M8 道具效用+开局路线：`utility_effect.py`（闪光价值=敌人秒数+0.5×队友秒数；烟中击杀/死亡=落点 120u 半径×真实时长判定）；`routes.py`（前 25s 轨迹弧长重采样 10 点→队均→种子化 k-means 肘点选 k，无 sklearn；修复半开区间回合窗泄漏 bug）；demo_detail 四个新区块 + 4 个 charts.json 端点，真机全部渲染验证。
  - 测试 97→**123** 全绿；playwright 全页 console 零错误。
- **Phase E 全站重设计 + 高级 2D 分析（已提交 933e9b1）**：
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
