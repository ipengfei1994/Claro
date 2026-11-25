# Phase 05 — Phase 01–04 集成审查

审计时间：2026-11-25 16:47 (UTC+8)
审计方式：直接读取本地仓库源码/配置，并以 `CLARO_APP__MODE=full` 连接本机 PostgreSQL 执行只读查询。
数据性质声明：**本项目中所有业务记录均为 Synthetic Data**。下文所有计数均来自本机数据库的真实查询，不代表任何真实线上运营数据。

---

## 1. 审查结论摘要

| 审查项 | 结论 | 状态 |
|---|---|---|
| PostgreSQL 业务表 | 31 张（含 `alembic_version`），表结构与 Phase 01–04 迁移一致 | Implemented / Verified |
| Kafka | 本机 127.0.0.1:9092 监听，Java 进程运行；Phase 01–04 已有生产者、消费者、Outbox、DLQ | Verified (running) |
| Redis | 本机 127.0.0.1:6379 监听；Phase 01–04 已有敏感词、策略、黑名单、限流与计数缓存 | Verified (running) |
| Apache Hive | 本机 `beeline` / `hive` / `hadoop` 均不存在；Phase 02 已生成 SQL 与导出快照，但引擎未执行 | **Blocked** |
| 风险链数据 | `risk_result` 仅 7 行；`risk_event` 8,856 行来自合成数据生成器，非在线风险检测产物 | Verified / 有缺口 |
| 治理链数据 | `policy_decision` 50,008 行，其中 50,003 行为生成器写入的 legacy 记录，`decision_status IS NULL` | Verified / 有缺口 |
| 人工审核数据 | `moderation_case` 4,039 行；`moderation_review` 0 行；`governance_feedback` 0 行 | Verified / 缺失 |
| 模型评估数据 | `ml_model` 1 个；`evaluation_run` 1 个；`evaluation_case` 264 行；`message_label` 50,000 行 | Verified |
| 策略版本 | 53 条策略 / 47 条 `policy_version`，**全部为 v1**，没有同一策略的多版本历史 | Verified / 缺失 |

**核心判断**：Phase 05 可以建立真实的分析链路，但必须严格区分三类数据来源——①生成器写入的合成业务快照；②真实引擎运行产生的记录；③模型评估持久化结果。不得把合成快照当作线上观测，也不得在缺失人工标签时声称准确率。

---

## 2. 可用数据资产与粒度

### 2.1 数据集

| dataset | 用途 | 关键事实 |
|---|---|---|
| `phase-01-synthetic-v1` | Phase 01 冒烟 | 3 条消息，非随机模板 |
| `phase-02-synthetic-s20261125-p5000-m50000` | **主分析数据集** | seed=20261125，5,000 玩家 / 10 服务器 / 500 联盟 / 50,000 消息 / 50,000 标签 |
| 4 × `phase-02-synthetic-gov-it-*` | Phase 04 集成测试 | 各 1 条消息，应默认从分析口径排除 |

### 2.2 表清单、粒度与关键字段

| 表 | 行数 | 粒度 | 关键关联字段 | 分析可用性 |
|---|---:|---|---|---|
| `dataset` | 6 | 一个数据集 | `id` | 维度；含 `generation_params`、`is_synthetic` |
| `server` | 10 | 一个服务器 | `id`, `dataset_id`, `server_ref` | 服务器维度 |
| `alliance` | 500 | 一个联盟 | `id`, `server_id`, `alliance_ref` | 联盟维度 |
| `player` | 5,000 | 一个玩家 | `id`, `server_id`, `alliance_id`, `player_ref` | 玩家维度；`risk_propensity` 为生成参数，不是观测违规率 |
| `message` | 50,007 | 一条消息 | `id`, `external_message_id`, `dataset_id`, `player_id`, `server_id`, `alliance_id`, `occurred_at` | 主事实表；`message_id` 用 UUID，业务标识用 `external_message_id` |
| `message_label` | 50,000 | 一条消息一个标注 | `message_id`, `label`, `risk_category`, `split` | **独立于检测结果的合成 ground truth**，仅用于可复现模型评估 |
| `processing_event` | 250,009 | 一条消息一个阶段一次事件 | `message_id`, `sequence`, `stage`, `status` | 处理链路追踪 |
| `detection_rule` | 63 | 一条规则一个版本 | `id`, `rule_key`, `version` | 规则维度 |
| `risk_finding` | 8,878 | 一次检测器命中 | `message_id`, `rule_id`, `detector`, `category`, `score` | 多标签明细；8,878 中绝大多数 detector 为 `synthetic-rule-engine` |
| `risk_event` | 8,856 | 一次风险识别事件 | `message_id`, `rule_id`, `category`, `severity`, `occurred_at` | **生成器合成事件**，非 `risk_result` 的在线产物 |
| `risk_result` | **7** | 一条消息一个最新融合结果 | `message_id`, `ml_model_id`, `risk_score`, `categories`, `detected_at` | 真实引擎结果；样本极小，不能代表全量 |
| `ml_model` | 1 | 一个模型版本 | `id`, `name`, `version`, `metrics`, `per_label_metrics`, `thresholds` | 模型版本维度 |
| `evaluation_run` | 1 | 一次评估运行 | `model_id`, `dataset_name`, `split`, `message_count`, `metrics`, `case_counts`, `leakage` | 模型指标的权威来源 |
| `evaluation_case` | 264 | 一个错误样例 | `run_id`, `message_id`, `error_type`, `truth_label`, `predicted_score` | FP/FN 与易混淆类别分析；仅含 borderline/conflicting 案例 |
| `policy` | 53 | 一条策略当前状态 | `id`, `policy_key`, `version`, `hit_count`, `enabled` | 策略维度；`hit_count` 为累计计数，无时间序列 |
| `policy_version` | 47 | 一个策略版本快照 | `policy_id`, `version`, `conditions`, `action`, `snapshot_hash` | **当前全部 v1**；版本对比缺乏历史 |
| `policy_evaluation` | 7 | 一次消息×策略快照评估 | `message_id`, `policy_snapshot_hash`, `matched_policies`, `suggested_action` | 唯一带完整输入快照的策略评估记录 |
| `policy_rule` | 40 | 一条策略规则 | `policy_id`, `detection_rule_id`, `threshold`, `action` | 策略规则明细 |
| `policy_decision` | 50,008 | 一次治理决策 | `message_id`, `policy_id`, `action`, `decision_status`, `requires_review`, `decided_at` | 50,003 行 legacy 合成记录 `decision_status IS NULL`；5 行真实治理决策 |
| `moderation_case` | 4,039 | 一个审核任务 | `message_id`, `decision_id`, `status`, `opened_at`, `closed_at` | 4,035 resolved，3 in_review，1 pending；仅 3 行有 `decision_id` |
| `moderation_review` | **0** | 一次人工审核操作 | `case_id`, `reviewer_ref`, `action`, `system_action`, `final_action` | **无数据**，无法计算审核耗时/一致性 |
| `moderation_record` | 7,770 | 一次审核动作记录 | `message_id`, `case_id`, `action`, `occurred_at` | 生成器合成记录，`actor_type` 非真实审核员会话 |
| `enforcement_action` | 1,208 | 一次模拟处置 | `decision_id`, `case_id`, `action_type`, `status`, `executed_at`, `simulated` | 1,206 `message_block` executed + 2 `mute` expired；全部 `simulated=true` |
| `player_enforcement_state` | 2 | 一个玩家×作用域状态 | `player_ref`, `mute_until`, `ban_until` | 状态快照，非历史 |
| `governance_feedback` | **0** | 一次反馈 | `message_id`, `decision_id`, `feedback_type` | **无数据**，无法基于反馈计算误杀/漏判 |
| `audit_event` | 1,846 | 一次审计事件 | `entity_type`, `entity_id`, `action`, `created_at` | 操作追溯 |
| `outbox_event` | 236 | 一次待发布事件 | `aggregate_id`, `topic`, `status`, `published_at` | Kafka 发布追溯 |
| `inbox_event` | 0 | 一次 Kafka 入站事件 | `source_topic`, `source_partition`, `source_offset` | 当前为空 |
| `player_blacklist_entry` | 0 | 一条黑名单记录 | `player_ref` | 当前为空 |

### 2.3 关联路径

现有模型使用 UUID 主键，不使用整数 ID。实际可追溯路径为：

```
message.id
  ├─ risk_finding.message_id          (多：一次检出多个类别)
  ├─ risk_event.message_id             (多：合成风险事件)
  ├─ risk_result.message_id            (一：最新融合结果，仅 7 行)
  ├─ policy_evaluation.message_id      (多：按 policy_snapshot_hash 唯一)
  ├─ policy_decision.message_id        (多：每个决策一行)
  │    └─ enforcement_action.decision_id (多)
  ├─ moderation_case.message_id        (一：每消息一个 case)
  │    ├─ moderation_review.case_id     (多，当前 0 行)
  │    └─ case_event.case_id            (多)
  └─ governance_feedback.message_id    (多，当前 0 行)
```

`moderation_case.decision_id` / `moderation_review.decision_id` 提供到决策的反向关联，但当前仅 3 行有值。
`policy_decision.policy_evaluation_id` 提供到评估记录的关联，当前仅 5 行有值。

**计数原则**：`message → risk_event`、`message → policy_decision`、`decision → enforcement` 均为一对多。任何跨这些实体的 COUNT 必须先按 `message_id` 做 `COUNT(DISTINCT ...)` 或预聚合，否则风险率会被放大。

---

## 3. 数据来源分级

Phase 05 将读取到的数据分为三级，UI 与报告必须显示来源：

| 级别 | 定义 | 例子 |
|---|---|---|
| OBSERVED | 真实运行引擎/服务写入的记录 | `risk_result`(7)、`policy_evaluation`(7)、5 条真实 `policy_decision`、`evaluation_run` |
| SYNTHETIC_SNAPSHOT | 生成器批量写入的业务快照，模拟一个完整业务过程 | 49,000+ 条 `risk_event`、`policy_decision`、`moderation_case`、`enforcement_action` |
| DERIVED | 基于上述数据按统一口径计算 | 所有 KPI、趋势、对比、回放指标 |

`message_label` 属于合成 ground truth，只用于可复现模型评估；它不是人工标注的线上真值。

---

## 4. 缺失数据与指标可行性

### 4.1 可直接计算（基于现有字段，需注明口径）

- 消息总量、风险事件量、风险率（按 `risk_event.message_id` 去重）
- 风险类别/等级分布、时间趋势、服务器/联盟/玩家维度分布
- 重复违规玩家（在指定窗口内 `COUNT(DISTINCT message_id) > 1`）
- 决策动作分布、审核任务状态分布、模拟处置分布
- 模型指标（从 `evaluation_run.metrics` / `per_label` 读取，不重新计算）
- 策略命中计数（`policy.hit_count`，仅累计值；明细命中用 `policy_evaluation.matched_policies`）

### 4.2 需补充数据或严格限定后方可计算

| 指标 | 障碍 | Phase 05 处理 |
|---|---|---|
| Automatic Handling Rate | 50,003/50,008 决策 `decision_status IS NULL` | 仅在 `decision_status IS NOT NULL` 子集计算，并显示样本量 |
| 审核平均耗时 / P50 / P90 | `moderation_review` 0 行；`moderation_case.closed_at` 来自生成器 | 用 `opened_at → closed_at` 计算**任务关闭耗时**并标注 SYNTHETIC_SNAPSHOT；不称为人工审核耗时 |
| 人工推翻率 / 模型-人工一致率 | `moderation_review` 0、`governance_feedback` 0 | 明确为 Not Implemented（数据缺失），UI 显示空状态 |
| 基于反馈的误杀/漏判 | `governance_feedback` 0 | 使用 `message_label` + `evaluation_case` 的评估口径，并标注为离线评估而非线上反馈 |
| Policy Version Comparison | 所有策略只有 v1 | 提供同数据集上的候选版本离线回放对比（Simulation），不声称历史版本效果 |
| 策略命中率（明细） | `hit_count` 无时间维度，且 `policy_evaluation` 仅 7 行 | 命中率分母限定为有评估记录的消息数，并标注样本量 |
| 关联缺失率 | `policy_decision` 中仅 5 行有 `policy_evaluation_id` | 数据质量报告中作为「关联记录缺失」列出 |

### 4.3 明确不可声称的能力

- 不声称模型-人工一致率（无人工标签）。
- 不声称线上误杀率/漏判率（无反馈标注）。
- 不声称策略多版本历史对比（无多版本数据）。
- 不声称 Hive 分析已执行（引擎不可用）。

---

## 5. Kafka / Redis / Hive 环境核验

### 5.1 Kafka（已运行）

- 监听：`127.0.0.1:9092`，Java 进程 PID 4956。
- 现有 Topic（来自 `runtime/kafka-logs/` 与配置）：`game.messages.raw`、`game.messages.retry`、`game.messages.processed`、`game.risk.events`、`game.moderation.events`、`game.governance.evaluated.v1`、`game.governance.decisions.v1`、`game.governance.moderation.v1`、`game.governance.enforcement.v1`、`game.governance.feedback.v1`、`claro.content.events.v1`。
- Phase 05 不新增业务 Topic；分析数据从 PostgreSQL 读取，回放结果写入新的分析表（通过 Alembic 迁移），不通过 Kafka 触达生产链。

### 5.2 Redis（已运行）

- 监听：`127.0.0.1:6379`，PID 18804。
- 现有缓存用途：敏感词、策略快照、玩家黑名单、风险计数、原子限流。
- Phase 05 不引入新的 Redis 键；如需缓存分析结果，必须注明缓存失效策略且不得作为审计来源。

### 5.3 Hive（Blocked）

- `command -v beeline` / `hive` / `hadoop` 均返回 NOT FOUND。
- `runtime/kafka-logs` 之外的 `runtime/warehouse-smoke` 仅含少量导出 CSV；`warehouse/hive/*.sql` 已存在但未在引擎执行。
- 阻塞原因：Windows 11 本机未安装原生 Hive/Hadoop/Beeline。项目约束禁止 Docker/WSL，因此不能通过容器补齐。
- Phase 05 只能继续复用 PostgreSQL 导出脚本与现有 Hive SQL 资产，并新增 ADS SQL 设计；**不得标记为 Executed / Verified**。

---

## 6. 需要扩展的模块

1. **分析数据层**：新建 `src/claro/analytics/`，封装 SQL 与指标计算；UI 不直接写 SQL。
2. **统一指标定义**：新建 `docs/KPI_DEFINITIONS.md`，全项目唯一口径来源。
3. **数据质量**：新建 `analytics/quality.py`，实现主键、外键、时间、重复、缺失、口径检查。
4. **回放隔离**：新增 Alembic 迁移建立 `analytics_replay_run` / `analytics_replay_case` 表；回放只读历史消息，结果写入分析表，绝不修改 `policy_decision` / `enforcement_action`。
5. **报告导出**：复用现有 pandas/openpyxl 可用性检查，不引入大型依赖。
6. **UI**：新增 6 个分析页面，复用现有 `theme_style` 与页面模式；全局筛选器必须下推到服务层。
7. **Hive**：仅补充 ADS SQL 设计与 ETL 说明，状态保持 Blocked。

---

## 7. 审计确认

- [x] 已确认每张表的实际行数与粒度。
- [x] 已确认实体关联路径与一对多关系。
- [x] 已确认缺失数据及其对指标的影响。
- [x] 已确认 Hive 环境不可用。
- [x] 在确认数据来源之前未编写任何 KPI。
