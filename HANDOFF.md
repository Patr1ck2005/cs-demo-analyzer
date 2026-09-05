# 交接文档 (HANDOFF)

> 给下一个开发 agent 的交接说明。目标：10 分钟内了解项目状态、运行环境、待审改动、开发计划与所有坑。**最后更新：2026-09-06（Phase T 性能底座完成——快照落盘 §13 + 进程池 ADOPT + 分片增量，待审+待验收）**

## 0. ⚠️ 铁律（先读这个）

1. **未经用户在对话里明确说"批准提交"，绝不执行 `git commit`**。计划文档/milestone/ExitPlanMode 批准都不构成提交授权（2026-08-30 用户申斥确立）。每次 commit 前问两件事：① 是否批准 ② provenance（`Origin: ai:<model>-<agent>`，模型随会话变必须每次问；历史值见 §8）。
2. 跑 Python 一律用显式路径 `"D:\Program Files\Python311\python.exe"`（bash PATH 的 `python` 指向失效的 enve/ venv）。
2b. **pip 装包可能清掉本机既有依赖**（2026-09-03 实证：`pip install pydantic` 后 pyyaml/fastapi/uvicorn/greenlet 全消失）——装完立刻 `pip install -e ".[dev]"` 恢复，并用 `python -c "import uvicorn, fastapi, yaml"` 自检。
3. **agent 可以读图片**：`read_image` 工具直接读 PNG/JPEG/WebP/GIF（2026-08-30 实证可用，旧"read 是纯文本"限制已失效）。视觉验收优先：playwright 截图 → read_image 亲眼看；像素采样断言仅作程序化补充。
4. 异常一律记录到 HANDOFF §7 与 dev_log，不分轻重。
5. **FastAPI 路由注册顺序**：`/{placeholder}` 通配路由在 app.py 中部注册——任何新的单段页面路由必须注册在它**之前**（L2 的 /utility-lab 曾被遮蔽 404）。

## 1. 项目状态摘要

CsDemoAnalyzer：本地优先 CS2 demo 分析平台（解析 `.dem` → 定量统计 + 电竞 OB 级 2D 实时回放）。FastAPI + Jinja2 全中文 SSR + canvas 回放器 + vendored ECharts。**当前 24 个 demo 在库、261 测试全绿、visual_check 22 页零 console 错误**。

**Git 状态（Phase T 完成待审）**：origin/main = `c7f42ed`（Phase S 稳定化已提交推送）。
**Phase T 性能底座已完成**（长周期路线图用户批准：T 性能底座 → U 分析强化 → V 竞技 AI；发布线继续冻结）——
快照落盘/进程池/分片增量三件全部落地，明细见 §13。**工作区待审，等用户验收 + provenance**。

- **Phase T 一句话**：冷重启 175s→**5.2s**（快照命中）；全量重算 201s→**131s**（进程池 -35%）；新 demo 导入重算 **5×**（分片增量）；/system 新增性能面板。
- **Phase M5/N 历史摘要**（已提交推送）：
  - **反样本量偏差整改**（用户原则："人与人对比的指标必须排除打得多=数据高"）：
    舔包王榜→每回合口径（用户裁决"除总回合数"）/ 地图最强选手→回合加权 Rating+同图多场池化
    （原 rating×rounds 且同图覆盖只留最后一场）/ 五排画像闪光·残局·最佳搭档→每场比率 /
    道具闪光榜→价值/投掷（<3 次标"少"）·烟中榜→每场净值 / 队伍视图组胜率→回合池化
  - **两处 funlab bug**：① ssg08 同时在长枪集+装逼集，装逼率永远漏鸟狙→鸟狙只认装逼（用户裁决）；
    ② "Desert Eagle" 显示名缺别名，沙鹰绕过发枪链→补 "desert eagle"→deagle
  - **口径上页面**（用户要求"点开必须能看到介绍"）：`funlab_data.METRIC_DEFS` 31 指标
    label/formula/note 随 /api/funlab.json 下发；/fun-lab 新增"📖 指标口径说明"面板（逐项展开）
    + 轴选择下方实时两轴公式行 + 榜单卡头口径小字；utility/map/teams 页口径脚注；
    compare 最佳搭档显示"X.X/场·共N次"
  - **docs/funlab-metrics.md v6**（Phase S 升版）：S 数值修复记录 + 指标数勘误（31 非 32）
  - **聚类分析 §10**（Phase N 已完成）：风格星系 + YamZzi 离群发现
  - 测试 212→221（M5）→231（N）→**239**（S 进行中）
  - **Phase M 历史批次**（已全部提交推送）：
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
  - ↑ Phase M 批次（已推送 938e01e）；以下 Phase L 批次**已全部提交推送**（027cf59 / 0d18492 / ac5c7fa）：
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

## 3a. Phase K 已完成部分（细节，供返工参考）

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
| **uvicorn 静默死亡（T 期实锤）** | agent 用 `Start-Process -WindowStyle Hidden`（无重定向）拉起的 uvicorn 会被父 pwsh 进程退出连带杀死——**必须 `-RedirectStandardOutput/-RedirectStandardError` 落盘文件**（挂在真实句柄上），否则"刚起→跑巡检就死"且零日志 |

**探针脚本模式**（demoparser2 pyo3 会 Rust panic 杀进程，探针必须子进程隔离）：`scripts/probe_events.py`、`scripts/probe_ammo.py`。

## 5. 关键入口

```bash
"D:\Program Files\Python311\python.exe" -m pytest -q        # 261 全绿
"D:\Program Files\Python311\python.exe" -m uvicorn cs_analyzer.web.app:app --port 8000
scripts/visual_check.py                                      # playwright 22 页
scripts/probe_events.py                                      # 事件可用性探针（子进程隔离）
scripts/bench_startup.py                                     # T4：冷启动三场景计时（起 8123 专用端口）
scripts/bench_process_pool.py                                # T2：进程池收益实测（决策依据）
```

核心文件：
- 解析: `cs_analyzer/parser/backend.py`（`_MATCH_ID_PATTERNS` 双平台 match_id、`_empirical_tick_rate`、legacy 降级重试）, `manager.py`（tick_fields 含 inventory）
- 缓存: `cache.py`（PARSER_VERSION **1.8.0**）
- 分析: `cs_analyzer/analysis/`——14 模块（basic_stats/ratings/preference/duels/economy/utility_effect/routes/highlights + kill_context/hitgroups/aim/postplant/weapon_splits + **teamplay**）+ **util.py**（`round_player_sides` 换边安全阵营，L0 numpy 化）+ **library.py**（L0 线程池全库扫描 + T2 `scan_demos_proc` 进程池 + T3 `scan_hashes`/`scan_hashes_proc` 子集扫描）+ **aggregate.py**（T3 起 per-demo 产出统一为 shard dict 形态 + `merge_aggregate_shards` 唯一合并）
- 回放前端: `static/viewer_canvas.js`（回放+重叠子模式+聚焦跟随+买装条）、`js/viewer_overlays.js`（事件覆盖层，SMOKE_SCALE=1.2）、`js/viewer_control.js`（控图/3D）、`js/viewer_prefs.js`（19 参数调节面板）、`js/viewer_camera.js`
- Web: `app.py`（路由；**专题页路由必须注册在 /{placeholder} 之前** + `/api/warmup.json` 预热协议 + `/api/system/status.json` 含快照清单）、`chart_data.py`（载荷）、`viewer_data.py`（v4 数据包）、`store.py`（match_key）、`aggregation.py`（memo 总失效入口：aggregate+teamplay+feed+utilitylab+mapdata+lineups+style_map + T3 分片 GC）、`warmup.py`（T1 快照感知两波预热）、`snapshots.py`（**T1/T3 核心**：全库快照 + per-demo 分片 + 指纹 + GC）、`feed_data.py` / `teamplay_data.py` / `utilitylab_data.py` / `mapdata.py` / `lineups_data.py`（memo 报告，各带 T1 snapshot pair）、`funlab_data.py`（scan 两层 + T3 分片）、`style_map.py`、`favorites_store.py`、`report_export.py`、`weapons.py`（武器单一事实源）
- 地图: `cs_analyzer/maps/data/`——**7 图**（mirage/ancient/inferno/nuke/dust2/cache/anubis，anubis 为 Phase N 小件 1 补入），yaml 含 provenance 注释与换算公式

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

Phase T 全部改动在工作区待审（见 §1/§13）。完整阶段日志见 dev_log.md（每个 Phase 一条，含模型名）。

## 9. 未来路线（Phase T 之后 = 长周期路线图的 U/V 阶段）

**路线图总纲（2026-09-06 用户批准）**：T 性能底座 ✅ → **U 分析强化 → V 竞技 AI**；
发布线/内容生产冻结；数据飞轮 = 被动积累（~10 场新 5E zip 一次入库批）。

### Phase U —— 分析深度强化（下一个大阶段，U1→U2→U3）
1. **U1 Rating 2.1 对齐**：`analysis/ratings.py` 新增 HLTV 2.1（实现前先 web_search 核实
   公开权重——开局击杀/死亡、多杀回合、残局，不凭记忆写系数）；生涯页 2.0 vs 2.1 并排卡 +
   全库分位；口径进 METRIC_DEFS 单一数据源；合成 demo 数值回归。
2. **U2 武器持有时间线**：新 `analysis/weapon_timeline.py` 从缓存 inventory 列推导
   持有时长/切枪序列/eco 武器使用（PARSER_VERSION 不 bump）；/match 战术 Tab 甘特/主题河流
   （注意 ECharts 容器显式宽度老坑）；生涯页"武器偏好演变"。
3. **U3 控图算法 v2（解冻）**：viewer_control.js 高斯核之上加 交战衰减/存活加权/密度去重；
   权重全进 viewer_prefs 面板，v1/v2 开关并存；验收 = 同回合 v1/v2 截图并排可解释
   （无地图几何，不做物理射线遮挡——诚实边界）。

### Phase V —— 竞技 AI 深水区（跨数据积累周期，24 场=方法验证期）
1. **V1 回合胜负概率**：新 `analysis/win_probability.py`——特征=存活差/买法态/装备差/
   下包态/路线簇；numpy 手写 logistic（L2）+ bootstrap 置信带 + LOO AUC 上页面；
   **验收页 = /match 胜势曲线**（逐回合实时胜率 + 事件标注）。零新依赖（不装 sklearn）。
2. **V2 经济决策 EV**：新 `analysis/economy_ev.py`——决策状态→胜率+存活 EV 查询表；
   每格最低样本量（不足灰显 + 实际 N）；**验收页 = /match 经济 Tab 决策 EV 面板**。
3. **V3 风格星系迭代**：时间窗向量漂移轨迹 + 变化点标注（style_map 管线自动随样本增长）。
- **纪律**：所有结论页强制标注样本量/置信区间；新依赖先报备 + 铁律 2b。

### 其他路线（保持）
1. ~~收藏备注编辑 UI~~ ✅ 已随 Phase S 完成（收藏编辑器）
2. **在线发布**（用户拍板继续暂缓，方向已定）：`csa export-static` 静态快照导出 → gh-pages（只读分享版）；公开仓库 + steamid/昵称匿名化
3. ~~控图算法 v2~~ → 升格为 U3（本路线图）
4. 更多地图 PNG（任何新地图：MurkyYT/cs2-map-icons + radar_info 公式，流程见 K4；K4 双重验证含 y 翻转锚点实测）
5. ~~预热进程池/磁盘快照~~ ✅ 已随 Phase T 完成（§13）
6. ~~可选：aim 模块接 inventory 做武器持有时间线；Rating 2.1~~ → 升格为 U1/U2（本路线图）
7. ~~选手风格聚类~~ ✅ Phase N 完成；迭代 → V3（本路线图）
8. **T 遗留小件**（§13）：teamplay/utilitylab/mapdata/lineups 接分片（模式照 feed 抄）

## 9a. Phase M5 —— 全面口径审计（2026-09-05，完成待审）

用户指令："全面审核整个项目，打得场次越多数据越高的指标全部整改（除非稳定性类）；
趣味数据每个指标必须在网页/文档里能点开看到计算口径。"

**审计结论（整改前）**：
| 位置 | 问题 | 整改 |
|---|---|---|
| /fun-lab 舔包王榜 | 按白嫖总次数（绝对值） | →每回合（用户裁决）；次数进括号 |
| /map-analysis 本图最强 | rating×rounds 绝对值乘积；同图多场被覆盖只留最后一场 | →回合加权 Rating + 池化（mapdata._pool_map_players/best_players_for_map） |
| /compare 五排画像 | 闪光发动机/残局大师按总次数；最佳搭档按总权重 | →每场比率取王，次数进 detail；搭档 per_demo 字段 |
| /utility-lab 闪光榜 | 按总价值 | →价值/投掷（投掷<3 前端标"少"）；烟中榜→每场净值列 |
| /teams 组胜率 | 各场胜率简单平均 | →回合池化 pooled_win_rate（Σ胜/Σ总） |
| funlab SSG（bug） | ssg08 同时在 RIFLE_WEAPONS+SHOWOFF_WEAPONS，装逼率永远漏鸟狙 | →鸟狙只认装逼（用户裁决） |
| funlab deagle（bug） | "Desert Eagle" 显示名不在 WEAPON_ALIAS，沙鹰绕过发枪链 | →补别名 |

**口径可视化**：`funlab_data.METRIC_DEFS`（32 指标 label/formula/note）+ BOARD_DEFS 随
/api/funlab.json 下发；/fun-lab 页"📖 指标口径说明"面板（details 逐项展开）+ 轴选择下方
实时两轴公式行；榜单卡头带口径小字；utility/map/teams 页 section 副标或脚注补口径。
单一数据源铁律：改口径先改 METRIC_DEFS（+docs 同步），前端不再硬编码指标名。

**验证**：tests 212→**221 全绿**（+9 test_metric_audit.py：SSG 装逼/别名/AK 叛逆回归/
METRIC_DEFS 完整性/free_pickup_pr 分母/map 池化+门槛/lineups 池化）；
4 页截图验收 `output/.visual/m5_*.png`（含口径面板展开图）。
实库效果：舔包王 Trippinnn 0.030/回合(3次) 反超杏愛 0.020(6次)——低场次不再吃亏；
装逼王计入鸟狙后 CCTV909 17 局 0.195 上榜。

## 9b. M5 收尾：全页面视觉检验 + 架构检查（2026-09-05，完成）

用户指令：对所有页面（含按钮行为）全面视觉检验；架构全面检验；给出收尾计划。

### 视觉检验（22/22 页逐页 read_image 人工复核 + 定向加拍）
- **逐页结论**：仪表盘/对局库/对局详情+6tab/选手库/高光/对比/系统/收藏/道具/地图/队伍/报告/单场报告/趣味/生涯/重叠/回放 —— 布局/图表渲染/中文/空状态全部正常；overlap/viewer 回放正常。
- **发现并修复 2 缺陷**：
  1. **"nan" 假选手**（§7.8 陷阱未清干净）：tab_tactics 武器拆分表 + tab_kills 对枪矩阵出现
     nan 行/轴——根因是 `str(NaN)`→"nan" 散布 8 个分析模块 23 处。修复：`util.clean_sid()`
     统一助手 + 机械清扫；test_metric_audit 新增 5 模块回归测试。
  2. **选手库 Rating 矩阵 Y 轴名被裁切**：charts.js `matrixOption` grid.left=90 太窄 →
     `left:8 + containLabel:true`；1600px 与 900px 窄视口复拍确认完整。
- **定向验证**：预设 chip 点击联动轴+公式行 ✓；口径面板四组 32 项全渲染 ✓；
  de_anubis chip 可切、数据瓦片正常（雷达 PNG 缺失维持 §9.4 已知项，非回归）；
  窄视口 900px 下 fun-lab canvas 852px 无零宽度回归 ✓。

### 架构检查结论（A-E）
- **A 数据契约/失效链 ✓**：`invalidate_aggregate()` 链覆盖全部 6 个 memo
  （teamplay/feed/utilitylab/mapdata/lineups/funlab）；funlab `stack=`/`dates=` 按键 re-merge
  实测正确（25 场全量 7 人 / stack=5 → 4 场 5 人 / 09/03 → 4 场 5 人）；METRIC_DEFS 单一数据源，
  前端无指标名硬编码（仅 key 引用）。
- **B 正确性 ✓**：路由顺序铁律 5 保持（/fun-lab 等在 /{placeholder} 前）；§7.8 全库清扫（23 处）；
  武器别名表补 Desert Eagle；换边安全（round_player_sides）未被触碰；绝对值取王残留仅剩
  teamplay 连线表/热图（网络可视化原始权重，页面已注明"双方向合计"）与高光 feed（tier 排序，
  非个人榜）——均有意保留。
- **C 性能 ✓**：25 场全库预热实测 **175s**（基线 ~190s）；`_module_cache` LRU 512 上限有效；
  进程池仍列 §9.5 不动。
- **D 前端卫生 ✓**：12 个 JS 全过 `node --check`；图表容器均有显式尺寸；esc() 8 处重复实现
  仅记录不合并（低价值）。
- **E 文档一致性 ✓**：docs/funlab-metrics.md v5 ↔ METRIC_DEFS 抽查 5 项同义；HANDOFF §1/§9a
  与工作树 diff 一致。
- **记录不动的小项**：compare 雷达叠加未选人时空箱（建议未来加"勾选上方选手"提示，§9.1）；
  tab_utility 闪光榜 Y 轴名右缘截断（单场页 axis name 过长，纯装饰）。

## 10. Phase N —— 选手风格聚类 🌌 风格星系（2026-09-05，完成待审）

用户六项裁决（问答确认）：聚类主线+两小件 / **全部 32 个 M5 比率指标**入向量 /
**欧氏距离**（稳健标准化空间）/ 标签自动命名 / 展示在 /fun-lab 新区块 / 门槛 ≥3 场。

- **`web/style_map.py`（新，零新依赖）**：复用 funlab_report 向量 → 常量列剔除 →
  稳健标准化（中位数/IQR，IQR=0 回退 std）→ PCA 前 2 主成分（numpy SVD，附解释方差比）→
  **Ward 层次聚类**（scipy 已装，不装 sklearn/umap——铁律 2b 规避；切簇 = 0.6×最大合并距离）→
  簇标签**对比式自动命名**（质心 vs 其余簇质心 top3 偏离，两簇标签互为镜像——
  初版"vs 全局中位数"命名在含离群者时 6 人标签同质，实库发现后修正）→
  最近邻（全特征欧氏，排除自己）。**单一巨簇时逐人画像兜底**（自己 vs 中位数）。
- **/fun-lab 新区块"🌌 风格星系"**：PC1×PC2 散点（色=簇、点大小=场数、tooltip=标签+最像队友）
  + 右栏风格画像列表；头部显示"PC1+PC2 解释方差 71% · 29 特征入向量 · 剔除常量 2 个"。
- **API**：`/api/style-map.json`（铁律 5：注册于通配路由前）；失效链接入
  `invalidate_aggregate → style_map`；无独立预热步（funlab 向量算完即得）。
- **测试**：tests/test_style_map.py 10 项（常量列剔除/标准化回退/PCA 形状方差/双 blob 分簇/
  对比式命名方向/最近邻排己/个人画像兜底/web 契约+3demo 契约）；**231 全绿**。
- **实库结果**：7 人 → Ward 2 簇；**YamZzi 是真离群者**（合并距离 5.4~8.8 vs 最后一步 16.3），
  标签"高烟中杀率·高纯eco率·低神仙率" vs 其余 6 人"低烟中杀率·低纯eco率·高神仙率"；
  PC1+PC2 解释方差 71%。研究预览定位：样本增长后星系自动变有意义（页面已注明）。
- **小件 1 — anubis 雷达 PNG（K4 流程）**：MurkyYT/cs2-map-icons 经 api.github.com base64
  下载 `de_anubis.png`（1024×1024 RGBA）+ radar_info（pos_x=-2796/pos_y=3328/scale=5.22）
  标准公式补 `maps/data/de_anubis.yaml`；**双重验证 PASS**：① 全 demo 109 万移动点
  bbox 落图 5%-95%；② 出生点锚实测 T(0.474,**0.923**)/CT(0.433,**0.217**) vs
  radar_info T(**0.93**)/CT(**0.22**) —— y 翻转校准正确（K4 教训落实）。地图分析页 anubis
  chip 已渲染雷达底图+路线。
- **小件 2 — compare 雷达空箱提示**：未选人时显示"勾选上方选手以叠加生涯雷达"。
- 验收截图 `output/.visual/n_galaxy.png / n_anubis.png / n_compare_hint.png`。

## 11. 给新对话的第一步建议

1. 读本文件 §0-§2（Phase L 全貌）、§7 的「5E 五排数据洞察」
2. `git status` 确认待审改动还在（Phase L 一批）；`git log` 若出现新 commit 说明用户已批准提交
3. Phase L 全部完成——下一步候选见 §9 未来路线
4. 任何 commit 前重读 §0 铁律 1 与铁律 5（路由注册顺序）

## 12. Phase S —— 稳定化（2026-09-05，计划已批准，分批执行）

用户令："全面审计并整改一次 + 视觉检验 + 架构检验 + 稳定化开发计划；找出开发到中途、太分散的地方。"
用户三裁决：**补全收藏备注/标签编辑器 / 全部清理磁盘残留 / 先推送再稳定化**（4 提交已推送 origin/main）。

### 审计（四路深度 + 视觉巡检）
- **视觉**：22+ 页 playwright 巡检（含 6 tab 逐个点击、fun-lab/compare/matches 交互、900px 窄视口）
  零 console 错误、零 4xx/5xx；生涯页"Jake"高光=同 steamid 曾用名（非 bug）。
- **P0 三项**：① routes T/CT 切换串台（charts.js merge 残留，10/25 场不对称可触发，实测复现）；
  ② funlab 抢人头/被抢人头跨生命误归因；③ funlab.norm_weapon 与真实武器名脱节
  （M4A1-S/USP-S 排除出发枪链、WMPVP awp_rate 恒 0、Tec-9 等连字符名漏计）。
- **架构**：app.py 身份过载（8 数据模块反向 import）、analysis→web 越层、常客判定 3 份、
  eco/force 阈值 4 处、换边逻辑 3 份、fetchJson ≥3 变体、悬空 placeholder 机制/悬空 API、
  warmup 失效后再冷阻塞 ~70s、async upload 阻塞事件循环、_kill_feed 双跑、/report 绕过 memo、
  funlab _scan_all 锁外竞态、收藏非原子写、pyproject 漏 uvicorn+scipy。
- **工程**：文档漂移（HANDOFF 双 10/双 3、GOALS 占位页、funlab-metrics 32→31、README 189、
  ARCHITECTURE studio 幽灵）；孤儿缓存 test_demo（25 缓存 vs 24 demo）；_probe5e 991MB。

### 批次与完成状态
- **S0 推送** ✅（938e01e→5b457d6，remote 更名 cs-demo-analyzer 已同步）
- **S1 数据/磁盘卫生** ✅：孤儿缓存删除+`_stale_cache_sweep` 双向对账（stale 重解析+孤儿 GC，
  demos/ 空时跳过防误删）；output 残渣清理（~1GB：_probe5e/991MB + 82 个探针脚本/旧图 +
  孤儿 web/{hash}/radar|pref|studio + aggregate 旧图）；batch_jobs/system 轮询失败终止（任务丢失/连败 5 停）；
  **+4 测试**（孤儿 GC 四场景）。
- **S2 前端修复+收藏编辑器** ✅：routes P0（mount() 按 dom dispose 旧实例+instances 去重）；
  tab 懒加载竞态（空 forEach→真 resize）；XSS 收口（新建 static/js/common.js 全局 esc/fetchJson，
  match_detail/highlights/player_career/compare 全部转义）；**收藏编辑器**（favorites.js 内联浮层
  备注textarea+标签输入+保存；match 详情页头独立星标挂载点 data-fav-standalone；/favorites 备注区
  可编辑+标签徽章；collectMeta 从 data-fav-meta-* 读展示名）——API 的 patch note/tags 首次有 UI 消费；
  compare 假 sortable 移除；table_sort.js 补 ?v=；上传防重（禁按钮+客户端 .dem 校验）；
  player_career picker 空串守卫+热力图 dispose；pollJob 补 r.ok。E2E：routes CT=3 PASS、
  收藏 round-trip PASS、零 console 错误。
- **S3 分析正确性（口径不变，实现对齐）** ✅：武器归一统一 `analysis/weapons.py`
  （canonical 增强：5e_/5Ex 段剥离+_txz/_vip/_ace 后缀+连字符别名，实库 164 名 100% 覆盖；
  web/weapons.py 变薄适配层；aim/kill_context/weapon_splits 改 import analysis——越层消除）；
  生命窗口（funlab.life_span 助手，抢人头/被抢人头均限本生命）；发枪成材率回合末截断；
  首杀统一（basic_stats 排自杀+窗口 <=）；economy 换边统一 round_player_sides+clean_sid；
  preference 弃 MR12 硬编码；ratings KAST trade 补队友复仇校验+无死亡回合只给上场者；
  funlab 分母改出场回合数；FORCE_MAX/常客单源（analysis.regulars.compute_regulars 三处收敛）；
  economy buy n=0 返 None；**+3 测试**（跨生命/归一/发枪回合边界）。数值变化见 docs v6。
- **S4 架构收敛** ✅：`web/runtime.py` 门面（8 数据模块不再 import app——解环第一步）；
  `_demo_context`/`_kill_feed`/`_kill_groups` 下沉 `web/match_data.py`（_kill_feed 双跑修复，
  app.py 1351→~1130 行）；`/report/{h}` 下沉 `web/report_data.py` 复用 memo；upload 改 sync def；
  funlab _scan_all 锁内 double-checked（修复过程中发现并修复重入死锁）；invalidate_aggregate
  清 _analysis_cache/_module_cache + warmup.kick()（失效后再冷走骨架，kick 有 ready 守卫防测试风暴）；
  favorites/ui-prefs 原子写（tmp+os.replace）+ui-prefs 加锁；未找到页真 404（4 处+测试同步）；
  economy.json 下发 thresholds（模板 $2000/$3700 硬编码退役）；删 _PLACEHOLDER_PAGES 机制+
  placeholder.html+悬空 /api/meta/weapons.json；system_import 失效出循环；
  **test_scan_demo_real 改 tmp 缓存**（真凶：它每次跑测试都往真实 .cache 重建 test_demo 孤儿）。
- **S5 卫生+文档** ✅：CSS 死类（.upload/.progress 全套/.stat-unit/legacy .ovp-*/video{}/.grid img，
  保留 .ovp-label/.ovp-phase-val）；pyproject 补 uvicorn/scipy/starlette+pytest-timeout+package-data；
  HANDOFF 编号修复（3a/11）+§1 刷新+本节；GOALS/README/funlab-metrics v6 同步；
  （dev_log/ARCHITECTURE studio 清理在收尾批）。

### S 里程碑状态
- 239 测试全绿；真实缓存 24 条（孤儿 GC 验证不反弹）；routes/收藏/上传 E2E PASS。
- ✅ 收尾项已全部随 S 提交完成（ARCHITECTURE studio 删除、dev_log Phase S 条目、
  test_stabilize 补测 cli/maps-loader/warmup 失败分支、22 页巡检复跑、分批提交）。

## 13. Phase T —— 性能与工程底座（2026-09-06，完成待审）

**长周期路线图**（用户四问四答拍板，见批准计划）：主航道 = T 性能底座 → U 分析强化
（Rating 2.1 对齐 / 武器持有时间线 / 控图 v2 解冻）→ V 竞技 AI（回合胜负概率 / 经济 EV /
风格星系迭代，被动积累样本分阶段）；发布线（gh-pages）与内容生产（GIF 导出）继续冻结；
大阶段制；验收形态 = 平台内新功能网页。

### T1 聚合快照落盘 ✅
- **`web/snapshots.py`（新，~370 行）**：8 个跨场 memo（aggregate/feed/teamplay/utilitylab/
  map/lineups/funlab_scan/style_map）的 payload 持久化到 `output/web/snapshots/<name>.json`
  （原子写 tmp+os.replace，favorites 同款）。指纹 = SHA256(SNAPSHOT_VERSION + PARSER_VERSION
  + **producer 源码内容摘要**（22 个 .py，口径修复自动失效）+ 逐 demo model.json 内容哈希)。
  **design rules**：只由预热线程在成功重建后落盘（请求路径零 IO）；invalidate 不删文件
  （指纹失配即惰性失效）；单文件损坏=单项 miss 不传染。
- **warmup 两波**：第 1 波 dashboard 五 memo（快照命中则跳过）→ ready；第 2 波专题页
  （map/lineups/stylemap）+ 二次 save_all（8/8 补齐）。`/api/warmup.json` 新增
  `snapshot_hits`/`snapshot_saved`；`/api/system/status.json` 新增 `snapshots` 清单 +
  `warmup` 状态。
- **8 个 memo 模块各带 snapshot pair**（`_snapshot_payload`/`restore_snapshot`）；
  aggregate 走 dataclass asdict↔重建（属性全派生零损失）；funlab 是 scan 层快照
  （set↔sorted-list 编解码），report 合并保持内存内。
- **/system 性能面板**（模板新增 section）：快照 N/N 有效 · 指纹前缀 · 本次预热秒数 ·
  逐快照状态/大小/落盘时间表 + 操作说明（可随时删除自动重建）。
- **验收**：快照命中重启 ready **5.2s**（基线 175s）；进程内 restore_all **0.068s**（8 文件）。

### T2 进程池实测与决策 ✅ ADOPT（-53.5% 实测 → 实库 -58%）
- **`scripts/bench_process_pool.py`**：serial/thread4/proc4 三场景。**关键实测**：
  ① ParsedDemo 跨进程 pickle 回传 **MemoryError**（ticks ~30MB/场）→ 唯一可行设计 =
  worker 内加载+分析、只回传小载荷；② worker 内计算 thread4 31.8s vs proc4 14.8s。
- **落地**：`Settings.scan_executor`（默认 `thread`；`configs/default.yaml` 置 `process`，
  **测试经 conftest 钉死默认值**——套件 42s→14s）；`library.scan_demos_proc` +
  `scan_hashes_proc`（子集版，T3 用），**BrokenProcessPool 自动降级线程池**（实测触发过：
  探针无 `__main__` 守卫 → spawn 重导入 → 降级后结果逐字段一致，降级链路被实证）。
- **接入三重头**：aggregate（worker 返回 shard dict 形态）/ feed（highlights）/ funlab。
  process vs thread 全库一致验收：178 玩家/24 demo **field_mismatches=[]**，
  25.1s vs **10.5s**。
- 全量重算（wipe 快照）基线：**201s → 131s（-35%）**；aggregate 单 memo 10s。
- **注意**：Windows spawn 会重新导入 `__main__`——任何新探针脚本必须带
  `if __name__ == "__main__"` 守卫（本轮踩过）。

### T3 分片增量 ✅（aggregate/feed/funlab 三重头 + GC）
- **shard API**（snapshots.py）：`shards/<memo>/<src8>/<demo_hash>_<model8>.json`——
  src8=源码摘要（代码变→整目录作废 GC 清）、model8=model.json 哈希（重解析→自动 miss）。
  **分片有效性与库指纹无关**：新 demo 到来，旧 23 场分片照常命中。
- **memo 改造**：compute 先 `load_shards` → 只对 missing 走 `scan_hashes[_proc]` →
  `save_shard` 回写 → 按当前库 sorted-hash 全量合并（合并顺序=旧契约，输出逐字段一致）。
  aggregate 的 per-demo 形态统一为 shard dict（process worker / 线程 / 落盘一份序列化）。
- `invalidate_aggregate` 尾部挂 `gc_shards`（孤儿分片清理，fail-soft）。
- **验收（探针）**：冷建分片 9.5-9.8s → 全热合并 **0.08-0.19s** → **+1 demo 增量 1.9-2.0s（5×）**；
  模拟新 demo 后 total_demos+1、清理还原验证通过。
- **范围裁决**：teamplay 的扫描封装在 `analysis.teamplay` 内部（CLI+web 共用），接分片要动
  analysis API——本轮跳过，utilitylab/mapdata/lineups 三小 memo 同为后续小件（模式已定型，
  照 feed 抄即可）。

### T4 收尾 ✅
- `scripts/bench_startup.py`（冷启动基准：8123 专用端口，--wipe-snapshots 对照场景，
  JSON 落盘 `output/bench_*.json`）。
- /system 性能面板 + `visual_check` 22 页复跑 FAILURES: none + playwright 截图
  `output/.visual/t1_system_perf.png`/`t_final_system.png` read_image 人工复核通过。
- 测试 239→**261**（test_snapshots.py 16 项 + test_process_scan.py 2 项 + 稳定化补丁）；
  全量 14s（thread 钉死后无 spawn）。
- **test_stabilize 两个 warmup 测试改为封闭式**（monkeypatch restore_all/save_all）——
  真实快照文件存在时，快照命中会让被 stub 的步骤跳过、error 路径不再触发（本轮踩过并修复）。
- **⚠️ 重大回归教训（本轮抓到并修复）**：T3 重构把 `_feed_from_demo` 的 `runtime` import
  丢了——线程路径 NameError 被 scan_demos 的 fail-soft 吞成**空 feed**，而 process worker
  路径正常（warmup 走 process）→ **线上 200 条高光掩盖了线程路径全坏**；原测试只断言
  `_feed is not None` 也照样绿。三重修复：① 修 import；② ruff F821 进验收清单
  （未定义名=真 bug；仓库其余 ~84 条 ruff 为存量基线）；③ test_feed 增加**直接调用线程路径
  fn** 的回归断言（异常会响，空列表是 1 杀合成 demo 的合法结果）。**教训：fail-soft +
  双执行路径 + 弱断言 = 静默坏死三角**，"worker/线程双路径"改造必须每条路径有直达测试。

### T 遗留（后续小件，非阻塞）
1. teamplay/utilitylab/mapdata/lineups 接入分片（模式照 feed 抄）
2. `bench_startup.py` 增量场景尚未脚本化（本轮用探针手工验证）
3. `library_fingerprint` 的源码摘要每次进程启动读 22 个文件（<50ms，可接受）

### T 里程碑状态
- **261 测试全绿；22 页巡检零失败；快照命中 ready 5.2s；重算 131s；增量 5×**。
- 待办：分批提交（等用户批准 + provenance）。**U 阶段（Rating 2.1 → 武器时间线 → 控图 v2）
  是下一个大阶段**，V 阶段（胜势曲线 → 经济 EV → 星系迭代）随样本积累跟进。
