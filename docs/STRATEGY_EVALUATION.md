# Phase 05 — Strategy Evaluation 实现说明

## 1. 历史策略效果

`AnalyticsService.strategy` 读取 `policy.hit_count`（累计快照）与 `policy_evaluation.matched_policies`（明细），输出命中数、命中率、自动动作比例、人工审核比例。

**命中率不是准确率**：分母为有策略评估记录的消息数（当前 7 行），且没有人工标签，因此 Precision/Recall/F1 显示为不可计算。

## 2. 版本比较

`policy_version` 当前 47 行，全部为 v1，没有同一策略的多版本历史。因此不提供「历史版本效果对比」，页面明确显示不可用原因。替代方案是 Strategy Replay：在相同历史消息上比较两个策略配置。

## 3. Strategy Playground / Replay

### 输入
- 历史时间窗口（通过全局筛选器）
- 主数据集消息 + 每条消息最新 `risk_event`
- `message_label` 合成 ground truth（用于离线 FP/FN）
- 基线策略集：回放执行时刻的 active policy snapshots
- 候选配置：`action_overrides`、`priority_overrides`、`disabled_policies`、`version_overrides`

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

### 隔离保证
只读历史数据；不调用 enforcement；不发布 Kafka；不修改 `policy_decision`、`enforcement_action`；结果带 `simulation=true`。集成测试对回放前后正式表行数做了断言。

## 4. 影响分析分类

| 类别 | 含义 | 实现状态 |
|---|---|---|
| Observed Metrics | 历史实际记录 | Implemented（`strategy()`） |
| Replay Metrics | 同输入重放 | Implemented（`replay.compare()`） |
| Estimated Impact | 基于假设的推算 | Not Implemented（不做无依据推算） |

## 5. 实测回放

2026-11-25 在主数据集 2026-01 窗口执行 300 条样本，候选将 `gov-critical-risk-review` 动作从 `review` 改为 `block`：

| 结果 | 值 |
|---|---:|
| 样本数 | 300 |
| 基线命中 | 300 |
| 候选命中 | 300 |
| 动作变化 | 23 |
| 人工审核负载变化 | -23 |
| FP 变化 | 0 |
| FN 变化 | 0 |

该结果标记为 Simulation，不是线上干预效果。样本数低于 100 的回放会显示探索性结果提示。

## 6. 策略评估报告

`analytics-report --type policy_evaluation` 生成包含执行摘要、数据窗口、口径版本、限制与建议的 Markdown，并导出真实结果 CSV。系统不自动修改正式策略；优化需人工确认。
