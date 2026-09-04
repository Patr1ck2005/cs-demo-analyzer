# 交接文档 (HANDOFF)

> 给下一个开发 agent 的交接说明。目标：10 分钟内了解项目状态、运行环境、待审改动、开发计划与所有坑。**最后更新：2026-09-03（Phase M v2 趣味数据实验室按用户口径定稿，待验收）**

## 0. ⚠️ 铁律（先读这个）

1. **未经用户在对话里明确说"批准提交"，绝不执行 `git commit`**。计划文档/milestone/ExitPlanMode 批准都不构成提交授权（2026-08-30 用户申斥确立）。每次 commit 前问两件事：① 是否批准 ② provenance（`Origin: ai:<model>-<agent>`，模型随会话变必须每次问；历史值见 §8）。
2. 跑 Python 一律用显式路径 `"D:\Program Files\Python311\python.exe"`（bash PATH 的 `python` 指向失效的 enve/ venv）。
2b. **pip 装包可能清掉本机既有依赖**（2026-09-03 实证：`pip install pydantic` 后 pyyaml/fastapi/uvicorn/greenlet 全消失）——装完立刻 `pip install -e ".[dev]"` 恢复，并用 `python -c "import uvicorn, fastapi, yaml"` 自检。
3. **agent 可以读图片**：`read_image` 工具直接读 PNG/JPEG/WebP/GIF（2026-08-30 实证可用，旧"read 是纯文本"限制已失效）。视觉验收优先：playwright 截图 → read_image 亲眼看；像素采样断言仅作程序化补充。
4. 异常一律记录到 HANDOFF §7 与 dev_log，不分轻重。
5. **FastAPI 路由注册顺序**：`/{placeholder}` 通配路由在 app.py 中部注册——任何新的单段页面路由必须注册在它**之前**（L2 的 /utility-lab 曾被遮蔽 404）。

## 1. 项目状态摘要

CsDemoAnalyzer：本地优先 CS2 demo 分析平台（解析 `.dem` → 定量统计 + 电竞 OB 级 2D 实时回放）。FastAPI + Jinja2 全中文 SSR + canvas 回放器 + vendored ECharts。**当前 25 个 demo 在库、212 测试全绿、visual_check 22 页零 console 错误**。

**Git 状态（关键）**：
- origin/main = `ac5c7fa`（Phase L 三连已推送：027cf59 L0 性能 / 0d18492 L 页面 / ac5c7fa L5+L6）
- **工作区新一批"待审"改动（Phase M 趣味数据实验室 v2——按用户口径定稿，尚未批准提交）**：
  - **口径文档 `docs/funlab-metrics.md` v2**：用户逐条裁决（抢人头/被抢人头改名、白给 <10 伤害、
    发枪全指标做、急停 v2、预设按意义组合）；**总原则：轴上只允许比率/每回合值，绝对值仅榜单/tooltip**（"打得多≠数据好"）
  - **发枪检测链（funlab.py 核心）**：无掉落事件，购买→拾取反推。四道闸门：同回合同款主武器/
    拾取者±2s 无自购（买枪必触发 pickup，5/5 实证）/捐赠者拾取时存活（排除死亡掉枪）/30s 窗口。
    武器名归一（5E 皮肤前缀剥离+别名表）。全库 18 场检出 ~250 次成功发枪
  - 指标全集（用户批准）：发枪贡献$(榜)/慷慨率/雪中送炭占比/发枪成材率/浪费发枪率/被发枪价值$(榜)/
    吸血率/白嫖枪（收紧为捡阵亡队友购的同款）/eco特率/神仙率(÷己方eco回合)/白给率(<10伤害)/
    抢人头率（归因修正：终击时 HP≤30 **且有其他队友打过**——自己打残自己收不再算）/被抢人头率
    （你打残被队友收走，按 HP 首次跌破 30 归因）/残局频率(÷回合)/多杀率/平均交战距离/狙击依赖/
    花活 7 项全比率化/队伤每回合/被复仇率/复仇率(机会分母=队友死亡数)/保枪率 Jame 指数
  - `/fun-lab` + `funlab.js`：25 指标任选轴 + **10 个意义化预设**（谁在养队/穷时的意志/数据毒瘤/
    人头账/残局画像/花活大师/保险大师/复仇网络/狙击手画像/闪光协同，每个带叙事 hint）+ 12 张榜单
  - `funlab_data.py` memo：≥3 局门槛（148→5 人）+ 聚合 + 榜单；`warmup.py` 预热含 funlab 步
  - 验收截图 `output/.visual/m_funlab*.png`；**212 测试全绿；22 页 visual_check 全 OK**
  - **v3（同批待审）**：用户数据三连问后的修复+新功能——① 交战距离修复（demoparser2
    `player_death.distance` **本身就是米**，误乘 0.019 导致全线 0.1-0.9m，删除换算后 10.2m/最大 55.3m 正常）；
    ② 赌狗胜率样本提示（"6.7% (1局0胜)"，小样本 100% 有误导）；③ 吸血鬼标签明确"**被**供枪占比"；
    ④ **排型筛选**（单排/3排/4排/5排 chips，lineup = 5E 库常客≥3场在同场数量）+ **日期筛选**
    （今天/昨天/前天/具体日，从 g161 文件名内嵌日期抽取，WMPVP 数字名不误判）+ funlab_data 重构为
    scan(贵,缓存)+merge(便宜,按 stack=/dates= 查询参数 memo)；⑤ **每选手固定专属色**（14 色板）；
    ⑥ **新 demo 导入**：库 18→25 场（09/02-09/03 的 3/4/5 排 7 场新对局，含 de_anubis 首图——
    **anubis 无雷达 PNG**，需按 K4 流程补）；5E 源目录 16 个完好 zip 已按用户裁决删除，6 个截断坏 zip 保留
  - 口径全文：`docs/funlab-metrics.md` v3
  - ↑ Phase M 批次；以下 Phase L 批次**已全部提交推送**（027cf59 / 0d18492 / ac5c7fa）：
  - L0 性能：`analysis/library.py`（新，线程池全库扫描 + demo_filenames metadata 预读）、
    `analysis/util.py`（round_player_sides 内循环 numpy 化 + player 边界提出回合循环——单场 highlights
    2.18s→0.55s、全库高光扫描 50.4s→17.0s）、`analysis/aggregate.py`（并行重写，结果与串行一致）、
    `analysis/teamplay.py`（load_all_demos + 5E 子集加载 + **CLI 路径 AnalysisRunner(analysis=) 无效关键字修复**）、
    `web/warmup.py`（新，启动预热 lifespan daemon 线程 aggregate→highlights→teamplay→utilitylab ~58s 后台完成）、
    `web/feed_data.py`（新，dashboard 高亮 feed memo——原首页 50s 大头）、`web/app.py`
    （lifespan + /api/warmup.json + /api/warmup/dashboard.json + dashboard 骨架渐进填充 + _module_cache LRU 512）、
    `static/js/warmup.js`、`templates/index.html`（骨架）
  - L1 收藏：`web/favorites_store.py`（新，output/favorites.json）、/api/favorites GET/POST、
    `static/js/favorites.js`（星标委托/meta 随点随存/favorites 页渲染）、`templates/favorites.html`、
    星标挂 `_match_card.html`（data-match-card）与 `player_career.html`、`base.html` 加 .nav-secondary 专题导航
  - L2 道具专题：`analysis/utility_effect.py`（**加性字段 smoke_events**；**修复静默 bug：0.42 的
    smokegrenade_detonate 列名是小写 x/y，代码读大写 X/Y——真实 demo 烟中击杀恒 0**，修复后 93 杀）、
    `web/utilitylab_data.py`（新 memo）、/utility-lab + /api/utilitylab.json + `static/js/utilitylab.js`
    （闪光价值榜/烟中击杀榜/6 图落点热力）
  - L3 地图分析：`analysis/postplant.py`（**修复：site 列真实值是数字 place id，改用 user_last_place_name
    推断 A/B**）、`web/mapdata.py`（新）、/map-analysis + /api/map-analysis.json + `static/js/map_analysis.js`
    （T/CT 开局路线 top3 叠加/A-B 包点条/本图最强选手）
  - L4 队伍视图：`web/lineups_data.py`（新，首发阵容指纹分组——**数据事实：18 场含 5E 全是 Team 2/3 占位名**）、
    /teams + /api/lineups.json + `static/js/teams.js`（车队局 5 场 45.0% vs 单排 4 场 65.1%，口径同 K5）
  - L5 报告导出：`templates/report_match.html`（白底打印版）、`web/report_export.py`（新，playwright PNG/PDF，
    asyncio.to_thread 防 sync-in-async）、/reports + /api/report/{hash}/export + exports/demos API、
    `static/js/reports.js`、pyproject 可选组 `reports=["playwright>=1.40"]`
  - L6：`scripts/visual_check.py` 16→21 页、system.html 专题卡转正、各入口 chip 去"即将上线"、HANDOFF/dev_log
  - 验收截图 `output/.visual/l0_*.png l1_*.png l2_*.png l3_*.png l4_*.png l5_*.png`
  - **208 测试全绿（+19）；6 个新 JS node --check 过；未提交，等待用户验收**


**服务器**：uvicorn 跑在 127.0.0.1:8000（含全部 18 场缓存）。

## 2. Phase L —— 占位页全部真实化 + 冷启动性能治理（2026-09-03，待审+待验收）

计划经用户批准（占位页全部 5 个 + 追加"第一次启动要很久"优化）。全部在工作区待审：

### L0 — 冷启动性能（先做）

- **实测根因**：首页纯 SSR 同步跑全库扫描 ~70s 白屏（aggregate 17.2s + 高亮 feed 50.4s——后者此前文档未记录）
- **算法**：`round_player_sides` 内循环 pandas→numpy + player 边界提出回合循环（单场 highlights 2.18s→0.55s）
- **架构**：`analysis/library.py` 线程池扫描（scan_demos/load_all_demos/demo_filenames）；teamplay 只全量读 9 场 5E（25s→19.9s）
- **体验**：`web/warmup.py` 启动预热线程 + dashboard 骨架渐进填充——**首屏 172ms，~44s 后台就绪后自动填充数字与高光**
- 顺手修：teamplay CLI 路径 `AnalysisRunner(analysis=)` 无效关键字（demo_ratings=None 必炸）；`_module_cache` LRU 512 上限（§9.5 旧账）

### L1 — 收藏标注（/favorites）

- `favorites_store.py`（output/favorites.json，ui-prefs 同款 Lock+容错）；GET/POST /api/favorites
- 星标按钮：对局卡片（委托 `.fav-star`，meta 随点随存）+ 选手页头；/favorites 页标签筛选/备注/跳转
- `base.html` 新增 `.nav-secondary` 二级专题导航（道具/地图/阵伍/收藏/报告）

### L2 — 道具专题（/utility-lab）

- `utility_effect.py` 加性字段 `smoke_events`（烟弹落点+烟中击杀位置，不改 PARSER_VERSION）
- `utilitylab_data.py` 跨场聚合 memo（与 aggregate 联动失效）；闪光价值榜（CCTV909 372.5 居首）/烟中击杀榜/6 图落点热力
- **修复静默 bug**：demoparser2 0.42 smokegrenade_detonate 列名是小写 `x/y`，代码读大写 `X/Y`——真实 demo 烟中击杀恒 0（合成测试列名大写所以从未暴露）。修复后 93 杀 / 1704 落点

### L3 — 地图分析（/map-analysis）

- `mapdata.py`：按图聚合场次/回合/T+CT 胜率/routes top3 合并/postplant A-B/本图最强选手（aggregate 按 map 过滤 ≥10 回合）
- **修复**：`postplant.py` 的 site 列真实值是数字 place id（313/376），改用 user_last_place_name 推断 A/B

### L4 — 队伍视图（/teams）

- **数据事实**：18 场（含 5E 原始事件）队名全是 "Team 2/3"/"CT/TERRORIST" 占位——无战队名可依
- `lineups_data.py`：首发阵容指纹分组 + teamplay 常客定义（≥3 场）；车队局 5 场己方回合胜率 45.0% vs 单排 4 场 65.1%（口径同 K5）；逐场双阵容 Rating 表；页面标注"匹配匹 demo 无战队名"

### L5 — 报告导出（/reports）

- `/report/{hash}` 白底打印模板（比分/回合走势色块/选手数据表/高光）；浏览器 Ctrl+P 也可用
- `report_export.py`：playwright chromium PNG（full-page）/PDF（A4）；**必须 `asyncio.to_thread`**（sync API 不能跑在事件循环里）
- 501 + 安装指引（未装 playwright）；pyproject 可选组 `reports=["playwright>=1.40"]`

### L6 — 收尾

- `visual_check.py` 16→**21 页全部 OK 零 console 错误**；system.html 专题卡转正；入口 chip 去"即将上线"
- **208 测试全绿（+19）**；6 个新 JS `node --check` 过；HANDOFF（本节）/ dev_log 同步；**未提交，等用户验收 + provenance**

## 3. Phase K —— 已全部完成（2026-08-30，已提交推送）

### K2 — 重叠子模式 UI 显著化 + 高级分析（已完成，待验收）

- **K2e UI 显著化**：工具条首位分段切换器 `[ 实时回放 | 回合重叠 ]`（`.ob-mode-switch`）；
  相位条 v2（accent 描边+辉光、加宽滑杆、等宽字时钟）
- **K2a 回合网格**：`.ov-rounds-bar` 横向滚动 chips（胜方色角标、点击勾选/取消、
  空选=全部、全选/清空/前4 快捷、已选 n/总 计数）；`state.ovRounds = Set`，
  `effectiveOvSegs()` 供绘制/镜头跟随/指标共用；半场切换自动清空重建
- **K2b 阵型指标相位曲线**：`.ov-metrics-wrap` 双线迷你图（全体散开度紫 / T/CT 重心间距绿，
  96 相位采样均值，缓存按 半场+选择失效）；白色相位竖线+交点圆点与滑杆/播放联动；点击/拖动设相位
- **K2c 路线模式聚类着色**：纯 JS k-means（k=2..3 肘点 0.55、farthest-first 确定性初始化），
  特征=进攻方（T）重心开局轨迹相位 0~0.3 采样 6 点；「模式着色」chip 开启后回合条
  chips 换聚类描边、轨迹描边按回合聚类色（标记保持阵营身份色）；chip 仅重叠模式可用
- **K2d 聚焦 vs 重心偏差**：聚焦时每回合相位位置 → 本方重心的紫色虚线 +
  相位条旁读数（`偏差 649u · 12.3m`，1u≈0.019m）
- 验收：playwright 逐项截图（`output/.visual/k2*.png`）+ `test_viewer_k2_overlap_ui_contract`

### K5 — 13 场 5E 的「有趣结果」（已完成，报告见 §7 专节）

- **K5a 五排默契度网络**：`analysis/teamplay.py`（助攻/复仇补枪/闪光助攻 有向连接，
  trade 复用 ratings.TRADE_WINDOW_TICKS，round_player_sides 换边安全同队校验）
  + `/compare`「五排协同」卡（矩阵热力 + Top 连线表 + 画像）+ `/api/compare/teamplay.json`
  （memo 与 aggregate 联动失效）
- **K5b 车队局 vs 混野**：阈值自适应（≥3 常客同场）；回合胜率/场均 Rating/首杀成功率对比 → §7 报告
- **K5c 五人跨场画像**：最佳搭档/闪光发动机/首杀先锋/残局大师标签（残局复用 highlights 模块）

### K6 — 收尾（已完成，随 cd2ec98 推送）

- 全量 pytest 189 全绿；playwright 零 console 错误
- HANDOFF / dev_log 同步；已按用户批准分两个 commit 推送（1a9a3c5 K5 / 44f7e7f K2 / cd2ec98 K6 文档）

## 3. Phase K 已完成部分（细节，供返工参考）

- **K1 重叠两 bug**（已在工作区）：① syncPanelFocus 的 overlap guard 移除，updateCamFollow 增加重叠分支（目标=聚焦选手在半场各回合同相位位置的均值 map-px）；② frame() 重排为 updateCamFollow → (camMoved 时) drawMapLayer → drawMainLayer → drawFxLayer → drawTimeline——修复底图滞后一帧。playwright 实测重叠 zoom 1.00→2.46 滑镜、回放无回归
- **K3 5E 导入**：9 个 zip 解压到 `demos/`（g161-*.dem），全部解析入缓存（match_id 正确提取，rounds 16-30，10/10 玩家，无 Team 0）。探针脚本 `output/_probe5e.py`、解析脚本 `output/_parse_5e.py`
- **K4 三新地图**：`maps/data/` 新增 de_nuke/de_dust2/de_cache 各 PNG+yaml。PNG 下载自 MurkyYT/cs2-map-icons（`images/radars/<m>_radar_psd.png`，经 api.github.com contents base64——raw.githubusercontent 超时）；bounds = radar_info（`data/radar_info/<m>.txt`）pos_x/pos_y/scale 标准公式。**双重验证**：① 全 demo 玩家 bbox 落入图像（`output/_bounds_fit.py`）② dust2 真实下包事件归一化落点与 radar_info 包点图标吻合（A: 0.79-0.82 vs 0.80；B: 0.17-0.18 vs 0.21，`output/_calib_check.py`）。五链路验证：/maps 路由 200、回放器底图非黑像素 9.9-29.9%、零 console 错误
- **K4 验收修复（warmup 伪回合，2026-08-30）**：用户报告 dust2 回放"出生点不对"，最终与 K4 校准无关——5E demo 热身期事件（round_start@43 round=1 warmup / round_end@43 round=0 / round_freeze_end@171）污染回合构建：r1 变成 43..12493（含 134s 热身），且 round_freeze_ends 索引拉链使**每个回合**的 freeze_end 错位到上一回合。修复：`_build_rounds` warmup 行跳过 + 非 warmup start 优先；`round_freeze_ends` 区间包含配对；`viewer_data` team0 原点行 alive=0 隐藏。版本 bump：PARSER 1.8.0 / VIEWER_DATA 4 / LAYER 3，18 demo 全量重解析。修复后实测：dust2 r1=8838..12493 fe=10214，t=0 时 T 五人落底图 T 出生绿框、CT 五人落 CT 绿 hatch，185 测试全绿，截图 `output/.visual/k4_dust2_spawn_fixed_t0.png`。**经验**：地图校准类报告先验证落弹双轴（旧 `_calib_check.py` 只对了 x，y 翻转查不出）+ 检查 demo 热身事件数量与回合数的差值
- **README 视觉改造已提交推送**（e839a1a）：GIF 头图（回放器实录）+ 10 张截图 + 徽章 + 中文重构；**重叠 GIF（overlap_hero.gif）在工作区待审未提交**

## 4. 运行环境（坑都在这）

| 项 | 值 |
| :--- | :--- |
| Python | **`D:\Program Files\Python311\python.exe`**（PATH 的 python 指向失效 enve/） |
| demoparser2 | 0.42.0（`>=0.42,<0.43`；0.42 起有 ammo/reload/inventory） |
| 服务器 | `uvicorn cs_analyzer.web.app:app --port 8000`，改动 JS/模板后重启 + `static_v` 防缓存 |
| Playwright | `scripts/visual_check.py`（21 页）；**沙箱可能拒绝其驱动进程管道创建**——提权或重试 |
| 本会话 shell | pwsh（无 bash）；python 输出偶发被管道吞——**重要结果写到文件再读** |
| 中文 .bat | **GBK + CRLF，禁 chcp 65001**（UTF-8 中文 + goto/call 标签定位会错位执行乱码；LF-only 也断） |
| pwsh 管道挂起 | bat 启动的孤儿 uvicorn 继承管道句柄 → `Start-Process -Wait` 永远等不到——测试用文件重定向 + 轮询状态，别 -Wait |

**探针脚本模式**（demoparser2 pyo3 会 Rust panic 杀进程，探针必须子进程隔离）：`scripts/probe_events.py`、`scripts/probe_ammo.py`。

## 5. 关键入口

```bash
"D:\Program Files\Python311\python.exe" -m pytest -q        # 208 全绿
"D:\Program Files\Python311\python.exe" -m uvicorn cs_analyzer.web.app:app --port 8000
scripts/visual_check.py                                      # playwright 21 页
scripts/probe_events.py                                      # 事件可用性探针（子进程隔离）
```

核心文件：
- 解析: `cs_analyzer/parser/backend.py`（`_MATCH_ID_PATTERNS` 双平台 match_id、`_empirical_tick_rate`、legacy 降级重试）, `manager.py`（tick_fields 含 inventory）
- 缓存: `cache.py`（PARSER_VERSION **1.8.0**）
- 分析: `cs_analyzer/analysis/`——14 模块（basic_stats/ratings/preference/duels/economy/utility_effect/routes/highlights + kill_context/hitgroups/aim/postplant/weapon_splits + **teamplay**）+ **util.py**（`round_player_sides` 换边安全阵营，L0 numpy 化）+ **library.py**（L0 线程池全库扫描）
- 回放前端: `static/viewer_canvas.js`（回放+重叠子模式+聚焦跟随+买装条）、`js/viewer_overlays.js`（事件覆盖层，SMOKE_SCALE=1.2）、`js/viewer_control.js`（控图/3D）、`js/viewer_prefs.js`（19 参数调节面板）、`js/viewer_camera.js`
- Web: `app.py`（路由；**专题页路由必须注册在 /{placeholder} 之前** + `/api/warmup.json` 预热协议）、`chart_data.py`（载荷）、`viewer_data.py`（v4 数据包）、`store.py`（match_key）、`aggregation.py`（memo 总失效入口：aggregate+teamplay+feed+utilitylab+mapdata+lineups）、`warmup.py`（L0 启动预热）、`feed_data.py` / `teamplay_data.py` / `utilitylab_data.py` / `mapdata.py` / `lineups_data.py`（五个 memo 报告）、`favorites_store.py`、`report_export.py`、`weapons.py`（武器单一事实源）
- 地图: `cs_analyzer/maps/data/`——**6 图**（mirage/ancient/inferno/nuke/dust2/cache），yaml 含 provenance 注释与换算公式

## 6. 数据资产

- **demos/**：18 个 .dem = 9 WMPVP（`9206...`~`9220...` 数字节名）+ 9 五排 5E（`g161-2026082x...`，2026-08-25~28）
- **缓存**：`.cache/` 18 条，全部 parser_version 1.8.0（2026-08-30 warmup 修复后全量重解析）
- **地图**：6 张有官方雷达资源；`de_nuke` 为双层图（用上层 primary radar，下层按 x/y 投影）
- **源目录**：`C:\Users\35311\AppData\Roaming\5E对战平台\demo` 还有 **4 个截断下载的坏 zip**（mirage×3 + inferno×1，EOCD 缺失）——用户若从 5E 客户端重新下载可补入
- **5E 文件名规律**：`g161-<日期时间><serial>_<map>.dem`——内嵌日期，天然时序

## 7. 已知问题 / 技术债务（Phase K 更新）

1. **4 个 5E zip 截断**（EOCD 缺失，文件头正常）：mirage×3 + inferno×1——`zipfile` 报 BadZipFile，导入脚本已容错跳过。用户重新下载后可补入
2. **money prop 不可用**（0.42 MISSING 实测）；`bullet_impact`/`*_thrown` 事件在 WMPVP/5E 广播缺失（Valve demo 有）——事件表已预留
3. **Team 0 玩家**：WMPVP 个别 pawn 不可解析（位置类跳过）；**5E 无此问题**
4. **CS2 header 无日期/tickrate/match_id**（实测）：tick_rate 用 velocity÷位移推导（实测 64.0）；match_id 从文件名提取；`parse_convars()` 会 pyo3 panic——探针必须子进程隔离
5. RWS/Rating 为自实现近似；KAST trade 语义 Phase I 已修正（旧值不可比）
6. 队名占位 "Team 2/3"（WMPVP 缺 begin_new_match）
7. 老条目仍有效：coverage.html 样式未对齐 v2、`output/web/{hash}/radar|pref|aggregate` 孤儿目录可删
8. **player_death 的 steamid 列含 NaN**（assister 空缺时）——`astype(str)` 会造出假玩家 "nan"；teamplay.py 已 fillna 处理，新事件消费方注意同样处理
9. 5E demo 的 `provider` 元数据实为 `valve`（5E 服务器发标准 SourceTV 头）——识别 5E 库只能靠文件名 `g161-` 前缀（teamplay.is_five_e）

### 5E 五排数据洞察（Phase K5 报告，2026-08-30）

数据基础：9 场 5E（g161-*，2026-08-25~28）+ 9 场 WMPVP。报告由 `analysis/teamplay.py` 生成，
`/compare` 页「五排协同」卡可视化（`/api/compare/teamplay.json`，与 aggregate 同 memo 失效）。
阈值适配：原计划 ≥4 常客判定五排局，实测 FENNEL的YamZzi本人仅 3 场 → 默认阈值改为
**≥3 场=常客、≥3 常客同场=车队局**（`build_teamplay_report` 参数可调）。

- **常客结构**：CCTV909（用户本人）9/9 全勤；核心车队 FywOo6666（5）、杏愛（5）、FENNEL的YamZzi本人（3）。
  **5 场车队局 vs 4 场混野局**（用户单排）。
- **协同网络**：核心四人两两互连。最强连线 杏愛→CCTV909（9 助攻 + 2 补枪 + 1 闪助，权重 12）；
  对称侧 CCTV909↔杏愛 10、CCTV909↔FywOo6666 11/10、杏愛↔FywOo6666 11——三人配合度均衡，无明显单核依赖。
- **五排画像**：CCTV909 一人包揽三标签——闪光发动机（3 闪助）、首杀先锋（首杀成功率 56%，27/48）、
  残局大师（1 次残局获胜）；最佳搭档 FywOo6666（权重 11）。杏愛 是对 CCTV909 的最强助攻手。
- **车队局 vs 混野（K5b，反直觉发现）**：车队局回合胜率 **46.4%**、常客场均 Rating **1.129**、
  首杀成功率 45.8%（83 次对枪）；混野局 **65.0%** / **1.545** / 66.7%（18 次对枪）——
  **用户在混野局表现显著更好（胜率差 +18.6pp）**。合理解释：车队局匹配到的是对方整队（对手池更强），
  且样本注：混野组"常客"只有 CCTV909 一人（4 场），车队局含 4 人 ×5 场样本，个体差异参与其中，不宜过度解读。
- **每场分类明细**（regs=常客数）：车队局 = dust2(4人, 胜率18.8%)、cache(3, 40.9%)、ancient(4, 68.4%)、
  nuke0822(3, 43.5%)、mirage0828(4, 53.3%)；混野局 = nuke0825/mirage0825/mirage0827×2（用户单飞，胜率 61.9-68.4%）。

## 8. 提交历史（近期）

```
cd2ec98 docs: README GIF overhaul + Phase K6 sync               ← origin/main（Phase K 六连已推送）
1a9a3c5 feat(analysis): K5 five-stack teamplay analytics + compare card
44f7e7f feat(viewer): K2 overlap sub-mode UI + interactions
e65f522 docs: README overlap hero GIF
c4a5fc4 feat: 5E match-id recognition, three new maps, warmup-round segmentation fix
2c40f81 fix(viewer): overlap camera-follow regression + base-map sync timing
e839a1a docs: README visual overhaul + robust start_web.bat
60e47c9 feat: Phase I deep analytics engine + Phase J viewer/overlap polish
04e39a9 Phase G | 03c9eb4 Phase F | 933e9b1 Phase E | ...（更早见 git log）
```

Phase L 全部改动在工作区待审（见 §1）。完整阶段日志见 dev_log.md（每个 Phase 一条，含模型名）。

## 9. 未来路线（Phase L 之后）

1. **收藏备注编辑 UI**：/favorites 已可星标/标签筛选/看备注，对局详情页内嵌标签/备注编辑器可作下一小步
2. **在线发布**（用户拍板暂缓，方向已定）：`csa export-static` 静态快照导出 → gh-pages（只读分享版）；公开仓库 + steamid/昵称匿名化；发布前 rename 仓库（现名 CS-Radar-Map-Generation 是早期项目名）
3. 控图算法 v2（视线/交战权重，用户暂缓中）
4. 更多地图 PNG（任何新地图：MurkyYT/cs2-map-icons + radar_info 公式，流程见 K4）
5. 预热进程池/磁盘快照（L0 线程池受 GIL 限制，全库预热 ~58s 后台完成；如需更快可上 ProcessPoolExecutor 或聚合快照落盘）
6. 可选：aim 模块接 inventory 做武器持有时间线；Rating 2.1

## 10. 给新对话的第一步建议

1. 读本文件 §0-§2（Phase L 全貌）、§7 的「5E 五排数据洞察」
2. `git status` 确认待审改动还在（Phase L 一批）；`git log` 若出现新 commit 说明用户已批准提交
3. Phase L 全部完成——下一步候选见 §9 未来路线
4. 任何 commit 前重读 §0 铁律 1 与铁律 5（路由注册顺序）
