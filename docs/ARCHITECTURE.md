# Claro — 架构（Phase 02 / Phase 03 / Phase 04）

## 1. 范围与运行约束

Phase 02 在 Phase 01 模块化单体基础上补齐数据工程链路：

```text
Synthetic Generator
    → PostgreSQL bulk load / Kafka raw topic
    → Kafka Consumer
    → PostgreSQL Inbox + Message + ProcessingEvent + AuditEvent
    → Kafka processed topic
    → Redis cache-aside
    → PostgreSQL export
    → Hive ODS → DWD → DWS → ADS
```

Phase 03 在 processed 事件之后增加风险智能链路：

```text
game.messages.persisted.v1
    → RiskPipelineService
    → preprocessing → rules → ML → semantic(unavailable) → LLM(optional)
    → fusion + explanation
    → PostgreSQL risk_result / risk_finding
    → game.risk.assessed.v1
```

Phase 04 在风险事件之后增加内容治理链路：

```text
game.risk.assessed.v1
    → GovernancePipelineService
    → PolicyEvaluationService → policy_evaluation
    → GovernanceDecisionService → policy_decision
    → Automatic Action / ModerationService → moderation_case / moderation_review
    → EnforcementService → enforcement_action / player_enforcement_state
    → FeedbackAuditService → governance_feedback / audit_event
    → outbox_event → game.governance.* topics
```

完整治理架构与职责边界见 [GOVERNANCE_ARCHITECTURE.md](GOVERNANCE_ARCHITECTURE.md)。

运行约束：

- Windows 11 原生 PostgreSQL、Redis、Kafka。
- 不引入容器化部署，不把 WSL 作为默认依赖。
- PostgreSQL 是业务数据、黑名单和审计的唯一权威来源。
- Kafka 负责真实事件传输；Redis 只承担缓存、计数和限流。
- 未真实执行的 Hive SQL 不标记为已验证。

## 2. 分层

| 层 | 职责 |
|---|---|
| UI | Streamlit 状态展示与六个治理页面，不执行 SQL，不包含审核核心逻辑 |
| Application | 事件契约、Kafka 摄入编排、风险流水线编排、治理服务、缓存用例、Hive 导出编排 |
| Domain | 枚举、黑名单值对象、限流结果、风险分类与评分结果、策略/决策/审核/处置纯逻辑 |
| Data Access | SQLAlchemy 模型、事务、批量加载、质量检查、安全仓储、风险仓储、治理与策略仓储 |
| Infrastructure | Kafka、Redis、日志、原生连接适配器、LLM HTTP 适配器 |
| Data Generation | 固定种子实体、行为时间分布、标签和数据集切分 |
| Risk Engine | 预处理、分类体系、规则、ML、语义占位、LLM 顾问、风险融合、评估 |
| Warehouse | Hive DDL/DML、PostgreSQL CSV 快照与加载 SQL |

`claro/risk_engine/` 不依赖 Streamlit 或 SQLAlchemy，通过应用层注入配置与仓储；检测器之间以结构化 `Finding` 通信，便于替换和单测。

`bootstrap.py` 负责组装应用依赖并释放 engine、Kafka 和 Redis 资源。

## 3. 关键架构决策

### 合成数据与标签隔离

原始 Kafka payload 不包含 `MessageLabel`、数据集 split、风险分或审核动作。标签由生成器独立构造，检测结果与真值标签不是同一来源。玩家级切分避免同一玩家跨 train/validation/test/holdout。

外部消息 ID 加入数据集名称哈希，避免默认数据集与自定义数据集发生 ID 冲突。

### Kafka 至少一次投递

Consumer 关闭自动提交，只在处理成功、重复确认或 Retry/DLQ 路由成功后提交源偏移。PostgreSQL Inbox 在同一事务中写 Message、ProcessingEvent、InboxEvent 和 AuditEvent。

Processed topic 发布位于数据库事务之后；发布失败后重投会命中 Inbox 重复分支并重新发布，从而避免数据库状态丢失。

### Redis 缓存旁路

敏感词来自 active keyword `DetectionRule`；策略来自 active `Policy`；玩家黑名单来自新增的 `player_blacklist_entry`。缓存键使用命名空间版本和 SHA-256 摘要，不直接暴露玩家 ID。

黑名单写入与审计在同一 PostgreSQL 事务完成，随后删除 Redis 键。Redis 故障时读路径回退数据库；黑名单写路径不会因缓存失效失败而回滚已提交业务。

### Hive 离线边界

PostgreSQL 导出器生成按事件日期分区的 CSV、manifest 和 `load_ods.sql`。ODS 保留导入批次数；DWD 按业务主键去重；DWS/ADS 提供玩家和服务器风险聚合。

Hive 执行器按顺序调用建库、建 ODS、加载、DWD、DWS/ADS 和质量检查。当前环境没有 Beeline，因此执行器会明确失败，不会输出成功状态。

### 风险检测分层与降级

预处理只生成分析视图，保留原文；规则、ML、语义、LLM 均为独立检测器，输出同构 `Finding`。融合层按数据库风险类别做加权 noisy-OR，标签取评估后的多标签结果。ML、语义或 LLM 不可用时记录状态并继续，不影响规则结果。

语义检测器当前为显式不可用占位；LLM 默认关闭，启用时仅作为顾问层，缺失凭据时拒绝启动而不是静默跳过。

### 风险结果幂等与 Kafka 语义

`risk_result.message_id` 唯一，重投同一 persisted 事件时返回已有结果，不重复写 findings。风险事件 ID 复用持久化的 `risk_result_id`，因此重发不会产生新事件 ID。

风险事件在数据库事务提交后发布；若发布失败，重投命中幂等分支并重新发布。处理异常中，格式错误映射为 `PermanentMessageError`，检测或持久化错误映射为永久失败，交由 Phase 02 的 Retry/DLQ 链路处理。

### 规则缓存

规则集来自 YAML 配置并行写入 active `DetectionRule`。Redis 键 `claro:risk:rules:v1` 缓存规则载荷与 SHA-256 摘要；摘要不一致或 Redis 不可用时回退数据库并重建缓存。

## 4. 事务与一致性

- 批量加载按事务与 batch size 写入，同一 fingerprint 重载幂等。
- 黑名单阻断/解除与 `AuditEvent` 原子提交。
- Kafka Inbox 唯一约束：`event_id` 主键，`(source_topic, source_partition, source_offset)` 唯一。
- Redis 限流使用 Lua 原子 `INCR + EXPIRE`。
- Hive 增量使用各表高水位，边界时间包含在导出中；ODS 可重复，DWD 负责去重。
- 风险结果在同一事务内写 `risk_result` 与 `risk_finding`，`risk_result.message_id` 唯一保证幂等。
- 风险事件在事务提交后发布，事件 ID 等于持久化的 `risk_result_id`。

## 5. 已验证与未验证

已验证：

- 当前 Alembic head `c4a7e1d9b2f6` 已应用到真实 PostgreSQL，`alembic check` 无漂移；Phase 02 迁移曾完成升级、降级、再升级。
- 50,000 条默认消息及完整关联数据落库。
- Kafka 真实传输、重试、DLQ、手动提交、Group lag 和 PostgreSQL Inbox。
- Redis 真实缓存、TTL、黑名单审计、风险聚合和限流。
- PostgreSQL 全量/增量 Hive 快照导出。
- 原生 PowerShell 环境检查、服务状态、重复启动保护和 Consumer 启停。
- 风险预处理、19 类分类体系、22 条规则、规则与 ML 融合、风险持久化幂等、风险 Kafka 事件发布。
- 真实 PostgreSQL 中风险检测重复执行只产生一条结果；真实 Redis 中规则缓存可读写与重载。
- ML 训练、模型序列化与加载、玩家级切分泄漏检查、验证/测试集评估。
- 123 个单元/默认测试通过；11 个真实集成测试通过；Ruff 检查通过。

未验证：

- 语义检测层，当前只有显式不可用占位。
- LLM 顾问层对真实兼容端点的调用，测试仅使用伪造传输。
- 生产级 Kafka 副本、ACL/TLS、Redis 高可用和 PostgreSQL 高可用。
- Hive SQL 的真实解析与执行，原因是缺少原生 Hive/Hadoop/Beeline。
- 模型在真实游戏文本上的准确率；当前指标来自合成模板数据，不可外推。
