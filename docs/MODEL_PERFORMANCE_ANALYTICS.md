# Phase 05 — Model Performance Analytics 实现说明

## 1. 指标来源

模型指标**直接读取** `evaluation_run.metrics` / `evaluation_run.per_label`，不在展示层重算。这保证了与 Phase 03 评估结果一致，也避免用不同标签口径重新计算得到不同结论。

## 2. 已实现

- 基础二分类指标：Accuracy、Precision、Recall、F1、FPR、FNR、混淆矩阵、FP/FN 计数。
- 多标签指标：per-label Precision/Recall/F1/Support、Hamming Loss、Micro/Macro/Weighted F1（若评估运行中包含）。
- 错误样例：`evaluation_case` 按 `error_type` 与类别聚合。
- 版本比较：仅当运行数量 > 1 且 `dataset_name`、`split` 完全一致时可用，否则页面明确拒绝比较。
- `risk_result` 与 `message_label` 对照：当前 7 条已落库结果，显示样本量。

## 3. 实测状态

| 项目 | 状态 |
|---|---|
| `ml_model` | 1 个（logistic_regression v1） |
| `evaluation_run` | 1 个（test split，5,060 条） |
| `evaluation_case` | 264 条（borderline / conflicting） |
| 模型版本比较 | 不可用（仅 1 个评估运行） |
| 推理耗时 | `risk_result.timings` 有 7 条样本，样本不足时不比较 |
| 模型-人工一致率 | **Not Implemented**：`moderation_review` 0 行 |

## 4. 解释边界

- 标签来自合成数据生成器，是合成 ground truth，不代表真实线上准确率。
- `label='boundary'` 在二分类口径中计为负例。
- 缺少独立标注集时，不把任何结果称为「严格模型准确率」。
- 人工标签可能具有主观性；即便未来可用，也应描述为审核一致性。
