# Claro — 统一 KPI 定义（全项目唯一口径）

版本：phase-05.2
生效范围：Streamlit 分析页、CLI 报告、导出文件、测试断言。任何模块不得自行定义同名指标。

## 0. 通用约定

- **时间轴**：所有筛选使用 `message.occurred_at`。窗口为半开区间 `[start, end)`。
- **数据集**：默认 `phase-02-synthetic-s20261125-p5000-m50000`。集成测试数据集需显式选择，不自动并入默认口径。
- **去重**：消息级指标一律 `COUNT(DISTINCT message.id)`；事件级指标按事件主键计数并注明。
- **多标签**：一条消息命中多个风险类别时，在「风险消息数」中只计一次；在「类别分布」中按 `(message_id, category)` 各计一次，因此类别合计可大于风险消息数。
- **数据分级**：OBSERVED=引擎真实写入；SYNTHETIC_SNAPSHOT=生成器模拟写入；DERIVED=计算结果。
- **样本量**：所有比例类指标必须同时展示分子、分母；分母为 0 时显示「不可计算」，不得显示 0。

### 0.1 低样本门禁（phase-05.2 新增）

- **门槛**：`MIN_RATE_DENOMINATOR = 30`。任何比例类指标的分母小于该值时，结果为**不可计算**（`None`），而不是 0、1 或任何具体百分比。
- **返回结构**：门禁后的指标以字典返回，包含 `value`、`numerator`、`denominator`、`sample_size`、`low_sample`、`reason`。
- **理由**：用 1–2 个观测值计算出的百分比不是度量。把 `n=1` 的 0/1 展示为 KPI 会直接导致错误结论（例如把"自动处置率 0%"误读为系统不自动处置）。
- **适用**：自动处置率、人工审核率、人工推翻率、策略命中率、策略自动执行比例、策略人工审核比例、逐策略 Precision/Recall/F1。
- **回放样本池**：`MIN_REPLAY_SAMPLES = 100`；逐策略质量判定门槛 `MIN_POLICY_DECISIONS = 30`。

### 0.2 JOIN 扇出防护

- 所有消息级指标使用 `COUNT(DISTINCT message.id)` 或先在 CTE 中 `SELECT DISTINCT` 去重。
- 一对多关系（消息 → 风险事件、消息 → 决策、消息 → 审核任务、消息 → 处罚）**不得**直接 JOIN 后 `COUNT(*)`。
- 集成测试 `test_join_does_not_inflate_message_counts` 用 EXISTS / IN 子查询独立重算并逐项比对，任何扇出都会导致该测试失败。

### 0.3 口径可复现性

- 指标分母必须**在重复运行中保持稳定**。若某次运行得到不同的分母，即使数值本身合理，也视为口径缺陷。
- 任何写入共享数据集的测试必须在结束时恢复原值。集成测试永久改写 `message.occurred_at` 会使窗口内消息数逐次漂移（实测 49,996 → 49,995 → …），使基于这些数字的结论不可复现。
- 生成器不变量 `message.occurred_at == message.ingested_at` 可作为演示库完整性的探针：偏离即说明有测试污染了数据。
- 独立交叉校验脚本 `scripts/verify_analytics_metrics.py` 用三条不同 SQL 路径重算同一指标并比对，可随时验证口径未被悄然改变。

---

## 1. 风险分析

| KPI | 定义（公式） | 数据来源 | 分级 | 说明 |
|---|---|---|---|---|
| Total Messages | `COUNT(DISTINCT m.id)` | `message m` | SYNTHETIC_SNAPSHOT | 分母基准 |
| Risk Messages | `COUNT(DISTINCT re.message_id)`，存在 `risk_event re` | `risk_event`，通过 message 时间窗过滤 | SYNTHETIC_SNAPSHOT | 多标签只计一次；包含全部 severity |
| Risk Rate | `Risk Messages / Total Messages` | 上两项 | DERIVED | 全项目唯一公式；不采用 `risk_result` 覆盖口径 |
| High Risk Messages | `COUNT(DISTINCT m.id)`，`risk_event.severity IN ('high','critical')` | `risk_event` | SYNTHETIC_SNAPSHOT | 与 Risk Messages 是子集关系 |
| High Risk Rate | `High Risk Messages / Total Messages` | 上两项 | DERIVED | 分母固定为总消息数 |
| Risk Distribution | 按 `risk_event.category` 分组，`COUNT(DISTINCT (message_id, category))` | `risk_event` | SYNTHETIC_SNAPSHOT | 占比分母为 Risk Messages；和可能 >100% |
| Severity Distribution | 按 `risk_event.severity` 分组，`COUNT(DISTINCT message_id)` | `risk_event` | SYNTHETIC_SNAPSHOT | 每条消息取最高 severity 进入单一桶 |
| Unique Risk Players | `COUNT(DISTINCT m.player_id)`，仅风险消息 | `message` + `risk_event` | SYNTHETIC_SNAPSHOT | 排除 `player_id IS NULL` |
| Repeat Offenders | 窗口内风险消息数 ≥ 2 的玩家数 | 按 `player_id` 聚合 | DERIVED | 阈值可配置，默认 2；需显示窗口 |
| Risk Trend | 按 hour/day/week/month 分桶的 Risk Messages 与 Risk Rate | 同上 | DERIVED | 时间桶按 UTC 日期，展示层换算 |
| Co-occurrence | 同一 `message_id` 上两个类别同时出现的消息数 | `risk_event` 自连接 | SYNTHETIC_SNAPSHOT | 对称矩阵，对角线为该类别消息数 |
| Anomaly Peak | 某时间桶 Risk Rate > `mean + 3 × std`（基于同窗口桶序列） | 趋势结果 | DERIVED | 仅统计异常识别，不推断因果 |

---

## 1.1 检测层识别质量（phase-05.2 新增）

以 `risk_event` 作为检测输出，以合成 `message_label` 作为 ground truth：

| KPI | 定义 | 说明 |
|---|---|---|
| Detection TP | 有 `risk_event` 且 `label='risk'` | 正确识别 |
| Detection FP | 有 `risk_event` 且 `label<>'risk'` | 误杀（含 boundary 计负例） |
| Detection FN | 无 `risk_event` 且 `label='risk'` | 漏判 |
| Detection TN | 无 `risk_event` 且 `label<>'risk'` | 正确放行 |
| Detection Precision / Recall / F1 | 由上述四格计算 | 分母为窗口内全部已标注消息 |
| Detection FPR / FNR | `FP/(FP+TN)`、`FN/(FN+TP)` | 标准二分类定义 |

**边界**：这是**检测层**（风险引擎）指标，不是治理决策层指标，也不是线上真实人工标注结果。数据源分级为 DERIVED（计算自合成真值）。

---

## 2. 社区分析

| KPI | 定义 | 数据来源 | 说明 |
|---|---|---|---|
| Server Risk Rate | 该服务器 `Risk Messages / Total Messages` | `message.server_id` | 必须同时展示两个计数 |
| Alliance Risk Rate | 该联盟 `Risk Messages / Total Messages` | `message.alliance_id` | 消息数 < 30 标记低样本 |
| High Risk Player Share | 联盟内至少一条 high/critical 风险消息的玩家数 / 联盟发消息玩家数 | `message` + `risk_event` | 不表示玩家恶意 |
| Player Message Count | 玩家在窗口内消息数 | `message.player_id` | 与风险率同时展示 |
| Player Risk Rate | 玩家风险消息数 / 玩家消息数 | 同上 | 窗口内计算，不跨窗口累计 |
| Historical Governance Count | 玩家关联决策数（**窗口内**） | `policy_decision` → `message` | 与玩家画像其余指标同窗口 |
| Historical Simulated Sanctions | 玩家作为 `target_ref` 的 `enforcement_action` 数（**窗口内**） | `enforcement_action` → `policy_decision` → `message` | 全部为模拟处置；与治理次数同窗口口径 |
| Last Risk Time | 玩家最近一条风险消息的 `occurred_at` | `message` + `risk_event` | 时区按展示层 |

**禁止事项**：不得把 `player.risk_propensity`（生成参数）描述为玩家真实违规概率；不得仅凭累计风险数判断恶意。

---

## 3. 治理分析

| KPI | 定义 | 分母 | 数据来源 | 说明 |
|---|---|---|---|---|
| Total Decisions | `COUNT(policy_decision.id)` | — | `policy_decision` | 含 legacy 合成记录 |
| Automatic Decisions | `decision_status='auto_decided'` | — | `policy_decision` | 仅 OBSERVED 子集有值 |
| Manual Reviews | `decision_status IN ('pending_review','human_reviewed','overridden')` 或存在 `moderation_case` | — | `policy_decision` + `moderation_case` | 两种口径分别展示，不混用 |
| Review Rate | 进入人工审核的决策数 | Eligible Finalized Decisions | 同上 | 受低样本门禁约束 |
| Automatic Handling Rate | `Automatic Decisions / Eligible Finalized Decisions` | `decision_status IN ('auto_decided','human_reviewed','overridden')` | `policy_decision` | **不得把所有未审核决策当作成功处置**；受低样本门禁约束 |
| Allow / Warn / Block / Mute / Ban Rate | 对应 `action` 计数 | Total Decisions | `policy_decision` | 动作名称以 `DecisionAction` 枚举为准 |
| Decision Override Rate | `overridden / (human_reviewed + overridden)` | 人工终审决策数 | `policy_decision` | 无人工审核数据时显示不可计算；受低样本门禁约束 |
| Pending Task Count | `moderation_case.status IN ('open','pending','in_review','second_review','escalated')` | — | `moderation_case` | 当前快照 |
| Completed Task Count | `moderation_case.closed_at IS NOT NULL` | — | `moderation_case` | SYNTHETIC_SNAPSHOT |
| Task Completion Duration | `closed_at - opened_at`，仅 closed 任务 | — | `moderation_case` | **任务关闭耗时**，不是人工审核耗时 |
| P50 / P90 Duration | 上述耗时的 50/90 分位 | — | 计算层 | `moderation_review=0` 时不提供人工耗时 |
| Backlog | Pending Task Count | — | `moderation_case` | 与 SLA 无关时不推断超时 |
| Second Review Rate | `required_second_review=true / completed tasks` | completed tasks | `moderation_case` | 当前 3/4035 |
| Enforcement Count | `COUNT(enforcement_action.id)` | — | `enforcement_action` | 全部 `simulated=true` |
| Expired / Released Count | 按 `status` 分组 | — | `enforcement_action` | 状态快照 |

**Eligible Finalized Decisions** 定义：`decision_status IS NOT NULL AND decision_status NOT IN ('cancelled')`。当前主数据集窗口内仅 1 行满足，低于门禁，因此自动处置率与人工审核率**显示为不可计算并标注样本量 1**，不显示 0% 或 100%。

---

## 4. 模型表现

| KPI | 定义 | 来源 | 说明 |
|---|---|---|---|
| Accuracy / Precision / Recall / F1 | 直接读取 `evaluation_run.metrics.binary` | `evaluation_run` | **不重算**；来源是合成标签上的离线评估 |
| Macro / Weighted / Micro F1 | 读取 `evaluation_run.metrics.multilabel` 或 `per_label` | 同上 | 若字段缺失显示不可计算 |
| Confusion Matrix | `metrics.binary.confusion_matrix` (tn/fp/fn/tp) | 同上 | FP/FN 来自离线评估集 |
| Per-label P/R/F1/Support | `evaluation_run.per_label[category]` | 同上 | 类别由 `RiskCategory` 枚举约束 |
| Hamming Loss | `metrics.multilabel.hamming_loss` | 同上 | 多标签指标 |
| Error Cases | `evaluation_case` 按 `error_type` / `category` 分组 | `evaluation_case` | 264 行，仅 borderline/conflicting |
| Model Version Compare | 同 `model.name` 下不同 `(version, dataset_name, split)` 的指标并列 | `ml_model` + `evaluation_run` | 数据集或 split 不同时**禁止**作为严格优劣对比 |
| Inference Time | `risk_result.timings` 中的真实耗时 | `risk_result` | 当前 7 行；样本不足时显示不可比较 |
| Model–Human Agreement | **Not Implemented** | `moderation_review` 0 行 | 无人工标签，不得声称准确率 |

---

## 5. 策略评估

### 5.1 逐策略指标（phase-05.2 修正）

**关键原则**：策略命中次数多、触发自动处罚多，**不等于**治理效果好。逐策略评估必须同时给出四个维度，任何单一维度都不得单独用于排名。

| KPI | 定义 | 来源 | 说明 |
|---|---|---|---|
| Policy Hit Count | 历史累计 `policy.hit_count` | `policy` | 累计快照，无时间序列 |
| Policy Hit Detail | `policy_evaluation.matched_policies` 中命中该策略的记录数 | `policy_evaluation` | 样本量必须展示 |
| Policy Hit Rate | `该策略命中消息数 / 有策略评估记录的消息数` | `policy_evaluation` | **不是策略准确率**；分母为 scope 级，受低样本门禁约束 |
| Policy Automatic Action Rate | `该策略命中且其动作为非 review、非 allow 的消息数 / 该策略命中消息数` | `policy_evaluation.matched_policies[].action` | **分母是该策略自身命中数**，不是 scope 级常量；受低样本门禁约束 |
| Policy Manual Review Rate | `该策略命中且其动作为 review 的消息数 / 该策略命中消息数` | 同上 | 同上 |
| Policy Precision | `该策略正确识别为风险的命中数 / 该策略全部命中数` | 同上 + `message_label` | 该策略命中中真阳/（真阳+假阳）；review 命中计入真阳 |
| Policy Recall | `该策略正确识别为风险的命中数 / 窗口内真实风险消息数` | 同上 | 漏判率 = 1 − Recall |
| Policy FPR | `该策略在非风险消息上的误伤数 / 窗口内非风险消息数` | 同上 | 误杀风险 |
| Policy Manual Review Share | `该策略 review 命中数 / 该策略全部命中数` | 同上 | 人工审核成本 |

**分母隔离规则（phase-05.2 修正）**：`evaluated_messages`、`hit_messages`、`automatic_hit_messages`、`review_hit_messages` 必须来自**该策略自身**的 `matched_policies` 展开，禁止用 scope 级聚合常量广播到每一行。集成测试 `test_policy_rates_use_per_policy_denominators` 校验该约束。

**review 命中的语义**：策略命中并送人工审核，视为**已识别**（计入真阳）。理由：送审已消耗审核人容量并拦截该消息，若同时计入漏判等于对同一动作惩罚两次。人工审核成本由 Manual Review Share 单独体现。

**从不处置的策略**（如 `gov-normal-allow`）：其 Precision/Recall/FPR 不可计算，返回 `None` 而非 0% Recall，避免"放行一切"的策略被误读为"漏判率 100%"。

### 5.2 回放指标

| KPI | 定义 | 来源 | 说明 |
|---|---|---|---|
| Precision（回放） | `TP / (TP+FP)`，`label='risk'` 为正例，预测为非 allow 即为正例 | 回放结果 + `message_label` | 离线模拟指标，使用合成 ground truth |
| Recall（回放） | `TP / (TP+FN)` | 同上 | 同上 |
| F1（回放） | `2PR/(P+R)` | 同上 | 同上 |
| FP / FN（回放） | `预测正例且 label!=risk` / `预测 allow 且 label=risk` | 同上 | boundary 计入负例，口径固定 |
| Replay Sample Pool | 窗口内**全部已标注消息**，含无风险事件的正常消息 | 回放输入 SQL | 见 5.3 |
| Per-Policy Effectiveness | 每条策略独立统计命中数、TP/FP、Precision/Recall、FPR/FNR、审核占比 | 回放逐条归因 | 与 5.1 同口径 |
| Version Comparison | 同一消息集合上两个策略快照的逐条决策差异 | 回放表 | 无历史多版本时采用候选配置回放，标记 Simulation |

### 5.3 回放样本池（phase-05.2 修正）

- 样本池必须包含窗口内**全部已标注消息**，包括没有 `risk_event` 的正常消息。
- **原因**：若样本池只含已被风险引擎标记的消息，则每条消息的预测必然为正，TN 与 FN 结构性恒为 0，误杀率与漏判率**永远无法被有意义地计算**。
- 无风险事件的消息以中性风险上下文参与评估：`risk_score=0`、`severity='normal'`、`confidence=0`。策略引擎对这类消息返回 `allow`，因而构成真正的真负例。
- 回放运行的 `parameters.sample_pool` 记录 `with_risk_event`、`without_risk_event`、`truth_positives`、`truth_negatives` 构成。

**混淆矩阵重建规则**：回放的 TP/FP/FN/TN 必须由逐条 case 的真值与预测标志推导，**禁止**由命中计数推导。命中（策略是否被选中）与预测（动作是否非 allow）是两个不同概念，混用会静默污染误杀率。集成测试 `test_replay_metrics_match_an_independent_recomputation` 逐项比对。

**边界**：`label='boundary'` 在二分类口径中计入负例；该定义适用于全部策略与模型二分类指标，不得在某一页面改为正例。

---

## 6. 回放差异指标

| 指标 | 定义 |
|---|---|
| Added Hits | 候选命中而基线未命中的消息数 |
| Removed Hits | 基线命中而候选未命中的消息数 |
| Action Changes | 两版本 `action` 不同的消息数 |
| Review Load Delta | 候选 `review` 动作数 − 基线 `review` 动作数 |
| FP Delta / FN Delta | 候选 FP/FN − 基线 FP/FN |
| Strictness Delta | 候选更严格动作数 − 基线更严格动作数，按 `ACTION_RESTRICTIVENESS` |

回放结果一律标记 `Simulation`，不得描述为线上干预效果。

---

## 7. 口径哈希与一致性

`claro.analytics.definitions.KPI_FORMULAS` 列出本文件的全部分子分母定义，`KPI_DEFINITION_HASH` 由其内容生成。数据质量检查会比对服务层返回的口径标识与常量；不一致即视为错误，分析页拒绝展示。

`KPI_FORMULAS` 必须显式包含全部策略质量维度（`policy_precision`、`policy_recall`、`policy_automatic_action_rate`、`policy_manual_review_rate`）与回放样本池定义（`replay_sample_pool`），确保任何模块都无法绕过门禁或改用别的分母。
