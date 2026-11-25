# 模型产物（Model artifacts）

`models/` 默认被 `.gitignore` 忽略，因为重新训练可能产生体积更大或被替代的产物。仓库里
**有意强制提交了一个产物**（`git add -f`），这样克隆仓库后克隆者不需要先训练就能看到
ML 检测层真的在工作，而不是"静默缺席"。

## 已提交的产物

`risk_ml/logistic_regression-hase-02-synthetic-s20261125-p5000-m50000-20261125T035902717586Z/`

| 文件 | 内容 |
| --- | --- |
| `model.joblib` | char_wb TF-IDF（1–4 gram，`min_df=2`，`sublinear_tf`）+ 逻辑回归（`C=1.0`，`class_weight=balanced`），约 112 KB |
| `metadata.json` | 训练数据集、超参数、候选结果、逐标签混淆矩阵、切分大小、阈值、泄漏检查 |

目录名里的 `hase-02` 是 Phase 02 训练时留下的拼写（少了一个 `p`）。重命名会让
`metadata.json` 的 `model_id` 与目录名不一致，所以保留原样而不是"顺手改名"。

## 如何重新训练

```powershell
.venv\Scripts\python.exe -m claro.cli train-model `
  --dataset phase-02-synthetic-s20261125-p5000-m50000 --seed 20261125
```

训练是确定性的（固定 seed + 固定模板语料），重跑会得到同名同结构的产物。

## 指标怎么读（重要）

`metadata.json` 里 `validation` / `test` 的 micro/macro F1 都是 **1.0**。这个数字**不能**
当作模型能力：

* 语料由模板生成，同一模板的行文高度重复。`test` 集里 5,060 条消息中有 5,033 条
  （99.47%）与训练集内容重复，这一点在 `test.leakage` 中如实记录。
* 换一批"内容完全不重叠"的测试消息（`content_disjoint`，27 条）后，micro F1 掉到 **0.0**：
  模型没有泛化到新表述，它记住的是模板。

所以 `metadata.json` 自带 `notice` 字段：
`"Metrics are computed on a synthetic template dataset and do not establish production accuracy."`

产品界面（模型分析页、风险情报页）读的是这份持久化指标，不在页面重算，也不做美化。
`docs/RISK_INTELLIGENCE.md` 与 `docs/KNOWN_LIMITATIONS.md` 都写了同一条限制。
