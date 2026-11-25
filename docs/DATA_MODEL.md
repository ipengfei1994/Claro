# Claro Phase 02 / Phase 03 / Phase 04 — 数据模型

## 1. 存储约定

- PostgreSQL 使用 UUID 主键、`TIMESTAMPTZ`、`NUMERIC` 和 JSON/JSONB。
- SQLite 仅用于 development/单元测试；JSONB 通过 SQLAlchemy variant 映射为 JSON。
- 所有时间在 ORM 边界规范为 UTC。
- 合成数据通过 `dataset.is_synthetic` 和记录级 `is_synthetic` 标记。
- Schema 只能通过 Alembic 修改；当前 head 为 `c79ffc3a04ff`（Phase 04 治理 schema）。

## 2. 表清单

| 表 | 职责 | 关键约束/索引 |
|---|---|---|
| `dataset` | 数据来源、种子、生成参数 | `name` 唯一 |
| `server` | 服务器维度 | `(dataset_id, server_ref)` 唯一 |
| `alliance` | 联盟维度 | `(dataset_id, alliance_ref)` 唯一，关联 server |
| `player` | 玩家维度与行为特征 | `(dataset_id, player_ref)` 唯一，风险倾向 0–1 |
| `player_blacklist_entry` | 玩家黑名单权威记录 | `player_ref` 唯一，`blocked_until` 索引 |
| `message` | 原始消息、状态、内容和时间 | `external_message_id` 唯一，发送方/时间索引 |
| `message_label` | 独立真值标签与 ML split | 每个 message 一个标签，split/category 索引 |
| `processing_event` | 消息处理历史 | `(message_id, sequence)` 唯一 |
| `detection_rule` | keyword/regex 规则及版本 | `(rule_key, version)` 唯一 |
| `risk_finding` | 单次检测证据（规则/ML/语义/LLM） | message/category 索引，score/confidence 0–1 |
| `risk_result` | 每条消息的最新融合结果 | `message_id` 唯一，`(dataset_id, detected_at)`、`(risk_level, detected_at)` 索引 |
| `risk_event` | 风险事件事实（Phase 02 规则事件） | message/rule/dataset/category/occurred_at |
| `ml_model` | 训练模型元数据与产物路径 | `(name, version)` 唯一，`(status, trained_at)` 索引 |
| `evaluation_run` | 评估运行汇总 | `(model_id, created_at)` 索引 |
| `evaluation_case` | 误报/漏报/边界样例 | `(run_id, error_type)` 索引 |
| `policy` | 策略版本与定义 | `(policy_key, version)` 唯一 |
| `policy_rule` | 策略规则、阈值和动作 | `(policy_id, rule_key, version)` 唯一 |
| `policy_decision` | 策略决策与原因码 | 关联 message/policy，风险分 0–1 |
| `moderation_case` | 人工审核工单 | 每个 message 最多一个 case |
| `moderation_record` | 审核动作记录 | `idempotency_key` 唯一 |
| `case_event` | 工单状态历史 | 关联 case |
| `enforcement_action` | 执法动作及状态 | `idempotency_key` 唯一 |
| `inbox_event` | Kafka 摄入去重与错误状态 | `event_id` 主键，源 topic/partition/offset 唯一 |
| `audit_event` | 关键业务审计 | entity/action/created_at 索引 |
| `policy_version` | 策略历史快照（Phase 04） | `(policy_id, version)` 唯一 |
| `policy_evaluation` | 策略评估结果（Phase 04） | `(message_id, policy_snapshot_hash)` 唯一 |
| `moderation_review` | 人工审核动作历史（Phase 04） | `(case_id, created_at)` 索引 |
| `player_enforcement_state` | 玩家模拟处置状态（Phase 04） | `(player_ref, scope_ref)` 唯一 |
| `governance_feedback` | 反馈与原始预测对照（Phase 04） | `(feedback_type, created_at)` 索引 |
| `outbox_event` | 事务内事件发件箱（Phase 04） | `dedupe_key` 唯一 |

Phase 04 治理表详细字段、扩展字段与关系见 [GOVERNANCE_DATA_MODEL.md](GOVERNANCE_DATA_MODEL.md)。

## 3. 关系

```text
dataset
 ├─ server ─ alliance ─ player
 ├─ message ─ message_label
 │    ├─ processing_event
 │    ├─ risk_finding / risk_event
 │    ├─ policy_decision ─ enforcement_action
 │    └─ moderation_case ─ case_event
 │           └─ moderation_record
 ├─ detection_rule ─ policy_rule ─ policy
 ├─ ml_model ─ evaluation_run ─ evaluation_case
 ├─ risk_result ─ message
 └─ generation_params / is_synthetic

message ─ risk_result (1:1，唯一约束)
message ─ risk_finding (1:N，检测器证据)
ml_model ─ risk_result (1:N，可空)
player_blacklist_entry ─ audit_event
inbox_event            ─ audit_event
```

`message.dataset_id` 允许为空以兼容不依赖数据集的行级摄入；玩家、服务器和联盟外键在实体未预加载时允许为空，但保留 `sender_ref/server_ref/alliance_ref`。

`risk_result` 保存融合后的等级、建议动作、类别列表、检测方法、证据、解释、检测器版本与耗时。`detection_rule.rule_type` 从 16 字符扩展到 32 字符以容纳 Phase 03 的 detector 类型标签。

## 4. Kafka 摄入事务

`persist_raw_message` 在一个事务中：

1. 复用或创建最小 Dataset 元数据。
2. 复用匹配的预加载 Message，或创建仅含原始字段的 Message。
3. 创建 sequence=1 的 ingestion ProcessingEvent。
4. 写入 processed InboxEvent。
5. 写入 `kafka_ingested` AuditEvent。

重复 Inbox 投递只增加 attempts，不重复 Message 或 ProcessingEvent。若同一 Kafka 源坐标被不同事件复用，则拒绝并进入永久错误/DLQ。

## 5. 标签泄漏防护

- 标签在生成器中独立采样，不读取检测器输出。
- train/validation/test/holdout 按玩家划分，比例为 70/10/10/10。
- 原始 Kafka payload 不包含 label、split、risk_score 或 action。
- processed topic payload 同样不包含这些字段。

## 6. 默认数据集

- 名称：`phase-02-synthetic-s20261125-p5000-m50000`
- fingerprint：`eb13a989d5c971626683bd011589f602cfb84861a65f3e5e166023a764d45c18`
- 10 servers、500 alliances、5,000 players、50,000 messages
- 50,000 labels、250,000 processing events
- 8,856 risk findings/events、50,000 policy decisions
- 4,035 moderation cases、7,770 moderation records
- 5 policies、40 policy rules、1,206 enforcement actions

清理命令只接受受保护的 Phase 02 synthetic 名称或 `template_version=2` 数据集，Phase 01 数据受到保护。

## 7. 风险结果与幂等

风险检测在一个事务中写 `risk_result` 和 `risk_finding`。`risk_result.message_id` 唯一，重复处理同一消息返回已有结果，不新增 findings。

- `risk_finding.detector` 区分 `rule`、`ml`、`semantic`、`llm`，每条 finding 记录 `detector_version`。
- `risk_result.categories` 保存全部标签得分，`risk_score` 为最高类别分，`risk_level` 与 `suggested_action` 由融合阈值决定。
- `risk_result.ml_model_id` 指向本次使用的 active 模型；规则-only 检测为空。
- 风险 Kafka 事件 ID 复用 `risk_result.id`，因此重发事件不会产生新 ID。
- 评估表只保存真实运行结果；`evaluation_case` 记录冲突、边界等错误样例，没有数据时为空，不生成占位记录。
