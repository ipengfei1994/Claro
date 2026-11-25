# Phase 05 — Completion Report

**Analytics & Strategy Evaluation · Claro**
完成时间：2026-11-25 (UTC+8)
验收审查时间：2026-11-25 (UTC+8)，见 `docs/PHASE_05_ACCEPTANCE_REVIEW.md`

状态词严格区分：Implemented（已实现）、Executed（已实际运行）、Tested（已测试）、Verified（已验证）、Designed（仅设计）、Not Implemented（未实现）、Blocked（环境阻塞）。

---

## 1. 完成概述

Phase 05 建立了统一分析数据层、五类分析视图、隔离策略回放、分析报告导出与六个 Streamlit 页面。所有指标口径集中在 `docs/KPI_DEFINITIONS.md`，所有 SQL 集中在 `src/claro/analytics/sql_queries.py`，UI 不直接执行 SQL。

完成初版后，追加了一轮**三项验收标准实证审查**（指标可信性 / 策略评估科学性 / 回放隔离性），以真实 PostgreSQL 执行结果为准，修复 6 个实质缺陷并将口径版本升至 `phase-05.2`。审查报告见 `docs/PHASE_05_ACCEPTANCE_REVIEW.md`。

**未声称完成的部分**：Hive 引擎执行（Blocked）、人工审核一致性（Not Implemented，数据缺失）、线上误杀/漏判（Not Implemented，数据缺失）、真实策略历史版本对比（Not Implemented，数据缺失）。

## 2. Phase 01–04 集成审查

Implemented / Executed / Verified。报告见 `docs/PHASE_05_INTEGRATION_AUDIT.md`。核心发现：31 张表、50,007 条消息、8,856 条合成风险事件、50,008 条决策；`moderation_review` 与 `governance_feedback` 为 0；所有策略仅 v1。

## 3. 分析数据架构

Implemented / Verified。分层见 `docs/ANALYTICS_ARCHITECTURE.md`。PostgreSQL 为唯一查询来源；分析服务返回 plain dict；CLI、报告、UI 共享同一服务层。

## 4. 数据粒度与维度设计

Implemented / Verified。见 `docs/ANALYTICS_DATA_MODEL.md`。定义 9 类事实粒度、11 类维度，明确 UUID 关联路径与一对多去重规则。

## 5. 数据质量检查

Implemented / Executed / Tested。见 `docs/ANALYTICS_DATA_QUALITY.md`。主键、外键、重复、时间、覆盖率、合成标记、口径哈希检查均已执行；error 级检查全部通过，warning 级缺口已显式记录。

## 6. KPI 指标定义

Implemented / Verified / Tested。`docs/KPI_DEFINITIONS.md` 为全项目唯一口径文档；`analytics.definitions.KPI_FORMULAS` 派生口径哈希并在质量检查中比对。当前版本 **`phase-05.2`**。

`phase-05.2` 相对 `phase-05.1` 的实质变更：

| 变更 | 内容 | 目的 |
|---|---|---|
| 新增 §0.1 低样本门禁 | `MIN_RATE_DENOMINATOR = 30`；分母不足时返回 `value=None` + `numerator`/`denominator`/`sample_size`/`reason` | 防止 n=1 的比率被当作权威 KPI 发布 |
| 新增 §0.2 JOIN 扇出防护 | 规定 `COUNT(DISTINCT)`、`SELECT DISTINCT` CTE、EXISTS/IN 独立路径三重校验 | 防止一对多 JOIN 放大统计量 |
| 新增 §1.1 检测层识别质量 | 以 `risk_event` 为检测输出、`message_label` 为 ground truth 的全窗口混淆矩阵 | 为误杀率/漏判率提供可复核基线 |
| 重写 §5 策略评估 | 逐策略 Precision / Recall / FPR / FNR / 人工审核占比 | 使「命中多 ≠ 效果好」可被数据检验 |
| 重写 §6 回放差异指标 | 混淆矩阵逐条推导；样本池口径公开 | 消除「命中」与「预测为正」的口径混用 |

## 7. Risk Analytics

Implemented / Executed / Tested，见 `docs/RISK_ANALYTICS.md`。

实测（主数据集，窗口 2026-01-01 → 2026-03-01，口径 `phase-05.2`）：

| 指标 | 值 |
|---|---:|
| 窗口内消息数 | 50,000 |
| 风险消息 | 8,856 |
| Risk Rate | 0.17712 |
| 高风险消息 | 4,035 |
| 高风险率 | 0.0807 |
| 去重风险玩家 | 3,130 |
| 重复违规玩家（阈值 2） | 1,874 |

数据集共 50,000 条消息，全部落在该窗口内。所有比例的分母统一为窗口内消息数。

> 注：本轮审查发现集成测试曾永久篡改共享演示库中 5 条消息的 `occurred_at`（不恢复），导致窗口内消息数在 49,995–50,000 之间逐次漂移。已修复测试并按生成器不变量恢复数据，口径分母现已稳定可复现。详见 `docs/PHASE_05_ACCEPTANCE_REVIEW.md` 缺陷 6。

检测层识别质量（`phase-05.2` 新增）：

| 指标 | 值 |
|---|---:|
| Detection Precision | 0.661134 |
| Detection Recall | 1.000000 |
| Detection FPR | 0.067981 |
| Detection FNR | 0.000000 |
| Sample Size | 50,000 |

该混淆矩阵以独立 EXISTS / IN 子查询路径重算复核，逐项一致。类别共现为空是真实数据情况。

## 8. Community Analytics

Implemented / Executed / Tested。服务器、联盟、玩家三维分析；低样本阈值 30；玩家画像标注为模拟治理用途，未泄露模型概率为「违规概率」。玩家画像的 `sanctions` 统计已从全表口径修正为窗口内口径（经 `policy_decision → scoped` 关联），与同行其他指标统一时间范围。

## 9. Governance Analytics

Implemented / Executed / Tested，见 `docs/GOVERNANCE_ANALYTICS.md`。

自动处置率分母限定为有决策状态记录；审核耗时明确为合成任务关闭耗时；模拟处置全部带 `simulated=true`。

**低样本门禁行为（`phase-05.2` 新增）**：主数据集窗口内 `eligible_finalized_decisions = 1`（其余 50,003 条决策 `decision_status` 为 NULL，属生成器 legacy 记录）。此前页面会显示「自动处置率 0% / 人工审核率 100%」，这会把单个观测样本误读为系统行为。现在：

```
automatic_handling_rate = None   # 0/1，样本量 1 < 30，比例不可解读
review_rate             = None   # 1/1，同上
override_rate           = None   # 分母为 0，不可计算
```

UI 显示「不可计算」并附样本量与原因，而非 0 或 1。

`observed_confusion`（基于 `risk_result` 的真实引擎输出，3 个样本）保留展示但标记 `low_sample=True` / `interpretable=False`，避免把 3 样本噪声当结论；全量误杀/漏判基线改由检测层混淆矩阵（§7）承担。

## 10. Model Performance Analytics

Implemented / Executed / Tested，见 `docs/MODEL_PERFORMANCE_ANALYTICS.md`。指标来自 `evaluation_run`；错误样例 264 条；模型-人工一致率为 Not Implemented。

## 11. Strategy Evaluation

Implemented / Executed / Tested，见 `docs/STRATEGY_EVALUATION.md`。

**逐策略四维评估（`phase-05.2` 新增）**：新增 `SQL_POLICY_QUALITY`，按 `policy_key` 展开 `matched_policies` 并关联 `message_label` 真值，逐策略计算 Precision / Recall / F1 / 误杀率 / 漏判率 / 人工审核占比。每条策略使用**自身命中数**作分母，scope 级常量不再被广播到全部策略行。

命中分析页面现按多维表呈现，而非仅按命中数排序的柱状图。回放执行时把每条消息的命中策略逐条归因写入 `parameters`，使回放从「两个策略集的总体对比」升级为「每条策略的质量对比」。

实测证明「命中多 ≠ 效果好」（500 条样本回放，基线）：

| 策略 | 命中 | Precision | Recall | 误杀率 | 漏判率 | 审核占比 |
|---|---|---:|---:|---:|---:|---:|
| gov-score-045-warn | 32 | **0.406** | 0.260 | 0.042 | **0.740** | 0.000 |
| gov-category-harassment-warn | 22 | 0.500 | 0.220 | 0.024 | 0.780 | 0.000 |
| gov-category-spam-flag | 17 | **0.706** | 0.240 | 0.011 | 0.760 | 0.000 |
| gov-score-070-review | 38 | **0.974** | 0.740 | 0.002 | 0.260 | 1.000 |

命中最多的 `gov-score-045-warn`（32 条）Precision 最低；命中仅 17 条的 `gov-category-spam-flag` Precision 反而高 74%。反向亦成立：`gov-low-risk-observe` 命中 9 条但 Precision 0.000。单一维度排序不可靠，四维并列才是可辩护的评估方式。

`gov-normal-allow` 这类从不处置的策略返回 `acts_on_risk=false` 且性能指标为 `null`，不参与质量排序。

Precision/Recall 建立在合成 `message_label` ground truth 之上，属离线模拟指标，不代表线上真实标注效果。

## 12. Strategy Replay 实际验证

Executed / Verified。

最新一次回放（run `f3c4162a`，500 条样本，`definition_version=phase-05.2`）：

| 结果 | 值 |
|---|---:|
| 样本数 | 500 |
| 样本池 truth_positives / truth_negatives | 50 / 450 |
| 样本池 with / without risk_event | 83 / 417 |
| 基线命中 | 500 |
| 基线混淆矩阵 | TP=50, FP=37, FN=0, TN=413 |
| 基线 Precision / Recall / FPR | 0.574713 / 1.0 / 0.082222 |
| 动作变化 | 10 |
| 人工审核负载变化 | -10 |
| FP / FN 变化 | 0 / 0 |

**隔离性验证已升级为内容级指纹**：对 9 张业务表（`message`、`risk_event`、`risk_result`、`policy_decision`、`policy_evaluation`、`moderation_case`、`moderation_review`、`enforcement_action`、`governance_feedback`）逐行 `t::text` 做 SHA-256，回放前后比对，全部一致。这比原先只比较 `policy_decision` 与 `enforcement_action` 行数更强——行数不变无法排除原地改写。该校验已固化为集成测试 `test_replay_leaves_business_tables_byte_identical`。

混淆矩阵改为逐条推导（由真值/预测标志推导 TP/FP/FN/TN），不再用命中计数反推。修复前 `false_positive_rate` 恒为 1.0（真负例结构性为 0），修复后为 0.082222，与独立重算逐项一致。

结果均标记 `simulation=true`。

## 13. PostgreSQL SQL 执行情况

Executed / Verified。**29 条具名 SQL** 全部在真实 PostgreSQL 18.3 上执行；覆盖总览、时间聚合、类别/等级、服务器/联盟/玩家、决策、审核、处置、模型、策略命中、**逐策略质量**、**检测层混淆矩阵**、错误样例、回放对比与数据质量。未使用硬编码结果。

`phase-05.2` 新增 `SQL_POLICY_QUALITY` 与 `SQL_DETECTION_QUALITY` 两条；`SQL_POLICY_HITS` 的分母隔离、`SQL_REPLAY_INPUT` 的样本池、`SQL_PLAYER_PROFILE` 的口径已修正。

## 14. Hive 运行与集成验证

**Blocked**。见 `docs/HIVE_OFFLINE_ANALYTICS.md`。本机无 `beeline` / `hive` / `hadoop`；项目禁止 Docker/WSL。Phase 02 导出与 SQL 资产保留，Phase 05 新增 ADS 设计为 `warehouse/hive/50_phase05_ads.sql`，状态 Designed，未执行。

## 15. Dashboard 页面与交互

Implemented / Tested。新增 6 个分析页面：总览、风险、社区、治理、模型、策略评估。全局筛选器（时间、数据集、服务器、联盟、玩家、类别、等级、策略、模型）下推到服务层；AppTest 逐页渲染无异常。支持 Light / Dark / System 主题（复用现有 `theme_style`）。

`phase-05.2` 变更：策略评估页的命中分析由单柱状图改为多维表（Precision / Recall / 误杀率 / 漏判率 / 人工审核占比），并新增「逐策略效果对比（基线 vs 候选）」区块；总览页误杀率标注为「误杀率（检测层）」并加入低样本警告。

## 16. 报告导出功能

Implemented / Executed / Tested。支持五类报告（daily_risk、weekly_risk、governance_performance、policy_evaluation、model_performance），导出 Markdown + CSV。Excel/PDF 为 Not Implemented：项目未安装对应依赖，按约束不引入大型依赖。

## 17. 测试结果

Tested。**单元测试 237 passed**（含新增 7 项指标完整性测试）；**集成测试 46 passed**（含新增 8 项：扇出防护与分母隔离 4、回放隔离与正确性 4）。Ruff 对 `src` / `tests` 全通过。`alembic check` 无漂移，head 为 `a7c3e91d4f62`。详见 `docs/PHASE_05_TEST_REPORT.md`。

## 18. 性能测试结果

Executed。真实测量并记录了 7 项服务查询与 7 项页面加载耗时；community 最慢（1,666.8 ms 服务 / 1,904.9 ms 页面）。未设置虚构阈值。

`phase-05.2` 新增的 `SQL_DETECTION_QUALITY` 为全窗口扫描，随窗口规模线性增长，未引入额外索引依赖。

## 19. 当前已知问题

1. `risk_result` 仅 7 行，真实引擎结果覆盖率极低；误杀/漏判基线因此建立在 `risk_event` 合成检测输出上。
2. `moderation_review` 与 `governance_feedback` 为 0，人工相关指标不可计算。
3. 所有策略仅 v1，无历史版本对比。
4. 人工标签缺失时的 Precision/Recall 只能作为合成 ground truth 上的离线模拟指标。
5. Hive 引擎缺失，ADS 层无法执行验证。
6. `rate_count=0` 使限流类策略的回放不等于线上行为。
7. 策略生效判断使用回放执行时刻，不是消息发生时刻的历史策略重建。
8. `policy_decision` 中 50,003 行 `decision_status` 为 NULL（生成器 legacy 记录），使自动/人工分流的可计算分母仅 1 条——已由门禁标记为不可解读，但意味着治理分析在当前数据集上无法给出有意义的分流比例。
9. `policy_evaluation` 仅 7 行、覆盖 2 条消息，因此线上（历史数据）逐策略命中率的分母极小；策略质量的实质证据来自回放而非历史评估记录。
10. 集成测试曾永久改写共享演示库中消息的 `occurred_at` 且不恢复，使分析窗口分母逐次漂移。已修复测试并恢复数据，分母现恒为 50,000；但该类"测试污染演示库"的风险需要持续关注——新增集成测试若写入共享数据集，应遵循同一恢复约定。

## 20. 文件变更清单

新增文档：`PHASE_05_INTEGRATION_AUDIT.md`、`ANALYTICS_ARCHITECTURE.md`、`ANALYTICS_DATA_MODEL.md`、`ANALYTICS_DATA_QUALITY.md`、`KPI_DEFINITIONS.md`、`RISK_ANALYTICS.md`、`GOVERNANCE_ANALYTICS.md`、`MODEL_PERFORMANCE_ANALYTICS.md`、`STRATEGY_EVALUATION.md`、`HIVE_OFFLINE_ANALYTICS.md`、`PHASE_05_TEST_REPORT.md`、`PHASE_05_ACCEPTANCE_REVIEW.md`、本文件。

新增代码：`src/claro/analytics/{__init__,definitions,filters,sql_queries,data_access,metrics,quality,services,strategy,reports}.py`；`src/claro/ui/analytics_ui.py`；6 个 `src/claro/ui/pages/analytics_*.py`；迁移 `migrations/versions/20261125_a7c3e91d4f62_phase_05_analytics_schema.py`；`warehouse/hive/50_phase05_ads.sql`。

新增测试：`tests/unit/test_analytics_metrics.py`、`tests/unit/test_analytics_services.py`、`tests/unit/test_analytics_metric_integrity.py`、`tests/integration/test_analytics_postgres.py`、`tests/integration/test_analytics_replay.py`、`tests/integration/test_analytics_delivery.py`。

修改：`src/claro/bootstrap.py`（注入分析服务）、`src/claro/cli.py`（分析命令与回放命令）、`src/claro/data_access/models.py`（两张回放表模型）、`src/claro/ui/app.py`（页面注册）、`README.md` 与 `docs/DEVELOPMENT_PLAN.md`（状态更新）。

### 20.1 `phase-05.2` 验收审查修复的改动

| 文件 | 变更 |
|---|---|
| `src/claro/analytics/sql_queries.py` | 新增 `SQL_DETECTION_QUALITY`、`SQL_POLICY_QUALITY`；修正 `SQL_POLICY_HITS` 分母隔离、`SQL_REPLAY_INPUT` 样本池、`SQL_PLAYER_PROFILE` 口径 |
| `src/claro/analytics/metrics.py` | 新增 `gated_rate()`、`policy_effectiveness()`；修正 `predicted_positive()` 语义说明 |
| `src/claro/analytics/definitions.py` | 版本升至 `phase-05.2`；新增 `MIN_RATE_DENOMINATOR`、`MIN_POLICY_DECISIONS` 与 5 个新公式标识 |
| `src/claro/analytics/services.py` | `overview()` / `governance()` / `strategy()` 接入门禁与逐策略质量 |
| `src/claro/analytics/data_access.py` | 新增 `policy_quality()`、`detection_quality()` 仓储方法 |
| `src/claro/analytics/strategy.py` | 回放逐策略归因；混淆矩阵改为逐条推导 |
| `src/claro/ui/pages/analytics_overview.py` | 低样本提示；误杀率标注为检测层 |
| `src/claro/ui/pages/analytics_strategy.py` | 多维策略表；逐策略基线/候选对比 |
| `src/claro/ui/analytics_ui.py` | `metric_row()` 支持门禁字典 |
| `tests/unit/test_analytics_metric_integrity.py` | 新增 7 项指标完整性测试 |
| `tests/unit/test_analytics_services.py` | FakeRepository 补齐两个新方法；断言更新为新口径 |
| `tests/integration/test_analytics_postgres.py` | 新增 4 项扇出与分母隔离测试；口径版本断言更新 |
| `tests/integration/test_analytics_replay.py` | 新增内容级指纹校验与 3 项回放正确性测试 |
| `tests/integration/test_postgresql.py` | **缺陷 6 修复**：选取范围限定为测试自身 seed 的数据集；`try/finally` 恢复 `occurred_at` 并断言恢复生效 |
| `docs/KPI_DEFINITIONS.md` | 升至 `phase-05.2`，新增 §0.1 门禁、§0.2 扇出防护、§1.1 检测层质量、§5 策略评估重写 |
| `docs/PHASE_05_ACCEPTANCE_REVIEW.md` | 新增（本轮审查报告） |

## 21. Phase 06 准备情况

Prepared。分析服务、KPI 口径与回放表已就绪，可作为后续模块的数据基础。建议 Phase 06 优先处理：①补充人工标注数据以启用一致性与线上误杀/漏判；②在 Hive 引擎可用后验证 ADS 层；③积累策略多版本后再启用真实版本对比。**本阶段到此停止，不自动开始 Phase 06。**
