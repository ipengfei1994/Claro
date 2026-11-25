# Claro Phase 03 — 模型评估报告

## 1. 结论先行

本阶段训练了一个真实的 Scikit-learn 多标签模型，并在真实 PostgreSQL 中持久化了评估结果。
**验证集和测试集指标全部为 1.0，但这不能证明生产准确率。** 原因是合成数据集由有限模板
生成，测试集与训练集的内容重复率为 99.47%。唯一的内容不相交子集只有 27 条，且全部是正常
样本，无法估计风险分类的泛化能力。

本报告把“已执行”“已测量”和“可外推”严格分开。

## 2. 可复现信息

| 项目 | 值 |
|---|---|
| 数据集 | `phase-02-synthetic-s20261125-p5000-m50000` |
| 数据规模 | 50,000 消息、5,000 玩家、10 服务器、500 联盟 |
| 训练日期（UTC） | 2026-11-25T03:59:02Z |
| 算法 | One-vs-Rest + Logistic Regression |
| 模型 ID | `logistic_regression-hase-02-synthetic-s20261125-p5000-m50000-20261125T035902717586Z` |
| 模型版本 | 1 |
| 模型名 | `risk-logistic_regression` |
| 产物 | `models/risk_ml/<model_id>/model.joblib`（被 `.gitignore` 排除） |
| 元数据 | 同目录 `metadata.json` |
| 评估 run | `bc2263fb-4119-483b-8cfa-49f1c0212f06` |

复现命令：

```powershell
.\.venv\Scripts\claro.exe risk-train --dataset phase-02-synthetic-s20261125-p5000-m50000
.\.venv\Scripts\claro.exe risk-evaluate --dataset phase-02-synthetic-s20261125-p5000-m50000 --split test
.\.venv\Scripts\claro.exe risk-cases --run bc2263fb-4119-483b-8cfa-49f1c0212f06
```

重复训练会创建新的模型版本并归档旧模型；重复评估会新增 run，不会覆盖旧 run。

## 3. 数据切分

按玩家切分，玩家不会同时出现在 train 和 test：

| split | normal | risk | boundary | 非边界总数 |
|---|---:|---:|---:|---:|
| train | 25,807 | 4,141 | 5,284 | 29,948 |
| validation | 3,683 | 595 | 760 | 4,278 |
| test | 3,733 | 557 | 770 | 4,290 |
| holdout | 3,451 | 562 | 657 | —（未用于本报告） |

模型训练使用 train + validation 的非边界样本；boundary 从训练和 precision/recall 指标中
排除。test 共 5,060 条，其中 770 条 boundary 只做单独统计。holdout 未参与训练或本报告评估。

测试集真实风险分类分布：

| fraud | harassment | spam | violence | sexual_content | other | hate_speech | self_harm |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 114 | 149 | 96 | 61 | 43 | 42 | 37 | 15 |

## 4. 特征与超参数

| 项目 | 值 |
|---|---|
| 文本视图 | `preprocess(text).ml_text`（实体替换为占位符） |
| 向量化 | `char_wb` TF-IDF |
| n-gram | 1–4 |
| `min_df` | 2 |
| `max_features` | 100,000 |
| `sublinear_tf` | true |
| 词表大小 | 3,114 |
| 分类器 | One-vs-Rest Logistic Regression |
| `class_weight` | balanced |
| 选择参数 | `C=1.0`（候选 1.0、4.0，以 validation macro-F1 选择） |

每个标签的阈值在 validation 上以 F1 为目搜索。由于模板数据高度可分，8 个标签全部选到
搜索网格的最低值 `0.20`。这本身是一个警示信号：阈值没有在困难样本上受到约束。

## 5. 指标

### 5.1 二分类（是否有风险）

| split | 样本 | accuracy | precision | recall | F1 | FPR | FNR | TN | FP | FN | TP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| validation | 4,278 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 3,683 | 0 | 0 | 595 |
| test | 4,290 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 3,733 | 0 | 0 | 557 |

### 5.2 多标签

| split | micro-F1 | macro-F1 | weighted-F1 | Hamming loss |
|---|---:|---:|---:|---:|
| validation | 1.0 | 1.0 | 1.0 | 0.0 |
| test | 1.0 | 1.0 | 1.0 | 0.0 |

测试集每个标签的 precision、recall、F1 均为 1.0，support 与第 3 节分布一致。

### 5.3 边界样本

| 项目 | 值 |
|---|---:|
| boundary 消息 | 770 |
| 被模型标记为风险 | 16 |
| 标记比例 | 2.08% |
| 平均最大风险概率 | 0.0304 |

边界样本不进入 precision/recall；该统计只说明模型对“讨论、举报、求助”类内容的倾向。

## 6. 泄漏检查

| 指标 | 值 |
|---|---:|
| train 消息（含 boundary） | 35,232 |
| test 消息 | 5,060 |
| test 中内容哈希与 train 重复 | 5,033 |
| 重复比例 | **99.47%** |
| 玩家重叠 | 0 |

玩家级隔离成立，但内容级隔离不成立。大量测试消息与训练消息共享同一模板，模型可以记住
模板而不是学习可迁移的表达。因此 1.0 的指标主要反映模板可分性。

## 7. 内容不相交评估

对 test 中内容哈希未出现在 train 的 27 条消息单独评估：

| 指标 | 值 |
|---|---:|
| 消息数 | 27 |
| normal / risk | 27 / 0 |
| 预测为风险 | 0 |
| precision | 0.0（没有正例预测） |
| recall | 0.0（没有真实正例） |
| accuracy | 1.0 |
| 多标签 macro-F1 | 0.0 |

accuracy 1.0 在这里没有意义，因为子集没有风险样本；precision/recall 0 也不代表模型很差，
而是没有可评估的正例。**该子集不能用于估计泛化能力。**

## 8. 错误案例

评估 run `bc2263fb-4119-483b-8cfa-49f1c0212f06` 持久化：

| 类型 | 数量 | 说明 |
|---|---:|---|
| false_positive | 0 | 测试集与训练集高度重复 |
| false_negative | 0 | 同上 |
| conflicting | 64 | 规则分类与 ML 分类不相交 |
| low_confidence | 0 | 阈值与模板可分性导致 |
| borderline | 770 | 每条 boundary 都保留为案例 |

`conflicting` 是当前最值得复核的案例：它们不是标注错误，而是规则和模型在“其他违规”
等分类上不一致。可使用：

```powershell
.\.venv\Scripts\claro.exe risk-cases --run bc2263fb-4119-483b-8cfa-49f1c0212f06 --type conflicting --limit 20
```

## 9. 指标定义

- precision：预测为风险的样本中真实风险的比例。
- recall：真实风险样本中被识别的比例。
- F1：precision 与 recall 的调和平均。
- FPR：正常样本被误报的比例；FNR：风险样本被漏报的比例。
- micro：所有标签的 TP/FP/FN 汇总后计算。
- macro：每个标签单独计算后取算术平均，小样本标签权重相同。
- weighted：按标签 support 加权。
- Hamming loss：多标签中错误标签数占全部标签位的比例。
- 所有指标由 `sklearn.metrics` 计算，未手工修改结果。

## 10. 如何正确解读

可以声称：

- 训练、序列化、加载和推理链路真实可运行。
- 在模板重复的合成测试集上，模型能够区分正常与风险模板。
- 评估指标、错误案例和泄漏报告已持久化，可追溯。
- 规则与模型在部分样本上存在分类分歧。

不能声称：

- 模型达到生产可用准确率。
- 1.0 指标可以外推到真实玩家聊天。
- 内容不相交子集的 accuracy 1.0 代表泛化。
- 阈值 0.20 在新数据上仍然合适。

## 11. 改进方向

1. 扩充生成器模板与表达多样性，降低测试集内容重复率。
2. 使用独立、人工标注的真实（或去标识化）语料做外部验证。
3. 在内容不相交且包含风险正例的子集上报告 precision/recall。
4. 增加概率校准评估（Brier score、可靠性曲线），再决定置信度语义。
5. 对 `conflicting` 案例建立人工复核闭环，反哺规则和标注指南。
6. 在 holdout 上做最终评估，但不得用 holdout 调参。
