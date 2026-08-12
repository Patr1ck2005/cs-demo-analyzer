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

### LTG-1 [A通道] 内容生产终极成品视频 —— 当前优先
- **成品**：用真实群友对局 .dem 产出一部 1080p 成片 = 标题 + 雷达图轮播 + 回放高光片段 + 背景/BGM 合成，可直接发社交平台
- **同时验证**：5 层全链路（解析/分析/渲染/导出）+ 2D 回放系统 + 合成导出
- **数据源**：WMPVP zip ×6（`C:\Users\35311\AppData\Roaming\Wmpvp\demo\`，约 600MB，zip 内直接是 .dem），主打 `9206943388297116556_0.dem`（de_mirage，⚡女帝⚡ 34杀46道具）
- **里程碑**：
  - M1 全量 zip 解压 + 解析跑通 + 覆盖度记录（含异常，交给 LTG-3）✅
  - M2 选定主打对局/选手 + 产出雷达图轮播片段 + 回放高光片段 ✅（回放配方系统已交付，雷达片段待做）
  - M3 合成终极视频（bg+BGM+标题），交付验收 ⏳
- **状态**：🟡 进行中

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
- **成品**：本地 Web 平台（FastAPI）
  - 阶段1 单场复盘：上传 demo → 交互查看统计/雷达图/回放/偏好，选手可切换，全中文
  - 阶段2 多场聚合：选手跨场雷达矩阵、团队对比、回合胜率趋势
- **同时验证**：后端 + 前端 + 缓存 + batch 编排 + 聚合分析
- **验收**：浏览器操作录屏/截图 + 真人在浏览器点一遍
- **状态**：⏸ 待 LTG-1 之后

### LTG-3 [地基] 解析工具集扎实化 —— 贯穿性
- **成品**：全部真实 demo 的解析+回放覆盖度报告（哪些 demo/玩家/异常、Team 0 玩家研究、庄小蔥类玩家回放可行性）
- **同时验证**：解析层全部路径 + 缓存版本管理 + 异常记录体系
- **节奏**：随 LTG-1/2 持续推进，优先保证解析可靠（用户明确：这部分的工具集是最宝贵的）
- **状态**：🔄 进行中（随各 LTG 推进）

## 短期台阶（通往 LTG，agent 可验收）

- **STG-1 回放打磨**：用户提到的改进点 + 我列的候选——开局重叠路径应在回合前淡出、射击标记别遮挡轨迹、HUD 事件流加道具投掷、"开局重叠"时长按 opening 秒数而非固定 7s、HUD 侧别色反馈
- **STG-2 解析扩展**：更多 demo 类型覆盖、Team 0 / 庄小蔥类玩家数据缺失调查
- **STG-3 测试基建**：测试扩增覆盖所有新模块

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
