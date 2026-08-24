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

### LTG-2 [B+C通道合并] 本地 Web 平台 —— Phase F 完成（2026-08-24）
- **成品**：本地 Web 平台（FastAPI + Jinja2 SSR，全中文）——深色分析工具风
  - Demo 库：拖拽多文件上传 + 哈希去重 + 批量任务页 + 统计条 + 密集表格 + 行点击
  - 单场复盘：比分 hero + 可排序选手表 + ECharts 雷达 + 回合时间线（深链回放器）+ 击杀流（武器图标）+ **对枪矩阵/经济分析/道具效用/开局路线** 四个高级分析区块
  - 选手页：stat tiles + 个人雷达（本人高亮）+ ECharts 地图位置图（热力/道具落点叠加雷达 PNG）
  - 跨场聚合：ECharts Rating 矩阵/条形/趋势 + 可排序明细表
  - 实时回放器 v3：相机缩放平移 + 高级覆盖层（枪口焰/曳光/换弹弧）+ **弹药/换弹真数据**（demoparser2 0.42）+ 缩放 LOD（血量环/弹药数字/武器贴图徽章）+ **控图实时染色 + 伪 3D 视图** + 击杀流挂件（图标）+ 炸弹倒计时 + 深链
- **技术要点**：图表 = ECharts 本地 vendor；回放数据 = viewer-data v3 + layers v2；武器图标 = MIT 社区包 vendor + 三命名体系归一；控图 = 客户端高斯核 EMA（p95 0.2ms）；路线聚类 = 种子化 k-means（无 sklearn）
- **状态**：🟢 Phase F 完成（待提交，123 测试全绿）

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
