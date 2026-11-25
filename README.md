# Claro

**Everything under control.**

Claro 是面向 SLG 场景的本地优先内容安全与风险治理平台。当前已实现 **Phase 02：数据工程**、**Phase 03：风险智能引擎**、**Phase 04：内容治理** 与 **Phase 05：数据分析与策略效果评估**，包括可重复合成数据、PostgreSQL 持久化、Kafka 生产/消费链路、Redis 业务缓存、Hive 分层 SQL、分层风险检测（规则 + ML）、风险融合与解释、模型评估与风险事件发布、策略中心与治理闭环，以及统一 KPI 口径、风险/社区/治理/模型分析、隔离策略回放、分析报告导出与六个分析页面。

## 验收状态

| 能力 | 状态与证据 |
|---|---|
| 合成数据生成器 | 已实现；默认 5,000 玩家、10 服务器、500 联盟、50,000 消息、40 条规则 |
| PostgreSQL | 24 张业务表；Phase 02 迁移升级/降级/再升级通过，Phase 03 head `c4a7e1d9b2f6` 已应用，`alembic check` 无漂移 |
| 默认数据集 | 50,000 条消息及标签、250,000 条处理事件真实落库，质量检查通过 |
| Kafka | 真实生产、消费、手动提交、重试、DLQ、Inbox 去重及 Group lag 检查通过 |
| Kafka → PostgreSQL | 100 条真实端到端测试、10 条重复投递验证通过；CLI 500 条链路通过 |
| Redis | 敏感词、策略、黑名单、风险计数、原子限流、规则缓存及 PostgreSQL 回退已验证 |
| Hive | PostgreSQL 导出与增量水位已验证；ODS/DWD/DWS/ADS SQL 已实现但**未执行** |
| 风险分类体系 | 19 类（18 风险 + normal）、7 个领域，YAML 配置；单元测试覆盖映射与校验 |
| 规则检测 | 22 条 YAML 规则；关键词、正则、否定词、黑白名单、重复消息检测通过 |
| ML 检测 | char_wb TF-IDF + OneVsRest 逻辑回归/线性 SVM；训练、保存、加载、预测、玩家级切分泄漏检查通过 |
| 风险融合 | 分层加权 noisy-OR、多标签、等级/动作映射、冲突与置信度解释，单元测试通过 |
| 评估 | 二分类与多标签指标、逐标签混淆矩阵、错误样例持久化；验证/测试集真实运行 |
| 风险持久化 | `risk_result` 唯一幂等；重复检测不新增结果；真实 PostgreSQL 验证通过 |
| 风险 Kafka 事件 | 持久化后发布 `game.risk.assessed.v1`；真实 Kafka 端到端验证通过 |
| PowerShell | 环境检查、服务状态、重复启动保护、Consumer 启停、Redis/Kafka 安全重启已验证 |
| 治理策略中心 | 11 类策略、结构化条件、版本/回滚/启停/冲突扫描/Playground，真实 PostgreSQL + Redis 缓存 |
| 治理决策 | 确定性优先级、冲突解决、严重度与置信度分离、自动/人工/观察分流、决策解释 |
| 人工审核 | 状态机、乐观锁、二次复核、重开、反馈提交、模拟身份切换 |
| 模拟处置 | WARN/BLOCK/MUTE/TEMP_BAN/PERM_BAN、玩家状态、到期/解除、幂等保护，全部 `simulated=true` |
| 反馈与审计 | 误杀/漏判与错误案例、原始模型结果对照、追加式审计日志、全链路 Trace |
| 治理事件流 | Outbox Pattern，6 类治理 Topic，真实 Kafka 发布验证（137 条事件 0 失败） |
| 治理 UI | 六个页面：总览、Policy Center、Moderation Workbench、Governance Decisions、Enforcement Center、Feedback & Audit；真实浏览器渲染验证 |
| 自动化 | **230 个单元测试通过，38 个真实集成测试通过**；Ruff 通过；6/6 治理 UI 页面 + 6/6 分析页面渲染通过 |
| Phase 05 分析层 | 27 条具名 SQL 在 PostgreSQL 真实执行；KPI 口径单一来源；数据质量检查通过 |
| Phase 05 回放 | 300 样本策略回放实际执行 23 处动作变化；正式决策与处置表行数不变 |
| Phase 05 报告 | 五类报告 Markdown + CSV 导出真实执行；Excel/PDF 未实现（无依赖） |

Hive 阻塞原因：当前 Windows 环境未安装原生 Hive、Hadoop 或 Beeline。不得将该部分标记为运行验证。语义检测器当前为显式不可用占位；LLM 顾问层默认关闭，未对真实端点验证。Phase 05 的 `moderation_review` 与 `governance_feedback` 为空，人工一致性及线上误杀/漏判不可计算；所有策略仅 v1，历史版本对比不可用。

## 原生环境快速开始

仅使用 Windows 原生服务，不引入容器化或 WSL 依赖。

```powershell
cd D:\桌面\Claro
.\scripts\claro.ps1 install
.\scripts\check_environment.ps1
.\scripts\start_services.ps1
.\scripts\init_database.ps1
.\scripts\check_services.ps1
.\scripts\claro.ps1 start
```

`init_database.ps1` 会提示输入数据库密码，或读取进程环境变量 `CLARO_DB_PASSWORD`；不会覆盖现有 `.env`。数据库密码应通过 `%APPDATA%\postgresql\pgpass.conf` 提供给应用，不写入连接 URL。

常用操作：

```powershell
.\scripts\generate_data.ps1
.\scripts\generate_data.ps1 -Load
.\scripts\start_pipeline.ps1
.\scripts\check_services.ps1 -IncludePipeline
.\scripts\stop_services.ps1 -Service Pipeline
.\scripts\stop_services.ps1
.\scripts\claro.ps1 test
.\scripts\claro.ps1 test -Integration
```

## 数据工程命令

```powershell
# 只生成并输出摘要
.\.venv\Scripts\python.exe -m claro generate-data --messages 1000 --output runtime\summary.json

# 全量加载到 PostgreSQL
.\.venv\Scripts\python.exe -m claro load-data --messages 1000

# 质量检查与定向清理
.\.venv\Scripts\python.exe -m claro check-data --dataset phase-02-synthetic-s20261125-p5000-m1000
.\.venv\Scripts\python.exe -m claro clean-data --dataset phase-02-synthetic-s20261125-p5000-m1000

# 独立 Kafka 生产者与消费者
.\.venv\Scripts\python.exe -m claro kafka-topics
.\.venv\Scripts\python.exe -m claro kafka-produce --messages 100 --topic game.messages.raw.smoke
.\.venv\Scripts\python.exe -m claro kafka-consume --topic game.messages.raw.smoke --persist --max-messages 100
.\.venv\Scripts\python.exe -m claro kafka-group --group claro.pipeline.v1

# PostgreSQL → Hive ODS 快照
.\.venv\Scripts\python.exe -m claro warehouse-export --full --output runtime\warehouse
```

## 风险引擎命令

```powershell
# 查看配置、启用检测器与 active 模型
.\.venv\Scripts\python.exe -m claro risk-status

# 同步 YAML 规则到 PostgreSQL（检测读取时仍走数据库/Redis）
.\.venv\Scripts\python.exe -m claro risk-sync-rules

# 在已加载的合成数据集上训练并登记模型
.\.venv\Scripts\python.exe -m claro risk-train --dataset phase-02-synthetic-s20261125-p5000-m50000

# 在指定 split 上评估并持久化指标与错误样例
.\.venv\Scripts\python.exe -m claro risk-evaluate --dataset phase-02-synthetic-s20261125-p5000-m50000 --split test

# 单条消息、整批待检测消息或直接文本
.\.venv\Scripts\python.exe -m claro risk-detect --message <message-id>
.\.venv\Scripts\python.exe -m claro risk-detect --dataset phase-02-synthetic-s20261125-p5000-m50000 --limit 200
.\.venv\Scripts\python.exe -m claro risk-detect --text "示例文本"

# 查看已存结果与证据
.\.venv\Scripts\python.exe -m claro risk-result --message <message-id>

# 消费 persisted 事件并发布风险评估事件
.\.venv\Scripts\python.exe -m claro risk-pipeline --max-messages 200

# 查看评估错误样例
.\.venv\Scripts\python.exe -m claro risk-cases --run <evaluation-run-id> --type borderline
```

## 内容治理命令

```powershell
# 初始化默认策略目录（42 条，幂等）
.\.venv\Scripts\python.exe -m claro governance-seed-policies

# 对一条消息评估策略 / 生成治理决策
.\.venv\Scripts\python.exe -m claro governance-evaluate --message <message-id>
.\.venv\Scripts\python.exe -m claro governance-decide --message <message-id>

# 治理总览、过期处置、Outbox 分发
.\.venv\Scripts\python.exe -m claro governance-status
.\.venv\Scripts\python.exe -m claro governance-expire-enforcements
.\.venv\Scripts\python.exe -m claro governance-dispatch-outbox

# 消费风险事件，执行评估→决策→审核→处置编排
.\.venv\Scripts\python.exe -m claro governance-pipeline --max-messages 200 --dispatch-outbox

# 启动治理 Web UI
.\.venv\Scripts\python.exe -m claro serve
```

## Phase 05 分析命令

```powershell
# 分析 KPI（全部来自 PostgreSQL 真实查询）
.\.venv\Scripts\python.exe -m claro analytics-overview --days 365
.\.venv\Scripts\python.exe -m claro analytics-risk --grain day
.\.venv\Scripts\python.exe -m claro analytics-community --limit 100
.\.venv\Scripts\python.exe -m claro analytics-governance
.\.venv\Scripts\python.exe -m claro analytics-model
.\.venv\Scripts\python.exe -m claro analytics-strategy
.\.venv\Scripts\python.exe -m claro analytics-quality

# 报告与隔离策略回放
.\.venv\Scripts\python.exe -m claro analytics-report --type daily_risk --output-dir runtime\reports
.\.venv\Scripts\python.exe -m claro strategy-replay --sample-limit 300 `
  --action-override gov-critical-risk-review=block --candidate-label "critical→block"
```

默认原始主题中保留了 Phase 02 早期 12 条旧 schema 冒烟消息。默认业务 Group 尚未消费它们；直接以 `earliest` 启动会把其路由到 DLQ。验收应使用新主题或明确处理这批历史消息。

## 配置

优先级：`config/default.yaml` < 模式 YAML < `.env` < 进程环境变量。

```dotenv
CLARO_APP__MODE=full
CLARO_DATABASE__URL=postgresql+psycopg://claro@127.0.0.1:5432/claro
CLARO_REDIS__URL=redis://127.0.0.1:6379/0
CLARO_KAFKA__BOOTSTRAP_SERVERS=127.0.0.1:9092
CLARO_UI__THEME=system
```

- development：SQLite + 内存事件总线，明确标记为模拟。
- full：必须使用真实 PostgreSQL、Redis、Kafka。
- PostgreSQL 是运营数据与审计的唯一权威来源；Redis 不是审计存储。
- 所有合成记录保留 `is_synthetic=True` 或数据集 synthetic 标记。
- 风险规则、分类体系、阈值位于 `config/detection_rules.yaml`、`config/risk_taxonomy.yaml`、`config/risk_thresholds.yaml`；LLM 凭据只从进程环境变量读取，不写入仓库。

## 文档

- [架构](docs/ARCHITECTURE.md)
- [数据模型](docs/DATA_MODEL.md)
- [开发计划与验收](docs/DEVELOPMENT_PLAN.md)
- [风险分类体系](docs/RISK_TAXONOMY.md)
- [风险引擎](docs/RISK_ENGINE.md)
- [风险评分](docs/RISK_SCORING.md)
- [模型评估](docs/MODEL_EVALUATION.md)
- [合成数据生成器](docs/DATA_GENERATOR.md)
- [Kafka 流水线](docs/KAFKA_PIPELINE.md)
- [Redis 缓存](docs/REDIS_CACHE.md)
- [Hive 数仓](docs/HIVE_WAREHOUSE.md)
- [原生部署](docs/DEPLOYMENT.md)
- [治理架构](docs/GOVERNANCE_ARCHITECTURE.md)
- [策略引擎](docs/POLICY_ENGINE.md)
- [审核工作流](docs/MODERATION_WORKFLOW.md)
- [处置模拟](docs/ENFORCEMENT_SIMULATOR.md)
- [治理数据模型](docs/GOVERNANCE_DATA_MODEL.md)
- [Phase 04 测试报告](docs/PHASE_04_TEST_REPORT.md)
- [Phase 04 完成报告](docs/PHASE_04_COMPLETION_REPORT.md)
- [Phase 05 集成审查](docs/PHASE_05_INTEGRATION_AUDIT.md)
- [分析架构](docs/ANALYTICS_ARCHITECTURE.md)
- [分析数据模型](docs/ANALYTICS_DATA_MODEL.md)
- [分析数据质量](docs/ANALYTICS_DATA_QUALITY.md)
- [KPI 统一口径](docs/KPI_DEFINITIONS.md)
- [风险分析](docs/RISK_ANALYTICS.md)
- [治理分析](docs/GOVERNANCE_ANALYTICS.md)
- [模型表现分析](docs/MODEL_PERFORMANCE_ANALYTICS.md)
- [策略评估](docs/STRATEGY_EVALUATION.md)
- [Hive 离线分析状态](docs/HIVE_OFFLINE_ANALYTICS.md)
- [Phase 05 测试报告](docs/PHASE_05_TEST_REPORT.md)
- [Phase 05 完成报告](docs/PHASE_05_COMPLETION_REPORT.md)

## 当前阶段边界

- Hive SQL 尚未在真实 Hive 引擎执行。
- 语义检测器只有显式不可用占位，不产生语义 finding。
- LLM 仅作为可选顾问层，默认关闭；没有真实端点验证记录。
- 模型指标来自合成模板数据，不代表真实游戏文本准确率。
- 所有治理处置均为平台内部模拟，不连接真实游戏服务器。
- UI 身份为模拟身份，鉴权/RBAC 与生产级高可用尚未实现。
- 分析层中人工审核标签、反馈标注与策略多版本历史缺失，相应指标标记为不可计算。
- Excel/PDF 报告导出未实现；仅提供 Markdown 与 CSV。
