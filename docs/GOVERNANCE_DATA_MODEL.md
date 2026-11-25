# Claro Phase 04 — 治理数据模型

## 1. 迁移

Phase 04 迁移：`20261125_c79ffc3a04ff_phase_04_governance_schema.py`。当前 Alembic head 为 `c79ffc3a04ff`。

设计原则：Phase 02 已存在 `policy`、`policy_decision`、`moderation_case`、`enforcement_action`、`audit_event`，因此 Phase 04 **扩展这些表**并新增少量表，避免同一业务概念双份存储。新字段全部可空或带默认值，兼容 50,003 条历史合成决策。

## 2. 新增表

| 表 | 职责 | 关键约束 |
|---|---|---|
| `policy_version` | 策略历史快照 | `(policy_id, version)` 唯一 |
| `policy_evaluation` | 一次策略评估的完整结果 | `(message_id, policy_snapshot_hash)` 唯一 |
| `moderation_review` | 人工审核动作历史 | `(case_id, created_at)` 索引，保留系统/人工判断 |
| `player_enforcement_state` | 玩家（按服务器）模拟处置状态 | `(player_ref, scope_ref)` 唯一 |
| `governance_feedback` | 人工反馈与原始模型结果对照 | `(feedback_type, created_at)`、`message_id` 索引 |
| `outbox_event` | 事务内事件发件箱 | `dedupe_key` 唯一，`(status, available_at)` 索引 |

## 3. 扩展表

| 表 | 新增字段 |
|---|---|
| `policy` | policy_key、policy_type、target_scope、conditions、action、priority、emergency、enabled、version、effective_from/until、hit_count、created_by/updated_by、is_default |
| `policy_decision` | risk_result_id、policy_evaluation_id、decision_key、decision_status、decision_reason、confidence、requires_review、priority、decided_by、explanation |
| `moderation_case` | decision_id、risk_result_id、risk_snapshot、final_*、lock_version、reopened_count、required_second_review、due_at、assignee_ref |
| `enforcement_action` | target_type、server_ref、duration_seconds、expires_at、simulated、released_at、release_reason、idempotency_key |
| `audit_event` | actor_role、before_state、after_state、reason |
| `message` | display_status（visible / blocked） |

## 4. 关系

```text
message
 ├─ risk_result ─ risk_finding
 ├─ policy_evaluation ─ selected_policy → policy ─ policy_version
 ├─ policy_decision ─ policy_evaluation
 │    ├─ moderation_case ─ moderation_review ─ governance_feedback
 │    └─ enforcement_action ─ player_enforcement_state
 └─ governance_feedback
outbox_event（独立，按 dedupe_key 幂等）
audit_event（追加式，entity_type + entity_id 索引）
```

## 5. 事务与并发

- 评估、决策、审核、处置都在单个 `session_scope` 事务内写入业务记录、审计与 Outbox 事件。
- `policy_evaluation`、`policy_decision`、`enforcement_action`、`inbox_event` 通过唯一键实现幂等。
- `moderation_case.lock_version` 提供乐观锁；`SELECT FOR UPDATE` 防止同一工单并发提交。
- `player_enforcement_state` 查询使用 `FOR UPDATE`，避免并发处置互相覆盖。

## 6. JSONB 使用

结构化条件、条件命中轨迹、策略快照、风险快照、决策解释、处置细节均以 JSON/JSONB 存储。PostgreSQL 使用 JSONB，SQLite（development）通过 SQLAlchemy variant 降级为 JSON。所有 JSON 内容都是受限结构，不存储可执行代码。

## 7. 历史数据兼容

`governance_stats()` 只统计 `decision_status IS NOT NULL` 的决策；Phase 02 合成决策标记为 `legacy`，不计入治理决策总数。治理页面明确说明这一口径，避免 50,003 条历史合成决策扭曲统计。
