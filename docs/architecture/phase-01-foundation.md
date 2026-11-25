# Claro Phase 01 — Architecture & Foundation

## 1. 目标与范围

Phase 01 建立可长期扩展的模块化单体工程基础，重点验证：

- Windows 11 + Python 3.12 可安装与启动。
- UI、Application、Domain、Data Access、Infrastructure 分层清晰。
- development 模式不依赖外部服务或 LLM 凭证。
- full 模式使用真实 PostgreSQL、Redis、Kafka，并明确报告连接失败。
- PostgreSQL 核心模型可通过 Alembic 重复迁移。
- 合成数据可重复生成且来源可追踪。
- Hive 只定义后续部署和接口，不假装已经集成。

本阶段不实现完整审核流水线、人工审核业务页面、ML/LLM 检测、Hive 查询、鉴权/RBAC 或生产部署。

## 2. 架构决策

| 决策 | 原因 |
|---|---|
| 模块化单体 | 保持本地部署简单，同时为后续业务模块保留清晰边界 |
| Python 3.12 | 当前环境已安装，避免默认 3.10 与 3.14 混用 |
| `src` 布局 + 可编辑安装 | 源码、配置和运行目录分离 |
| Pydantic + YAML + `.env` | 类型校验、模式配置和密钥隔离 |
| SQLAlchemy 2 + Alembic | 统一 ORM、仓储和可重复迁移 |
| Windows 原生服务 | 所有运行依赖使用本机进程或 Windows 服务，不依赖容器化编排 |
| Hive 后置 | 本阶段没有离线分析业务，不为了形式启动全部服务 |

## 3. 分层与依赖

```text
Streamlit UI
    ↓
Application 用例与服务
    ↓
Domain 实体、值对象、领域规则
    ↑
Application Ports
    ├── Data Access：SQLAlchemy 仓储、ORM、事务
    └── Infrastructure：PostgreSQL、Redis、Kafka 技术适配器
```

- UI 不执行 SQL，不包含核心业务规则。
- Application 负责用例编排、事务边界和端口调用。
- Domain 不依赖 SQLAlchemy、Streamlit、Redis 或 Kafka。
- Data Access 实现仓储端口，ORM 模型不属于 Domain。
- Infrastructure 只处理技术协议，不承载审核策略。
- `src/claro/bootstrap.py` 是唯一组成根，负责装配和资源释放。

后续业务模块按 content、risk、policy、moderation、enforcement、analytics 拆分，避免 Application 层膨胀。

## 4. 配置系统

优先级：

```text
default.yaml < mode YAML < .env < process environment
```

实现约束：

- 嵌套环境变量使用 `CLARO_<SECTION>__<FIELD>`。
- UI 主题使用 `CLARO_UI__THEME=system|light|dark`，系统模式通过 CSS 媒体查询实现。
- 未知环境变量和未知配置字段会被拒绝。
- 配置在启动时校验并冻结，避免运行中隐式变化。
- `.env` 不纳入 Git，日志不输出明文密码。
- SQLite 相对路径、日志目录均基于项目根目录解析。

### 模式能力矩阵

| 能力 | development | full |
|---|---|---|
| 数据库 | SQLite，真实本地持久化 | PostgreSQL，真实持久化 |
| 事件总线 | 内存同步模拟 | Kafka 真实适配器 |
| Redis | disabled | 真实缓存/计数器适配器 |
| Kafka | disabled | 真实生产/消费适配器 |
| Hive | 未实现 | 未实现 |
| 外部 LLM | 不需要 | 不需要 |

development 的内存总线状态为 `in-memory-simulation`，不能等同于 Kafka。full 模式缺少 PostgreSQL、Redis 或 Kafka 时，健康检查和启动验证会失败。

## 5. 核心数据模型

所有时间统一为 UTC。PostgreSQL 使用 `TIMESTAMPTZ` 保存带时区时间；SQLite 保存规范化后的 naive UTC，并由 ORM 在读写时恢复为 UTC 感知时间。UUID、JSON、`DECIMAL(5,4)` 和检查约束在两种数据库之间保持契约一致。

| 表 | 职责 | 关键约束 |
|---|---|---|
| `dataset` | 合成数据来源与生成参数 | `name` 唯一，包含 seed |
| `message` | 消息内容、发送方、渠道、状态 | `external_message_id` 唯一，内容非空 |
| `processing_event` | 消息处理阶段追踪 | `(message_id, sequence)` 唯一 |
| `detection_rule` | keyword/regex 规则及版本 | `(rule_key, version)` 唯一 |
| `risk_finding` | 风险类别、评分、置信度、证据 | score/confidence 在 0–1 |
| `policy` | 策略版本与定义 | `(policy_key, version)` 唯一 |
| `policy_decision` | 决策动作、风险分、原因码 | 关联 message/policy |
| `moderation_case` | 人工审核工单 | 每个 message 最多一个 case |
| `case_event` | 工单追加式操作历史 | 关联 case |
| `enforcement_action` | 执法动作与执行状态 | `idempotency_key` 唯一 |
| `audit_event` | 关键操作审计 | entity/action/trace 可检索 |

`message -> processing_event/risk_finding/policy_decision -> moderation_case/enforcement_action` 形成可追踪治理链路。合成消息同时具有 `dataset_id` 和 `is_synthetic=True`，数据集记录固定种子与生成参数。

## 6. 事务与异步语义

已实现：

- Application 管理事务，仓储不自行提交。
- `external_message_id` 防止重复消息。
- `processing_event.sequence` 保证处理顺序可追踪。
- `enforcement_action.idempotency_key` 防止重复执法。
- Kafka `EventEnvelope` 包含 `event_id`、`event_type`、`schema_version`、`occurred_at`、`trace_id`、`payload`。
- Kafka 生产者启用 `acks=all` 和幂等生产。

后续接入真实 ingestion worker 时再实现 outbox/inbox、重试、死信和消费去重；Phase 01 不把内存总线冒充异步流处理。

## 7. 基础设施边界

### PostgreSQL

运营数据唯一可信来源。连接使用 SQLAlchemy engine/session factory 和 psycopg 3，启用 `pool_pre_ping`。迁移由 Alembic 管理，开发库为 SQLite，full 模式要求 `postgresql+psycopg://` URL。

### Redis

用于缓存、黑名单、限流和计数器。适配器提供 get/set/increment/delete/health；Redis 不作为运营数据持久化来源。

### Kafka

用于异步事件传输。适配器提供 publish、topic 创建、元数据健康检查和生产/消费回环。本地配置采用单节点 KRaft，生产环境需单独设计副本、ACL、TLS 和监控。

### Hive（后续）

建议部署组件：

- Hadoop HDFS 或对象存储。
- Hive Metastore。
- HiveServer2。
- 独立离线分析任务，不与在线审核请求耦合。

数据接口：

1. PostgreSQL 按 `dt`、`server_ref` 导出 Parquet。
2. Hive 使用 external table 读取离线快照。
3. `OfflineAnalyticsPort` 提供 `risk_summary(start, end)` 和 `policy_effectiveness(start, end)`。
4. 返回不可变 `RiskSummary`、`PolicyEffectiveness` DTO。

Phase 01 不包含 Hive 服务、Hive JDBC 适配器或分析实现。

## 8. 本地部署

### Windows 原生服务（唯一支持方案）

- PostgreSQL：Windows 原生安装，初始化 SQL 位于 `deploy/postgresql/init/001-create-claro.sql`。
- Redis：Windows 原生 Redis 8.10.3，参考 `deploy/redis/redis.conf`，启用 AOF。
- Kafka：Microsoft OpenJDK 17 + Apache Kafka 3.9.2，参考 `deploy/kafka/server.properties`，使用单节点 KRaft。
- `scripts/check_environment.ps1`、`scripts/start_services.ps1`、`scripts/check_services.ps1`、`scripts/stop_services.ps1` 管理环境、状态和进程生命周期。
- Phase 02 的 `scripts/start_pipeline.ps1` 管理 Consumer 与 Streamlit 的 PID、日志和重复启动保护。
- 所有服务通过 `.env` 接入；容器化编排和 WSL 不属于支持方案。

## 9. 日志与安全

- structlog JSON 日志，控制台与滚动文件双输出。
- 密码、token、secret、authorization、api_key 字段脱敏。
- 数据库 URL 仅用于内部连接，CLI 输出会屏蔽密码。
- 原生服务默认只监听本地回环地址。
- `.env`、数据库文件、日志和运行目录不纳入 Git。

尚未实现认证、RBAC、审计保留策略和生产密钥管理，这些属于后续业务阶段。

## 10. 验证策略

- `pytest` 默认执行单元/契约测试，排除 integration marker。
- `pytest -m integration` 要求 full 模式和真实服务；配置缺失时测试明确失败。
- Alembic 验证 upgrade、downgrade、upgrade 和 `alembic check` 无漂移。
- Streamlit 状态页必须通过浏览器冒烟测试。
- 本机 PostgreSQL 18、Windows 原生 Redis 8.10.3 和 Kafka 3.9.2 均已运行；无 Docker、无 WSL 的真实服务验收已完成。

## 11. 当前验证结果

- Python 3.12.10 虚拟环境安装成功。
- Ruff lint 与 format 检查通过。
- 24 个单元/契约测试通过。
- PostgreSQL、Redis、Kafka 共 3 个真实集成测试通过：`3 passed, 24 deselected`。
- PostgreSQL Alembic 当前版本为 `ee9e95d718c3 (head)`，`alembic check` 无新增操作。
- SQLite Alembic 迁移回环成功。
- 合成数据首次创建成功，后续执行保持幂等，3 条消息均标记 synthetic。
- PowerShell `check`、`test`、`test -Integration`、`migrate`、`seed` 工作流通过。
- Redis 8.10.3 在 `127.0.0.1:6379` 返回 PONG，AOF 启用，真实读写/计数/TTL 测试通过。
- Kafka 3.9.2 在 `127.0.0.1:9092/9093` 启动，主题 `claro.content.events.v1` 为 1 分区、1 副本，真实生产/消费回环通过。
- `start-native`/`check-native`/`stop-native` 已验证；停止后重启保留 Kafka 元数据与主题。
- full 模式健康检查返回 PostgreSQL、Redis、Kafka 全部 healthy。
- PowerShell 启动脚本可拉起 Streamlit；Playwright 使用本机 Chrome 验证 full 模式、kafka 传输、三项 healthy、明暗主题和零控制台错误。
- 数据库密码未写入连接 URL 或聊天；本机使用 `%APPDATA%\postgresql\pgpass.conf`。
