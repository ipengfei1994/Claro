# Phase 04 — Phase 01–03 集成审查

日期：2026-11-25
审查对象：Phase 01 基础架构、Phase 02 数据工程、Phase 03 风险智能引擎
审查方式：阅读源码、配置、Alembic 迁移、测试，并连接真实 PostgreSQL、Redis、Kafka 验证当前状态。

## 1. 当前已具备的能力

### Phase 01 基础

- `claro.bootstrap.AppContainer` 统一组装配置、数据库、事件总线、Redis、健康检查与风险服务。
- development（SQLite + 内存总线）与 full（PostgreSQL + Redis + Kafka）双模式，full 模式连接失败会拒绝启动。
- 结构化日志、配置分层（YAML < .env < 进程环境变量）、Pydantic 校验、健康检查接口。
- PowerShell 原生环境检查、服务状态、启停与流水线控制。

### Phase 02 数据工程

- 固定 seed 合成数据生成器：5,000 玩家、10 服务器、500 联盟、50,000 消息、40 条策略规则。
- PostgreSQL 真实落库；当前库内 2 个数据集、50,003 条消息、50,003 条 `policy_decision`、4,036 个 `moderation_case`、1,206 条 `enforcement_action`。
- Kafka 真实生产/消费、手动提交、Retry/DLQ、Inbox 去重、Consumer Group lag。
- Redis 缓存旁路、黑名单、原子限流、风险计数，缓存失败回退 PostgreSQL。
- Hive ODS/DWD/DWS/ADS SQL 与 PostgreSQL 导出；Hive 引擎未安装，SQL 未执行。
- 22 条默认测试 + 11 个真实集成测试通过（Phase 03 基线）。

### Phase 03 风险智能

- 19 类风险分类体系（18 风险 + normal），映射到 8 个数据库 `RiskCategory`。
- 预处理、22 条 YAML 规则、char_wb TF-IDF + 逻辑回归/线性 SVM、语义占位、可选 LLM 顾问。
- 加权 noisy-OR 融合、风险等级、建议动作、置信度、冲突解释。
- `risk_result`（每条消息唯一）与 `risk_finding` 持久化，`risk_result.id` 作为风险事件 ID 发布 `game.risk.assessed.v1`。
- 当前库内仅 3 条 `risk_result`、8,862 条 `risk_finding`，说明 Phase 03 检测只在少量消息上真实执行过；其余 50,000 条消息只有 Phase 02 的合成 `policy_decision`。
- Alembic head：`c4a7e1d9b2f6`。

## 2. 可以直接复用的数据模型

| 表 | 复用方式 | 说明 |
|---|---|---|
| `message` | 直接读取 | 提供原文、发送者、服务器、联盟、发生时间、合成标记 |
| `player` / `server` / `alliance` | 直接读取 | 玩家上下文、作用范围匹配 |
| `player_blacklist_entry` | 直接读取 | Blacklist 策略与豁免判断 |
| `risk_result` | 直接读取 | 风险分、等级、类别、置信度、建议动作、解释 |
| `risk_finding` | 直接读取 | 规则/ML 证据，审核详情展示 |
| `ml_model` | 直接读取 | 反馈记录中的模型版本 |
| `policy_decision` | 扩展复用 | 作为治理决策表；新增治理字段，保留 Phase 02 合成行 |
| `moderation_case` | 扩展复用 | 作为人工审核任务；扩展状态、乐观锁、最终结论字段 |
| `case_event` | 直接复用 | 工单状态流转历史 |
| `enforcement_action` | 扩展复用 | 作为模拟处置记录；新增目标类型、时长、到期、释放字段 |
| `audit_event` | 扩展复用 | 作为追加式审计日志；新增角色、前后状态、原因 |
| `inbox_event` | 直接复用 | Kafka 消费去重（Phase 04 新消费者使用独立 Group） |

结论：不新建与已有表含义重复的 `policies`、`governance_decisions`、`moderation_tasks`、`enforcement_records`、`audit_logs`。Phase 04 通过**扩展已有表 + 少量新表**实现，避免同一业务概念双份存储。

## 3. 需要扩展的服务与组件

| 组件 | 扩展内容 |
|---|---|
| `domain/enums.py` | 新增 PolicyType、GovernanceAction（扩展现有 DecisionAction）、DecisionStatus、审核状态与动作、目标类型、反馈类型、Outbox 状态 |
| `data_access/models.py` | 扩展 Policy、PolicyDecision、ModerationCase、EnforcementAction、AuditEvent；新增 PolicyVersion、PolicyEvaluation、ModerationReview、PlayerEnforcementState、GovernanceFeedback、OutboxEvent |
| `data_access/repositories/` | 新增 `GovernanceRepository`，覆盖策略、评估、决策、审核、处置、反馈、审计、Outbox 查询与事务写入 |
| `application/` | 新增治理编排、策略评估、决策、审核、处置、反馈/审计、Outbox 分发、Kafka 治理流水线 |
| `infrastructure/kafka.py` | 复用 Producer/Consumer；仅新增 Topic 配置，不重写传输层 |
| `infrastructure/redis.py` | 复用 CachePort；治理缓存使用独立命名空间，不修改风险缓存键 |
| `config/settings.py` + YAML | 新增 GovernanceSettings 与治理 Topic；保持既有配置兼容 |
| `bootstrap.py` | 注册治理仓储、缓存与服务；关闭顺序保持先 Kafka/Redis 后数据库 |
| `ui/app.py` | 保留现有状态页，新增导航与五个治理页面；UI 只调用服务层 |
| `cli.py` | 新增策略种子、治理流水线、Outbox 分发、处置到期、评估/决策/审核/处置命令行入口 |

## 4. 尚未实现、Phase 04 必须补齐的能力

1. 治理策略中心：策略 CRUD、类型、优先级、启停、有效期、作用范围、版本、回滚、版本比较、策略测试。
2. 策略评估引擎：结构化条件匹配、确定性优先级、冲突解决、默认策略、完整评估记录。
3. 治理决策引擎：动作映射、风险严重度与置信度分离、自动/人工/观察三路径、决策解释与覆盖。
4. 人工审核工作台：队列、筛选、认领、状态机、二次复核、重开、并发保护、审核历史。
5. 处置模拟引擎：WARN/BLOCK/MUTE/TEMP_BAN/PERM_BAN、玩家状态、到期、解除、重复处置保护、失败记录。
6. 反馈与审计：误杀/漏判、类别/等级/处置错误、原始预测与最终结论对照、追加式审计。
7. Redis 治理缓存：生效策略、策略版本、玩家处置状态、高频计数；TTL 与失效。
8. Kafka 治理事件：评估、决策、审核任务、审核完成、处置、反馈；Outbox Pattern 保证数据库与消息一致。
9. Streamlit 治理 UI：真实数据、真实按钮、校验、二次确认、操作反馈。
10. 单元、集成、业务场景测试与阶段文档。

## 5. 本阶段需要新增的表、接口和服务

### 新增表

- `policy_version`：策略历史快照，每次修改/回滚新增版本，唯一 `(policy_id, version)`。
- `policy_evaluation`：一条消息在一个策略快照下的评估结果，唯一 `(message_id, policy_snapshot_hash)`。
- `moderation_review`：人工审核动作历史，保留系统判断与人工判断。
- `player_enforcement_state`：玩家（可按服务器）当前模拟状态。
- `governance_feedback`：人工反馈与原始模型/风险结果对照。
- `outbox_event`：事务内事件发件箱，唯一 `dedupe_key`。

### 扩展表

- `policy`：名称、描述、类型、作用范围、条件、动作、优先级、紧急标记、启用、版本、命中次数、创建/更新人。
- `policy_decision`：风险结果、策略评估、决策键、状态、原因、置信度、是否需审核、优先级、决策人、解释。
- `moderation_case`：决策、风险快照、最终类别/等级/动作、二次复核、到期、乐观锁、重开次数。
- `enforcement_action`：目标类型、服务器、时长、原因、到期、模拟标记、释放信息。
- `audit_event`：角色、前状态、后状态、原因。
- `message`：`display_status`（visible/blocked），用于 BLOCK 的可展示状态模拟。

### 新服务

- `PolicyService`：创建、更新、启停、列表、详情、版本、回滚、比较、测试、冲突扫描、种子策略。
- `PolicyEvaluationService`：上下文组装、策略匹配、优先级、冲突、评估持久化、解释。
- `GovernanceDecisionService`：决策生成、审核分流、决策解释、决策覆盖。
- `ModerationService`：队列、认领、提交审核、升级、二次复核、重开、历史、并发控制。
- `EnforcementService`：模拟处置、玩家状态、历史、解除、到期、重复保护。
- `FeedbackAuditService`：反馈提交、误杀/漏判统计、审计查询。
- `OutboxDispatcher`：发件箱投递、重试、失败标记。
- `GovernancePipelineService`：消费风险事件，编排评估→决策→审核任务→Outbox。

## 6. 技术风险与处理

| 风险 | 影响 | 处理 |
|---|---|---|
| 已有 `policy` / `policy_decision` 被 Phase 02 合成数据占用 | 新字段与旧行冲突 | 新字段全部可空或带默认值；治理查询以 `policy_type`/`decision_status` 过滤；不改写旧行 |
| 已存在 50,003 条 Phase 02 `policy_decision` | 决策统计失真 | 治理页面只统计 `decision_status IS NOT NULL` 的行，并在界面注明 Phase 02 合成决策不计入 |
| 仅 3 条真实 `risk_result` | 治理流程可处理消息很少 | 提供 `governance-detect`/批量检测命令；业务场景测试使用独立小数据集 |
| Kafka 消费与数据库提交不一致 | 事件丢失或重复 | 事务内写 `outbox_event`，提交后分发；事件 ID 使用资源 ID，消费者幂等 |
| 审核并发 | 双人重复提交 | `lock_version` 乐观锁 + 条件 UPDATE；冲突返回明确错误 |
| Redis 不可用 | 评估效率下降 | 缓存旁路，读取失败回退 PostgreSQL；写失败不回滚业务事务 |
| 单人演示无真实认证 | 角色伪造 | 使用模拟账号选择器，界面明确标注“模拟身份”，不宣称生产级认证 |
| 回滚覆盖历史 | 审计断裂 | 回滚生成新版本，历史版本只读保留 |
| 白名单被滥用 | 高危内容豁免 | 白名单必须有明确作用范围，默认最高只豁免 medium；high/critical 不自动豁免并记录冲突 |
| 高严重度低置信度 | 误处罚 | 决策引擎将严重度与置信度分离，低置信度强制 REVIEW |
| Hive 未安装 | 数仓不完整 | 本阶段不声称 Hive 执行；治理分析走 PostgreSQL 查询与 Streamlit |

## 7. 实施顺序

1. 数据模型与 Alembic 迁移。
2. 领域层纯逻辑：条件求值、优先级、冲突、决策、状态机、处置计划。
3. 治理仓储与事务写入。
4. 策略中心与版本管理。
5. 策略评估与治理决策。
6. 审核工作台与并发保护。
7. 处置模拟与到期/解除。
8. 反馈、审计、Outbox、Redis 缓存、Kafka 流水线。
9. Streamlit UI。
10. 单元/集成/业务场景测试。
11. 文档与阶段报告。

本审查不修改 Phase 01–03 已验证的行为；所有扩展保持向后兼容。
