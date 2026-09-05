# GOALS（长期托管目标）

> 本文件是长期托管对话的验收标准锚点。每个长期目标 (LTG) 必须收尾成**人类可直接验收的成品**（视频/图片/网页，高信息量、同时验证多个模块的正确性）；短期目标 (STG) 是 agent 可验收的中途台阶（测试全绿、模块可用、数据落地）。**agent 自己能验证的结果不配当长期目标，只配当中途阶段。**
>
> 运行纪律：异常一律记录（不分轻重）；开局(opening) 与重叠(overlap) 是独立概念；解析工具集是最宝贵资产，一切建立其上。

## 分级原则

| 层级 | 收尾形态 | 谁验收 |
| :--- | :--- | :--- |
| **LTG 长期目标** | 视频 / 图片 / 网页，高信息量，一箭多雕验证多个模块 | 人类 |
| **STG 短期目标** | 测试全绿、模块可用、数据落地 | agent |

## 长期目标

### LTG-1 [A通道] 内容生产终极成品视频 —— 已终止并归档（用户 2026-08-13 取消 M3；Phase E 2026-08-24 删除管线）
- **原成品**：用真实群友对局 .dem 产出一部 1080p 成片 = 标题 + 雷达图轮播 + 回放高光片段 + 背景/BGM 合成
- **里程碑**：
  - M1 全量 zip 解压 + 解析跑通 + 覆盖度记录 ✅
  - M2 选定主打对局/选手 + 回放配方系统 ✅（雷达图轮播片段未做）
  - M3 合成终极视频 —— **由用户取消**（"不需要这个视频了"），2D 回放系统仍是核心交付物
- **状态**：🗄️ 归档（M3 取消；Phase E 删除 matplotlib/manim 视频管线与配方系统，参数规格归档于 `docs/video_pipeline_archive.md`；交互式回放器 + ECharts 取代）

### 回放配方系统（LTG-1 内）—— 已随管线归档（Phase E 2026-08-24）
配方系统（recipes.yaml + csa recipe）已删除。其视觉模板（道具弧线/多层烟雾云/火焰区/击杀连线/枪线/闪光/炸弹标记）已移植到 canvas 回放器覆盖层（`static/js/viewer_overlays.js`），参数规格见 `docs/video_pipeline_archive.md` §3。

### LTG-2 [B+C通道合并] 本地 Web 平台 —— Phase H 信息架构重写完成（2026-08-25）
- **成品**：本地 Web 平台（FastAPI + Jinja2 SSR，全中文）——"Violet Observatory" 电竞数据平台风 + 实体中心三区 IA
  - 信息架构：顶栏六链接（仪表盘/对局/选手/高光/对比/系统）；`/`=仪表盘（KPI+最近对局卡墙+上传+高光精选）；`/matches` 对局库双视图；`/match/{h}` 五 Tab 详情（概览/击杀/经济/道具/路线，?tab= 深链）；`/players` 选手库+`/player/{sid}` 跨场生涯页；`/highlights` 高光库；`/compare` 大数据对比（≥5 场门槛+全库分位+雷达叠加）；`/system` 系统页；5 个专题页（趣味数据/道具/地图/队伍/收藏，均已真实化）；旧 /demo/... URL 301 兼容
  - 设计系统：紫罗兰主强调（#a78bfa）+ 三字体体系（Inter/Rajdhani/JetBrains Mono 本地 vendor）+ 拉满展示级动效（全部 respects prefers-reduced-motion）
  - 数据管线：aggregation memo（single-flight+失效钩子）、highlights 模块（多杀/残局/ACE 事件推导）、compare 分位数、系统状态/未入库管理 API
  - 性能底座（Phase T 2026-09-06）：全库快照落盘（冷重启 175s→5.2s）+ 进程池扫描（重算 -35%）+ per-demo 分片增量（新 demo 5×）+ /system 性能面板
- **技术要点**：对比=大数据思想（个体 vs 大样本基线，非两两 PK）；viewer JS 双前缀契约（demo|match）+ 源码契约测试；API 路径全程零改动
- **状态**：🟢 Phase H 完成 + Phase T 性能底座完成（2026-09-06，工作区待审）

### LTG-3 [地基] 解析工具集扎实化 —— 已交付
- **成品**：`csa coverage` 扫描全部真实 demo → `output/coverage/coverage.html`（总览矩阵 + 逐 demo 明细 + 调查结论 + 已知限制，全中文高信息量）
- **Team 0 / 庄小蔥类玩家调查结论**：demoparser2 库层限制——WMPVP SourceTV 中个别玩家 pawn 实体无法解析（ticks + 所有事件位置全 NaN、is_alive 恒 False、逐广播特定，如 '杏愛' 一场可回放另一场不可），**不可修复/不可重建**；7/60 玩家位次受影响，事件类统计仍完整
- **同时验证**：解析层全部路径 + 缓存命中/耗时 + 异常记录 + 事件表覆盖矩阵
- **状态**：🟢 完成（判定逻辑沉淀在 `cs_analyzer/coverage.py` + `scripts/probe_team0.py`）

## 短期台阶（通往 LTG，agent 可验收）

- **STG-1 回放打磨** ✅ 完成——重叠类回合/结束淡出（`overlay_fade_seconds`）、射击标记 z-order 降到轨迹之下、HUD 事件流已含道具投掷（验证）、开局时长按 opening 秒数（验证）、HUD 侧别色反馈（T黄/CT蓝）
- **STG-2 解析扩展** ✅ 完成——Team 0 / 庄小蔥类玩家数据缺失调查（根因=demoparser2 库层 pawn 解析限制，见 LTG-3）；无更多 demo 类型可覆盖
- **STG-3 测试基建** ✅ 完成——覆盖 coverage/web/aggregate/radar_static/preference_charts/aggregate_charts/tasks/打磨项，113 测试全绿

## 数据源

| 源 | 位置 | 用途 |
| :--- | :--- | :--- |
| 真实对局 WMPVP | `C:\Users\35311\AppData\Roaming\Wmpvp\demo\` ×6 zip | LTG-1/2/3 主力数据（zip 内含 .dem，解压到 `demos/`，gitignore 已排除 `*.dem`） |
| 测试 demo Valve | `tutorial/demoparser/src/parser/test_demo.dem` | 快速回归 |

## 运营纪律

- 每次会话记录 agent 模型到 `dev_log.md`（`[YYYY-MM-DD HH:MM | Model: <name> | Task: <brief>]`）
- 每个 commit 末尾追加 `Origin:` trailer（来源分类 + 模型名，由用户确认）
- 异常一律记录到 HANDOFF §5 与记忆，不因"小"而漏记
- 经验教训沉淀到记忆 `lessons_*.md`
