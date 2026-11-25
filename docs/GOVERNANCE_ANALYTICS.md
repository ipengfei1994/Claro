# Phase 05 — Governance Analytics 实现说明

## 1. 实现范围

治理总览、决策动作分布、自动/人工分流、模拟处置统计、审核任务完成率与任务关闭耗时、审核结果分布、误杀/漏判数据边界提示、低样本门禁。

指标公式以 `docs/KPI_DEFINITIONS.md` 为唯一依据；当前口径版本 `phase-05.2`。

## 2. 数据来源与口径

| 分析项 | 表 | 口径 |
|---|---|---|
| 决策总量 | `policy_decision` | 按决策行计数；消息级统计用 `DISTINCT message_id` |
| 自动处置率 | `policy_decision` | `auto_decided / (auto_decided + human_reviewed + overridden)`，分母不足 30 时不发布数值 |
| 审核率 | `policy_decision` + `moderation_case` | 仅统计有决策状态的子集，显示样本量 |
| 推翻率 | `policy_decision` | `overridden / (human_reviewed + overridden)` |
| 任务关闭耗时 | `moderation_case` | `closed_at - opened_at`，仅 closed 任务 |
| 模拟处置 | `enforcement_action` | 全部 `simulated=true` |
| 检测层误杀/漏判 | `risk_event` × `message_label` | 全窗口混淆矩阵，见 `docs/RISK_ANALYTICS.md` §4.1 |
| 引擎观测混淆 | `risk_result` × `message_label` | 仅 3 样本，标记为不可解读 |

## 3. 低样本门禁（`phase-05.2` 新增）

`MIN_RATE_DENOMINATOR = 30`。分母低于该阈值时，比例不作为数值发布，而是返回：

```json
{
  "value": null,
  "numerator": 1,
  "denominator": 1,
  "sample_size": 1,
  "low_sample": true,
  "reason": "人工审核率 样本量 1 < 30，比例不可解读"
}
```

分母为 0 时 `reason` 为「分母为 0，不可计算」。

**为什么需要**：当前主数据集窗口内只有 1 条决策带真实 `decision_status`（其余 50,003 条为生成器 legacy 的 NULL）。修复前页面显示「自动处置率 0% / 人工审核率 100%」，读者无法分辨这是系统行为还是单样本噪声——这正是把 0/1 当成 0.0/1.0 的风险。门禁把「不可计算」显式说出来，而不是让读者误读。

## 4. 实测结果（2026-11-25）

- `policy_decision` 共 50,008 行，其中 50,003 行 `decision_status IS NULL`（生成器 legacy 记录）；有决策状态记录 5 行。
- 窗口内 `eligible_finalized_decisions = 1`：自动处置率与人工审核率均因样本量不足而显示「不可计算」（0/1 与 1/1），推翻率分母为 0。
- `moderation_case` 4,039 行，4,035 行已关闭，3 行 in_review，1 行 pending。
- 任务关闭耗时 P50 = 120 秒，P90 由 PostgreSQL `percentile_cont` 计算；这是合成任务数据，不是人工审核耗时。
- `moderation_review` 0 行：人工推翻率、审核耗时、模型-人工一致率均不可计算。
- `governance_feedback` 0 行：线上误杀/漏判不可计算。
- `enforcement_action` 1,208 行，其中 1,206 条 `message_block` executed、2 条 `mute` expired，全部模拟。

## 5. UI 行为

- 比例指标在分母为 0 或样本量不足时显示「不可计算」并附样本量与原因，不以 0 代替。
- 误杀/漏判分两层呈现：检测层混淆矩阵（有 50,000 样本，可解读）与引擎观测混淆（3 样本，明确标记不可解读）。
- 模拟处置表格明确标注 simulated 状态。
- 审核耗时文案明确区分「任务关闭耗时」与「人工审核耗时」。

## 6. 未实现

- 人工审核员维度分析（`reviewer_ref` 无数据）。
- 审核 SLA 超时分析（当前只有任务状态快照）。
- 真实处置执行（项目范围内仅模拟）。
- 基于真实人工标注的一致性 / 误杀 / 漏判（数据缺失，非实现缺陷）。
