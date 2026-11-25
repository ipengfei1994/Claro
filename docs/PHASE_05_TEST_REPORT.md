# Phase 05 — 测试与验证报告

执行时间：2026-11-25（UTC+8）
验收审查追加：2026-11-25（UTC+8），见 `docs/PHASE_05_ACCEPTANCE_REVIEW.md`
环境：Windows 11 (10.0.26340)、Python 3.12.10、PostgreSQL 18.3、Redis 与 Kafka 本机运行。
运行方式：项目 `.venv` 内的 pytest 8、Ruff、Alembic、Streamlit AppTest。

## 1. 测试结果汇总

| 项目 | 命令 | 实际结果 |
|---|---|---|
| 单元测试（全量） | `python -m pytest tests/ -q` | **237 passed, 46 deselected** |
| Phase 05 单元测试 | `python -m pytest tests/unit/test_analytics_*.py -q` | **21 passed** |
| 集成测试（全量） | `python -m pytest tests/ -q -m integration` | **46 passed, 237 deselected** |
| Phase 05 集成测试 | `pytest -m integration tests/integration/test_analytics_*.py` | **21 passed** |
| 代码规范 | `python -m ruff check src tests` | **All checks passed** |
| 迁移一致性 | `python -m alembic check` | **No new upgrade operations detected** |
| 迁移应用 | `python -m alembic current` | `a7c3e91d4f62 (head)` |

所有结果均为上述命令的真实输出；未编造通过数。

## 2. 单元测试覆盖

| 主题 | 测试 | 状态 |
|---|---|---|
| KPI / Risk Rate | `test_risk_rate_uses_distinct_messages_and_rejects_zero_denominator` | Passed |
| 去重 | `test_dedupe_by_and_count_by_handle_duplicate_event_rows` | Passed |
| 时间聚合 | `test_time_aggregation_whitelists_grains` | Passed |
| 类别聚合 | `test_risk_service_reports_category_share_and_anomalies` | Passed |
| 服务器/联盟/玩家聚合 | `test_community_service_flags_low_sample_units` | Passed |
| 模型评估 | `test_binary_confusion_and_classification_metrics_are_consistent` | Passed |
| 策略评估 | `test_replay_binary_semantics_and_action_diff` | Passed |
| 版本比较口径 | `test_model_and_strategy_services_expose_limited_comparisons` | Passed |
| 回放语义 | `test_replay_binary_semantics_and_action_diff` | Passed |
| 审核耗时 | `test_percentile_and_duration_stats_ignore_incomplete_tasks` | Passed |
| 数据质量与口径哈希 | `test_kpi_definition_hash_is_derived_from_formulas` | Passed |

### 2.1 指标完整性专项（`phase-05.2` 新增，7 项）

文件：`tests/unit/test_analytics_metric_integrity.py`

| 测试 | 锁定的不变量 |
|---|---|
| `test_gated_rate_suppresses_ratios_below_threshold` | 分母 < 30 时 `value=None` 且 `low_sample=True` |
| `test_gated_rate_handles_zero_denominator` | 分母为 0 时返回不可计算与原因 |
| `test_gated_rate_publishes_value_above_threshold` | 达标分母正常给出数值 |
| `test_policy_quality_is_not_derived_from_hit_count` | 逐策略质量与命中数解耦 |
| `test_review_hits_count_as_detected_positives` | review 命中计入真阳，不重复计罚 |
| `test_replay_pool_contains_true_negatives` | 回放样本池含真负例 |
| `test_kpi_formulas_cover_all_published_ratios` | KPI 公式标识完整 |

## 3. 集成测试覆盖

| 主题 | 测试 | 状态 |
|---|---|---|
| Analytics + PostgreSQL | `test_analytics_postgres.py`（8 项） | Passed |
| 筛选器真正影响后端 | `test_category_and_dimension_filters_change_query_results` | Passed |
| 数据质量 SQL | `test_data_quality_queries_report_no_foreign_key_orphans` | Passed |
| JOIN 不膨胀消息数 | `test_join_does_not_inflate_message_counts` | Passed |
| 检测层有全窗口基线 | `test_detection_quality_has_a_full_window_baseline` | Passed |
| 逐策略使用自身分母 | `test_policy_rates_use_per_policy_denominators` | Passed |
| 低样本比率不发布数值 | `test_low_sample_governance_ratios_are_not_published_as_values` | Passed |
| PostgreSQL 核心 schema | `test_postgresql.py`（时区往返，**含演示库不污染的恢复断言**） | Passed |
| Strategy Replay + Policy Engine | `test_replay_is_isolated_from_formal_decisions` | Passed |
| 回放内容级隔离 | `test_replay_leaves_business_tables_byte_identical` | Passed |
| 回放样本池含真负例 | `test_replay_pool_includes_clean_messages_so_false_positives_are_measurable` | Passed |
| 独立重算一致 | `test_replay_metrics_match_an_independent_recomputation` | Passed |
| 逐策略效果 | `test_replay_reports_per_policy_effectiveness` | Passed |
| 回放结果持久化 | `test_replay_comparison_uses_stored_metrics` | Passed |
| Dashboard + Analytics | `test_all_analytics_pages_render_without_exceptions` | Passed |
| 报告导出 | `test_report_export_writes_markdown_and_csv`（5 个报告类型参数化） | Passed |
| 筛选范围传播到报告 | `test_filter_summary_propagates_to_report_scope` | Passed |
| Analytics + Hive | 未执行 | **Blocked**：无 Hive/Beeline |
| Analytics + Redis | 未执行 | Not Applicable：分析层不引入新 Redis 键 |

### 3.1 内容级隔离验证（`phase-05.2` 强化）

原隔离测试只比较 `policy_decision` 与 `enforcement_action` 的**行数**——行数不变无法排除原地改写。现改为对 9 张业务表逐行 `t::text` 做 SHA-256 指纹，回放前后比对：

```
message                True      moderation_case        True
risk_event             True      moderation_review      True
risk_result            True      enforcement_action     True
policy_decision        True      governance_feedback    True
policy_evaluation      True

ALL BUSINESS TABLES UNCHANGED BY CONTENT: True
```

## 4. 数据验证（手工可核算）

| 用例 | 输入 | 期望 | 实测 |
|---|---|---|---|
| Risk Rate | 10 条消息 / 2 条风险 | 0.2 | 0.2 |
| 去重 | 3 行（m1 重复） | 2 个唯一消息 | 2 |
| 混淆矩阵 | TP/FP/FN/TN = 1/1/1/1 | P=R=F1=0.5 | 0.5 |
| P50 / P90 | [10,20,30] | 20 / 28 | 20 / 28 |
| 动作差异 | review→block | stricter | stricter |
| 低样本 | 10 条消息，阈值 30 | true | true |
| 服务器风险率（FakeRepo） | 20/100 | 0.2 | 0.2 |
| 策略命中率（FakeRepo） | 2/4 | 0.5 | 0.5 |

跨视图一致性（真实 PostgreSQL）：日度序列的总消息/风险消息求和等于总览值；类别去重计数求和等于风险消息数。

### 4.1 独立路径重算（真实 PostgreSQL）

为验证 JOIN 扇出防护有效，同一指标用三条不同 SQL 路径重算：

| 指标 | EXISTS 子查询 | IN 子查询 | 生产 scoped CTE | 一致 |
|---|---:|---:|---:|:---:|
| 窗口内消息数 | 50,000 | 50,000 | 50,000 | ✓ |
| 风险消息数 | 8,856 | 8,856 | 8,856 | ✓ |
| `scoped × risk_event` 原始 JOIN 行数 | — | — | 8,856 | 无膨胀 |
| `enforcement_action` JOIN 后行数 / distinct | — | — | 1,206 / 1,206 | 无膨胀 |
| `moderation_case` JOIN 后行数 / distinct | — | — | 4,036 / 4,036 | 无膨胀 |

检测层混淆矩阵亦经独立 EXISTS/IN 路径重算复核，逐项一致（TP=5,855、FP=3,001、FN=0、TN=41,144，样本 50,000）。

### 4.2 演示库不被污染（`phase-05.2` 修复）

审查中发现 `tests/integration/test_postgresql.py` 会把一条消息的 `occurred_at` 永久改写为 `2026-11-24 12:30:00+08:00` 且不恢复。由于 PostgreSQL 的 `UPDATE` 会把新行版本移到堆尾，下一次运行会选中另一条消息——**每跑一次集成测试，就有一条消息被永久移出分析窗口**，窗口内消息数在 49,995–50,000 之间逐次漂移。

修复后实测：

| 检查 | 修复前 | 修复后 |
|---|---|---|
| 连续两次运行后 `occurred_at <> ingested_at` 的行数 | 4 → 5 | 0 → 0 |
| 连续两次运行后窗口内消息数 | 49,996 → 49,995 | 50,000 → 50,000 |

修复内容：选取范围限定为测试自己 seed 的 `phase-01-synthetic-v1` 数据集；用 `try/finally` 恢复原始 `occurred_at` 并断言恢复生效。已污染的 5 行按生成器不变量（`occurred_at == ingested_at`）精确恢复。

## 5. 性能测试实测

所有查询在主数据集（50,000 消息、250,009 处理事件）上执行 3 次，取中位数：

| 操作 | 中位耗时 |
|---|---:|
| overview | 523.6 ms |
| risk（日粒度） | 640.4 ms |
| community（100 玩家） | 1,666.8 ms |
| governance | 582.2 ms |
| model | 128.3 ms |
| strategy | 152.5 ms |
| quality | 87.3 ms |
| AppTest 首次加载 | 1,482.1 ms |
| 分析 · 总览页面 | 3,405.4 ms |
| 分析 · 风险页面 | 1,169.6 ms |
| 分析 · 社区页面 | 1,904.9 ms |
| 分析 · 治理页面 | 785.5 ms |
| 分析 · 模型页面 | 167.4 ms |
| 分析 · 策略评估页面 | 247.8 ms |

性能说明：community 页面包含 500 个联盟与 5,000 玩家的全量聚合，耗时最高；现有索引已覆盖 `message(server_id/alliance_id/player_id, occurred_at)`。未设置人为性能阈值，也未编造优化比例。

`phase-05.2` 新增的 `SQL_DETECTION_QUALITY` 与 `SQL_POLICY_QUALITY` 为窗口内全量扫描，耗时随窗口规模线性增长，未引入额外索引依赖。

## 6. 已知测试限制

- 集成测试对共享演示库执行，其他集成用例可能增删合成验证行；因此断言使用跨视图一致性而非固定字面值。
- Hive 层无引擎可测，状态保持 Blocked。
- 人工审核与反馈数据为空，相关指标仅验证「不可计算」路径。
- `policy_evaluation` 仅 7 行，历史逐策略指标的分母极小，其质量断言依赖回放样本而非历史评估记录。
