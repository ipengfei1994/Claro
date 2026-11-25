# Claro Phase 03 — 风险智能引擎

## 1. 范围

Phase 03 在 Phase 02 的消息入库链路上增加可追溯的风险检测：

```text
game.messages.persisted.v1
    → RiskPipelineService
    → RiskService.detect(message_id)
        → preprocessing
        → rules
        → ML (optional, degraded if no model)
        → semantic (deferred)
        → LLM (optional, advisory, disabled by default)
        → fusion + explanation
    → PostgreSQL risk_result / risk_finding
    → game.risk.assessed.v1
```

检测结果先提交 PostgreSQL，再发布风险事件；风险事件不参与执行动作，Phase 04 的策略与
审核模块消费它。

## 2. Phase 02 集成审计

实现前检查并复用了以下既有结构：

- `message`、`message_label`、`dataset`、`detection_rule`、`risk_finding` 与
  `processing_event` 表；未重建 schema，未迁移或修改既有消息数据。
- 玩家级 train/validation/test/boundary 切分与独立真值标签。
- Kafka 手动提交、重试、DLQ、Inbox 去重及 `game.message.persisted.v1` 事件。
- Redis 缓存端口、SQLAlchemy session 工厂、structlog 配置和 CLI 结构。
- `RuleType` 枚举原先列长度为 7，新增 `url_pattern`、`blacklist`、`repetition` 后
  通过迁移 `c4a7e1d9b2f6` 扩展为 `VARCHAR(32)`；这是本阶段唯一的既有列修改。

新增表：`ml_model`、`risk_result`、`evaluation_run`、`evaluation_case`。
迁移 head：`c4a7e1d9b2f6`。

## 3. 代码结构

| 路径 | 职责 |
|---|---|
| `src/claro/risk_engine/preprocessing.py` | 规范化、实体抽取、压缩/折叠文本、重复短语特征 |
| `src/claro/risk_engine/taxonomy.py` | 加载并校验 19 类分类体系 |
| `src/claro/risk_engine/rules.py` | 5 类规则、否定词抑制、Redis 规则缓存、规则同步 |
| `src/claro/risk_engine/fusion.py` | 配置驱动的加权 noisy-OR、多标签聚合、冲突报告 |
| `src/claro/risk_engine/explainability.py` | 文本、证据、分层状态、评分形成与限制声明 |
| `src/claro/risk_engine/ml/` | 特征、训练、模型包、预测、泄漏检查 |
| `src/claro/risk_engine/evaluation/` | 二分类/多标签指标、错误案例、边界与内容不相交评估 |
| `src/claro/risk_engine/llm.py` | 可选 advisory LLM 适配器，仅通过环境变量配置 |
| `src/claro/application/risk_service.py` | 编排检测、训练、评估、查询与状态 |
| `src/claro/application/risk_events.py` | `game.risk.assessed.v1` 契约 |
| `src/claro/application/risk_pipeline.py` | persisted → detection → publish，持久化后发布 |
| `src/claro/data_access/repositories/risk_repository.py` | 结果、规则、模型、评估的唯一持久化边界 |

UI 不直接调用这些模块中的 SQL，也不包含检测业务逻辑。

## 4. 预处理

`preprocess(text)` 保留原文，并生成：

- `normalized`：NFKC、去除零宽字符、小写、空白折叠。
- `compact`：去除空格、标点与分隔符，用于识别“加 群”“微*信”等规避写法。
- `squashed`：折叠连续重复字符，用于识别“啊啊啊啊”。
- `ml_text`：URL、邮箱、手机号替换为 `<url>`、`<email>`、`<phone>`，避免模型记忆实体。
- `features`：URL/域名、邮箱、手机号、联系方式、重复片段计数、零宽字符数、
  全角字符标记、最大连续重复长度、合成链接标记。

非法空文本立即抛出 `ValueError`，不会静默跳过。

## 5. 规则层

规则文件：[`config/detection_rules.yaml`](../config/detection_rules.yaml)。当前 22 条
合成规则，覆盖 5 种类型：

| 类型 | 行为 |
|---|---|
| `keyword` | 在 normalized/compact/squashed 中匹配 terms |
| `regex` | 正则匹配并记录 span |
| `url_pattern` | 匹配非白名单域名 URL |
| `blacklist` | 精确域名或 token 黑名单 |
| `repetition` | 单条消息短语重复，或 24 小时内同发送方重复内容 |

规则包含 `category`、`severity`、`weight`、`priority`、`version` 和
`negative_terms`。当消息包含否定词（如“举报”“请勿相信”）时，对应规则被抑制，避免把
防诈骗提醒误判为诈骗。该抑制是消息级粗粒度策略，不是上下文语义理解。

`risk-sync-rules` 将 YAML 同步到全局 `detection_rule`。新增规则带
`definition.managed_by` 标记；同步只禁用该标记下已从文件移除的规则，不会停用 Phase 02
的旧规则。规则加载按文件 SHA-256 计算摘要，`RuleProvider` 优先使用 Redis 缓存
`claro:risk:rules:v1`，文件变化后摘要不匹配自动重载。

## 6. ML 层

- 文本特征：`char_wb` TF-IDF，1–4 gram，`sublinear_tf`，默认 `min_df=2`，
  `max_features=100000`。
- 分类器：One-vs-Rest + Logistic Regression 或 Linear SVC，`class_weight=balanced`。
- 多标签：8 个数据库风险分类；`normal` 不进入模型标签，边界例不进入训练和指标。
- 候选 `C` 在 validation 上用 macro-F1 选择；每个标签在 validation 上独立调阈值。
- 模型包包含 vectorizer、classifier、labels、thresholds 和 metadata；默认写入
  `models/risk_ml/<model_id>/model.joblib`，`metadata.json` 同步记录。
- 模型注册到 `ml_model`，按 `name/version` 唯一；新模型激活时旧模型归档。
- 启动时读取 `CLARO_RISK__ML__ACTIVE_MODEL_ID` 指定的模型，否则取最新 active；
  无模型、文件缺失或加载失败都会降级为规则/语义可用，不会阻断检测。

训练和评估命令：

```powershell
.\.venv\Scripts\claro.exe risk-train --dataset phase-02-synthetic-s20261125-p5000-m50000
.\.venv\Scripts\claro.exe risk-evaluate --dataset phase-02-synthetic-s20261125-p5000-m50000 --split test
.\.venv\Scripts\claro.exe risk-cases --run <evaluation-run-id> --type conflicting
```

## 7. 语义层与 LLM 层

语义检测器当前明确返回 `not_available`，原因记录在 `explanation.layers` 与
`risk-status`。没有伪造“语义模型已接入”的状态。后续接入需要独立模型、版本和评估，
不能只增加一个接口占位。

LLM 是可选 advisory 层：

```dotenv
CLARO_RISK__LLM__ENABLED=true
CLARO_RISK__LLM__BASE_URL=https://your-endpoint/v1
CLARO_RISK__LLM__API_KEY=...
CLARO_RISK__LLM__MODEL=gpt-4o-mini
```

- 默认关闭；没有凭据时 `not_available`，不影响本地运行。
- 只接收原文与已有规则分类，不接收玩家标识。
- 返回 JSON 经 Pydantic 严格校验；失败按配置重试，仍失败则记录原因并降级。
- LLM 结果只作为 advisory finding，不直接产生最终执行动作。

## 8. 融合、解释与输出

融合公式、权重和阈值见 [RISK_SCORING.md](RISK_SCORING.md)。输出包含：

- `risk_score`、`risk_level`、`suggested_action`、`confidence`。
- 多标签 `categories`，含各层贡献和分类级分数。
- `detection_methods`，仅包含实际产生证据的层。
- `explanation`：预处理视图、匹配规则、证据 span、模型概率、评分形成、
  层级状态、冲突和“非校准概率”声明。
- `timings_ms`：预处理、规则、ML、语义、LLM、融合、解释和总耗时。

`risk-result --message` 返回持久化结果；`explain()` 只返回 Phase 03 检测器
（`rule.*`、`ml.*`、`semantic.*`、`llm.*`）的 findings，避免混入 Phase 02 的旧规则
审计行。

## 9. 持久化、幂等与 Kafka

- `risk_result.message_id` 唯一。`save_detection` 先查后写，并捕获并发唯一约束冲突，
  返回 `created=False`。
- 同一消息重复调用 `detect` 返回既有结果，不重复写 findings。
- 证据按 `risk_finding` 保存；`risk_result.evidence` 保留完整 findings 快照，
  `categories` 保留分类级贡献，便于追溯。
- `risk-pipeline` 消费 persisted 事件，调用检测，然后发布
  `game.risk.assessed.v1`。发布事件的 `event_id` 固定为 `risk_result_id`，重试发布
  同一逻辑事件，下游可据此去重。
- 只有 handler 成功返回后 Kafka Consumer 才提交源偏移；payload 非法或消息不存在映射为
  `PermanentMessageError`，进入既有 DLQ。
- 检测结果不会因为发布失败而丢失；重投会命中既有结果并重新发布。

风险事件 payload 字段：

```json
{
  "synthetic": true,
  "message_id": "…",
  "dataset_id": "…",
  "risk_result_id": "…",
  "risk_score": 0.8686,
  "risk_level": "high",
  "suggested_action": "block",
  "confidence": 0.9986,
  "categories": [{"category": "harassment_personal", "db_category": "harassment", "name": "Harassment", "score": 0.8686, "level": "high"}],
  "detection_methods": ["ml", "rule"],
  "model_id": "…",
  "detected_at": "2026-11-25T03:59:02.717586Z"
}
```

## 10. 命令

```powershell
# 配置、规则、模型与检测统计
.\.venv\Scripts\claro.exe risk-status

# 同步规则，训练与评估
.\.venv\Scripts\claro.exe risk-sync-rules
.\.venv\Scripts\claro.exe risk-train --dataset <dataset> [--algorithm linear_svm]
.\.venv\Scripts\claro.exe risk-evaluate --dataset <dataset> [--split test]

# 单条、数据集待处理消息或临时文本
.\.venv\Scripts\claro.exe risk-detect --message <uuid>
.\.venv\Scripts\claro.exe risk-detect --dataset <dataset> --limit 20
.\.venv\Scripts\claro.exe risk-detect --text "限时广告 立即点击"
.\.venv\Scripts\claro.exe risk-detect --message <uuid> --force

# 查询与流水线
.\.venv\Scripts\claro.exe risk-result --message <uuid>
.\.venv\Scripts\claro.exe risk-pipeline --group claro.risk.v1 --max-messages 10
```

`--force` 会重新计算但仍不会覆盖既有 `risk_result`；它用于临时文本或诊断时绕过缓存读取，
不产生第二份持久化结果。

## 11. 降级行为

| 情况 | 行为 |
|---|---|
| 无 active 模型 | 跳过 ML，规则/语义/LLM 继续，解释记录 `degraded_reason` |
| 模型文件缺失或损坏 | 同无模型，记录错误原因，不抛给调用方 |
| 模型推理异常 | 该消息跳过 ML，记录 warning，规则结果继续 |
| Redis 不可用 | 规则文件直接读取；缓存写入失败只记录 warning |
| 语义未配置 | `not_available`，不产生 finding |
| LLM 未配置或失败 | `disabled` 或降级原因，不阻断检测 |
| 非法规则/阈值/分类配置 | 启动或首次加载抛出明确配置异常，不静默使用默认值 |

## 12. 实测性能与观测

单进程本地 Windows、PostgreSQL/Redis/Kafka 原生运行的实测：

- 首次检测冷启动：总耗时约 99–127 ms，主要耗时在规则编译和模型首次加载。
- 预热后同一进程：示例消息总耗时 3.891 ms，其中 ML 3.137 ms、规则 0.397 ms、
  融合 0.094 ms。
- 已持久化 3 条检测的 `latency_ms`：平均 76.526 ms、p50 98.819 ms、p95 124.064 ms；
  这些样本包含冷启动，不代表稳定吞吐。

这些数字是单机观测，不是容量基准。`risk-status` 提供结果数、等级分布和最近的耗时统计；
`timings_ms` 按消息保存。

## 13. 已知限制

- 规则和数据集均为合成内容，22 条规则未经过生产语料校准。
- 否定词抑制只看消息是否包含词，可能同时抑制正确规则或漏掉复杂反讽。
- ML 指标受模板重复影响；内容不相交子集只有 27 条且全部为正常样本，不能证明泛化能力。
- 融合权重和严重度是人工配置，不是统计校准概率；`confidence` 不是“正确概率”。
- 语义层未接入；LLM 默认关闭，未在真实供应商端点上验证。
- 无人工审核闭环、策略执行和 UI 审核台；这些属于后续阶段。
- 模型热更新需要重启进程或调用 `reset_model_cache()`；CLI 每次命令重新加载。
