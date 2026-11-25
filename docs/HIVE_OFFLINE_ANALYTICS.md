# Phase 05 — Hive 离线分析状态

## 1. 状态：Blocked（未执行）

Phase 05 没有把任何 Hive 查询标记为已运行。本机核验结果（2026-11-25）：

| 检查 | 结果 |
|---|---|
| `beeline` | NOT FOUND |
| `hive` | NOT FOUND |
| `hadoop` | NOT FOUND |
| Java / Kafka 运行 | 是（Kafka 使用独立运行目录，与 Hive 无关） |
| Docker / WSL | 项目约束禁止引入 |

结论：当前 Windows 11 原生环境没有 Hive 引擎，无法执行 DDL/DML、动态分区、ORC 构建或质量查询。不得用 Pandas 或 PostgreSQL 查询结果冒充 Hive 执行结果。

## 2. 已完成的准备工作

- Phase 02 已实现 PostgreSQL → CSV 快照导出与 manifest 水位（`claro warehouse-export`），并真实执行。
- `warehouse/hive/00_create_databases.sql` 至 `40_data_quality.sql` 已编写。
- `warehouse/hive/run_warehouse.ps1` 在缺少 Beeline 时明确失败，不伪装成功。
- Phase 05 新增 `warehouse/hive/50_phase05_ads.sql`：风险日报、治理日报、策略评估与模型表现 ADS 设计。
- Phase 05 新增 `docs/ANALYTICS_DATA_MODEL.md` 与 `docs/KPI_DEFINITIONS.md`，为后续 Hive 层提供统一口径。

## 3. 未完成集成

| 项目 | 状态 | 阻塞原因 |
|---|---|---|
| ODS 增量载入 Hive | Not Implemented（未执行） | 无 Hive 引擎 |
| DWD 清洗与关联 | Designed only | 无 Hive 引擎 |
| DWS 主题聚合 | Designed only | 无 Hive 引擎 |
| ADS 报表层 | Designed only | 无 Hive 引擎 |
| Hive 数据质量检查 | Designed only | 无 Hive 引擎 |
| PostgreSQL → Hive 调度与重试 | Not Implemented | 无 Hive 引擎 |

## 4. 可行的后续方案

1. 用户在 Windows 原生安装 Hadoop + Hive + Beeline，并启动 HiveServer2。
2. 使用 `warehouse/hive/run_warehouse.ps1` 传入 `-BeelinePath`、`-JdbcUrl`、`-OdsRoot`，按顺序执行分层 SQL。
3. 执行后核对 ADS 行数与 PostgreSQL 口径一致，再在报告中标记为 Executed / Verified。
4. 在 Hive 可用之前，所有分析查询在 PostgreSQL 上执行，并在 UI 与报告中标注数据来源。

## 5. 严格边界

- 本文件及 `50_phase05_ads.sql` 均为 **Designed**，不是 **Implemented/Executed**。
- 任何页面或报告不得显示「Hive 分析已完成」。
