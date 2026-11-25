# Phase 05 — 分析架构

## 1. 分层

```text
PostgreSQL (authoritative)
   ↓ SQL (claro.analytics.sql_queries)
claro.analytics.data_access.AnalyticsRepository
   ↓ rows
claro.analytics.services.AnalyticsService          ← KPI 口径唯一实现
claro.analytics.strategy.StrategyReplayService     ← 隔离回放
   ↓ plain dict
CLI / ReportService / Streamlit pages
```

Streamlit 页面只调用服务层，不执行 SQL，不重复计算指标。

## 2. 模块

| 模块 | 职责 |
|---|---|
| `definitions.py` | KPI 公式标识、口径哈希、数据分级、低样本阈值 |
| `filters.py` | 全局筛选器；半开时间窗；筛选参数下推到 SQL |
| `sql_queries.py` | 集中 SQL，具名常量，绑定参数，统一 `scoped` CTE |
| `data_access.py` | SQL 执行与行转换；只读写分析相关表 |
| `metrics.py` | 纯函数：去重、比率、分位数、混淆矩阵、动作差异 |
| `quality.py` | 主键/外键/重复/时间/覆盖率/口径检查 |
| `services.py` | 风险、社区、治理、模型、策略五个分析视图 |
| `strategy.py` | 策略回放、结果持久化与对比 |
| `reports.py` | Markdown 报告与 CSV 导出 |

## 3. 统一时间轴与去重

所有查询先构建 `scoped` CTE：以 `message.occurred_at` 为过滤字段，同时应用数据集、服务器、联盟、玩家筛选。风险消息子集 `risk` 再按类别/等级收窄，但分母不变。

一对多Join（risk_event、policy_decision、enforcement_action）在 SQL 中使用 `COUNT(DISTINCT message_id)` 或先聚合为每消息一行，避免指标膨胀。

## 4. 筛选器

`AnalyticsFilters` 支持：时间范围、数据集、服务器、联盟、玩家、风险类别、风险等级、策略、策略版本、模型版本。筛选器通过 `params()` 传入每条 SQL；UI 修改筛选器后服务结果和图表同步变化。

风险类别/等级筛选只作用于风险事件侧，这是固定口径，保证 Risk Rate 分母始终是全量筛选后的消息集合。

## 5. 数据分级展示

每个服务返回 `data_source_tier` 与 `data_source_label`：
- `OBSERVED`：引擎真实写入（如 evaluation_run、risk_result）。
- `SYNTHETIC_SNAPSHOT`：生成器写出的模拟业务过程（大部分风险与治理明细）。
- `DERIVED`：由上述数据按统一口径计算。

## 6. 回放隔离

回放读取历史消息、风险事件、标签与策略快照，在内存中执行两个策略集合，写入 `analytics_replay_run` / `analytics_replay_case`。不调用执行服务、不发布 Kafka 事件、不修改 `policy_decision` 或 `enforcement_action`。每次运行记录数据集、时间窗、候选参数、样本数、口径版本与 `simulation=true`。

## 7. 扩展点

- Hive 引擎可用后，可复用 `docs/KPI_DEFINITIONS.md` 口径实现 ADS 层；当前状态见 `docs/HIVE_OFFLINE_ANALYTICS.md`。
- 人工标注数据到位后，可启用模型-人工一致性与线上误杀/漏判，但需新增口径版本。
