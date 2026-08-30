# 交接文档 (HANDOFF)

> 给下一个开发 agent 的交接说明。目标：10 分钟内了解项目状态、运行环境、待审改动、开发计划与所有坑。**最后更新：2026-08-30（Phase K 进行中）**

## 0. ⚠️ 铁律（先读这个）

1. **未经用户在对话里明确说"批准提交"，绝不执行 `git commit`**。计划文档/milestone/ExitPlanMode 批准都不构成提交授权（2026-08-30 用户申斥确立）。每次 commit 前问两件事：① 是否批准 ② provenance（`Origin: ai:<model>-<agent>`，模型随会话变必须每次问；历史值见 §8）。
2. 跑 Python 一律用显式路径 `"D:\Program Files\Python311\python.exe"`（bash PATH 的 `python` 指向失效的 enve/ venv）。
3. **agent 可以读图片**：`read_image` 工具直接读 PNG/JPEG/WebP/GIF（2026-08-30 实证可用，旧"read 是纯文本"限制已失效）。视觉验收优先：playwright 截图 → read_image 亲眼看；像素采样断言仅作程序化补充。
4. 异常一律记录到 HANDOFF §7 与 dev_log，不分轻重。

## 1. 项目状态摘要

CsDemoAnalyzer：本地优先 CS2 demo 分析平台（解析 `.dem` → 定量统计 + 电竞 OB 级 2D 实时回放）。FastAPI + Jinja2 全中文 SSR + canvas 回放器 + vendored ECharts。**当前 18 个 demo 在库、182 测试全绿**。

**Git 状态（关键）**：
- HEAD = `e839a1a`（README 视觉改造），**已推送** origin/main
- **工作区有一批"待审"改动（用户要求退回待审，尚未批准提交）**：
  - K1 修复：`viewer_canvas.js`（重叠镜头跟随回归 + 底图同步时序）
  - K3：`backend.py`（match_id 识别 5E `g161-<id>_` 形态）、`store.py`（match_key 双平台）、两个测试
  - K4：`de_nuke/de_dust2/de_cache` 三张新地图（各 PNG+yaml，共 6 个新文件）
  - **K4 验收阻塞修复（2026-08-30，用户报告"出生点不对"后定位）**：`backend.py` `_build_rounds`（warmup round_start 不抢占 starts_by_round + 跳过 warmup round_end）、`replay/timeline.py` `round_freeze_ends`（区间包含配对）、`viewer_data.py`（team0 原点行 alive=0）、`cache.py`（PARSER_VERSION **1.8.0**）、`viewer_data.py` 版本（VIEWER_DATA **4** / LAYER **3**）、3 个回归测试（185 全绿）。**5E demo 热身伪回合曾把回合 1 变成 43..12493（含 134s 热身）且所有回合 freeze_end 错位到上一回合**——t=0 显示热身期（9 人无数据行+1 人乱跑），被误认为地图校准错误。K4 校准实为无罪（落弹 A/B 双轴均落图标内）。18 demo 已全量重解析至 1.8.0 验证无回归
  - README.md + `docs/screenshots/overlap_hero.gif`（用户单独要求暂缓的重叠动画）
  - dev_log.md / HANDOFF.md（本次修复记录）
- 用户验收后建议拆三个 commit（K1 / K3+K4+warmup修复 / README+GIF），provenance 上次为 `ai:glm-5.3-flash-dsh`（每次仍须问）

**服务器**：uvicorn 跑在 127.0.0.1:8000（含全部 18 场缓存）。

## 2. Phase K 进行中 —— 剩余工作（新对话的主线任务）

计划全文见对话或按下面细节直接实施。K1/K3/K4 已完成（在工作区待审）；**剩 K2、K5、K6**：

### K2 — 重叠子模式 UI 显著化 + 高级分析（用户拍板全做）

当前重叠子模式（`viewer_canvas.js` 内，`?mode=overlap` 深链）只有：半场切换（state.ovHalf）、相位滑杆、轨迹/道具/击杀线/炸弹/ghost chips、聚焦变暗。要补：

- **K2e UI 显著化**：工具条「重叠」chip 升级为分段模式切换器 `[ 实时回放 | 回合重叠 ]`（工具条首位）；相位条（`.ov-phase-bar`，地图层内 bottom-center）重设计得更醒目
- **K2a 回合网格回归**：重叠模式加横向滚动回合条（旧独立页语义：胜方色角标 chips、单回合勾选/取消、空选=全部、全选/清空/前4 快捷）。需要 `state.ovRounds = new Set()` + `drawOverlapLayer` 按 Set 过滤 segs + 回合条 UI（数据源 `D.segments.winner_side`）。这是旧独立页有、合并时丢掉的功能
- **K2b 阵型指标相位曲线**：重叠模式下原时间轴区域（`#tl-wrap`，目前 hidden）改绘双线迷你图：全体散开度（平均两两距离 u）+ T/CT 重心间距；当前相位竖线与滑杆联动；用 canvas 手绘（别用 ECharts 每帧重渲），10 人 O(n²) 每帧可忽略
- **K2c 路线模式聚类着色**：对每回合开局段（相位 0~0.3 采样 6 点队伍重心轨迹）做纯 JS 小 k-means（k=2..3 肘点、固定种子、~40 行），「模式着色」chip 开启后回合条 chips + 轨迹描边按聚类着色（默认仍阵营色）
- **K2d 聚焦 vs 重心偏差**：聚焦时画该选手各回合相位位置 → 队伍重心的细连线（紫低透明）+ 相位条旁偏差读数（u 与米，1u≈0.019m）
- 验收：playwright 截图逐项人工检查 + JS 契约测试

### K5 — 13 场 5E 的「有趣结果」（用户拍板全做）

数据基础（已探明）：18 场缓存 = 9 WMPVP（更早，用户单排/小队）+ **9 场 5E 五排**（2026-08-25~28，g161-* 前缀）。跨场普查（已跑）：**CCTV909 16x（=用户本人，旧 WMPVP 场叫 Jake，改名了）**、FywOo6666 7x、杏愛 7x、FENNEL的YamZzi本人 4x、你的内脏变成了外脏 3x。**注意**：常客判定要用"5E 场内出现次数"单独统计（9 场里出现 ≥5 次的才是稳定五排；混入 WMPVP 会稀释）。

- **K5a 五排默契度网络**：跨场统计 assister→attacker 连接频次、补枪（trade=击杀者窗内被复仇，复用 ratings 的 TRADE_WINDOW 语义）、闪光助攻连接（player_death.assistedflash）。落点：`analysis/teamplay.py` 新模块（跨全部缓存 demo）+ `/compare` 页新增「五排协同」卡（矩阵热力 + Top 连线）+ HANDOFF 报告段落
- **K5b 五排 vs 混野**：同场出现 ≥4 常客 → 五排局；对比回合胜率/场均 Rating/首杀成功率。报告交付
- **K5c 五人跨场画像**：compare 分位（≥5 场门槛自动覆盖常客）+ 报告提炼标签（最稳残局/最猛首杀/最佳闪光手…）
- 报告写入 HANDOFF §7 新小节「5E 五排数据洞察」

### K6 — 收尾
- 全量 pytest + `scripts/visual_check.py`（含新地图与重叠新 UI 截图）
- HANDOFF/dev_log/README 同步；**提交前问用户批准 + provenance**

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
| Playwright | `scripts/visual_check.py`（16 页）；**沙箱可能拒绝其驱动进程管道创建**——提权或重试 |
| 本会话 shell | pwsh（无 bash）；python 输出偶发被管道吞——**重要结果写到文件再读** |
| 中文 .bat | **GBK + CRLF，禁 chcp 65001**（UTF-8 中文 + goto/call 标签定位会错位执行乱码；LF-only 也断） |
| pwsh 管道挂起 | bat 启动的孤儿 uvicorn 继承管道句柄 → `Start-Process -Wait` 永远等不到——测试用文件重定向 + 轮询状态，别 -Wait |

**探针脚本模式**（demoparser2 pyo3 会 Rust panic 杀进程，探针必须子进程隔离）：`scripts/probe_events.py`、`scripts/probe_ammo.py`。

## 5. 关键入口

```bash
"D:\Program Files\Python311\python.exe" -m pytest -q        # 185 全绿
"D:\Program Files\Python311\python.exe" -m uvicorn cs_analyzer.web.app:app --port 8000
scripts/visual_check.py                                      # playwright 16 页
scripts/probe_events.py                                      # 事件可用性探针（子进程隔离）
```

核心文件：
- 解析: `cs_analyzer/parser/backend.py`（`_MATCH_ID_PATTERNS` 双平台 match_id、`_empirical_tick_rate`、legacy 降级重试）, `manager.py`（tick_fields 含 inventory）
- 缓存: `cache.py`（PARSER_VERSION **1.7.0**）
- 分析: `cs_analyzer/analysis/`——13 模块（basic_stats/ratings/preference/duels/economy/utility_effect/routes/highlights + **kill_context/hitgroups/aim/postplant/weapon_splits**）+ **util.py**（`round_player_sides` 换边安全阵营）
- 回放前端: `static/viewer_canvas.js`（回放+重叠子模式+聚焦跟随+买装条）、`js/viewer_overlays.js`（事件覆盖层，SMOKE_SCALE=1.2）、`js/viewer_control.js`（控图/3D）、`js/viewer_prefs.js`（19 参数调节面板）、`js/viewer_camera.js`
- Web: `app.py`（路由 + `/analysis/{name}.json` × 9 + `_analyze_module` memo）、`chart_data.py`（载荷）、`viewer_data.py`（v3 数据包 + bombs 尾缝钳制）、`store.py`（match_key）、`aggregation.py`（memo）、`weapons.py`（武器单一事实源）
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

## 8. 提交历史（近期）

```
e839a1a docs: README visual overhaul + robust start_web.bat   ← 已推送 HEAD
60e47c9 feat: Phase I deep analytics engine + Phase J viewer/overlap polish
04e39a9 Phase G | 03c9eb4 Phase F | 933e9b1 Phase E | ...（更早见 git log）
```

工作区待审（§1）+ Phase K 剩余（§2）完成后，历史追加 Phase K 条目。完整阶段日志见 dev_log.md（每个 Phase 一条，含模型名）。

## 9. 未来路线（Phase K 之后）

1. **占位页填充**：/utility-lab（烟中击杀/闪光价值载荷已就绪）、/map-analysis（aggregate per-map 分组）、/teams（队伍视图）、/favorites（收藏标注）、/reports（PDF/长图导出）
2. **在线发布**（用户拍板暂缓，方向已定）：`csa export-static` 静态快照导出 → gh-pages（只读分享版，上传/解析不存在）；**公开仓库 + steamid/昵称匿名化**；发布前 rename 仓库（现名 CS-Radar-Map-Generation 是早期项目名）
3. 控图算法 v2（视线/交战权重，用户暂缓中）
4. 更多地图 PNG（任何新地图：MurkyYT/cs2-map-icons + radar_info 公式，流程见 K4）
5. 可选：aim 模块接 inventory 做武器持有时间线；Rating 2.1；`_module_cache` 上限

## 10. 给新对话的第一步建议

1. 读本文件 §0-§2
2. `git status` 确认待审改动还在（若用户已批准提交则 git log 会有新 commit）
3. 询问用户：继续 K2 重叠强化，还是先验收/提交已完成的 K1/K3/K4
4. 任何 commit 前重读 §0 铁律 1
