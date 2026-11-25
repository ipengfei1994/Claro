# Phase 05 — 测试与验证报告

执行时间：2026-11-25（UTC+8）
环境：Windows 11 (10.0.26340)、Python 3.12.10、PostgreSQL 18.3、Redis 与 Kafka 本机运行。
运行方式：项目 `.venv` 内的 pytest 8、Ruff、Alembic、Streamlit AppTest。

## 1. 测试结果汇总

| 项目 | 命令 | 实际结果 |
|---|---|---|
| 单元测试（全量） | `python -m pytest -q` | **230 passed, 38 deselected** |
| Phase 05 单元测试 | `python -m pytest tests/unit/test_analytics_metrics.py tests/unit/test_analytics_services.py -q` | **14 passed** |
| 集成测试（全量） | `python -m pytest -q -m integration` | **38 passed, 230 deselected** |
| Phase 05 集成测试 | `pytest -m integration tests/integration/test_analytics_*.py` | **13 passed** |
| 代码规范 | `python -m ruff check src tests` | **All checks passed** |
| 迁移一致性 | `python -m alembic check` | **No new upgrade operations detected** |
| 迁移应用 | `python -m alembic upgrade head` | `a7c3e91d4f62` 已应用 |

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

## 3. 集成测试覆盖

| 主题 | 测试 | 状态 |
|---|---|---|
| Analytics + PostgreSQL | `test_analytics_postgres.py`（4 项） | Passed |
| 筛选器真正影响后端 | `test_category_and_dimension_filters_change_query_results` | Passed |
| 数据质量 SQL | `test_data_quality_queries_report_no_foreign_key_orphans` | Passed |
| Strategy Replay + Policy Engine | `test_replay_is_isolated_from_formal_decisions` | Passed |
| 回放结果持久化 | `test_replay_comparison_uses_stored_metrics` | Passed |
| Dashboard + Analytics | `test_all_analytics_pages_render_without_exceptions` | Passed |
| 报告导出 | `test_report_export_writes_markdown_and_csv`（5 个报告类型） | Passed |
| Analytics + Hive | 未执行 | **Blocked**：无 Hive/Beeline |
| Analytics + Redis | 未执行 | Not Applicable：分析层不引入新 Redis 键 |

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

## 6. 已知测试限制

- 集成测试对共享演示库执行，其他集成用例可能增删合成验证行；因此断言使用跨视图一致性而非固定字面值。
- Hive 层无引擎可测，状态保持 Blocked。
- 人工审核与反馈数据为空，相关指标仅验证「不可计算」路径。
