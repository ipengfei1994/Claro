# Claro Phase 02 / Phase 03 / Phase 04 — 开发计划与验收

## 1. 阶段目标

Phase 02 在不破坏 Phase 01 分层的前提下完成数据工程闭环：确定性合成数据、PostgreSQL 持久化、Kafka 传输、Redis 缓存、Hive 数仓接口与 Windows 原生运维脚本。

Phase 03 在既有 processed 事件后增加风险智能链路：配置化分类体系、预处理、规则与 ML 检测、可选语义/LLM 层、风险融合、评估、风险持久化与风险事件发布。

严格边界：

- 仅使用 PostgreSQL、Redis、Kafka 和 Windows 原生服务。
- 不使用 Docker、Docker Compose、容器化或 WSL。
- PostgreSQL 是业务与审计权威来源。
- 未真实运行的 Hive SQL 不得标记为已验证。
- Phase 03 不实现策略决策、人工审核、执法和完整运营 UI。
- 语义检测与 LLM 真实端点未验证，不得写成已上线能力。

## 2. 分步状态

| 步骤 | 交付物 | 状态 |
|---|---|---|
| 1. 环境与模型审查 | 配置、现有 ORM、Alembic、原生环境 | 已完成并验证 |
| 2. 合成数据生成器 | 固定 seed、规模参数、真值标签、玩家 split | 已完成并验证 |
| 3. PostgreSQL 持久化 | 20 表、JSONB、批量事务、质量检查、定向清理 | 已完成并验证 |
| 4. Kafka Producer/Consumer | 独立 CLI、重试、DLQ、手动提交、Group lag | 已完成并验证 |
| 5. Kafka → PostgreSQL | Inbox 去重、原子历史/审计、processed 发布 | 已完成并验证 |
| 6. Redis 缓存 | 敏感词、策略、黑名单、计数、原子限流 | 已完成并验证 |
| 7. Hive 数仓 | ODS/DWD/DWS/ADS SQL、全量/增量导出、质量 SQL | SQL 已实现；PostgreSQL 导出已验证；Hive 未执行 |
| 8. 原生服务脚本 | 环境检查、启停、状态、初始化、数据与流水线脚本 | 已验证，初始化为 WhatIf |
| 9. 回归与文档 | 单元/集成测试、Ruff、操作与模型文档 | 已完成 |

### Phase 03 分步状态

| 步骤 | 交付物 | 状态 |
|---|---|---|
| 1. Phase 02 集成审计 | 现有 pipeline、数据模型、Kafka、Redis、测试基线 | 已完成 |
| 2. 风险分类体系 | 7 领域、19 类 YAML、包含/排除标准、示例与标注原则 | 已完成并验证 |
| 3. 文本预处理 | Unicode/全半角/大小写、零宽字符、混淆视图、URL/邮箱/电话、重复段 | 已完成并验证 |
| 4. 规则检测 | 22 条关键词/正则规则、否定词、黑白名单、重复消息 | 已完成并验证 |
| 5. 风险融合 | 加权 noisy-OR、多标签、等级/动作、置信度与冲突解释 | 已完成并验证 |
| 6. ML 检测 | char_wb TF-IDF、逻辑回归/线性 SVM、阈值、模型元数据与产物 | 已完成并验证 |
| 7. 评估框架 | 二分类/多标签指标、逐标签矩阵、错误样例、泄漏检查 | 已完成并验证 |
| 8. 语义/LLM 层 | 语义占位；LLM 可选顾问、默认关闭、凭据仅环境变量 | 语义未实现；LLM 仅伪造传输测试 |
| 9. 风险持久化与事件 | `risk_result` 幂等、`risk_finding` 证据、风险 Kafka 事件 | 已完成并验证 |
| 10. 回归与文档 | 单元/集成测试、Ruff、风险/评估/评分/架构文档 | 已完成 |

## 3. 验收证据

### 自动测试

Phase 02 基线（保留）：

```text
.venv\Scripts\python.exe -m pytest tests/unit -q
71 passed

.venv\Scripts\python.exe -m pytest tests/integration -m integration -q
8 passed, 1 warning
```

Phase 03 当前：

```text
.venv\Scripts\python.exe -m pytest -q
123 passed（默认排除 integration）

.venv\Scripts\python.exe -m pytest tests/integration -m integration -q
11 passed, 1 warning
```

- 警告为 Alembic `path_separator` 弃用提示，不影响测试通过。
- Ruff lint 与 format 检查通过。
- 集成测试要求 `CLARO_APP__MODE=full` 和真实 PostgreSQL、Redis、Kafka，缺失时明确失败而非跳过。

### 真实基础设施

- PostgreSQL 18：迁移 upgrade/downgrade/upgrade、`alembic check` 无漂移。
- 默认 50,000 条消息真实落库，全部数据质量检查通过。
- Kafka 3.9.2：生产、消费、重试、DLQ、手动提交、Inbox 去重、Group lag 和 processed 发布通过。
- Redis 8.10.3：PING、TTL、缓存失效、PostgreSQL 回退、原子限流与风险计数通过。
- 原生 PowerShell：PostgreSQL/Redis/Kafka 状态、重复启动保护、Redis/Kafka 安全重启、独立 consumer 启停通过。

### Phase 03 真实运行证据

- PostgreSQL：Phase 03 迁移 `b3f1c9d2a7e4` 与 `c4a7e1d9b2f6` 已应用；真实数据集消息重复检测只保留一条 `risk_result`，findings 与统计可查询。
- Kafka：持久化事件经真实 Consumer 处理，风险结果先落库，再在指定 topic 收到 `game.risk.assessed.v1`；重复投递返回幂等结果。
- Redis：规则缓存键 `claro:risk:rules:v1` 写入 22 条规则与 SHA-256 摘要，第二个 Provider 命中缓存，重载后重写。
- 模型：默认数据集 50,000 条，按玩家切分 train 35,232 / validation 5,038 / test 5,060 / holdout 4,670。
- 模型产物：逻辑回归、`C=1.0`、词表 3,114、所有标签阈值 0.2；验证集与测试集指标均为 1.0。
- 泄漏与边界：验证/测试与训练集文本重复率 0.9947；内容不相交子集仅 27 条 normal；边界标签 16/770 被标记。
- 错误样例：冲突 64 条、边界 770 条，已通过 `risk-cases` 持久化查询。

### Phase 04 分步状态

| 步骤 | 交付物 | 状态 |
|---|---|---|
| 1. 集成审查 | `PHASE_04_INTEGRATION_AUDIT.md` | 已完成 |
| 2. 数据模型与迁移 | 6 张新表 + 6 张扩展表，head `c79ffc3a04ff` | 已完成并验证 |
| 3. Policy Center | CRUD、版本、回滚、启停、冲突扫描、Playground | 已完成并验证 |
| 4. Policy Evaluation | 条件树、确定性优先级、冲突解决、默认策略 | 已完成并验证 |
| 5. Governance Decision | 严重度/置信度分离、三路径分流、决策解释 | 已完成并验证 |
| 6. Moderation Workbench | 队列、状态机、乐观锁、二次复核、重开 | 已完成并验证 |
| 7. Enforcement Simulator | 五类动作、玩家状态、到期、解除、幂等 | 已完成并验证 |
| 8. Feedback & Audit | 反馈、误杀漏判、追加式审计、Trace | 已完成并验证 |
| 9. 基础设施集成 | PostgreSQL + Redis + Kafka，Outbox Pattern | 已完成并验证 |
| 10. Streamlit UI | 六个页面，真实浏览器渲染 | 已完成并验证 |
| 11. 测试 | 单元/集成/业务场景/UI 冒烟 | 216 单元 + 25 集成通过 |
| 12. 文档与交付 | 设计文档、测试报告、完成报告 | 已完成 |

### Phase 04 真实运行证据

```text
.venv\Scripts\python.exe -m pytest tests/unit -q
216 passed

.venv\Scripts\python.exe -m pytest tests/integration -q -m integration
25 passed, 1 warning

.venv\Scripts\python.exe -m ruff check src tests
All checks passed
```

- 真实 Kafka：`governance-dispatch-outbox` 发布 137 条治理事件，0 失败。
- 真实 PostgreSQL：策略版本/回滚、审核状态机、处置到期/解除、反馈审计均有集成测试覆盖。
- 真实 Redis：策略缓存失效、限流计数、玩家状态缓存失效均有集成测试覆盖。
- 真实浏览器：六个治理页面全部渲染成功，无页面异常。
- 详细结果见 [PHASE_04_TEST_REPORT.md](PHASE_04_TEST_REPORT.md)。
- 性能（本机冷/热各 3 次）：冷启动 99–127 ms；热路径总计 3.891 ms（ML 3.137、规则 0.397、融合 0.094）；落库平均 76.526 ms（p50 98.819、p95 124.064）。

上述指标来自合成模板数据，不能外推为真实游戏文本的准确率。完整参数与限制见 [MODEL_EVALUATION.md](MODEL_EVALUATION.md)。

### 隔离流水线冒烟

- Topic：`game.messages.raw.script-smoke`
- Group：`claro-script-smoke-v1`
- 10 条真实消息生产并消费，Group lag=0。
- PostgreSQL 新增 10 messages、10 processing events、10 audit events、10 inbox events、0 labels。
- 重复启动保护通过，Consumer 通过 PID 所有权检查停止，测试数据集随后定向清理。

## 4. 已实现但未真实执行

| 项目 | 原因 |
|---|---|
| Hive ODS/DWD/DWS/ADS SQL | 当前 Windows 未安装原生 Hive/Hadoop/Beeline；执行入口明确失败 |
| 语义检测层 | 只有 `UnavailableSemanticDetector` 占位，不产生 finding |
| LLM 顾问对真实端点调用 | 默认关闭；测试使用伪造传输，未配置真实凭据 |
| `init_database.ps1` 实际初始化 | 会修改数据库角色/密码；仅执行 `-WhatIf` |
| PostgreSQL stop/start | 会影响系统数据库服务；仅 dry-run，未停止 |

PostgreSQL 快照导出及生成的 Hive `LOAD DATA` SQL 已真实执行；它们不等价于在 Hive 引擎执行数仓 SQL。

## 5. 已知限制

- 默认 raw topic 保留 Phase 02 早期 12 条旧 schema 冒烟消息；默认业务 Group 尚未消费，`earliest` 会将其路由到 DLQ。验收应使用新主题。
- Kafka 测试主题保留，因为 Windows broker 在即时 topic 删除时曾发生文件锁/崩溃。
- `game.messages.raw.script-smoke` 的 Kafka 事件不随 PostgreSQL 测试数据清理而删除。
- 原生 Hive 未安装；未安装任何容器化替代品。
- 模型在高重复模板数据上接近完美，评测集存在模板泄漏；内容不相交子集样本量不足，不能代表泛化能力。
- 训练超参数通过 `TrainingConfig` 传入；CLI 仅暴露算法选择，C 值、词表大小等默认值尚未外置为 YAML。
- 风险分未做概率校准；融合分为可解释加权分，不是校准后的概率。
- 语义检测与真实 LLM 端点未实现/未验证；LLM 启用需要外部兼容端点。
- 尚无认证/RBAC、生产级 Kafka HA、完整人工审核业务页面、策略决策与执法执行。

## 6. Phase 05 分步状态

| 步骤 | 状态 | 证据 |
|---|---|---|
| Phase 01–04 集成审查 | Executed | `docs/PHASE_05_INTEGRATION_AUDIT.md` |
| 分析数据模型 | Implemented | `docs/ANALYTICS_DATA_MODEL.md` |
| 数据质量检查 | Implemented / Executed | `docs/ANALYTICS_DATA_QUALITY.md` |
| KPI 统一定义 | Implemented | `docs/KPI_DEFINITIONS.md` |
| SQL 分析层 | Implemented / Executed | 27 条具名 SQL 在 PostgreSQL 18.3 上真实执行 |
| Risk / Community / Governance / Model 分析 | Implemented / Tested | 14 项 Phase 05 单元测试 |
| Strategy Evaluation 与隔离回放 | Implemented / Executed | 300 样本回放；正式表行数不变 |
| Hive 离线数仓 | **Blocked** | 无原生 Hive/Beeline；ADS 仅 Designed |
| Streamlit 分析页面 | Implemented / Tested | 6/6 页面 AppTest 渲染通过 |
| 报告导出 | Implemented / Executed | Markdown + CSV；5 类报告 |
| 测试与文档 | Executed | 230 单元 + 38 集成通过；Ruff 通过 |

详细结果见 `docs/PHASE_05_TEST_REPORT.md` 与 `docs/PHASE_05_COMPLETION_REPORT.md`。

## 7. 下一步（Phase 06 建议，未开始）

1. 补充 `moderation_review` 与 `governance_feedback` 数据，启用人工一致性及线上误杀/漏判分析。
2. 积累策略多版本后再启用真实版本效果对比。
3. 在真实 Hive 引擎可用时执行 ADS SQL 并完成离线/在线对账。
4. 提升 `risk_result` 覆盖率，使模型运行指标能代表全量消息。

旧 schema Kafka 历史消息与 Hive 原生可行性仍应作为前置清理项处理。Phase 05 到此停止，不自动开始 Phase 06。
