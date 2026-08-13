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

### LTG-1 [A通道] 内容生产终极成品视频 —— 已终止（用户 2026-08-13 取消 M3）
- **原成品**：用真实群友对局 .dem 产出一部 1080p 成片 = 标题 + 雷达图轮播 + 回放高光片段 + 背景/BGM 合成
- **里程碑**：
  - M1 全量 zip 解压 + 解析跑通 + 覆盖度记录 ✅
  - M2 选定主打对局/选手 + 回放配方系统 ✅（雷达图轮播片段未做）
  - M3 合成终极视频 —— **由用户取消**（"不需要这个视频了"），2D 回放系统仍是核心交付物
- **状态**：🟢 终止（M3 取消，回放系统已交付并打磨）

### 回放配方系统（LTG-1 内，用户 2026-08-13 敲定）
所有配方带投掷物（标配，无投掷物版本不做），自动去准备时间（round_freeze_end 起播）与死亡时间（单人存活窗口裁剪；团队尸体☠继续播）。死亡打 ☠。团队配色 T 黄系 / CT 蓝系。

**统一渲染配方框架**（2026-08-13）：配方在 `configs/recipes.yaml` 声明式定义，`csa recipe <demo> <名>` 统一渲染，`--override my_style.yaml` 细粒度覆盖任意视觉参数。样式分层 canvas/trail/marker/hud/team/effects，effects 含逐项开关（show_smoke/show_flash/...）+ 各类颜色/半径/时长。ReplayConfig 已细粒度化，渲染器全部读配置（不再硬编码）。低层 `csa replay --mode` 保留。

| 配方 | 统一入口 |
| :-- | :-- |
| S-单人全场重叠 | `csa recipe <demo> s-overlap-full` |
| S-单人开局重叠 30s | `csa recipe <demo> s-openings --player X` |
| S-单人高光 | `csa recipe <demo> s-highlights --player X` |
| T-10人全场记录(不重叠) | `csa recipe <demo> t-full` |
| T-10人高光 | `csa recipe <demo> t-highlights` |
| T-10人高亮单人 | `csa recipe <demo> t-highlight --player X` |
| T-10人逐回合重叠 | `csa recipe <demo> t-overlap-round` |
| T-10人全场重叠 | `csa recipe <demo> t-overlap-full` |

已删除：montage、S1 连续 15x、单人高光（换 t-highlight）。成品在 `output/replay_*`。

### LTG-2 [B+C通道合并] 本地 Web 平台
- **成品**：本地 Web 平台（FastAPI + Jinja2 服务端渲染，全中文）—— 已建成，待人工验收
  - 阶段1 单场复盘：`GET /` 列表 + 上传（后台解析任务+轮询）→ `/demo/{hash}` 比分/选手统计表/雷达图/回合时间线/击杀流 → `/demo/{hash}/player/{steamid}` 雷达/偏好（热力图/道具落点/风格）/回放（按需后台渲染 + `<video>`）
  - 阶段2 多场聚合：`/aggregate` 选手跨场 Rating 矩阵、T/CT 胜率、T 方得分趋势（按 steamid 匹配）
- **技术要点**：雷达图用 matplotlib 静态 PNG（`render/radar_static.py`，替代慢速 manim）；慢渲染走 `web/tasks.py` 线程任务管理器 + `/api/jobs/{id}` 轮询；`analysis/aggregate.py` 纯函数聚合
- **验收**：浏览器操作录屏/截图 + 真人在浏览器点一遍（服务器 `csa serve`，http://127.0.0.1:8000）
- **状态**：🟡 已建成，待人工全面验收（未提交 git）

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
