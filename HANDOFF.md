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
- HEAD = `e65f522`（Phase K 三连提交已获用户批准：K1 viewer 修复 / K3+K4+warmup 修复 / README GIF，
  provenance `Origin: ai:glm-5.3-flash-dsh`），**未推送** origin/main
- **工作区新一批"待审"改动（Phase K2+K5+K6 + K2 验收修复，尚未批准提交）**：
  - K2：`viewer_canvas.js`（模式切换器/回合网格/阵型曲线/聚类着色/偏差连线 + **验收修复两轮：① 手势守卫豁免
    .ov-controls（拖相位滑杆曾同时平移地图）/ 渲染签名跳过静止重绘 / 轨迹步长 3 / 相位条内播放键；
    ② 全局 `[hidden]{display:none!important}`（回放切重叠时 buy-strip 曾穿透——hidden 被 CSS display 覆盖）/
    半场切分改为换边语义 ovHalfGroupsOf（首发 T 方活体阵营多数，R1-R12 上半场，废弃 ceil(n/2)）**）、
    `replay_viewer.html`（重叠控制合并为单一 .ov-controls 栈——两栏结构性不再互相压盖 + ov-play 按钮）、
    `style.css`、`tests/test_web.py`（+K2 契约测试含守卫/播放键/[hidden]/半场断言 + LAYER_VERSION 哨兵 3）
  - K5：`analysis/teamplay.py`（新模块）、`web/teamplay_data.py`（新 memo）、`aggregation.py`
    （联动失效）、`app.py`（/api/compare/teamplay.json）、`compare.html`（五排协同卡）、`tests/test_teamplay.py`（+3）
  - K6：`HANDOFF.md`（状态+K5 报告）、`dev_log.md`（K 条目）
  - 验收截图在 `output/.visual/k2a_*.png / k2c_*.png / k2d_*.png / k2_half2.png / k5_tp_*.png`
  - 189 测试全绿；playwright 16 页零 console 错误（dashboard 冷启动 aggregate 需预热，memo 后正常）
  - 用户验收后建议拆两个 commit（K2 / K5+K6 文档），provenance 每次仍须问

**服务器**：uvicorn 跑在 127.0.0.1:8000（含全部 18 场缓存）。

## 2. Phase K —— 已全部完成（2026-08-30，待审+待验收）

计划全文见对话或 git 历史。**K1/K3/K4 已提交（e65f522 三连）**；**K2/K5/K6 完成在工作区待审**：

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

### K6 — 收尾（已完成）

- 全量 pytest **189 全绿**；`scripts/visual_check.py` 16 页零 console 错误
  （dashboard 冷启动 aggregate 预热 ~12s 为已知特性，memo 后正常）
- HANDOFF（本节+§7 报告）/ dev_log 同步；**提交前问用户批准 + provenance**

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
e65f522 docs: README overlap hero GIF                         ← Phase K 三连提交（已批准）
c4a5fc4 feat: 5E match-id recognition, three new maps, warmup-round segmentation fix
2c40f81 fix(viewer): overlap camera-follow regression + base-map sync timing
e839a1a docs: README visual overhaul + robust start_web.bat
60e47c9 feat: Phase I deep analytics engine + Phase J viewer/overlap polish
04e39a9 Phase G | 03c9eb4 Phase F | 933e9b1 Phase E | ...（更早见 git log）
```

Phase K 剩余工作（K2/K5/K6）完成后的待审改动见 §1。完整阶段日志见 dev_log.md（每个 Phase 一条，含模型名）。

## 9. 未来路线（Phase K 之后）

1. **占位页填充**：/utility-lab（烟中击杀/闪光价值载荷已就绪）、/map-analysis（aggregate per-map 分组）、/teams（队伍视图）、/favorites（收藏标注）、/reports（PDF/长图导出）
2. **在线发布**（用户拍板暂缓，方向已定）：`csa export-static` 静态快照导出 → gh-pages（只读分享版，上传/解析不存在）；**公开仓库 + steamid/昵称匿名化**；发布前 rename 仓库（现名 CS-Radar-Map-Generation 是早期项目名）
3. 控图算法 v2（视线/交战权重，用户暂缓中）
4. 更多地图 PNG（任何新地图：MurkyYT/cs2-map-icons + radar_info 公式，流程见 K4）
5. 可选：aim 模块接 inventory 做武器持有时间线；Rating 2.1；`_module_cache` 上限

## 10. 给新对话的第一步建议

1. 读本文件 §0-§2、§7 的「5E 五排数据洞察」
2. `git status` 确认待审改动还在（K2/K5/K6 一批）；`git log` 若出现新 commit 说明用户已批准提交
3. Phase K 全部完成——下一步候选见 §9 未来路线（占位页填充 / 在线发布 / 控图 v2）
4. 任何 commit 前重读 §0 铁律 1
