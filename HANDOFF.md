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
2. **道具飞行轨迹为反推**：SourceTV 无道具轨迹实体；`*_thrown` 事件在 WMPVP 广播缺失（探针 output/.event_probe.json 证实），投掷起点由投掷者位置按飞行秒数反推（`timeline._reconstruct_throw`），区域时长为真实值（`*_expired` 实体匹配）。
3. **Team 0 玩家（pawn 未解析）**：某些 WMPVP SourceTV demo 个别玩家全位置 NaN 且不可重建（逐广播特定）。viewer/热力图跳过，统计完整。判定：`cs_analyzer/coverage.py`。
4. **RWS / Rating 是近似**：自实现 HLTV 公式，与平台数值有差异。Phase I 修正了 KAST trade 语义（旧实现反转：给"杀人后速死"者记 T，标准是"杀我者速死"给受害者记 T）与 ratings 输入过滤口径（warmup/TK 与 basic_stats 对齐）——历史数值与旧版不可直接比较。
5. **队名为占位**："Team 2/3"；真实队名在 `begin_new_match`（viewer-data 已输出 `teams`，WMPVP demo 该事件常缺失 → 客户端回退 T/CT）。
6. **bomb 事件坐标三级回退**：事件坐标 → 下包者快照插值 → null（客户端画 site 徽章）。
7. **孤儿产物目录**：`output/web/{hash}/radar|pref|aggregate`（matplotlib 时代 PNG）已无生产者，可手动删除。
8. **coverage.html 内联样式**：仍是 Phase D token 快照（调色板一致，未引入 v2 组件类）；后续可对齐。
9. **PARSER_VERSION 1.7.0 缓存失效**：Phase I bump 后旧缓存已全部懒重解析完成（9/9，含 inventory 列 25 列 ticks、bomb_begindefuse/dropped/pickup、weapon_zoom、cs_win_panel_match 共 25 张事件表）。
10. **demoparser2 探测死路**（Phase I 实证，勿再试）：CS2 header 无日期/tickrate/match_id；`money` prop 在 0.42 MISSING；`bullet_impact` 与 `*_thrown` 事件在 WMPVP 缺席；`parse_convars()` 在真实 WMPVP demo 上 pyo3 Rust panic——任何探针必须子进程隔离（`scripts/probe_events.py` 模式）。
11. **tick_rate 为推导值**：header 无 tickrate，`backend._empirical_tick_rate` 用 velocity÷位移中位数推导（实测 64.0，n=116k），样本不足回落 64。match_id 从 WMPVP 文件名 `^(\d{10,})_` 前缀提取（同时是 B8 时序键）。
12. **拆弹尝试为近似**：postplant 用 `bomb_begindefuse`（含 haskit）计数；表缺失的旧缓存回落为"成功数=尝试数"。

## 5. 关键入口

```bash
"/d/Program Files/Python311/python.exe" -m pytest -q        # 181 全绿
PYTHONIOENCODING=utf-8 "/d/Program Files/Python311/python.exe" -m uvicorn cs_analyzer.web.app:app --port 8000
scripts/visual_check.py                                      # playwright 16 页截图 + console 错误
scripts/probe_events.py                                      # 事件可用性探针（子进程隔离，防 pyo3 panic）
scripts/probe_ammo.py                                        # 弹药字段探针（同上）
```

核心文件：
- CLI: `cs_analyzer/cli.py`（parse/analyze/coverage/serve/info）
- 覆盖度: `cs_analyzer/coverage.py` + `scripts/probe_team0.py`
- 解析: `cs_analyzer/parser/backend.py`（demoparser2；`_parse_ticks` 带 legacy 字段降级重试；`_empirical_tick_rate`/`_match_id_from_filename`）, `providers.py`
- 模型/缓存: `cs_analyzer/model/`, `cache.py`（PARSER_VERSION **1.7.0**）
- 分析: `cs_analyzer/analysis/`——基础 8 模块 + Phase I 五模块（**kill_context, hitgroups, aim, postplant, weapon_splits**）+ 共享助手 `util.py`（`round_player_sides` 逐回合阵营，duels/utility/highlights 三处消费）
- 回放数据层: `cs_analyzer/replay/timeline.py`（PlayerTimeline/UTILITY_END_TABLES/_reconstruct_throw）
- Web: `cs_analyzer/web/`——`app.py` 路由（含 `/analysis/{duels,economy,utility,routes,kill_context,hitgroups,aim,postplant,weapons}.json` + 惰性 `_analyze_module` memo）、`viewer_data.py`（**v3** 数据包+layers v2）、`chart_data.py`（ECharts 载荷+9 个分析载荷）、`weapons.py`（**武器单一事实源**）、`store.py`（`match_key` B8 时序）、`aggregation.py`（memo）、`tasks.py`、`templates/`、`static/`（viewer_canvas.js + js/viewer_camera.js + viewer_overlays.js + viewer_control.js + weapon_meta.js + viewer_prefs.js + charts.js + img/weapons/ + vendor/echarts）
- 地图: `cs_analyzer/maps/loader.py` + `maps/data/`（mirage/ancient/inferno）

## 6. 下一步建议（按优先级）

1. **提交 Phase I 全部改动**（工作区待提交，provenance 待用户确认）。
2. **更多地图**：从 MurkyYT/cs2-map-icons 取 PNG + radar_info 校准 yaml（对局库卡片墙/控图/路线/热力图都吃地图资源；de_nuke 当前缺图走占位底）。
3. **控图算法升级**（用户暂缓）：位置存在性 → 含视线/交战/时间权重。
4. **预留页填充**（Phase H 占位）：收藏标注 /teams 队伍视图 /map-analysis 地图分析（后端数据已备：aggregate per-map 分组）/utility-lab 道具专题（烟中击杀/闪光价值载荷已就绪）/reports 报告导出。
5. **可选深化**：aim 模块接 R2 inventory 做武器持有时间线；`_module_cache` 加上限；经济模块接 `is_warmup` 过滤；高光库加"残局失败"类目；KAST 修正后可考虑 Rating 2.1 公式。
6. **在线发布（用户 2026-08-30 拍板：暂缓，方向已定）**：GitHub Pages 只能托管静态文件（无 Python/Rust 服务端），完整产品上不去；可行路线 = `csa export-static` 静态快照导出（预渲染页面 + viewer-data/图表载荷落静态 JSON + fetch 路径改写 → gh-pages 分支，只读分享版）。**用户已确认：公开仓库 + steamid/昵称匿名化导出**。注意：GitHub 远程仓库名仍是早期项目名 `CS-Radar-Map-Generation`（Patr1ck2005），发布前建议 rename 为 CsDemoAnalyzer。main 已推送至该仓库（60e47c9）。

## 7. 已验证里程碑（本阶段成果）

- **Phase I 底层功能全面深化（ox-alpha, 2026-08-26，待提交）**：
  - 用户拍板：三层审计（分析引擎/解析层/Web 数据面）+ 真机探测后全选 B1-B8 修复 + F1-F8 免费分析 + P1-P6 页面补全 + R1/R2/R3/R5/R6 解析升级（跳过 R4 手雷轨迹）。
  - **M1 解析 bump 1.7.0**：tick += `inventory`（money 实测 MISSING 跳过）；事件 += bomb_begindefuse(haskit)/abortdefuse/dropped/pickup、weapon_zoom、cs_win_panel_match、bullet_impact（后两类 WMPVP 缺席但保留兼容 Valve demo）；`_empirical_tick_rate`（velocity÷位移中位，实测 64.0）；`_match_id_from_filename`；降级重试剔除集 += inventory。9 demo 懒重解析验证：25 列 ticks + 25 张事件表。
  - **M2 公式修复**：B1 KAST trade 反转重写（标准语义：杀我者窗内死→我记 T）；B2 共享 `analysis/util.py` `round_player_sides`（逐回合 512t 窗口 team_num 众数，换边安全）改造 duels/utility_effect（事件 tick 解析闭包）/highlights 三处；B3 聚合加权（ADR=Σdamage/Σrounds，Rating/KAST 回合加权均值，PlayerRow.demos += damage）；B4 生涯雷达改服务器 RADAR_AXES 注入；B5 ratings 过滤对齐 basic_stats；B6 preference 三修（pitch 双重转换去除——实测已是度数、engagement 用 weapon_fire 代理、采样 searchsorted 右邻+回合钳制）；B7 routes 窗口起点改 freeze-end + P3 双方聚类直接载入 result（删 ctx hack）；B8 `store.match_key` 文件名 match-id 时序（仪表盘最近对局 + DemoRow.match_key 趋势序）。
  - **M3 五新模块**（全部 @register_module + `/api/demo/{h}/analysis/{name}.json` + chart_data 载荷）：kill_context（穿墙/烟中/盲狙/空中/距离徽章 + round_mvp + item_pickup 捡枪 + weapon_mix）、hitgroups（hitgroup×dmg 分布 + 护甲效率，仅计 armor 交互命中）、aim（weapon_fire⋈ticks：出手/转化（每杀单认领）/走路/开镜/蹲下开火占比/freeze-end 首发延迟）、postplant（守包率/retake 率/拆弹尝试 begindefuse 计数/拆弹用时）、weapon_splits（皮肤折叠类别拆分 + top-3 武器）；F8 basic_stats += first_deaths/FirstDeathsPerRound；F4 utility_effect += flash_assists（assistedflash 归因，flash-only 玩家也建行）；weapons.py knife 别名补全（knife_bayonet 等 10 个）。
  - **M4 页面补全**：经济 Tab（消费柱 tooltip 买法/胜负 + win_by_buy 分组柱 + 连败 streak 行）、道具 Tab（烟中击杀/死亡双向条形图）、路线 Tab（T/CT toggle + 样本不足提示 + 下包后四卡）、击杀 Tab（情境徽章 + 武器分布环图 + 部位伤害堆叠条）、新**战术 Tab**（枪法纪律表 + 武器拆分表）、生涯页（RWS 第三序列 + 单场热力图场次选择器接入孤儿 API）、回放器**买装条**（economy 层首次被消费：回合前 20s 底部双方购枪图标+$spend，「买装」chip 开关）；孤儿模板删除（demo_detail/player_detail/aggregate/job.html）。
  - 测试 148→**181** 全绿（+33）；web_client fixture 提升到 conftest 共享；playwright 16 页 console 零错误（新增五个 Tab 深链截图）；真机截图人工检查（击杀徽章/环图/堆叠条/买装条全部渲染正确）。
- **Phase H 信息架构完全重写（已提交 d7e7632）**：
  - 用户拍板：页面逻辑完全重写——实体中心三区（仪表盘/对局/选手/高光/对比/系统），对比=大数据思想（个体 vs ≥5 场全库基线分位，非两两 PK），对局详情五 Tab 化，覆盖度降出导航（保留 CLI），URL 全新语义化 + 旧路径 301。
  - 路由：`/matches` `/match/{h}`（Tab 化）`/match/{h}/viewer|overlap` `/players` `/player/{sid}`（生涯）`/highlights` `/compare` `/system` + 5 占位页；301 query 透传；API 路径零改动。
  - 数据：`web/aggregation.py` memo（single-flight 锁 + `invalidate_aggregate()` 三调用点）；PlayerRow += HS%/FKPR/Survivals/逐场 demo_hash；`analysis/highlights.py`（多杀 2k-ACE + 残局 1vN 事件推导 + roster 名字回退）；`compare_payload`（≥5 场门槛 percentile-rank + 雷达叠加）；`/api/jobs` 列表、`/api/system/{status,unparsed}.json`、`POST /system/import`。
  - 页面：仪表盘（KPI 四卡+最近对局卡墙+上传+高光精选）、对局库（卡片/表格双视图 localStorage + 地图筛选 chips）、对局详情五 Tab（`?tab=` 深链 + 面板懒 fetch + 骨架）、选手库（Rating 矩阵+样本量列）、生涯页（KPI+六轴雷达+跨场趋势+场次列表+个人高光）、高光库（类型筛选卡片流）、对比页（排行+分位条+勾选雷达叠加+门槛灰显）、系统页（缓存版本/任务队列 2s 轮询/未入库一键入库/数据质量+即将上线）。
  - 修复：base.html `{% set p %}` 遮蔽页面 context 的 PlayerRow（改名 nav_path）；缺图地图（de_nuke）卡片占位底；高光卡 map_name/undefined 名字。
  - 测试 123→**146** 全绿（+23）；playwright 11 页 console 零错误。
- **Phase G 全站美术重设计 "Violet Observatory"（已提交 04e39a9）**：
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
