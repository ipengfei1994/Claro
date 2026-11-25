# Phase 05 — Governance Analytics 实现说明

## 1. 实现范围

治理总览、决策动作分布、自动/人工分流、模拟处置统计、审核任务完成率与任务关闭耗时、审核结果分布、误杀/漏判数据边界提示。

## 2. 数据来源与口径

| 分析项 | 表 | 口径 |
|---|---|---|
| 决策总量 | `policy_decision` | 按决策行计数；消息级统计用 `DISTINCT message_id` |
| 自动处置率 | `policy_decision` | `auto_decided / (auto_decided + human_reviewed + overridden)` |
| 审核率 | `policy_decision` + `moderation_case` | 仅统计有决策状态的子集，显示样本量 |
| 推翻率 | `policy_decision` | `overridden / (human_reviewed + overridden)` |
| 任务关闭耗时 | `moderation_case` | `closed_at - opened_at`，仅 closed 任务 |
| 模拟处置 | `enforcement_action` | 全部 `simulated=true` |

## 3. 实测结果（2026-11-25）

- `policy_decision` 共 50,008 行，其中 50,003 行 `decision_status IS NULL`（生成器 legacy 记录）；有决策状态记录 5 行。
- `moderation_case` 4,039 行，4,035 行已关闭，3 行 in_review，1 行 pending。
- 任务关闭耗时 P50 = 120 秒，P90 由 PostgreSQL `percentile_cont` 计算；这是合成任务数据，不是人工审核耗时。
- `moderation_review` 0 行：人工推翻率、审核耗时、模型-人工一致率均不可计算。
- `governance_feedback` 0 行：线上误杀/漏判不可计算。
- `enforcement_action` 1,208 行，其中 1,206 条 `message_block` executed、2 条 `mute` expired，全部模拟。

## 4. UI 行为

- 比例指标在分母为 0 时显示「—」，不以 0 代替。
- 误杀/漏判显示「不可计算」并说明缺少人工标签。
- 模拟处置表格明确标注 simulated 状态。
- 审核耗时文案明确区分「任务关闭耗时」与「人工审核耗时」。

## 5. 未实现

- 人工审核员维度分析（`reviewer_ref` 无数据）。
- 审核 SLA 超时分析（当前只有任务状态快照）。
- 真实处置执行（项目范围内仅模拟）。
