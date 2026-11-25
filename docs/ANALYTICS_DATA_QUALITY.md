# Phase 05 — 分析数据质量

## 1. 检查框架

数据质量检查位于 `src/claro/analytics/quality.py`，由 `analytics-quality` CLI 与分析页脚注调用。
每项检查返回 `CheckResult(name, passed, severity, observed, expected, detail)`，不静默丢弃异常。

## 2. 检查项

| 类别 | 检查 | 实现 | 严重度 |
|---|---|---|---|
| 主键完整性 | 关键表主键非空且唯一 | `COUNT(*) - COUNT(DISTINCT id)` | error |
| 外键关联完整性 | `risk_event.message_id` → `message.id` 孤儿数 | LEFT JOIN / `IS NULL` | error |
| 外键关联完整性 | `policy_decision.message_id` → `message.id` 孤儿数 | LEFT JOIN | error |
| 外键关联完整性 | `enforcement_action.decision_id` → `policy_decision.id` 孤儿数 | LEFT JOIN | error |
| 关联记录缺失 | `policy_decision.policy_evaluation_id IS NULL` 比例 | 聚合计数 | warning |
| 关联记录缺失 | `moderation_case.decision_id IS NULL` 比例 | 聚合计数 | warning |
| 时间字段有效性 | `occurred_at IS NULL`、结束时间早于开始时间 | 条件计数 | error |
| 时间字段有效性 | 非闭任务 `closed_at < opened_at` | 条件计数 | error |
| 重复事件 | `risk_event` 同 `(message_id, rule_id, category, occurred_at)` 重复 | GROUP BY HAVING | warning |
| 重复事件 | `message.external_message_id` 重复 | 唯一索引 + 计数 | error |
| 缺失数据 | `moderation_review` / `governance_feedback` 行数为 0 | 行数检查 | warning |
| 异常值 | `risk_score`、`confidence` 超出 `[0,1]` | CheckConstraint + 查询复核 | error |
| 异常值 | 审核耗时负值或超过 30 天 | 条件计数 | warning |
| 数据延迟 | `message.occurred_at` 与 `ingested_at` 差值 P95 | 分位数查询 | info |
| 统计口径一致性 | 分析层的 Risk Rate 与 KPI 定义版本一致 | 定义哈希比对 | error |
| 合成标记 | 事实表 `is_synthetic` 与 dataset 标记冲突 | 关联检查 | warning |
| 低样本量 | 联盟/服务器样本数低于阈值（默认 30 条消息） | 聚合检查 | info |

## 3. 当前基线（2026-11-25 实测）

| 检查 | 结果 | 说明 |
|---|---|---|
| 主数据集消息数 | 50,000 | 与生成参数一致 |
| `message.external_message_id` 唯一 | 通过 | 50,007 行全局唯一 |
| `risk_event → message` 孤儿 | 0 | 8,856 行全部可关联 |
| `policy_decision → message` 孤儿 | 0 | 50,008 行全部可关联 |
| `enforcement_action → policy_decision` 孤儿 | 0 | 1,208 行全部可关联 |
| `risk_result` 覆盖 | 7 / 50,007 | 极低；真实引擎结果不足以代表全量 |
| `policy_decision` 关联评估 | 5 / 50,008 | 其余为生成器 legacy 记录 |
| `moderation_review` 行数 | 0 | 无法计算人工审核耗时与一致性 |
| `governance_feedback` 行数 | 0 | 无法计算基于反馈的线上误杀/漏判 |
| 策略版本 | 全部 v1 | 不支持真实历史版本对比 |
| `risk_score` / `confidence` 范围 | 通过 | 数据库 CheckConstraint + 查询复核 |
| 合成标记 | 主数据集全部 `is_synthetic=true` | 需在 UI 持续展示 |

**结论**：分析链路可用，但覆盖率与人工标注存在结构性缺口。所有依赖缺失数据的指标必须在 UI/报告中显示空状态或明确标注不可计算，不得用合成快照替代。

## 4. 低样本量规则

- 服务器：消息数 < 30 → 标记「低样本量」。
- 联盟：消息数 < 30 → 标记「低样本量」，排名页默认过滤。
- 策略回放：样本数 < 100 → 标记「探索性结果」，不得作为决策依据。
- 模型版本比较：必须使用同一 `dataset_name` + `split`；不满足时拒绝比较。

## 5. 质量与指标的关系

数据质量结果不改变指标公式，但影响指标的可解释性：

- 覆盖率低 → 指标只代表已覆盖样本，不代表全量。
- 关联缺失 → 分母只取可关联记录，并单独显示排除数量。
- 合成快照 → 指标描述为「模拟业务过程统计」，不得描述为线上效果。
