# 交接文档 (HANDOFF)

> 给下一个开发 agent 的交接说明。目标：10 分钟内了解项目状态、运行环境、待审改动、开发计划与所有坑。**最后更新：2026-09-07（Phase X 信息架构重组完成——单行三簇导航 + 深度合并 fun-lab/utility-lab + 遗留小件清账，待审+待验收）**

## 0. ⚠️ 铁律（先读这个）

1. **未经用户在对话里明确说"批准提交"，绝不执行 `git commit`**。计划文档/milestone/ExitPlanMode 批准都不构成提交授权（2026-08-30 用户申斥确立）。每次 commit 前问两件事：① 是否批准 ② provenance（`Origin: ai:<model>-<agent>`，模型随会话变必须每次问；历史值见 §8）。
2. 跑 Python 一律用显式路径 `"D:\Program Files\Python311\python.exe"`（bash PATH 的 `python` 指向失效的 enve/ venv）。
2b. **pip 装包可能清掉本机既有依赖**（2026-09-03 实证：`pip install pydantic` 后 pyyaml/fastapi/uvicorn/greenlet 全消失）——装完立刻 `pip install -e ".[dev]"` 恢复，并用 `python -c "import uvicorn, fastapi, yaml"` 自检。
3. **agent 可以读图片**：`read_image` 工具直接读 PNG/JPEG/WebP/GIF（2026-08-30 实证可用，旧"read 是纯文本"限制已失效）。视觉验收优先：playwright 截图 → read_image 亲眼看；像素采样断言仅作程序化补充。
4. 异常一律记录到 HANDOFF §7 与 dev_log，不分轻重。
5. **FastAPI 路由注册顺序**：`/{placeholder}` 通配路由在 app.py 中部注册——任何新的单段页面路由必须注册在它**之前**（L2 的 /utility-lab 曾被遮蔽 404）。

## 1. 项目状态摘要

CsDemoAnalyzer：本地优先 CS2 demo 分析平台（解析 `.dem` → 定量统计 + 电竞 OB 级 2D 实时回放）。FastAPI + Jinja2 全中文 SSR + canvas 回放器 + vendored ECharts。**当前 24 个 demo 在库、303 测试全绿、visual_check 22 页零 console 错误、accept_buttons 13 步零失败**。

**Git 状态（Phase X 完成待审）**：origin/main = `acfb704`（Phase W 已提交推送）。
**Phase X 信息架构重组已完成**——单行三簇导航（对象/洞察/工具）、/fun-lab 与
/utility-lab 深度合并退役（301）、五排协同迁 /teams、/report 入口补链+导出防泄漏、
遗留小件清账（utilitylab/mapdata 分片化、V1 跨场 LOO、V3 阈值客户端化），明细见 §17。
**工作区待审，等用户验收 + provenance**。

- **Phase X 一句话**：13 一级页 → 10 + 链接卫生 + 遗留性能/科学性小件全清，303 测试。
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

- **demos/**：**35 个 .dem = 19 完美平台 WMPVP（`9205...`~`9221...` 数字节名，provider=perfect_world）+ 16 个 5E（`g161-2026082x...`，2026-08-25~09-03）**（Phase Y 更新）
- **缓存**：`.cache/` 35 条，全部 parser_version 1.8.0（Y 批 11 场随导入即解析）
- **地图**：8 张有官方雷达资源（Y 补 de_vertigo，K4 五链路验证）；`de_nuke` 为双层图（用上层 primary radar，下层按 x/y 投影）
- **平台源目录**（沉淀于 `configs/demo_sources.yaml`，未来自动扫描的锚点）：
  - 完美：`C:\Users\35311\AppData\Roaming\Wmpvp\demo` —— **已清空**：19 zip 全部按内层哈希去重验证后移入回收站（8 个与库内容字节一致 + 11 个已导入）
  - 5E：`C:\Users\35311\AppData\Roaming\5E对战平台\demo` —— 6 个 zip **全部 EOCD 截断损坏**（4 旧账 + 2 新截断）——用户若从 5E 客户端重新下载可补入
- **批量导入**：`scripts/platform_import.py`（扫平台 zip → 内层 dem 内容哈希去重 → 导入 demos/；`--dry-run` 预览；坏 zip 容错跳过）
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

## 14. Phase D —— 职业选手数据集（2026-09-06 启动，D1 侦察完成）

用户令：下载职业选手（s1mple/m0NESY/donk 等）**天梯 demo 优先**做参照数据集；
一次性做到尾。规模拍板：先 30 场验证再扩容；D 盘余 57.6GB。

### D1 通道侦察结论（2026-09-06 实测）

| 通道 | 状态 | 细节 |
|---|---|---|
| **FACEIT open API** | 🟡 **需免费 API key** | `open.faceit.com/data/v4`：无 key=403；假 key=400 `invalid_token`（key 有效即可用：players→history→matches→`demo_url` 直链 FACEIT CDN，社区下载器 Bl4CkGuuN/FACEIT-Demo-Downloader 证实此协议）。key 在 faceit.com 开发者页免费注册即得 |
| HLTV | 🔴 403 | Cloudflare 拦截，UA/sec-ch-ua/Referer/代理全试皆 403；mirror 站也 403/302 |
| **bo3.gg** | 🟡 **元数据真实、demo 文件已删** | API 完全公开无鉴权：`matches?sort=-start_date`、`matches/{slug}`（含 match_maps）、`matches/{slug}/games/{de_map}`（真实 players_stats/game_rounds/**steam64 配对**）、`games/{id}/players_stats`（ZywOo=76561198113666193 等全部选手 steam64）。但 `demo_url` 指向的 CDN 子域 DNS 全灭（cdn/static/demos.bo3.gg 不解析），`bo3.gg/{demo_url}` 返回 SPA HTML 非文件——**2020 至今所有抽样 demo 文件本体均已不可下载**；desc 列表只暴露 10 场 2026-11/12 未来占位赛（parsed=waiting） |
| Valve MM | 🔴 不可行 | 职业选手的 MM sharecode 无法获取（只能本人账号） |
| Leetify/csstats/scope.gg | 🔴 无公开 demo 直链 | |

**结论**：demo 文件本体唯一可行通道 = **FACEIT open API + 免费 key**。bo3.gg 虽拿不到
demo 文件，但其**公开统计 API（含职业选手 steam64、逐图逐回合数据）可直接做职业基准
参照数据**（无需 demo 文件）——D3 可双轨：demo 文件（等 key）/ bo3 统计聚合（立即可做）。

### D 阶段待用户输入
1. **FACEIT API key**（用户到 faceit.com → Developers 免费注册 App 即得；或提供已有 key）
2. key 到位前：D3 改用 bo3.gg 统计 API 做职业基准（无需 demo 文件），U/V 不受影响

### D2/D3 完成状态（2026-09-06，key 未到，双线落地）
- **D2a 下载器框架** ✅：`scripts/pro_fetch.py`（FACEIT open API 协议：players→history→
  matches→demo_url 直链；幂等 + parse-check 门 + manifest.json + 限速）——**等 key 即用**，
  无 key 时 exit 2 并提示注册路径
- **D3a 统计基准采集器** ✅：`scripts/pro_baseline.py` → `output/pro_baseline.json`。
  坑：bo3.gg 对非浏览器 UA 返回字面 `null`（反爬）；数字 id 端点有长冷却（by-slug 才稳）；
  限速触发后 `null` 持续 ~1 分钟（脚本内置 8s 间隔 + null 三次退避重试）。三人数据已入库：
  s1mple 711 场 / m0NESY 839 场 / donk 795 场，各 9-10 图逐图拆分（rating/avg_kills/avg_damage）
  + accuracy（爆头率）+ 六月均分
- **D3b 职业基准卡** ✅：`web/pro_baseline_data.py`（mtime 感知读取）+ `/api/pro-baseline.json`
  + /compare 新"职业基准参照"区块（三人卡：场次/K-D/近期图池 ADR 带）。
  **口径诚实**：bo3 评分与本地 demo 统计非同一标尺，卡片只做参照带不做跨尺排名

## 15. Phase U/V —— 分析强化与竞技 AI（2026-09-06，一次到底全部完成）

### U1 Rating 2.1 对齐 ✅
- **公式核实**（web archive）：HLTV 新闻 40051 "Introducing Rating 2.1"（Wayback 快照）——
  2.1 是 2.0 的口径修正而非新公式：KAST 保枪规则（败回合无 K/A 的存活不计 KAST）、
  败回合存活在 survival 子评分降权、CS2 助攻 26 伤（原 41）加成上调、均值回 1.00（实测漂移 1.06）。
  混合常数沿用 HLTV 2017 公开的 2.0 blend（0.0073/0.3591/0.5329/0.2372/0.0032/0.1587）。
- **`analysis/ratings21.py`**：KAST21 重算（败回合 save 规则）+ Impact 助攻 1.25× +
  DPR 存活折半 + 1/1.06 再校准；result 带 rounds_total（回合加权）。
  **注册坑**：新模块必须加进 runner.py 的 import 清单，否则 run_one 报
  "failed to produce a result"（本轮踩过）。
- 展示：生涯页"场均 Rating 2.1"卡（2.0 对照 + 保枪回合数）+ KAST%(2.1)。
  实库：CCTV909 2.1=1.91 vs 2.0=2.02（保枪者降分方向正确）。

### U2 武器持有时间线 ✅
- **`analysis/weapon_timeline.py`**：active_weapon_name 逐 tick → 持有段（死亡分段）
  → 每武器持有时长/段数/击杀转化 + 每回合开局主武器（round_equips）。
  武器名用 `analysis.weapons.canonical` 归一（否则事件表 ak47 vs 展示名 AK-47 对不上，
  kills 恒 0——踩过）；is_alive=False 的 tick 必须参与遍历（作为分段边界），
  只遍历 alive 会把两段粘成一段（踩过）。
- API `/api/demo/{h}/analysis/weapon_timeline.json` + 战术 Tab"武器持有时间线"
  （ECharts custom series 每回合一格、按武器哈希取色、tooltip 带时长与击杀）。
  **custom series 坑**：data value 数组维度要与 encode 对齐（value=[yIdx, r-0.4, r+0.4] +
  encode x:[1,2] y:0）——第一版 value 只有 2 维导致渲染空白（踩过）。

### U3 控图算法 v2 ✅（解冻）
- viewer_control.js computeInstant 增三因子：**交战衰减**（新鲜击杀点半径 400u 内
  |field|×0.45，6s TTL 线性衰减）、**存活加权**（死亡 tick 强制分段+清场）、
  **密度去重**（|v|^0.72——3 人抱团不再 3×线性）。
- viewer_prefs 新"控图 v2"参数组（v2 开关/交战半径/衰减/存续/去重指数），
  canvas 侧 setFightProvider 从 D.events.kills 取 ≤TTL 的击杀点（attacker/victim 中点）。
- 验收：v2 开/关回合 13 对照截图（output/.visual/u3_v2_on/off.png）像素差 1.98%。

### V1 回合胜势曲线 ✅
- **`analysis/win_probability.py`**：逐事件快照（存活差/买法差/装备差/下包/回合计数）
  → **numpy 手写 logistic（L2）+ 特征标准化**（原始量纲梯度爆炸——未标准化时全 1.0，踩过）
  + 80% bootstrap 置信带。单场拟合；跨场 LOO 聚合列遗留小件。
- 实库 AUC **0.94**（184 快照）；API `/api/demo/{h}/analysis/win_probability.json`；
  概览 Tab"胜势曲线（实验）"：24 回合曲线 + 下包 pin 标记 + 击杀事件色点 + 置信带。
- AUC 排序用 average-rank（ties 平均）；测试覆盖 ties/单调性/可分数据三性质。

### V2 经济决策 EV 表 ✅
- **`analysis/economy_ev.py`**：决策状态（买法/方/比分差/连败≥2）→ 胜率+平均存活；
  **N<5 灰显铁律**（"1 局 100%"误导教训的制度化）。
- `web/ev_data.py` 跨库聚合 memo（invalidate 链挂入）+ `/api/ev/table.json`
  + 经济 Tab"决策 EV 查询表"（36 格实库：eco/force/full × T/CT × 比分 × 连败）。
  **UnboundLocalError 坑**：模块级 `_cells` 在函数内写前必须 `global` 声明（踩过）。

### V3 风格演变轨迹 ✅
- style_map._style_trajectories：funlab scan 按时间窗（5 场/窗）向量漂移 →
  同一 SVD 基投影 → 星系虚线轨迹 + 窗口节点 W1/W2…；漂移阈值 1.5·√k（29 维→8.1）。
- /fun-lab 星系"演变轨迹"开关（ECharts lines series **data 必须是 [{coords:[…]}] 每线一元素**
  ——写成分散 coord 会静默失败，踩过）；实库 4 人轨迹（CCTV909 5 窗）。

### U/V 里程碑状态
- **276 测试全绿**（261→276）；visual_check 22 页零失败（player_career 一次偶发超时复跑过）。
- 新 API：weapon_timeline / win_probability / economy_ev / ev/table / pro-baseline（路由在通配前）。
- 新文件：analysis/{ratings21,weapon_timeline,win_probability,economy_ev}.py、
  web/{pro_baseline_data,ev_data}.py、scripts/{pro_fetch,pro_baseline}.py、
  tests/{test_ratings21,test_weapon_timeline,test_win_probability,test_economy_ev}.py

### 遗留（下轮小件）→ **X 期已全部核销**
1. ~~D2b：30 场 FACEIT demo 下载~~（仍等用户 key；`scripts/pro_fetch.py --key ...` 即跑）
2. ~~V1 跨场 LOO 拟合~~ → `web/winprob_loo.py`（X4b，见 §17）
3. ~~V3 轨迹阈值做成 prefs~~ → 客户端 σ 滑杆（X4c，见 §17）

## 16. Phase W —— 高危交互全量审计与修复（2026-09-07）

**审计方法**：通读全部 68 条路由 + 15 个 JS 模块 + 8 类写盘路径，逐按钮
"前端 → API → 落盘/重算"链路核对；服务端合同整体健康（原子写/白名单/去重/GC
守卫均已有），缺陷集中在**前端状态机与少数后端口径**。

### 修复清单（F1-F12，全部带测试或验收断言）

| # | 缺陷 | 修复 |
|---|------|------|
| F1 P0 | `favorites.js` mountAll 在 doc fetch 返回前以空 doc 渲染并打 `data-fav-mounted=1`，**星标永不回显**（点按生效但刷新前全显 ☆） | mounted 标记只防重复插入；新增 `applyStars()` 在 doc 到达后刷新已挂载节点状态；POST 成功后 `applyLocal()` 同步内存 doc；失败 `.catch` 回滚乐观 UI |
| F2 P0 | funlab 筛选 chips 快速连点：并发 fetch 后发先至覆盖新数据，失败时 chip 与数据不一致 | fetchSeq 竞态守卫（旧响应丢弃）+ 失败回滚到 `applied`（最近成功筛选集）+ `__funlabDebug.state()` 验收钩子 |
| F3 P0 | `ev_data.py` `demo_rounds` 硬编码 0 → EV 表"本表 N=0"恒假 | per-demo 分片载荷携带 `rounds`，ev_table 按 SUM 聚合（实库 524）；surv=0 是合法存活率不再塌缩成 None；**顺手接入 ev_cells T3 分片**；docstring 失实描述修正 |
| F4 P0 | viewer_control seek 重建用当前 tick 的 fights 积分历史步骤，**未来击杀 age<0 反向放大控制场** | computeInstant 因果守卫 `ageRaw<0||>1 → skip`（正常播放路径不变） |
| F5 P0 | weapon_timeline API 秒数硬编码 /64（128-tick demo 虚大一倍） | 用 `demo.metadata.tick_rate`，响应附 `tick_rate` |
| F6 P1 | warmup.js hydration 失败无限 `location.reload()` 循环 | sessionStorage 计数，≥2 次失败停在骨架并显示指引 |
| F7 P1 | 同一 demo 并发解析无锁（双击一键入库/上传+导入竞态）→ 并发写同一 `<hash>/` 缓存目录 | app.py per-hash `threading.Lock` 注册表 + 临界区内二次 `cache.exists` 短路；测试证明 FakeManager.parse 恰跑 1 次 |
| F8 P1 | system.html 任务列表 `j.label`/`j.error`、compare.html pro 卡片未转义（外部文件名 XSS） | 统一 `CSACommon.esc` |
| F9 P1 | 报告导出无 in-flight 防抖（双击=双 chromium）+ 秒级时间戳同秒覆盖 | reports.js 按钮禁用；`_export_stamp()` 加 %f 毫秒（实盘证据：导出历史出现同秒 139514/567709 双文件共存）；list_exports stat() TOCTOU 包容 |
| F10 P1 | 上传仅前端拦非 .dem，craft POST 直接落盘 | `_save_upload` 服务端 `.dem` 校验（ValueError → 行内"只支持 .dem"错误，不落盘）；混合批次好文件不受阻 |
| F11 P2 | TaskManager._jobs 无限增长 | 超 200 淘汰最旧 done/error（running 不动） |
| F12 P2 | prefs"恢复默认"只改 localStorage，服务器残留旧值复活 | resetAll 后自动 `save()` 同步服务器 |

### 计划外命中（审计运行时发现）

- **player_career 卡 230s 冷访问**（U1 卡片首访全库 ratings21 同步扫描 + 3 个并发
  弃请求磁盘争用，45s 网关超时必炸）→ 双修复：① warmup wave2 增加 `rating21`
  步骤；② `_player_rating21` 改走 **rating21 T3 分片**（每 demo 一个小 JSON，
  24 分片读取 <1s）。实测 230s → **0.2s 首访 / 0s 复访**。
- `snapshots._SNAPSHOT_SOURCES` 补录 `web/ev_data.py`（载荷形状变更分片自动失效）。
- `_module_cache` 注释如实化（FIFO 非 LRU——避免后人误信）。
- EVCell.survived 注释与实现对齐（回合末存活率均值，非"败方存活"）。

### 验收（全绿）

- **pytest 286**（276→286：tests/test_phase_w.py 10 项：F3 分片往返/F5 tick_rate/
  F7 并发序列化/F9 时间戳/F10 双测/F11 淘汰/rating21 分片稳定性）。
- **visual_check 22 页 0 失败**；关键页 read_image 人工复核：match_detail（胜势
  曲线+雷达）、tab_economy（**本表 N=524** 实证 F3）、player_career（2.1 卡片）、
  fun_lab（星系+轨迹+榜单）、viewer（实时回放）、favorites、system（8/8 快照
  有效+预热 0.2s）、reports（F9 毫秒时间戳双导出共存实证）。
- **scripts/accept_buttons.py（新增）12 步全绿**：dashboard hydration、F1 星标
  跨刷新持久、备注往返、F12 保存/重置服务器同步、F4 因果守卫（未来击杀 0 影响+
  过去击杀有效）、F3 页面断言、F5 tick_rate、F2 连点筛选=applied、F9 单飞+
  恰 +1 导出、一键入库反馈、F10 上传门+任务生命周期、tabs/chips/视图切换。
  注意：脚本对"真实服务器+真库"运行（同 visual_check 前置），假 .dem 会走
  parse-error 路径，属预期断言。
- 全部 JS `node --check` 通过。

### W 期坑（新增）

1. **pwsh 直接调 `python -m uvicorn -RedirectStandardOutput` 会把参数透传给
   uvicorn**（"No such option '-R'"）——重定向是 Start-Process 的参数，必须
   `Start-Process -RedirectStandardOutput/-RedirectStandardError`（§4 规则的
   变体：uvicorn 必须 Start-Process 落盘日志）。
2. **acceptance 断言要区分"功能正确"与"计数守恒"**：导出 +1 断言首跑失败是
   因为上轮遗留导出已存在（before 计数漂移），不是 F9 失效；修脚本不修功能。
3. **doc() 空对象渲染竞态**是 Phase L1 以来的隐性 bug——乐观 UI 会掩盖"回显
   失效"类缺陷，验收必须含"刷新后状态仍在"步骤（F1 断言设计）。

### W 里程碑状态
- 286 测试全绿；22 页 visual_check 零失败；accept_buttons 12 步零失败。
- 新文件：`scripts/accept_buttons.py`、`tests/test_phase_w.py`。
- 改动面：web/{app,ev_data,report_export,tasks,snapshots,warmup,aggregation 无改}.py、
  analysis/economy_ev.py、static/js/{favorites,funlab,viewer_control,viewer_prefs,
  warmup,reports}.js、templates/{system,compare}.html。
- 残留未做（有意）：~~分片化推广到 teamplay/utilitylab/mapdata/lineups~~ → utilitylab/mapdata
  已在 §17 X4a 落地（teamplay 派生自分片 aggregate、lineups 只读 store，均无需分片）；
  CSRF/Auth 维持本地单用户边界（HANDOFF §13 已记录）。

## 17. Phase X —— 信息架构重组 + 遗留小件清账（2026-09-07，一次到底）

**背景**：用户要求全面重新梳理项目功能性与网页层级/跳转关系（"避免过多的网页导致
跳转杂乱不清晰"）。审计确认 10 项问题（P1 概念无家可归 3 项 / P2 层级导航 4 项 /
P3 入口链接卫生 3 项），用户拍板：**深度合并（C 档）+ 五排协同迁 /teams + 单行三簇
导航 + /与/matches 保持两页 + IA 与遗留小件一次做完 + system 精简保留**。

### 审计结论（修复前）

| # | 问题 | 证据 |
|---|------|------|
| 1 | 五排协同存在于 /compare 与 /teams 两页，两页互指 + utility 也指 compare | compare.html:119-202 / teams.html:10 |
| 2 | `/report/{hash}` 近乎孤儿页（唯一入口是 reports 页下拉选中后的预览链） | grep 全站 |
| 3 | /compare 一页 4 个不相干区块，身份混乱 | compare.html |
| 4 | 双导航分层标准不成立（收藏/报告混在"专题"，系统混在主导航） | base.html:24-43 |
| 5 | `/` 三个名字（仪表盘/Demo 库/对局库） | batch_jobs/error/index 文案 |
| 6 | system"专题工具"卡片区与次导航 1:1 重复且漏收藏/趣味 | system.html:40-50 |
| 7 | `/report/{hash}` 导航无高亮（active 只判 `=='/reports'`） | base.html:41 |
| 8 | 上传入口单一，matches 空状态却提示上传 | _upload_zone 仅 index |
| 9 | batch_jobs 站内链接走 legacy `/demo/*`（多一跳 301） | batch_jobs.html:26,50 |
| 10 | 专题页互链随开发顺序堆叠，无规则 | 各模板 page-actions |

### 目标 IA（13 一级页 → 10）

单行三簇导航：**品牌(→/) ｜ 对象：对局·选手·队伍 ｜ 洞察：高光·对比·地图 ｜ 工具：收藏·报告·系统**
（`/report/*` 现在正确高亮"报告"）。退役页全部 301（query 透传，`_redirect` 修了
"目标已带 query"的 `?`→`&` 拼接）：

- `/fun-lab` → `/players?tab=lab`（趣味实验室成为选手库第二个 tab，echarts+funlab.js
  **tab 首次激活才注入**——表格页不再付 1MB vendor；matrix 图同样只在总览 tab 可见时 mount）
- `/utility-lab` → `/map-analysis#utility`（道具专题整页并入地图分析；页级地图 chips 是
  唯一选择器，`csa:map-changed` 事件联动落点热力；两个 API 均保留，页面层组合）
- `/demo/*`、`/aggregate` 301 保留；batch_jobs/error 文案统一"首页"；batch 链接改 canonical `/match/`

### 跳转补链

- match_detail page-actions 新增 **"📄 打印报告"** → `/report/{hash}`；report 页新增
  no-print 工具栏（返回对局 / 导出 PNG-PDF → `/reports?demo={hash}`；reports.js 读
  `?demo=` 预选）；**导出器走 `?print=1`，模板按参数隐藏工具栏**（截图导出不泄漏工具栏，
  实测导出 PNG 干净）。
- compare 瘦身后 page-actions 加"五排协同 / 阵容 → /teams"；teams 删原指向 compare 的按钮。
- system"专题工具"4 卡 → **站点索引**（10 页全覆盖，含此前漏掉的收藏）。

### 五排协同迁家（X2）

HTML 区块 + 内联 IIFE 从 compare.html **整体迁入** teams.html + teams.js（esc 本地化）。
API：`/api/teams/teamplay.json` 为 canonical，`/api/compare/teamplay.json` 保留别名
（同 payload）。实现时核实：teamplay_data 派生自分片 aggregate → **无需再做分片**。

### 遗留小件清账（X4）

1. **X4a 分片化**：`utilitylab_data.py`、`mapdata.py` 重写为 ev_data 同款 T3 分片模式
   （memo 族 `utilitylab`/`mapdata`，per-demo 载荷，缺片才扫，GC 自动覆盖新 memo 目录）；
   T1 整页快照对保留（restore 播种合并 memo）。**lineups 不分片**（只读 store，
   T1 快照已覆盖冷启动）。
2. **X4b V1 跨场 LOO**：新 `web/winprob_loo.py`——留一场、其余场训练同款 numpy 逻辑回归、
   留出场算 rank-AUC（兑现 win_probability.py 文档里承诺多年的"LOO at web layer"）。
   per-demo 快照特征走分片（memo 族 `winloo`），LOO 拟合每次从分片重算（24 个小拟合 ≪1s）。
   **对局页用 `loo_peek` 只读暖 memo**（U1 教训：冷首访绝不同步扫全库），wave2 新增
   `winloo` 步骤后台物化；`/api/demo/{h}/analysis/win_probability.json` 响应加 `loo_auc` 键。
3. **X4c V3 阈值客户端化**：`style_map.py` 轨迹载荷加 `n_features`；funlab.js 星系区头
   σ 滑杆（1.0–3.0，localStorage `csa.trajSigma`），客户端按 `max_jump > σ·√k` 重着色
   （漂移=橙实线，稳定=紫虚线）；服务端 change_note 保持默认 1.5σ 不动 → **零快照失效**。

### X 期坑（新增）

1. **非重入锁死锁**：report 级 memo 的 `*_report()` 在持有 `_lock` 时调 `_build()`，
   `_build` 内 `_scan_all()` 冷路径再抢同一把 `threading.Lock` → 自死锁（表现为
   test_snapshots 挂死 5 分钟+）。修法：**先 `_scan_all()` 暖分片 memo，再进锁构建**
   （utilitylab/mapdata/winloo 三处同修）。fast path 不加锁所以暖后无竞争。
2. **`_redirect` 目标已带 query**（`/players?tab=lab`）时拼接出 `?…?…`——
   `_redirect` 改为按 `?` 有无选 `&`/`?`。
3. **导出截图 ≠ 打印**：`.rp-noprint` 的 `@media print` 只护 Ctrl+P，playwright
   `page.screenshot` 是 screen media——no-print 工具栏必须由**服务端 query 参数**隐藏。
4. pytest 收尾时 wave2 后台线程报 "cannot schedule new futures after interpreter
   shutdown"——预热线程与解释器关闭竞速的良性噪音（rating21 步同款），非失败。

### 验收（全绿）

- **pytest 303**（286→303：test_phase_x.py 17 项：301×2+query 透传、teamplay 别名、
  lab/utility/system 标记、utilitylab/mapdata/winloo 分片往返、LOO 合成可分数据 AUC>0.5、
  loo_peek 不触发计算、win_probability 响应形状、轨迹 n_features、batch canonical 链接；
  另修 test_web 导航断言与 test_funlab 页面断言到新 IA）。
- **死锁回归**：修复后 test_snapshots 0.86s（挂死→秒过）。
- **visual_check 22 页 0 失败**（fun_lab→players_lab、utility_lab→map_utility 换靶，
  补 report_match）；关键页 read_image 人工复核：仪表盘（三簇导航）、teams（五排协同
  整区渲染）、map_utility（道具区完整+落点热力随图）、players_lab（双 tab+星系 σ 滑杆
  +轨迹双色）、compare（瘦身）、report_match（工具栏）。
- **accept_buttons 13 步零失败**（新增第 13 步：/report 导航高亮 + 退役页 301 落点 +
  players?tab=lab 深链激活）。
- **实盘导出回归**：真库 PNG 导出成功且无工具栏泄漏（print=1 生效实证）。

### X 里程碑状态

- 测试 286→**303**；visual_check 22 页；accept_buttons 12→**13** 步。
- 新文件：`cs_analyzer/web/winprob_loo.py`、`tests/test_phase_x.py`。
- 退役模板：`fun_lab.html`、`utility_lab.html`（git 删除；URL 由 301 兜底）。
- 改动面：web/{app,snapshots,aggregation,warmup,mapdata,utilitylab_data,style_map,
  report_export}.py、static/js/{teams,funlab,utilitylab,map_analysis,reports}.js、
  static/style.css、templates/{base,index,matches,match_detail,compare,teams,
  map_analysis,players,system,report_match,batch_jobs,error}.html、
  scripts/{visual_check,accept_buttons}.py、tests/{test_web,test_funlab}.py。
- 待用户输入：D2b（FACEIT key，`scripts/pro_fetch.py --key ...` 即跑）。

### 17a. Phase Y —— 完美平台全量导入 + 去重清源（2026-09-07，随 X 同批待审）

**任务**：`C:\Users\35311\AppData\Roaming\Wmpvp\demo` 的 19 个 zip 按 5E 先例全部导入；
确认无损后删除重复；平台路径沉淀为配置。

**执行记录**：

1. **Y1 内层哈希去重（关键方法）**：zip 容器哈希 ≠ 内层 dem 哈希（压缩层，8/8 实证
   不同）——重合判定必须对 **zip 内层 .dem 流式 SHA256** vs demos/ 同名文件。8 个
   重合 zip 内层哈希 **8/8 与库内 .dem 字节一致** → 确认纯冗余副本（解析必然缓存命中）。
2. **Y2 导入**：新 `configs/demo_sources.yaml`（完美 + 5E 两平台源路径与注记）+
   新 `scripts/platform_import.py`（可复用批量导入器：扫 zip → 内层哈希去重 → 导入；
   坏 zip 容错跳过；`--dry-run`）。dry-run 精确（11 新 / 8 已存在 / 6 坏），正式导入 11 个
   新 .dem（~940MB），`/system/import` 一键入库 **11/11 解析 done**。
3. **Y3 验证**：库 24→**35**（perfect_world 8→**19**）；19 场 sanity 探针全 OK
   （10 玩家 / 16-24 回合 / tick 64 / match_id 正确）；新图 **de_vertigo** 按 K4 流程补
   雷达 PNG+yaml（MurkyYT contents API base64 下载），**五链路验证**：bbox 796380/796380
   入图、bomb_planted 实测落点（u≈0.23/v≈0.22 与 0.67-0.70/v≈0.57-0.60）与 radar_info
   包点图标（B 0.222/0.223、A 0.705/0.585）吻合、/maps 路由 200、回放器底图真实渲染
   （read_image 亲验）、零 console 错误；预热重建后 /system 未入库清零；仪表盘实证
   35 demo / 8 地图 / 756 回合 / 239 选手。
4. **Y4 删除**：19 个源 zip 全部 **移入回收站**（SendToRecycleBin，可恢复，非永久删除）；
   5E 目录 6 个截断坏 zip 按用户既有裁决保留；demos/ 解析文件一律未动。

**Y 期坑（新增）**：

1. **zip↔dem 哈希陷阱**：zip 容器（压缩+EOCD）与内层 dem 字节恒不同——任何"平台 zip
   是否已在库"的判断都必须解流内层文件再哈希，不能比容器。
2. demoparser2 的 `bomb_planted` 列名是 `user_X/user_Y`（plant 者位置），不是 `x/y`。
3. MurkyYT/cs2-map-icons 的 PNG 不在 raw  guesses 路径，走 `api.github.com contents
   images/radars/<m>_radar_psd.png` base64（K4 已记录，vertigo 复用同路）。

**状态**：库 35 场（19 完美 + 16 5E 名/valve 头）；新增 `scripts/platform_import.py`、
`configs/demo_sources.yaml`、`maps/data/de_vertigo.{png,yaml}`。未来小件：system 页
"扫描平台目录"按钮（复用 platform_import，配置锚点已就位）。

### 17b. Phase W2 —— X/Y 之后全量交互复审（2026-09-07，随 X/Y 同批待审）

**审计方法**：X/Y 改了导航壳/双 tab 懒加载/合并页/35 场库之后，重跑全部实盘验收
+ 新交互面专项探针（5 条此前无脚本覆盖的路径）+ 静态复查（17 模板 + 13 JS 的全部
事件绑定、legacy 残链 grep）。

**发现与修复**：

| # | 级别 | 发现 | 修复 |
|---|------|------|------|
| F-A | P1 | **players 页 echarts 重复注入**（探针实证 `script[src*=echarts.min]==2`）：`ensureLab`（lab tab）与 `mountMatrix`（总览 tab）各自独立注入 vendored echarts——lab→总览往返即双份，window.echarts 被初始化两次，先挂 chart 实例在新副本注册表查不到 → `activate()` 的 0×0 resize 静默失效，每路径多付 1MB | players.html `loadScript` 改 **promise 缓存版**（`loadScriptCache`），两路径共享，全页生命周期恰注入一次；accept 第 14 步锁死 `scripts===1` |
| F-B | P2 | `/reports` 预览链 href 平时 `#`，只在左键 click 瞬间赋值——**中键/Ctrl+点（新标签）拿到 #** 开空白页 | reports.js 新 `syncPreview()`：demos.json 到位与 change 时即同步 href；click handler 降级为兜底（无 hash 才 preventDefault） |
| F-C | P3 | `ensureLab` 脚本加载失败时标志已置位 → lab tab 会话内永久假死 | 失败分支回滚 `labLoaded=false`，下次激活自动重试；文案提示"切回再进可重试" |
| F-D | 验收基建 | visual_check 45s GOTO 超时对 35 场库偏紧（首跑 4 页瞬态超时，重试/整轮均过） | goto 90s + **每页自动重试一次**再判 FAIL |

**验收**：pytest 303→**305**（+2：players 共享加载器静态锁、reports.js syncPreview
静态锁）；探针 5/5 过（P1 往返单注入 + 三图非零尺寸、P2 预选+href、P3 σ 滑杆
persist/restore、P4 35 行表格/排序/卡片、P5 地图联动道具图）；visual_check **22 页
0 失败**；accept_buttons **16 步零失败**（新增 14-16：往返单注入/预选 href/σ 滑杆）。

**W2 期坑（新增）**：

1. **验收脚本 race**：click 切 tab 后 `sleep(2s)` 断言 DOM 状态会偶发竞态（P1 曾
   假报"panel did not hide"，MutationObserver stakeout 证明行为正确）——交互断言
   一律 `wait_for_function` 轮询，禁止固定 sleep 后断言。
2. **波次重建撞车**：Y 导入 11 场 + X 代码变更使分片 src-digest 变更 → wave2 需要
   重算 30 个 rating21 + 35 个 winloo 分片（in-process CPU）；此时首个 career 页请求
   同步等 `_rating21_shards` 冷路径 → 单次 241s（非回归：重建完成后 0.02-0.03s）。
   与 W 期 U1 地雷同类，但触发条件是"代码变更/导入后未等 wave2 结束"——重演概率低，
   已在 §17 记录；后续可考虑 rating21 冷路径也走 kick-only（本期不动，避免范围膨胀）。

**W2 里程碑状态**：测试 303→305；accept_buttons 13→16 步；visual_check 22 页。
改动面：templates/players.html、static/js/reports.js、scripts/{visual_check,
accept_buttons}.py、tests/test_phase_x.py。

### 17c. Phase Y2 —— 平台维度 + donor 榜每场化（2026-09-07，随批次待审）

**用户两问**：① "刚传了完美平台数据怎么日期还是旧的？"——19 个完美场根本不在
日期体系里（CS2 demo 头无日期字段（实证 12 键）、WMPVP 文件名是纯序号、mtime=下载
时间不可用作比赛日期；日期筛选只认 5E 文件名内嵌日期）；且 5E match_id 内嵌日期前缀
（2.0e22）恒大于完美纯序号（9.2e18），排序上完美场永远沉底，加重"旧日期"错觉。
② donor 榜绝对值违反总原则。**用户裁决**：实验室+对局库加平台维度（徽章+标注，
不做假日期）；donor 改每场均值。

**落地**：

1. **平台一等维度**：`store.platform_of(filename)`（g161- → five_e / 数字名 →
   perfect_world；provider 元数据不可靠——5E demo 头是标准 SourceTV="valve"）；
   list_demos 每行加 `platform`；funlab `funlab_report(stack, dates, platform)`
   过滤 + `platform_counts` 下发 + API `?platform=` 白名单参数；前端 lab 平台 chips
   （全部·35/完美·19/5E·16）进 F2 竞态守卫集。
2. **互斥语义**：选平台=完美时**禁用**排型/日期 chips（排型基于 5E 常客、日期仅 5E，
   组合会产生误导性空态），自动清空对应筛选。
3. **徽章**：`_match_card.html`（仪表盘+对局库卡片）与 matches 表格"平台"列
   （原样显示 provider "valve"——误导，已换徽章）渲染 5E/完美 徽章（.badge.fe/.pw，
   中性色）；对局库 page-meta 注明"完美平台场无日期信息，按平台序号时序排列"。
4. **donor 每场化（v7）**：`drops_value_per_demo = Σ发枪价值 ÷ 场次` 排序，绝对值
   进行内括号"（共 X$）"（舔包王先例）；BOARD_DEFS 更新；docs/funlab-metrics.md
   升 v7（含日期边界的数据事实记录）。

**验收**：pytest 305→**307**（+2：平台过滤三态/未知值回退、donor per-demo 排序
语义 B 总额 9000>A 8000 但均值 1125<4000 → A 先）；accept_buttons 16 步零失败；
Y2 探针 3/3（chips 过滤+互斥禁用+计数徽章 / donor 每场+括号 / 徽章 16+19 实证）；
截图人工复核（donor 榜与筛选行）。快照零失效（platform 过滤在 merge 层，scan 层未动）。

**Y2 里程碑状态**：测试 305→307。改动面：web/{store,app,funlab_data}.py、
static/js/funlab.js、static/style.css、templates/{players,_match_card,matches}.html、
docs/funlab-metrics.md、tests/test_funlab.py。
