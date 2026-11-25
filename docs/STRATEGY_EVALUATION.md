# Phase 05 — Strategy Evaluation 实现说明

指标公式以 `docs/KPI_DEFINITIONS.md` 为唯一依据；当前口径版本 `phase-05.2`。

## 1. 核心原则：命中数不是效果

策略命中次数多、自动处罚多，**不代表治理效果越好**。一个把 32 条消息全部误判的策略，命中数远高于一个精准命中 17 条的策略。因此策略评估同时输出四个维度：

| 维度 | 回答的问题 |
|---|---|
| Precision（精确率） | 命中的消息里有多少真的是风险？ |
| Recall（召回率） | 真实风险里有多少被命中？ |
| FPR / FNR（误杀率 / 漏判率） | 代价在哪一侧？ |
| Manual Review Rate（人工审核占比） | 要付出多少人工审核成本？ |

命中数只作为规模参考，不参与质量排序。

## 2. 历史策略效果

`AnalyticsService.strategy` 读取 `policy_evaluation.matched_policies`（明细），按 `policy_key` 展开后逐策略计算：

- **分母隔离**：每条策略用自己的命中数作分母。修复前 `evaluated` 是 scope 级单行聚合，经 `LEFT JOIN evaluated e ON TRUE` 广播到全部 53 条策略行——实测三条比率列的 distinct 值均为 `{2}`，`automatic_action_rate` 恒为 `0.0`，是伪指标。
- **逐策略质量**（`SQL_POLICY_QUALITY`）：关联 `message_label` 真值，逐策略给出 TP / FP、Precision / Recall / F1 / FPR / FNR / 人工审核占比。
- **低样本门禁**：分母 < 30 时比率返回 `value=None` 并附样本量，不发布数值。
- **从不处置的策略**：返回 `acts_on_risk=false`，性能指标为 `null`。`gov-normal-allow` 这类只放行的策略没有检测性能可言，初版给出 `recall=0.0 / fnr=1.0` 会被误读为「漏判最严重的策略」。

**历史数据的覆盖限制**：`policy_evaluation` 当前仅 7 行、覆盖 2 条消息，因此历史命中率的分母极小，绝大多数策略的比率显示「不可计算」。策略质量的实质证据来自回放（§4），而非历史评估记录。

## 3. 版本比较

`policy_version` 当前 47 行，全部为 v1，没有同一策略的多版本历史。因此不提供「历史版本效果对比」，页面明确显示不可用原因。替代方案是 Strategy Replay：在相同历史消息上比较两个策略配置。

## 4. Strategy Playground / Replay

### 输入
- 历史时间窗口（通过全局筛选器）
- 窗口内**全部已标注消息**（含无风险事件的正常消息），每条取最新 `risk_event`
- `message_label` 合成 ground truth（用于离线 FP/FN）
- 基线策略集：回放执行时刻的 active policy snapshots
- 候选配置：`action_overrides`、`priority_overrides`、`disabled_policies`、`version_overrides`

### 样本池口径（`phase-05.2` 修正）

修复前样本池用 `INNER JOIN risk_event`，只取已被风险引擎标记的消息。每条消息预测必然为正，**TN 与 FN 结构性恒为 0，误杀率永远无法计算**——实测 `false_positive_rate` 恒为 1.0，是一个失真值。

修复后改为窗口内全部已标注消息（`LEFT JOIN`），无风险事件的消息以中性上下文（`risk_score=0`、`severity='normal'`）参与评估。经引擎行为探针确认，这类消息返回 `allow`，构成真正的真负例。

实测样本池（500 条样本）：`with_risk_event=83`、`without_risk_event=417`、`truth_positives=50`、`truth_negatives=450`。

### 执行
- 复用 `claro.governance.policy.evaluate_policies`，不重写策略引擎。
- 每次运行在固定 `now`（执行时刻）上评估两策略集，保证输入相同。
- 策略生效判断使用执行时刻而非消息发生时刻：当前策略创建于 2026-11-25，消息历史始于 2026-01-01，无法做历史时点重建。该参数写入 `analytics_replay_run.parameters`。
- `rate_count` 固定为 0，限流类策略回放不等同于线上实时行为。
- 消息内容只在内存中用于关键词/正则判定；落库的 `input_snapshot` 仅保存 content_hash 与结构化字段。

### 输出
逐条记录基线/候选动作、命中状态、差异类型、FP/FN，写入：
- `analytics_replay_run`
- `analytics_replay_case`

并按 `policy_key` 逐条归因写入 `parameters.baseline_policy_effectiveness` / `candidate_policy_effectiveness`，使回放从「两个策略集的总体对比」升级为「每条策略的质量对比」。

### 隔离保证
只读历史数据；不调用 enforcement；不发布 Kafka；不写 Redis；不修改 `policy_decision`、`enforcement_action`；结果带 `simulation=true`。

**隔离验证采用内容级指纹**：对 9 张业务表（`message`、`risk_event`、`risk_result`、`policy_decision`、`policy_evaluation`、`moderation_case`、`moderation_review`、`enforcement_action`、`governance_feedback`）逐行 `t::text` 做 SHA-256，回放前后比对全部一致。这比只比较行数更强——行数不变无法排除原地改写。已固化为集成测试 `test_replay_leaves_business_tables_byte_identical`。

### 指标语义约定

- **review 命中计入真阳**：策略匹配并送审 = 已识别（消耗了审核容量并拦截了消息），因此 `review_true_positives` 并入 TP。人工审核成本由独立的 Manual Review Rate 体现，不对同一动作惩罚两次。
- **混淆矩阵逐条推导**：由每条 case 的真值/预测标志推出 TP/FP/FN/TN，不使用命中计数反推。「命中」（策略是否被选中）与「预测为正」（动作是否非 `allow`）是两个不同概念，混用会静默污染误杀率。
- **`predicted_positive` 谓词**：动作非 `allow` 即为预测为正。

## 5. 影响分析分类

| 类别 | 含义 | 实现状态 |
|---|---|---|
| Observed Metrics | 历史实际记录 | Implemented（`strategy()`） |
| Replay Metrics | 同输入重放 | Implemented（`replay.compare()`） |
| Estimated Impact | 基于假设的推算 | Not Implemented（不做无依据推算） |

## 6. 实测回放

### 6.1 总体对比

2026-11-25 在主数据集 2026-01 窗口执行 500 条样本，候选将 `gov-critical-risk-review` 动作从 `review` 改为 `block`（run `f3c4162a`）：

| 结果 | 值 |
|---|---:|
| 样本数 | 500 |
| 基线命中 | 500 |
| 基线混淆矩阵 | TP=50, FP=37, FN=0, TN=413 |
| 基线 Precision / Recall / FPR | 0.574713 / 1.0 / 0.082222 |
| 动作变化 | 10 |
| 人工审核负载变化 | -10 |
| FP 变化 | 0 |
| FN 变化 | 0 |

该结果标记为 Simulation，不是线上干预效果。样本数低于 100 的回放会显示探索性结果提示。

### 6.2 逐策略效果（基线）

| 策略 | 命中 | TP | FP | Precision | Recall | 误杀率 | 漏判率 | 审核占比 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| gov-score-045-warn | 32 | 13 | 19 | 0.406 | 0.260 | 0.042 | 0.740 | 0.000 |
| gov-category-harassment-warn | 22 | 11 | 11 | 0.500 | 0.220 | 0.024 | 0.780 | 0.000 |
| gov-category-spam-flag | 17 | 12 | 5 | 0.706 | 0.240 | 0.011 | 0.760 | 0.000 |
| gov-score-070-review | 38 | 37 | 1 | 0.974 | 0.740 | 0.002 | 0.260 | 1.000 |
| gov-score-085-mute | 17 | 17 | 0 | 1.000 | 0.340 | 0.000 | 0.660 | 0.000 |
| gov-low-risk-observe | 9 | 0 | 9 | 0.000 | 0.000 | 0.020 | 1.000 | 0.000 |
| gov-keyword-cheat-tool | 10 | 3 | 7 | 0.300 | 0.060 | 0.016 | 0.940 | 0.000 |
| gov-normal-allow | 417 | — | — | — | — | — | — | `acts_on_risk=false` |

**这张表就是「命中多 ≠ 效果好」的证据**：

- 命中最多的 `gov-score-045-warn`（32 条）Precision 最低（0.406），漏判率 0.740；
- 命中仅 17 条的 `gov-category-spam-flag` Precision 达 0.706，比前者高 74%；
- 命中 38 条的 `gov-score-070-review` Precision 0.974，是本组最优——但它的代价是 100% 进人工审核队列；
- 反向也成立：`gov-low-risk-observe` 命中仅 9 条，但 Precision 0.000、漏判率 1.000，命中量小不代表质量好。

任何单一维度排序都不足以支撑治理决策，必须四维并列。

## 7. 策略评估报告

`analytics-report --type policy_evaluation` 生成包含执行摘要、数据窗口、口径版本、限制与建议的 Markdown，并导出真实结果 CSV。系统不自动修改正式策略；优化需人工确认。
