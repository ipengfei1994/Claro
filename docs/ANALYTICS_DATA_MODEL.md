# Phase 05 — 分析数据模型

## 1. 设计原则

1. 分析层与在线业务分离：所有查询通过 `claro.analytics` 服务层执行，Streamlit 页面不直接执行 SQL。
2. 一个事实表只表达一种粒度；不允许跨粒度直接 JOIN 后 COUNT。
3. 统一时间轴：所有分析的时间过滤均使用 `message.occurred_at`，即使分子来自 `risk_event` 或 `policy_decision`。这样分母与分子始终处于同一消息集合。
4. 实体主键为 UUID；`message.external_message_id` 是业务标识，仅用于展示与外部对账。
5. 每条分析记录携带 `data_source_tier`（OBSERVED / SYNTHETIC_SNAPSHOT / DERIVED），UI 必须展示。

## 2. 事实与维度

| 分析实体 | 粒度 | 物理来源 | 主键 | 去重规则 |
|---|---|---|---|---|
| Message Fact | 一条消息 | `message` | `message.id` | `COUNT(DISTINCT id)` |
| Risk Event Fact | 一次风险识别事件 | `risk_event` | `risk_event.id` | 风险消息数按 `DISTINCT message_id` |
| Risk Result Fact | 一条消息一个融合结果 | `risk_result` | `risk_result.message_id` (unique) | 天然去重 |
| Governance Decision Fact | 一次治理决策 | `policy_decision` | `policy_decision.id` | 消息级统计用 `DISTINCT message_id` |
| Moderation Fact | 一个审核任务 | `moderation_case` | `moderation_case.id` | 一消息一 case，`message_id` unique |
| Enforcement Fact | 一次模拟处置 | `enforcement_action` | `enforcement_action.id` | 按 `idempotency_key` 唯一 |
| Policy Snapshot | 一个策略在一个版本的状态 | `policy_version` | `(policy_id, version)` | 以 `snapshot_hash` 校验内容 |
| Player Daily Snapshot | 一个玩家一天 | 由 Message Fact 聚合 | `(player_id, dt)` | 按日期桶聚合，不落库 |
| Server Daily Snapshot | 一个服务器一天 | 由 Message Fact 聚合 | `(server_id, dt)` | 按日期桶聚合，不落库 |
| Alliance Daily Snapshot | 一个联盟一天 | 由 Message Fact 聚合 | `(alliance_id, dt)` | 按日期桶聚合，不落库 |

## 3. 维度

| 维度 | 来源 | 字段 |
|---|---|---|
| 时间 | `message.occurred_at` | hour / day / week / month（UTC+8 展示，UTC 存储） |
| 服务器 | `server` / `message.server_ref` | `server_id`, `server_ref`, `name`, `region` |
| 联盟 | `alliance` | `alliance_id`, `alliance_ref`, `name`, `server_id` |
| 玩家 | `player` | `player_id`, `player_ref`, `display_name`（UI 仅显示脱敏标识） |
| 风险类别 | `risk_event.category`, `risk_finding.category`, `risk_result.categories` | category |
| 风险等级 | `risk_event.severity`, `risk_result.risk_level` | severity |
| 治理动作 | `policy_decision.action` | action |
| 策略 / 策略版本 | `policy`, `policy_version` | `policy_key`, `version`, `snapshot_hash` |
| 模型版本 | `ml_model`, `risk_result.ml_model_id`, `evaluation_run.model_id` | `model_id`, `name`, `version` |
| 审核人员 | `moderation_review.reviewer_ref`, `moderation_record.actor_ref` | reviewer_ref（当前审核明细为空） |

## 4. 关联映射

```text
message.id ─┬─< risk_finding.message_id
            ├─< risk_event.message_id
            ├─< policy_evaluation.message_id
            ├─< policy_decision.message_id ──< enforcement_action.decision_id
            ├─  moderation_case.message_id ──< moderation_review.case_id
            └─< governance_feedback.message_id

policy_decision.policy_evaluation_id → policy_evaluation.id
policy_decision.risk_result_id       → risk_result.id
policy_evaluation.risk_result_id     → risk_result.id
moderation_case.decision_id          → policy_decision.id
risk_result.ml_model_id              → ml_model.id
evaluation_run.model_id              → ml_model.id
```

一对多关系处理规则：

- 风险消息数：`COUNT(DISTINCT message_id)`，不使用 `COUNT(*)`。
- 多标签类别分布：按 `(message_id, category)` 去重后计数；各类别数量之和可大于风险消息数，UI 需提示。
- 决策→处置：先按 `decision_id` 聚合成「是否有处置」，再与消息事实关联。
- 审核耗时：仅使用 `closed_at IS NOT NULL` 的记录；未完成任务不进入耗时分布。

## 5. 分析查询约定

- 查询模块：`src/claro/analytics/sql_queries.py`，具名 SQL 字符串，全部使用绑定参数。
- 数据库：正式模式为 PostgreSQL；查询使用 `date_trunc`、`FILTER`、`percentile_cont` 等 PostgreSQL 语法。
- 时间窗口：使用半开区间 `[start, end)`，`end` 为排他边界，避免日界重复计数。
- 数据集：默认主数据集 `phase-02-synthetic-s20261125-p5000-m50000`；集成测试数据集可通过筛选器选择，不混入默认口径。
- 时区：数据库以 UTC 存储；展示层按本机时区（UTC+8）格式化，日期桶按 UTC 日期计算并在 UI 说明。

## 6. 回放数据模型

Strategy Replay 使用两张独立分析表（见迁移 `20261125_..._phase_05_analytics.py`）：

- `analytics_replay_run`：一次回放的元数据（数据集、时间窗、基线/候选策略版本、参数、样本量、生成时间、执行者、simulation 标记）。
- `analytics_replay_case`：逐条消息的输入快照、基线动作、候选动作、差异类型、FP/FN 判定。

回放只读 `message` / `risk_event` / `message_label` / `policy_version`，写入仅限上述两张表。不调用任何执行或服务写入路径，不发布 Kafka 事件，不修改 `policy_decision` 或 `enforcement_action`。

## 7. 数据分级标记

| 级别 | 含义 | UI 展示 |
|---|---|---|
| OBSERVED | 引擎/服务真实运行写入 | 显示「实际观测记录」 |
| SYNTHETIC_SNAPSHOT | 生成器批量写入的模拟业务数据 | 显示「合成快照 · 非线上数据」 |
| DERIVED | 从上述数据计算出的指标 | 显示口径与来源 |
