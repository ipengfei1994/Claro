# Claro — 统一 KPI 定义（全项目唯一口径）

版本：phase-05.1
生效范围：Streamlit 分析页、CLI 报告、导出文件、测试断言。任何模块不得自行定义同名指标。

## 0. 通用约定

- **时间轴**：所有筛选使用 `message.occurred_at`。窗口为半开区间 `[start, end)`。
- **数据集**：默认 `phase-02-synthetic-s20261125-p5000-m50000`。集成测试数据集需显式选择，不自动并入默认口径。
- **去重**：消息级指标一律 `COUNT(DISTINCT message.id)`；事件级指标按事件主键计数并注明。
- **多标签**：一条消息命中多个风险类别时，在「风险消息数」中只计一次；在「类别分布」中按 `(message_id, category)` 各计一次，因此类别合计可大于风险消息数。
- **数据分级**：OBSERVED=引擎真实写入；SYNTHETIC_SNAPSHOT=生成器模拟写入；DERIVED=计算结果。
- **样本量**：所有比例类指标必须同时展示分子、分母；分母为 0 时显示「不可计算」，不得显示 0。

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

## 2. 社区分析

| KPI | 定义 | 数据来源 | 说明 |
|---|---|---|---|
| Server Risk Rate | 该服务器 `Risk Messages / Total Messages` | `message.server_id` | 必须同时展示两个计数 |
| Alliance Risk Rate | 该联盟 `Risk Messages / Total Messages` | `message.alliance_id` | 消息数 < 30 标记低样本 |
| High Risk Player Share | 联盟内至少一条 high/critical 风险消息的玩家数 / 联盟发消息玩家数 | `message` + `risk_event` | 不表示玩家恶意 |
| Player Message Count | 玩家在窗口内消息数 | `message.player_id` | 与风险率同时展示 |
| Player Risk Rate | 玩家风险消息数 / 玩家消息数 | 同上 | 窗口内计算，不跨窗口累计 |
| Historical Governance Count | 玩家关联决策数 | `policy_decision` → `message` | 含 legacy 记录，需注明 |
| Historical Simulated Sanctions | 玩家作为 `target_ref` 的 `enforcement_action` 数 | `enforcement_action` | 全部为模拟处置 |
| Last Risk Time | 玩家最近一条风险消息的 `occurred_at` | `message` + `risk_event` | 时区按展示层 |

**禁止事项**：不得把 `player.risk_propensity`（生成参数）描述为玩家真实违规概率；不得仅凭累计风险数判断恶意。

---

## 3. 治理分析

| KPI | 定义 | 分母 | 数据来源 | 说明 |
|---|---|---|---|---|
| Total Decisions | `COUNT(policy_decision.id)` | — | `policy_decision` | 含 legacy 合成记录 |
| Automatic Decisions | `decision_status='auto_decided'` | — | `policy_decision` | 仅 OBSERVED 子集有值 |
| Manual Reviews | `decision_status IN ('pending_review','human_reviewed','overridden')` 或存在 `moderation_case` | — | `policy_decision` + `moderation_case` | 两种口径分别展示，不混用 |
| Review Rate | 进入人工审核的决策数 | Eligible Finalized Decisions（见下） | 同上 | 分母显示 |
| Automatic Handling Rate | `Automatic Decisions / Eligible Finalized Decisions` | `decision_status IN ('auto_decided','human_reviewed','overridden')` | `policy_decision` | **不得把所有未审核决策当作成功处置** |
| Allow / Warn / Block / Mute / Ban Rate | 对应 `action` 计数 | Total Decisions | `policy_decision` | 动作名称以 `DecisionAction` 枚举为准 |
| Decision Override Rate | `overridden / (human_reviewed + overridden)` | 人工终审决策数 | `policy_decision` | 无人工审核数据时显示不可计算 |
| Pending Task Count | `moderation_case.status IN ('open','pending','in_review','second_review','escalated')` | — | `moderation_case` | 当前快照 |
| Completed Task Count | `moderation_case.closed_at IS NOT NULL` | — | `moderation_case` | SYNTHETIC_SNAPSHOT |
| Task Completion Duration | `closed_at - opened_at`，仅 closed 任务 | — | `moderation_case` | **任务关闭耗时**，不是人工审核耗时 |
| P50 / P90 Duration | 上述耗时的 50/90 分位 | — | 计算层 | `moderation_review=0` 时不提供人工耗时 |
| Backlog | Pending Task Count | — | `moderation_case` | 与 SLA 无关时不推断超时 |
| Second Review Rate | `required_second_review=true / completed tasks` | completed tasks | `moderation_case` | 当前 3/4035 |
| Enforcement Count | `COUNT(enforcement_action.id)` | — | `enforcement_action` | 全部 `simulated=true` |
| Expired / Released Count | 按 `status` 分组 | — | `enforcement_action` | 状态快照 |

**Eligible Finalized Decisions** 定义：`decision_status IS NOT NULL AND decision_status NOT IN ('cancelled')`。当前仅 5 行满足，UI 必须显示样本量。

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

| KPI | 定义 | 来源 | 说明 |
|---|---|---|---|
| Policy Hit Count | 历史累计 `policy.hit_count` | `policy` | 累计快照，无时间序列 |
| Policy Hit Detail | `policy_evaluation.matched_policies` 中命中该策略的记录数 | `policy_evaluation` | 当前 7 行；样本量必须展示 |
| Policy Hit Rate | `命中消息数 / 有策略评估记录的消息数` | `policy_evaluation` | **不是策略准确率** |
| Automatic Action Rate | 命中结果中 `suggested_action != 'review'` 的比例 | `policy_evaluation` | 分母为命中记录数 |
| Manual Review Rate | `suggested_action='review'` 的比例 | 同上 | 同上 |
| Override Rate | 命中决策中 `decision_status='overridden'` 的比例 | `policy_decision` | 数据缺失时显示不可计算 |
| Precision（回放） | `TP / (TP+FP)`，`label='risk'` 为正例，预测为非 allow 即为正例 | 回放结果 + `message_label` | 离线模拟指标，使用合成 ground truth |
| Recall（回放） | `TP / (TP+FN)` | 同上 | 同上 |
| F1（回放） | `2PR/(P+R)` | 同上 | 同上 |
| FP / FN（回放） | `预测正例且 label!=risk` / `预测 allow 且 label=risk` | 同上 | boundary 计入负例，口径固定 |
| Version Comparison | 同一消息集合上两个策略快照的逐条决策差异 | 回放表 | 无历史多版本时采用候选配置回放，标记 Simulation |

**边界**：`label='boundary'` 在二分类口径中计入负例；该定义适用于全部策略与模型二分类指标，不得在某一页面改为正例。

---

## 6. 回放指标

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

`claro.analytics.definitions.KPI_DEFINITION_HASH` 由本文件列出的公式标识生成。数据质量检查会比对服务层返回的口径标识与常量；不一致即视为错误，分析页拒绝展示。
