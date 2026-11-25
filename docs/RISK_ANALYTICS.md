# Phase 05 — Risk Analytics 实现说明

## 1. 实现范围

已实现：风险总览、趋势（hour/day/week/month）、类别分布、等级分布、共现矩阵、异常峰值、服务器/联盟/玩家维度分布、重复违规玩家。

指标公式以 `docs/KPI_DEFINITIONS.md` 为唯一依据；本文件不重复定义公式。

## 2. 页面与查询映射

| 页面 | 服务方法 | SQL |
|---|---|---|
| Analytics · 总览 | `AnalyticsService.overview` | `SQL_OVERVIEW`, `SQL_REPEAT_OFFENDERS`, `SQL_GOVERNANCE_TOTALS` |
| Analytics · 风险 | `AnalyticsService.risk` | `daily_counts_sql`, `SQL_CATEGORY_DISTRIBUTION`, `SQL_SEVERITY_DISTRIBUTION`, `SQL_COOCCURRENCE` |
| Analytics · 社区 | `AnalyticsService.community` | `SQL_SERVER_RANKING`, `SQL_ALLIANCE_RANKING`, `SQL_PLAYER_PROFILE` |

## 3. 关键实现决策

1. **Risk Rate 唯一口径**：`COUNT(DISTINCT risk_event.message_id) / COUNT(DISTINCT message.id)`，时间过滤统一使用 `message.occurred_at`。
2. **多标签**：风险消息数按消息去重；类别分布按 `(message_id, category)` 去重，因此类别占比之和可超过 100%。
3. **等级分布**：每条消息取最高 severity 进入单一桶，使用 `ROW_NUMBER()` 实现，避免多等级重复计数。
4. **共现矩阵**：当前合成生成器每条消息只产生一个风险类别，共现结果为空是真实情况，页面显示空状态而非伪造数据。
5. **异常峰值**：基于同一窗口桶序列的 `mean + 3σ`，只标记统计异常，不推断原因。

## 4. 实测结果（2026-11-25，主数据集，2026-01-01 → 2026-03-01）

| 指标 | 值 |
|---|---:|
| 消息数 | 50,000 |
| 风险消息 | 8,856 |
| Risk Rate | 0.17712 |
| 高风险消息 | 4,035 |
| 去重风险玩家 | 3,130 |
| 重复违规玩家（阈值 2） | 1,874 |
| 类别共现消息 | 0 |

## 5. 限制

- `risk_event` 为 Phase 02 生成器合成事件，不是在线风险检测产物；`risk_result` 仅 7 行，不能替代全量。
- 玩家风险画像不表示恶意；`risk_propensity` 是生成参数。
- 时间桶按 UTC 日期计算，展示层按本机时区格式化。
