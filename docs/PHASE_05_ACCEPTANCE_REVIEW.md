# Phase 05 — 三项验收标准审查报告

审查日期：2026-11-25
审查对象：Phase 05 分析与策略评估实现
审查方式：以真实 PostgreSQL 执行结果为准，不采信文档声明

---

## 结论摘要

| 标准 | 审查前状态 | 审查后状态 | 处置 |
|---|---|---|---|
| 1. 指标是否可信 | **不达标**：JOIN 扇出防护已到位，但存在 scope 级常量广播、低样本比率照常发布、口径跨表混用、集成测试污染演示库导致分母逐次漂移 | 达标 | 已修复 4 项 + 自动化测试锁定 |
| 2. 策略评估是否科学 | **不达标**：策略页以命中数排序，误杀/漏判/审核成本四项指标全部缺失或为常量 | 达标 | 已修复 + 逐策略效果统计 |
| 3. 历史回放是否真正隔离 | **达标**：内容级指纹验证业务表零变更 | 达标 | 已补充内容级自动化测试 |

审查过程中发现并修复 **6 个实质缺陷**（其中 3 个为硬缺陷：策略指标全部是伪指标、回放样本池结构性缺失真负例、集成测试永久篡改演示库数据导致口径漂移）。

修复后所有关键数字均可在重复运行中复现：窗口内消息数恒为 50,000、风险率 0.17712、检测层 FPR 0.067981、回放基线 FPR 0.082222。跨路径交叉校验脚本见 `scripts/verify_analytics_metrics.py`。

---

## 标准 1：指标是否可信

### 1.1 已有正确项（审查确认）

JOIN 扇出防护在生产查询中基本到位：

- `scoped` CTE 对消息窗口做去重，`risk` / `high_risk` 子查询均使用 `SELECT DISTINCT re.message_id`。
- 所有消息级指标使用 `COUNT(DISTINCT ...)`。
- 实测扇出体检：主数据集窗口内 `scoped × risk` JOIN 行数 = 8,856，与 `DISTINCT` 路径完全一致，无膨胀。

### 1.2 发现的缺陷

**缺陷 1（硬缺陷）：策略页三项比率是 scope 级常量广播**

`SQL_POLICY_HITS` 中 `evaluated` 为 scope 级单行聚合，通过 `LEFT JOIN evaluated e ON TRUE` 广播到全部 53 条策略行。实测：

```
distinct evaluated_messages across ALL policies : {2}
distinct review_suggestions  across ALL policies : {2}
distinct restrictive_sugg.    across ALL policies : {2}
```

后果：53 条策略的 `hit_rate`、`automatic_action_rate` 全部相同。`automatic_action_rate` 恒为 `0.0`（`(2-2)/2`），是一个**恒定伪指标**——它看起来是"该策略的自动执行比例"，实际是 scope 级常量。

修复：新增 `hit_counts` CTE，按 `policy_key` 从 `matched_policies` JSONB 展开，逐策略计算 `replay_hit_messages`、`automatic_hit_messages`、`review_hit_messages`、`enforcement_hit_messages`。自动/人工拆分改用**该策略自身命中的消息**作分母。

**缺陷 2（硬缺陷）：n=1 的比率被当作权威 KPI 发布**

主数据集窗口内 `eligible_finalized_decisions = 1`（其余 50,003 条决策的 `decision_status` 为 NULL，属生成器 legacy 记录）。审查前 Overview 页面显示：

```
automatic_handling_rate  = 0.0     ← 实际是 0/1
review_rate              = 1.0     ← 实际是 1/1
```

0% 自动处置率 / 100% 人工审核率会被直接误读为系统行为，而真实情况是**只有一个观测样本**。

修复：引入 `MIN_RATE_DENOMINATOR = 30` 门禁与 `gated_rate()` 函数。分母不足时返回 `value=None` 并附 `numerator`/`denominator`/`sample_size`/`reason`，UI 显示"不可计算"而非 0 或 1。

**缺陷 3：误杀率/漏判率此前完全不可计算**

审查前 `governance_feedback = 0` 行、`moderation_review = 0` 行，`observed_confusion` 仅 3 个样本却照常输出 `precision=0.667`、`false_positive_rate=1.0`。这是把 3 个样本的噪声当结论。

修复：新增检测层混淆矩阵 `SQL_DETECTION_QUALITY`，以 `risk_event` 为检测输出、合成 `message_label` 为 ground truth，覆盖窗口内全部 50,000 条消息（数据集共 50,000 条，全部落在 2026-01-01 → 2026-03-01 窗口内）。实测基线（并以独立 EXISTS/IN 路径重算复核，逐项一致）：

```
Detection Precision = 0.661134   (TP=5,855 / (TP+FP=8,856))
Detection Recall    = 1.0        (FN=0)
Detection FPR       = 0.067981   (FP=3,001 / (FP+TN=44,145))
Detection FNR       = 0.0
Detection Sample    = 50,000
```

同时给 `observed_confusion` 加 `low_sample` / `interpretable` 标记，3 样本切片明确标记为不可解读。

**缺陷 4：玩家画像口径跨表混用**

`SQL_PLAYER_PROFILE` 的 `sanctions` CTE 直接统计全表 `enforcement_action`，而同一行的 `decision_count`、`risk_messages` 等均为窗口内口径。同一行内混用两种时间范围会直接误导。

修复：`sanctions` 改为经 `policy_decision → scoped` 关联，全部指标统一为窗口内口径。

**缺陷 5：回放混淆矩阵由命中计数推导，口径混用**

原实现以 `tp = hits - fp`、`tn = case_count - hits - fn` 重建混淆矩阵。但"命中"（策略是否被选中）与"预测为正"（动作是否非 `allow`）是两个不同概念。实测导致 `tn` 恒为 0、`false_positive_rate = 1.0`——一个失真的误杀率。

修复：改为由逐条 case 的真值与预测标志推导；样本池修正后实测 `tp=50, fp=37, fn=0, tn=413`，与独立重算逐项一致，FPR 从失真的 1.0 修正为真实的 0.082。

**缺陷 6（硬缺陷）：集成测试永久篡改共享演示库，分析口径逐次漂移**

审查过程中对比"文档记录值"与"实测值"时发现窗口内消息数不一致（49,996 vs 49,995）。追查后定位到 `tests/integration/test_postgresql.py`：

```python
message = session.scalar(select(Message).where(Message.is_synthetic.is_(True)))   # 无序、无数据集限定
...
connection.execute(update(Message).where(Message.id == message_id).values(occurred_at=source_time))
```

该测试把 `occurred_at` 永久改写为 `2026-11-24 12:30:00+08:00`（超出分析窗口），且**从不恢复**。而 PostgreSQL 的 `UPDATE` 会把新行版本移到堆尾，于是下一次运行 `select ... where is_synthetic is true` 会选中**另一条**消息——每跑一次集成测试，就有一条消息被永久移出分析窗口。

实测证据：

| 时点 | 窗口内消息数 | `occurred_at <> ingested_at` 的行数 |
|---|---:|---:|
| 审查开始（初次跑完集成测试） | 49,996 | 4 |
| 再次跑完整集成测试后 | 49,995 | 5 |
| 修复并恢复数据后 | 50,000 | 0 |

这直接违反「指标必须可追溯」：同一个数据集、同一个窗口，两次运行得到不同分母，任何基于这些数字的结论都不可复现。

修复（`tests/integration/test_postgresql.py`）：

1. 选取范围限定为测试自己 seed 的 `phase-01-synthetic-v1` 数据集，不再触碰共享的主数据集；
2. 用 `try/finally` 在断言后恢复原始 `occurred_at`，并断言恢复生效。

修复后连续两次运行该测试，`occurred_at <> ingested_at` 恒为 0、窗口内消息数恒为 50,000，漂移消除。

已污染的 5 行按生成器不变量（`occurred_at == ingested_at`）精确恢复，恢复后窗口内消息数回到 50,000、风险率回到 0.17712、FPR 回到 0.067981。

---

## 标准 2：策略评估是否科学

### 2.1 审查前的问题

策略页只有一条 `hit_rate` 柱状图，且按命中数排序。`precision`、`recall`、`f1`、`false_positive_rate`、`false_negative_rate` 五个字段在服务层被**硬编码为 `None`**。也就是说，页面在结构上就无法回答"这个策略效果好不好"。

更严重的是，缺失的这五项正是"命中次数越多不代表治理效果越好"这一命题所需要的全部证据。

### 2.2 修复内容

**（a）逐策略四维评估**

新增 `SQL_POLICY_QUALITY`，按 `policy_key` 展开 `matched_policies` 并关联 `message_label` 真值，逐策略计算 TP/FP、Precision、Recall、FPR、FNR 与人工审核占比。

**（b）回放逐策略归因**

回放执行时把每条消息的命中策略逐条归因（`baseline_policy_stats` / `candidate_policy_stats`），存入 `parameters`，供 `compare()` 还原为可读指标。这使回放从"两个策略集的总体对比"升级为"每条策略的质量对比"。

**（c）review 命中的语义修正**

初版实现把 review 命中同时计入真阳与漏判，等于对同一动作惩罚两次。修正为：策略匹配并送审 = 已识别（计入真阳），人工审核成本由独立的 Manual Review Share 体现。

**（d）从不处置的策略不输出性能指标**

`gov-normal-allow` 这类只放行的策略没有检测性能可言。初版给出 `recall=0.0`、`fnr=1.0`，会被误读为"漏判最严重的策略"。修正后返回 `None` 并以 `acts_on_risk=false` 标记。

### 2.3 实测结果：命中多 ≠ 效果好

500 条样本回放的逐策略效果（基线，实测自 run `f3c4162a`，`definition_version=phase-05.2`）：

| 策略 | 命中 | TP | FP | Precision | Recall | 误杀率 | 漏判率 | 审核占比 |
|---|---|---|---|---|---|---|---|---|
| gov-score-045-warn | 32 | 13 | 19 | **0.406** | 0.260 | 0.042 | **0.740** | 0.000 |
| gov-category-harassment-warn | 22 | 11 | 11 | **0.500** | 0.220 | 0.024 | 0.780 | 0.000 |
| gov-category-spam-flag | 17 | 12 | 5 | **0.706** | 0.240 | 0.011 | 0.760 | 0.000 |
| gov-score-070-review | 38 | 37 | 1 | **0.974** | 0.740 | 0.002 | 0.260 | 1.000 |

`gov-score-045-warn` 命中数（32）高于 `gov-category-spam-flag`（17），但 Precision 只有 0.406，是后者 0.706 的 58%，漏判率高出 48 个百分点；命中更多的 `gov-score-070-review`（38 条）Precision 达 0.974。**按命中数排序会把效果最差的策略排在前面**——这正是审查要证伪的命题，现已有数据支撑。

反向样本同样存在：`gov-low-risk-observe` 命中 9 条、Precision 0.000、漏判率 1.000；`gov-keyword-cheat-tool` 命中 10 条、Precision 0.300、漏判率 0.940。这两条策略命中量不大，但质量更差——说明单一维度（命中数或 Precision）都不足以排序，必须四维并列看。

`gov-normal-allow` 命中 417 条但从不处置，`acts_on_risk=false`，其 Precision / Recall / 误杀率 / 漏判率一律为 `null`，不参与质量排序。

> 说明：`gov-score-070-review` 是纯送审策略，全部命中进入人工审核队列，因此其 TP 来自 review 命中（`review_true_positives=37`），审核占比 1.000 单独成轴——人工审核成本不与检测质量重复计罚。

### 2.4 采样偏差修复

审查发现回放样本池用 `INNER JOIN risk_event`，只取已被风险引擎标记的 8,856 条消息，排除 41,141 条正常消息。后果是每条消息预测必然为正，TN 与 FN 结构性恒为 0，**误杀率永远无法被计算**。

修复：样本池改为窗口内全部已标注消息（`LEFT JOIN`），无风险事件的消息以中性上下文（`risk_score=0`、`severity='normal'`）参与评估。经探针验证，策略引擎对这类消息返回 `allow`，构成真正的真负例。

修复后实测样本池：`with_risk_event=83, without_risk_event=417, truth_positives=50, truth_negatives=450`。

---

## 标准 3：历史回放是否真正隔离

### 3.1 验证方法升级

审查前的隔离测试只比较 `policy_decision` 与 `enforcement_action` 的**行数**。行数不变无法排除原地改写，因此验证强度不足。

改为**内容级指纹**：对 9 张业务表逐行 `t::text` 做 SHA-256，回放前后比对。

```
table                    content-identical after replay?
  message                True
  risk_event             True
  risk_result            True
  policy_decision        True
  policy_evaluation      True
  moderation_case        True
  moderation_review      True
  enforcement_action     True
  governance_feedback    True

ALL BUSINESS TABLES UNCHANGED BY CONTENT: True
```

### 3.2 代码层证据

- `evaluate_policies()` 为纯函数，只读取传入的 `PolicyContext` 与 `PolicySnapshot`，无 I/O、无副作用。
- `StrategyReplayService.run()` 的写入目标是 `analytics_replay_run` 与 `analytics_replay_case` 两张隔离表，通过独立事务提交。
- 不调用 `EnforcementService`，不发布 Kafka 事件，不写 Redis。

### 3.3 自动化保障

新增集成测试 `test_replay_leaves_business_tables_byte_identical`，把内容级校验固化进 CI，防止后续改动破坏隔离性。

---

## 遗留边界（明确标注，未夸大）

以下项目**未实现**，报告中不作为达标项：

| 项目 | 状态 | 原因 |
|---|---|---|
| 线上真实人工审核一致性 | Not Implemented | `moderation_review` 0 行；页面显示"不可计算"，不称准确率 |
| 线上误杀/漏判（真实标注） | Not Implemented | `governance_feedback` 0 行；当前误杀率基于合成 ground truth |
| 多版本策略对比 | Not Implemented | 全部策略仅 v1；以候选配置回放替代 |
| Hive 离线数仓 | Blocked | 本机无 `beeline`/`hive`/`hadoop`；未引入 Docker/WSL |
| Excel / PDF 导出 | Not Implemented | 依赖不足，未引入大型依赖；实际提供 Markdown + CSV |

---

## 变更影响面

| 文件 | 变更 |
|---|---|
| `src/claro/analytics/sql_queries.py` | 新增 `SQL_DETECTION_QUALITY`、`SQL_POLICY_QUALITY`；修正 `SQL_POLICY_HITS` 分母隔离、`SQL_REPLAY_INPUT` 样本池、`SQL_PLAYER_PROFILE` 口径 |
| `src/claro/analytics/metrics.py` | 新增 `gated_rate()`、`policy_effectiveness()`；修正 `predicted_positive()` 语义说明 |
| `src/claro/analytics/definitions.py` | 版本升至 phase-05.2；新增 `MIN_RATE_DENOMINATOR`、`MIN_POLICY_DECISIONS` 与 5 个新公式标识 |
| `src/claro/analytics/services.py` | `overview()` / `governance()` / `strategy()` 接入门禁与逐策略质量 |
| `src/claro/analytics/strategy.py` | 回放逐策略归因；混淆矩阵改为逐条推导 |
| `src/claro/ui/pages/analytics_overview.py` | 低样本提示；误杀率标注为检测层 |
| `src/claro/ui/pages/analytics_strategy.py` | 多维策略表；逐策略基线/候选对比 |
| `src/claro/ui/analytics_ui.py` | `metric_row()` 支持门禁字典 |
| `tests/unit/test_analytics_metric_integrity.py` | 新增 7 项指标完整性测试 |
| `tests/integration/test_analytics_postgres.py` | 新增 4 项扇出与分母隔离测试 |
| `tests/integration/test_analytics_replay.py` | 新增 4 项隔离性与回放正确性测试 |
| `tests/integration/test_postgresql.py` | 修复演示库污染：限定 seed 数据集 + 恢复 `occurred_at` |
| `scripts/verify_analytics_metrics.py` | 新增可复用的独立交叉校验脚本（三路径重算、检测层混淆矩阵、内容级隔离指纹、逐策略质量） |
| `docs/KPI_DEFINITIONS.md` | 升至 phase-05.2，新增 §0.1 门禁、§0.2 扇出防护、§1.1 检测层质量、§5 策略评估重写 |
