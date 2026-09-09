# 研究台账（research ledger）——对战算法基准迭代

> **方法论**：baseline-driven iteration（基准驱动迭代）。冻结基线与评估协议 →
> 每轮一个假设 → 实现 → 同一协议测量 → 记账（含负结果）→ 接受或回滚。
> 连续两轮无改进 → 提议收尾稳定化。**口径铁律**：口径改动先送用户审核，批准后才写代码。

## 评估协议（冻结，2026-09-09，Round 1 起）

- **数据**：T3 分片载荷（winloo family = 模块产出的逐快照特征行 + 标签）——评估与页面消费同一份数据，永不漂移。
- **切分**：跨场留一（LOO）——训练集 = 其余全部场次的快照，评估 = 被留出场次。35 场小样本下唯一能回答"跨场泛化"的切分。
- **指标**：
  - `weighted_auc`：按快照数加权的逐场 AUC 均值（LOO memo 头条口径）；
  - `pooled_auc`：全部留一预测混池 rank-AUC；
  - `brier`：混池 Brier 分数（概率校准+分辨力的合成惩罚，越低越好）；
  - `logloss`：混池对数损失（clip 1e-6）；
  - `calibration`：固定十分位校准表（等宽 10% 桶：预测均值 vs 实际胜率——固定桶跨轮可比，分位桶会随模型漂移）。
- **执行**：`python scripts/research_eval.py`（输出 `output/research/eval_<ts>.json`，台账引用该文件）。
- **诚实边界**：无地图几何 → 无视线遮挡特征；64tick ±1 tick = ±15.6ms。

## Round 0 —— V1 基线冻结（2026-09-09）

**模型**：V1 逻辑回归，4 特征（alive_diff / buy_diff / equip_diff / planted），
单场 T 视角快照，L2=0.01，梯度 600 iters，特征内部标准化。

| 指标 | 值 |
|---|---|
| weighted_auc | **0.8168** |
| pooled_auc | 0.8217 |
| brier | **0.171** |
| logloss | 0.510 |
| 样本 | 35/35 场可评 · 6031 快照 |

校准（十分位）：整体贴合；`[0%,10%]` 桶预测 4.9% vs 实际 1.7%（n=418，极端桶略过自信），
`[70%,100%]` 三桶略欠自信（+2~3pt）。证据文件：`output/research/eval_20260909_034945.json`。

**V1 结构性缺陷（V2 假设来源）**：
1. `side` 特征恒为 1（全部快照 T 视角生成）→ 阵营不对称完全没学进去；
2. alive 只有差值，无绝对人数/存活质量（谁还活着比剩几个更重要的假设未检验）；
3. 无 HP/时间/道具/AWP/下包时长信息。

## Round 1 —— 胜率模型 V2（进行中）

**口径**（用户已批准，见计划送审表 A）：
12 特征：alive_diff、buy_diff、equip_diff、planted、plant_sec、elapsed_sec（**截断于名义时长 115s/加时 20s——防泄露**）、
hp_diff、awp_diff、util_diff、rating_diff（存活者 Rating21 和之差）、side（T=1/CT=0，**双侧视角建样**）、
alive_diff×planted 交互项。仍是纯 numpy 逻辑回归。

**页面语义**：曲线默认展示**跨场诚实曲线**（其余 34 场训练对本场的 OOS 预测，memo 暖时），
memo 冷时回退单场 in-sample 曲线并注明。OOS 曲线暂无逐点置信带（bootstrap 全池拟合实测成本超预算，台账记录，后续轮可再评估）。

**结果（协议实测，eval_20260909_044120.json）**：

| 指标 | V1 基线 | V2 | Δ |
|---|---|---|---|
| weighted_auc | 0.8168 | **0.8335** | **+1.7pt** |
| pooled_auc | 0.8217 | 0.8304 | +0.9pt |
| brier | 0.1710 | **0.1682** | −0.003 |
| logloss | 0.5100 | 0.5064 | −0.004 |
| 快照 | 6031 | 12770（双侧视角） | — |

校准：两端显著改善——`[0%,10%]` 桶 pred 5.4% vs obs 5.5%（基线 4.9% vs 1.7% 的过自信消失），
`[90%,100%]` 桶 pred 94.6% vs obs 94.5%。中段 `[70%,80%]` 仍有 +3.6pt 欠自信。

**裁决：接受**（AUC 与 Brier 同时改善，满足事前标准）。35/35 场全部可评。测试 343→**355** 全绿。

**实现记录**：
- `analysis/win_probability.py`：`FEATURE_NAMES` 12 特征定序（shard 行序契约）；`_TickState`
  （per-player 连续段 + searchsorted 单点状态查询）；`brier_score`/`decile_calibration`
  共享 helper（script 与 memo 单一事实源）；双侧视角快照生成，T 视角切片为页面曲线；
  `requires=("economy","ratings21")`。
- `web/winprob_loo.py`：payload v2（12 宽行 + sides/positions + meta + **形状守卫**
  拒绝 legacy 4 宽载荷）；`_build()` 保留逐场 OOS 预测（by_pos 键含 side，防 T/CT 同 tick
  覆盖）+ 混池 Brier/校准；`loo_memo_peek()` 只读全 memo。
- `web/app.py`：API 增加 `model`/`curve_source`/`brier`/`calibration` 字段；曲线 OOS 优先合并
  （p_win 替换、band 置 None），`note` 报告训练场数与留一 AUC。
- `web/snapshots.py`：`_SNAPSHOT_SOURCES` += `analysis/economy.py`（winloo 抽取的新依赖，
  S3-A1 缺口预防）。
- **修复**：重写 `_auc` 时丢失并列组步进 `i=j+1` → 任何并列预测死循环（pytest 挂起根因，
  已修复并注释）。教训：纯函数重构后先跑含并列的单元测试再进大流程。
- **观察（留给后续轮）**：本次 AUC 增益主要来自双侧视角建样 + alive 语义换血；未做逐特征
  消融——若后续轮需要归因，在 research_eval.py 加 `--ablate` 开关再测，本轮不扩协议。

## Round 2 —— 对枪胜率模型（首个诚实基线，2026-09-09）

**口径**（用户已批准的计划送审表 B）：每回合每对敌对玩家**首次伤害**建一条样本
（aim_science engagement 同源）；标签=本回合先死者归谁；**排除**：没死/同亡/
第三方打断（先死者凶手不在交战二人内）/超 15s 窗口。17 特征：距离（tick XY
平面距离——WMPVP `player_hurt` 无 distance 列的实证 fallback，游戏单位）、
血量差/护甲差、双方武器类别 one-hot（rifle 基线）、双方停/动、攻击方预瞄角
（aim_science 同款四候选视角校准）、受击方被闪（2.5s 窗口）、受击方视线朝向
（"被偷"代理）、首伤爆头、双方 Rating21、攻击方阵营。

**结果（协议实测，eval_20260909_061356.json）**：

| 指标 | 首测（061043） | 修复后（061356） |
|---|---|---|
| weighted_auc | 0.7483 | **0.8062** |
| brier | 0.1927 | **0.1527** |
| 判定样本 | 4296 | **5871** |

35/35 场可评。校准中段贴合（[40%,70%] 三桶 |pred−obs|≤5pt）。

**Round 2 的研究时刻（口径迭代留痕）**：首测排除计数暴露 `no_tick_state` 高达
2953/9116（32%）——排查发现**致命首伤**会在同 tick 把 victim 的 is_alive 翻成
False，整个"一枪毙命"类（最干净的 y=1 样本）被 alive 检查系统性排除。修复为
t0−1 重试后：样本 4296→5871，AUC +5.8pt，Brier −0.040。这就是基准迭代闭环的
价值：不做排除流分析，这个偏差会一直埋着。

排除流量（修复后）：判定 5871 / 第三方打断 1123 / 超窗 725 / 无 tick 态 1367
（Team 0 无 tick 玩家为主，§5.8 已知库层限制）/ 回合内无死亡 27 / 同亡 3。

**页面**：生涯页"🎯 对枪实力"块——对枪数 / 实际胜率（Wilson）/**模型期望**
（跨场留一 p，自己不在训练集）/**超预期差** = 实际−期望（EB 收缩 k=32 仅展示，
主值不缩）；<20 场灰显；诚实边界脚注（无视线遮挡判定，被偷≈受击方视线夹角）。
API `/api/duel-model.json(?player=)` peek-503；duelmo 分片族入失效链
（`analysis/duel_model.py` + `web/duel_data.py`）+ wave2 `_step_duelmo` +
family 映射锁 + warmup 桩清单同步。

**裁决：基线入账**（新模型无前置基线，如实记录 0.806/0.153 为 Round 2 起点）。
测试 355→**369**。

## Round 3 —— 假设迭代（2026-09-09）

**H-A（对枪 + 先开火特征）**：`att_fired_before`/`vic_fired_before` = 首伤前
3s 内（严格早于 t0）是否已开火（weapon_fire）。动机：先手开喷/压枪节奏 vs
干净首发的信息差。**结果（eval_duel_ha.json）：weighted AUC 0.8062→0.8063、
Brier 0.1527→0.1523——增益 ≈0，负结果。** 裁决：**不采纳进页面**（特征保留在
模块里零成本，但默认模型已无增益；台账照记负结果）。解读：先伤信息几乎完全
被"首伤时刻的预瞄角/停动/被闪"吸收——交战级谁赢在首伤瞬间已基本定型。

**H-B（胜率模型 rating_diff → 跨库生涯 Rating）——已验证，裁决：不采纳**：
去掉 per-demo rating_diff（--ablate 9）→ AUC 0.8335→0.8188（−1.5pt）；
换成跨库生涯 Rating（每场排除自身，rating21 分片轮加权，--rating-mode career）
→ **AUC 0.8177 / Brier 0.1754**（eval_winprob_career.json）。
结论：career 版 ≈ 完全去掉该特征（0.8188 vs 0.8177，差异在噪声内），而
per-demo 版比两者高 ~1.5pt。**per-demo rating_diff 的增量贡献基本来自
"本场内谁还活着"的状态信息（合规）+ 轻微的同场强弱编码（跨场视角下无泛化
价值）**。页面维持 per-demo 版（页面快照本来就是"本场视角"，不构成训练泄露
——泄露只发生在把同场信息喂进跨场训练集时，而 OOS 曲线的训练集是其它 34 场
的行，rating_diff 列本来就是各场自己的值，语义一致）。H-B 记负结果结案。

**Round 3 汇总**：两条预设假设全部验证完毕，均为负结果（H-A 增益 ≈0 已从
页面缺席，H-B 确认 per-demo 版就是正确口径）。基建沉淀：`--ablate`/
`--rating-mode` 消融开关 + winloo 分片 alive_keys（形状守卫同步）。
**连续两轮无改进 → 按预定规则触发收尾**：Round 3 记账后进入稳定化收尾
（全量测试/验收/文档），待用户批准提交。

**消融基建**：`research_eval.py --ablate <col>`（winloo 行 FEATURE_NAMES 序），
零分片重建成本——特征贡献归因从此是一句话的事。
