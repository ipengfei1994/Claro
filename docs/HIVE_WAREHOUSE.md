# Claro Phase 02 — Hive 数仓

## 1. 当前状态

PostgreSQL 快照导出、manifest 水位和生成的 Hive `LOAD DATA` SQL 已真实执行。Hive ODS/DWD/DWS/ADS SQL 已编写，但当前 Windows 环境没有原生 Hive、Hadoop 或 Beeline，**未在 Hive 引擎执行**。

`warehouse/hive/run_warehouse.ps1` 在缺少 Beeline 时明确失败：

```text
Beeline was not found. Hive SQL was not executed.
```

## 2. 分层

| 层 | 表 | 格式/策略 |
|---|---|---|
| ODS | message、risk_event、policy_decision、moderation_record | external CSV，按 `dt` 分区 |
| DWD | message_detail、risk_detail、policy_decision_detail、moderation_record_detail | ORC，业务主键去重 |
| DWS | player_risk_daily | 按玩家/日期聚合 |
| ADS | risk_overview_daily | 风险总览聚合 |

质量 SQL 检查重复、内容哈希、孤儿风险、synthetic 标记及 ODS/DWD 数量对账。

## 3. PostgreSQL 导出

```powershell
# 全量快照
.\.venv\Scripts\python.exe -m claro warehouse-export --full --output runtime\warehouse

# 仅指定数据集
.\.venv\Scripts\python.exe -m claro warehouse-export --full --dataset phase-01-synthetic-v1 --output runtime\warehouse-smoke

# 从显式 UTC 时间增量导出
.\.venv\Scripts\python.exe -m claro warehouse-export --since 2026-11-25T00:00:00+00:00 --output runtime\warehouse-incremental

# 指定表
.\.venv\Scripts\python.exe -m claro warehouse-export --full --tables message risk_event --output runtime\warehouse-subset
```

输出结构：

```text
runtime/warehouse/
├── message/dt=YYYY-MM-DD/<batch-id>.csv
├── risk_event/dt=YYYY-MM-DD/<batch-id>.csv
├── policy_decision/dt=YYYY-MM-DD/<batch-id>.csv
├── moderation_record/dt=YYYY-MM-DD/<batch-id>.csv
├── manifest.json
└── load_ods.sql
```

- CSV 为 UTF-8、quote-all，null 使用 `\N`。
- manifest 记录每张表的高水位和导出时间。
- 增量查询使用 `>=` 边界包含，避免水位边界漏数。
- 空表在首次 manifest 无水位时回退到上次 `exported_at`。
- 新 batch 文件名不覆盖已有快照。
- 全量生成 `LOAD DATA ... OVERWRITE`；增量生成追加加载 SQL。

## 4. Hive 执行入口

安装原生 Hive/Hadoop/Beeline 后，先创建数据库和 ODS 外部表，再加载快照：

```powershell
.\warehouse\hive\run_warehouse.ps1 `
  -JdbcUrl "jdbc:hive2://127.0.0.1:10000/default" `
  -WarehouseRoot "file:///D:/claro-warehouse" `
  -OdsRoot "file:///D:/Claro/runtime/warehouse" `
  -BeelinePath "D:\apache-hive\bin\beeline.cmd" `
  -ExportDirectory "D:\Claro\runtime\warehouse"
```

脚本按顺序执行 create databases、create ODS、load ODS、build DWD、build DWS/ADS、data quality。任一脚本非零退出立即失败。

如果表已创建，可用 `-SkipLoad` 跳过 ODS 快照加载，但仍会执行后续构建与质量 SQL。

## 5. 验证边界

已真实验证：

- PostgreSQL 导出 Phase 01 数据：3 messages、3 policy decisions、0 risk events、0 moderation records。
- CSV 列、synthetic 标记、manifest 和 load SQL 正确。
- 增量导出使用 manifest 水位成功。

未执行：

- 任何 Hive DDL/DML。
- Hive ORC 构建、动态分区、DWS/ADS 聚合和质量查询。

在 Beeline 实际执行并核对结果前，不得将本文件中的 Hive SQL 标记为运行通过。
