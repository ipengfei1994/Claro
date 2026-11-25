# Claro Phase 03 — 风险评分与融合

## 1. 定位

评分是**配置驱动的决策规则**，不是统计校准的概率。它把规则证据和模型概率转换成分类级
分数、多标签结果、风险等级和建议动作，并保留完整的评分形成过程。

权威配置：[`config/risk_thresholds.yaml`](../config/risk_thresholds.yaml)。

## 2. 分类级融合

同一数据库分类内的多个证据按加权 noisy-OR 合并：

```text
weighted_rule = severity_score × rule_score × layer_weight["rule"]
weighted_ml   = ml_probability × layer_weight["ml"]
weighted_other = strength × layer_weight[layer]

category_score = 1 - Π(1 - weighted_i)
category_score = min(category_score, max_category_score)
```

当前配置：

| 参数 | 值 | 说明 |
|---|---|---|
| `layer_weights.rule` | 0.90 | 规则证据权重 |
| `layer_weights.ml` | 0.80 | ML 概率权重 |
| `layer_weights.semantic` | 0.60 | 语义层预留 |
| `layer_weights.llm` | 0.50 | advisory 层权重 |
| `severity_scores.low` | 0.35 | 仅用于规则层 |
| `severity_scores.medium` | 0.55 | |
| `severity_scores.high` | 0.75 | |
| `severity_scores.critical` | 0.95 | |
| `max_category_score` | 0.99 | 防止单一信号达到 1.0 |
| `ml_min_probability` | 0.50 | ML 证据最低概率 |
| `conflict_gap` | 0.35 | 规则与 ML 分数差异告警阈值 |
| `minimum_confidence` | 0.30 | 置信度下限 |

规则先按严重度缩放，再乘层级权重；ML 不再按严重度缩放。`finding.layer == "ml"` 的
持久化 finding 不参与加权，ML 贡献由原始 `ModelPrediction` 计算一次，避免重复计数。

## 3. 多标签与总体分数

每个数据库分类独立计算分数，按分数降序输出。总体分数：

```text
overall_score = max(category_score)
```

选择 max 而不是求和或平均，是为了避免把多个轻量分类人为叠加成严重风险，同时保留每个
分类的独立证据。总体等级和动作由总体分数决定。

## 4. 等级与动作

| 分数区间 | 风险等级 | 建议动作 |
|---|---|---|
| `< 0.20` | normal | allow |
| `[0.20, 0.45)` | low | warn |
| `[0.45, 0.70)` | medium | review |
| `[0.70, 0.90)` | high | block |
| `>= 0.90` | critical | restrict |

配置要求等级切点和动作切点严格递增。`else` 必须是合法 `DecisionAction`。建议动作只是
建议，Phase 03 不执行封禁；策略与执行属于后续阶段。

## 5. ML 证据

- 每个数据库分类的模型概率必须达到 `max(per_label_threshold, ml_min_probability)`
  才产生 ML 证据。
- 阈值由 validation 集逐标签优化，目标为 F1；没有正例的标签使用 0.5。
- 未达阈值的概率记录在冲突信息中，但不进入分数。
- 模型缺失、加载失败或推理失败时，ML 层整体降级，其他层继续工作。

## 6. 置信度

分类级贡献存在时：

```text
confidence = max(contribution.confidence)
```

没有贡献但有 ML 预测时，使用 `1 - risk_probability` 作为“没有风险的置信度”；两者都
没有时为 0.5。最终值限制在 `[minimum_confidence, 1.0]`。

这是启发式置信度，不是校准概率。规则层固定使用 0.85（keyword/repetition）或 0.95
（regex/blacklist），ML 使用概率本身。

## 7. 冲突报告

| 类型 | 条件 | 含义 |
|---|---|---|
| `rule_only` | 规则命中某分类，ML 概率低于阈值 | 规则有证据但模型不确定 |
| `ml_only` | ML 命中分类且产生分类分数，但无规则证据 | 模型单独触发 |
| `layer_disagreement` | 规则分类集合与 ML 命中集合完全不相交 | 两层指向不同风险 |
| `score_gap` | 同分类规则强度与 ML 概率差 `>= 0.35` | 两层强度明显不一致 |

冲突不会自动改变分数，只写入解释与评估的 `conflicting` 案例，供人工复核和调参。

## 8. 实际评分示例

以下数值来自本机持久化结果，模型为
`logistic_regression-hase-02-synthetic-s20261125-p5000-m50000-20261125T035902717586Z`。

### 示例 A：人身攻击

- 规则：`R-HAR-001`，weight 0.7，severity medium。
- 规则加权：`0.55 × 0.7 × 0.90 = 0.3465`。
- ML `harassment` 概率约 0.9986，加权 `0.9986 × 0.80 = 0.7989`。
- 分类分数：`1 - (1 - 0.3465) × (1 - 0.7989) ≈ 0.8686`。
- 结果：`high`，`block`，置信度约 0.9986。

### 示例 B：账号交易 + 站外资产交易

- 规则：`R-ACC-001` 与 `R-TRD-001`，weight 均为 0.8，severity high。
- 单条规则加权：`0.75 × 0.8 × 0.90 = 0.54`。
- 两条规则合并：`1 - (1 - 0.54)² = 0.7884`。
- ML `other` 概率约 0.9987，加权约 0.7990。
- 分类分数：`1 - (1 - 0.7884) × (1 - 0.7990) ≈ 0.9575`。
- 结果：`critical`，`restrict`，置信度约 0.9987。

### 示例 C：正常消息

- 无规则命中，ML 概率低于所有阈值。
- 总体分数 0，等级 `normal`，动作 `allow`。
- 置信度 `1 - 最大风险概率 ≈ 0.9985`。

### 示例 D：规则与模型分歧

规则命中 `spam`、ML 命中 `harassment` 时，两个分类各自形成分数；总体取较高者，同时报告
`layer_disagreement`。如果 ML 对 `spam` 的概率低于阈值，还会报告 `rule_only`。

## 9. 为什么要这样设计

- 可解释：每个分数都能展开到规则、span、模型概率、权重和阈值。
- 可配置：权重、严重度、切点和动作不写死在业务代码中。
- 可降级：缺少 ML/语义/LLM 时仍有确定性规则结果。
- 多标签：不强行把多类风险压缩成单一类别。
- 不冒充概率：文档、解释和输出都明确声明这是决策规则，不是校准概率。

## 10. 已知限制

- 权重、严重度和切点是人工设置，未用独立验证集校准。
- 规则的严重度缩放是线性的，复杂组合可能需要非线性策略。
- 同一消息的重复历史只在规则层使用，未进入 ML 特征。
- 分类合并到 8 个数据库分类后，`other` 下的 4 个 taxonomy 分类不能单独评估。
- `confidence` 只反映最强贡献者的置信度，不能解释为“判定正确的概率”。
