# 视频管线能力归档（video pipeline archive）

> **状态**：已退役（2026-08-24，Phase E）。本管线的渲染代码已删除；本文档是唯一存档，
> 作用有二：(1) 记录被删能力的完整清单与质量评估依据；(2) 作为把视觉模板移植到
> canvas 回放器时的**参数规格来源**（颜色/尺寸/时序均从此处查）。
>
> 替代者：实时回放器 `cs_analyzer/web/static/viewer_canvas.js`（Phase C，用户验收基准）
> + ECharts 定量图表（Phase E/M6）+ viewer-data v2 数据包。

## 1. 质量评估（结论：低，删除）

| 维度 | 事实 | 依据 |
|---|---|---|
| 渲染耗时 | 整场预渲染 ~6 min 原始 / ~3.5 min 加速后（仅 640×360@20）；studio 单clip ~25s 低画质 | dev_log 2026-08-13 |
| 逻辑重复 | 特效/轨迹/HUD 逻辑在 replay_animation / team_animation / effects 三处重复实现；现由 timeline.py + viewer_data.py + viewer_canvas.js 单点承接 | 仓库结构 |
| 依赖负担 | 硬依赖 ffmpeg（PATH 探测+rcParams 注入）；manim 仅用于雷达视频且单支成片 ~93s 时长渲染数分钟 | export/video.py、render/radar_chart.py |
| 交互性 | 只能按预渲染 segment seek，无任意拖拽/倍速即时生效 | replay_map.py legacy 流程 |
| 维护状态 | Phase C 起冻结迭代，配方系统（recipe.py+recipes.yaml）为渲染器服务的间接层不再有价值 | HANDOFF §8 |

## 2. 能力目录（被删模块 → 能力）

| 模块（已删） | 行数 | 能力 | 移植去向 |
|---|---|---|---|
| render/replay_animation.py | 547 | 单人动画回放 all/highlights/openings/overlap-full 四模式；段数学 _build_segments/_opening_windows/_full_windows；hold-and-fade | viewer 深链 ?round=&t= 取代 openings/overlap 模式 |
| render/team_animation.py | 660 | 10 人同图回放+逐回合/全场路径 overlay；尸体、halo、团队 HUD、死亡线变灰 | viewer 主层已有 10 人+尸体；overlay 模式被深链取代 |
| render/effects.py | 501 | 全部道具/战斗特效池（§3 规格表） | **M4 移植目标（viewer_overlays.js）** |
| render/hud.py | 133 | HUD 文本池：玩家名/阵营徽章/K-D/比分/回合/时钟/事件流 | viewer DOM OB 面板已更好；击杀流挂件 M4 补 |
| render/radar_chart.py | 661 | manim 雷达统计视频（标题卡→维度卡→逐选手入场→尾卡） | ECharts 静态雷达（M6）取代 |
| render/image_utils.py | 58 | PIL 圆形裁剪/透明度（manim 用） | 不移植 |
| render/fonts.py | 62 | matplotlib CJK 字体注册+断言 | 不移植（无 matplotlib 残留后） |
| export/video.py | 179 | ffmpeg 合成：背景视频循环+brightness/contrast+NVENC+BGM mux | 不移植 |
| utils/ffmpeg.py | 35 | ffmpeg 发现（PATH+oopz 目录） | 不移植 |
| recipe.py + configs/recipes.yaml | 163+ | 8 配方声明式渲染（kind/mode/speed/style→ReplayConfig 扁平覆盖） | 不移植（viewer 即时交互取代配方） |
| batch.py + csa run/batch | — | 批量雷达+合成流水线 | 不移植 |
| cli: render/export/replay/action-map | — | 各视频/静态图命令 | 不移植 |
| web /studio×3 页 + /api/studio/* + /api/demo/{h}/replay + /api/demo/{h}/replay-map | — | 视频导出工作台 | 不移植（canvas 录制若将来要做另立计划） |

## 3. 移植规格：参数/色板/时序总表

> 来源：config.py ReplayConfig（L100-218）、effects.py（L25-111）、hud.py（L13-14, L41-50）。
> canvas 侧 Phase C 已自带的分歧值一并记录，注明"以哪边为准"。

### 3.1 特效生命周期（游戏秒）

| 特效 | 时长 | 备注 |
|---|---|---|
| smoke 区域 | 18.0 | v2 改用真实时长 dur_s（smokegrenade_expired 实体匹配），18s 为默认回退 |
| fire 区域 | 7.0 | 同上，inferno_expire 匹配 |
| flash 爆闪 | 2.0 | |
| HE 冲击环 | 1.0 | |
| 击杀连线组 | 1.2 | 金线+★+☠ 整组渐隐 |
| 死亡标记 | 1.0 | |
| 跳跃环 | 0.4（环扩散 0.6s） | |
| 枪声标记 | shot_frames=1 帧 | M4 改 ~0.12s 游戏时间 |

### 3.2 尺寸（像素半径，matplotlib 输出空间）

| 元素 | 半径/尺寸 | canvas 换算 |
|---|---|---|
| smoke 最大半径 | 120（grow 1.0s，末段 fade 2.5s） | world 半径换算 px-per-world-unit = map.width/(max_x−min_x) |
| flash | 130×(0.7+0.3·prog) | |
| HE | 85×(0.5+0.5·prog) 描边环 lw3 | |
| fire | 50×(0.8+0.2·rampup) | |
| 弹道点 | size 4，path alpha 0.8 lw2 | |
| trail | 窗 1.5s(单人)/1.2s(团队)，6 段，宽 1.2→3.5，alpha .15→1，瞬移断线阈值 300 world units | viewer 已用 1.2s 窗 |
| 玩家点 | ms 9 黑边；halo 白环 r20 lw2.5 z10 | viewer 已有 dot r5.5+yaw fan |

### 3.3 颜色

| 类别 | 值 |
|---|---|
| smoke 云 | #AAAAAA（多层 alpha .30/.26/.22/.24/.18 × RADIIS[1,.85,.7,.95,.75]，offsets RandomState(7) spread .45，首层居中） |
| flash | #FFFFFF |
| HE/molly | #FF8800 |
| fire | #FF6600 |
| 弹道线 | smoke #9E9E9E / flash #FFFFFF / he·molly #FF8800 / fire #FF6600 |
| 枪声/跳跃环/击杀线 | #FFD700 |
| 死亡标记 | #FF3333；受害者 X #FF6666 |
| 死亡线变灰（团队 overlay） | #7A7A7A |
| T palette | ["#FFD54F","#FFB300","#FF8F00","#FF7043","#F4511E"]（暖系五阶） |
| CT palette | ["#81D4FA","#29B6F6","#00BCD4","#0288D1","#1565C0"]（冷系五阶）；canvas CT_PALETTE slot-2=#3d9bff 分歧——**区域类以 config 族为准，玩家标记沿用 canvas 现值** |
| 历史遗留 | effects.py `_SIDE_T #FF6B6B`/`_SIDE_CT #4ECDC4`（action_map 时代，不移植） |

### 3.4 结构性规则

- **弹道飞行窗端点排他** `[throw_tick, land_tick)`——落点瞬间切区域特效
- 枪声标记 z 序低于轨迹（开火闪光不得遮挡路径）
- 烟雾 offsets/fire phases 用固定种子 RNG（RandomState(7)/RandomState(11)）保证确定性渲染
- HUD feed 文案：`击杀 {victim} ({weapon})` / `{name} 投掷了{烟雾|闪光|手雷|燃烧弹}`；窗口 12s 上限 5 条
- nade flight seconds 反推投掷起点：smoke 2.0s、其余 1.5s
- 胜方横幅 "T/CT 获胜"，round_end hold 1.2s 内显示并整体淡出

## 4. 明确不移植

- manim 雷达视频（ECharts 静态雷达取代）
- bg/music 背景合成（VideoExportConfig/NVENC/BGM mux）
- openings/overlap 蒙太奇模式（viewer 深链 `?round=N&t=S` + 自由 seek 取代）
- ffmpeg 合成链路

## 5. 存活代码指针

- `cs_analyzer/replay/timeline.py` — build_timeline / Utility/Kill/Shot / UTILITY_END_TABLES 真实时长实体匹配 / _reconstruct_throw 投掷起点反推（M3 viewer-data v2 复用）
- `cs_analyzer/maps/loader.py` — MapResource.world_to_pixel / load_map_or_fallback
