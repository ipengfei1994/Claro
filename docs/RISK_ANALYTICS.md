# Phase 05 — Risk Analytics 实现说明

## 1. 实现范围

已实现：风险总览、趋势（hour/day/week/month）、类别分布、等级分布、共现矩阵、异常峰值、服务器/联盟/玩家维度分布、重复违规玩家、检测层识别质量（误杀率/漏判率）。

指标公式以 `docs/KPI_DEFINITIONS.md` 为唯一依据；本文件不重复定义公式。当前口径版本 `phase-05.2`。

## 2. 页面与查询映射

| 页面 | 服务方法 | SQL |
|---|---|---|
| Analytics · 总览 | `AnalyticsService.overview` | `SQL_OVERVIEW`, `SQL_REPEAT_OFFENDERS`, `SQL_GOVERNANCE_TOTALS`, `SQL_DETECTION_QUALITY` |
| Analytics · 风险 | `AnalyticsService.risk` | `daily_counts_sql`, `SQL_CATEGORY_DISTRIBUTION`, `SQL_SEVERITY_DISTRIBUTION`, `SQL_COOCCURRENCE` |
| Analytics · 社区 | `AnalyticsService.community` | `SQL_SERVER_RANKING`, `SQL_ALLIANCE_RANKING`, `SQL_PLAYER_PROFILE` |

## 3. 关键实现决策

1. **Risk Rate 唯一口径**：`COUNT(DISTINCT risk_event.message_id) / COUNT(DISTINCT message.id)`，时间过滤统一使用 `message.occurred_at`。
2. **多标签**：风险消息数按消息去重；类别分布按 `(message_id, category)` 去重，因此类别占比之和可超过 100%。
3. **等级分布**：每条消息取最高 severity 进入单一桶，使用 `ROW_NUMBER()` 实现，避免多等级重复计数。
4. **共现矩阵**：当前合成生成器每条消息只产生一个风险类别，共现结果为空是真实情况，页面显示空状态而非伪造数据。
5. **异常峰值**：基于同一窗口桶序列的 `mean + 3σ`，只标记统计异常，不推断原因。
6. **JOIN 扇出防护**：所有消息级指标使用 `COUNT(DISTINCT ...)`；`risk` / `high_risk` 子查询使用 `SELECT DISTINCT re.message_id`。实测 `scoped × risk_event` 原始 JOIN 行数（8,856）与 DISTINCT 路径完全一致，无膨胀。
7. **检测层识别质量**（`phase-05.2` 新增）：误杀率/漏判率不再只依赖 `risk_result`（仅 7 行），而是新增 `SQL_DETECTION_QUALITY`——以 `risk_event` 为检测输出、合成 `message_label` 为 ground truth，在**窗口内全部消息**上计算混淆矩阵。样本量从 3 提升到 50,000，指标从此具备可复核的分母。

## 4. 实测结果（2026-11-25，主数据集，2026-01-01 → 2026-03-01）

数据集共 50,000 条消息，全部落在该窗口内。

| 指标 | 值 |
|---|---:|
| 窗口内消息数 | 50,000 |
| 风险消息 | 8,856 |
| Risk Rate | 0.17712 |
| 高风险消息 | 4,035 |
| 高风险率 | 0.0807 |
| 去重风险玩家 | 3,130 |
| 重复违规玩家（阈值 2） | 1,874 |
| 类别共现消息 | 0 |

### 4.1 检测层识别质量

| 指标 | 值 | 分子/分母 |
|---|---:|---|
| Precision | 0.661134 | TP=5,855 / (TP+FP=8,856) |
| Recall | 1.000000 | FN=0 |
| FPR（误杀率） | 0.067981 | FP=3,001 / (FP+TN=44,145) |
| FNR（漏判率） | 0.000000 | FN=0 / (FN+TP=5,855) |
| F1 | 0.796003 | — |
| Sample Size | 50,000 | 窗口内全部已标注消息 |

该矩阵已用独立 EXISTS / IN 子查询路径重算复核，逐项一致。UI 中该指标标注为「误杀率（检测层）」以区别于真实人工审核口径。

> 口径稳定性说明：本轮审查发现集成测试曾永久改写共享演示库中部分消息的 `occurred_at` 且不恢复，使窗口内消息数在 49,995–50,000 间逐次漂移。已修复测试并恢复数据，当前分母恒为 50,000，可在重复运行中复现。

## 5. 限制

- `risk_event` 为 Phase 02 生成器合成事件，不是在线风险检测产物；`risk_result` 仅 7 行，不能替代全量。因此检测层误杀/漏判基线是**合成 ground truth 上的离线指标**，不代表线上真实标注效果。
- 玩家风险画像不表示恶意；`risk_propensity` 是生成参数。
- 时间桶按 UTC 日期计算，展示层按本机时区格式化。
