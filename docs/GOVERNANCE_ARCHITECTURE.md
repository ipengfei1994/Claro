# Claro Phase 04 — 内容治理架构

## 1. 职责边界

Phase 03 回答「这条内容有什么风险」；Phase 04 回答「面对这些风险应该采取什么治理措施」。Phase 04 不重新实现风险检测，只消费 `game.risk.assessed.v1` 中的已提交结果，并把治理结论写回 PostgreSQL、Redis 与 Kafka。

完整链路：

```text
game.risk.assessed.v1
    → GovernancePipelineService
    → PolicyEvaluationService（策略匹配 / 优先级 / 冲突）
    → GovernanceDecisionService（自动 / 人工 / 观察分流）
    → ModerationService（状态机 / 二次复核 / 反馈）
    → EnforcementService（内部模拟处罚）
    → FeedbackAuditService（反馈 / 追加式审计）
    → outbox_event → Kafka
```

职责边界由代码保证：

- 风险引擎 `claro/risk_engine/` 不导入治理模块。
- 治理领域层 `claro/governance/` 为纯函数与不可变数据类，不依赖 SQLAlchemy / Streamlit / Kafka。
- UI 只通过 `AppContainer` 上的服务层访问业务能力，不执行 SQL。

## 2. 分层与组件

| 层 | 组件 | 职责 |
|---|---|---|
| Domain | `governance/policy.py` | 条件树校验、求值、优先级、冲突检测、快照哈希 |
| Domain | `governance/decision.py` | 严重度与置信度分离，自动/人工分流 |
| Domain | `governance/moderation.py` | 审核状态机、动作合法性、理由校验 |
| Domain | `governance/enforcement.py` | 处置计划、目标类型、时长与到期 |
| Application | `policy_service.py` | 策略 CRUD、版本、回滚、启停、Playground |
| Application | `policy_evaluation_service.py` | 组装上下文并持久化评估 |
| Application | `governance_decision_service.py` | 生成决策、审核分流、解释、覆盖 |
| Application | `moderation_service.py` | 队列、认领、提交、升级、二次复核、重开 |
| Application | `enforcement_service.py` | 模拟处置、玩家状态、到期、解除 |
| Application | `feedback_audit_service.py` | 反馈、误杀漏判统计、审计查询 |
| Application | `outbox_dispatcher.py` | 事务内事件投递到 Kafka |
| Application | `governance_pipeline_service.py` | 风险事件到治理链路的编排 |
| Data Access | `governance_repository.py` | 治理事务写入、乐观锁、Outbox、Trace |
| Data Access | `policy_repository.py` | 策略与版本、冲突扫描、命中计数 |
| Infrastructure | `kafka.py` / `redis.py` | 复用 Phase 02 适配器，不重写传输层 |
| UI | `ui/pages/*.py` | 六个治理页面，Minimal Enterprise 风格 |

## 3. 状态权威与一致性

- PostgreSQL 是唯一业务状态权威来源；Redis 只缓存可重建的读模型。
- 关键事件在业务事务内写入 `outbox_event`，由 `OutboxDispatcher` 在事务提交后投递到 Kafka，避免数据库提交与消息发送不一致。
- `dedupe_key` 唯一约束保证重复投递不产生重复业务记录。
- 审核提交使用 `lock_version` 乐观锁，重复或过期提交返回确定性错误。
- 处置使用 `idempotency_key = enforcement:{decision_id}:{action}:{target_ref}`，重复消费同一事件不会重复处罚。

## 4. 确定性决策

策略选择顺序（`governance/policy.py::_selection_key`）为：

1. `emergency=True` 优先；
2. `priority` 数值大者优先；
3. 作用范围更具体者优先（玩家 > 联盟 > 服务器 > 全局）；
4. 动作更严格者优先；
5. `policy_key`、`policy_id` 作为最终确定性排序键。

该顺序显式编码，不依赖数据库返回顺序或 Python 字典顺序。所有匹配、未匹配、冲突与最终选择依据均写入 `policy_evaluation` 并可解释。

白名单不会无条件豁免：`high` / `critical` 风险即使命中白名单，也会被跳过并记录原因。

## 5. 自动与人工分流

`decide_governance_action` 将风险严重度与模型置信度分离：

- 限制级动作（`block` / `mute` / `temp_ban` / `perm_ban` / `restrict`）在置信度低于阈值时降级为 `REVIEW`。
- `high` / `critical` 风险在置信度不足时强制 `REVIEW`。
- 无足够证据的高严重度内容不自动处罚。
- 默认阈值：`low_confidence=0.55`，`high_risk_confidence=0.70`，来自 `GovernanceSettings`。

## 6. 模拟边界

- 所有处置记录 `simulated=true`。
- 不连接真实游戏服务器，不执行真实玩家处罚。
- `BLOCK` 仅修改本地 `message.display_status`；`MUTE` / `TEMP_BAN` / `PERM_BAN` 只写入 `player_enforcement_state`。
- UI 身份选择器是模拟身份，界面明确标注，不宣称生产级认证。

## 7. 运行约束

- Windows 11 原生 PostgreSQL 5432、Redis 6379、Kafka 9092。
- 禁止 Docker / Docker Compose / WSL 作为依赖。
- Hive 引擎未安装；本阶段治理分析走 PostgreSQL 查询与 Streamlit 展示，不声称 Hive 已执行。
