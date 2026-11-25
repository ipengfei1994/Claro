# Claro Phase 04 — 策略引擎

## 1. 策略类型

`PolicyType` 支持 11 类：keyword、regex、risk_threshold、category、player、server、alliance、whitelist、blacklist、rate_limit、composite。类型不是装饰字段：`validate_policy_definition` 对每类要求特定字段条件，例如 keyword 必须有 `content` 的 `contains`/`in` 条件，regex 必须有 `content` 的 `regex` 条件，rate_limit 必须有 `rate_count` 条件。

## 2. 条件表达

条件使用受限 JSON 结构，不执行任意 Python 或 SQL：

```json
{
  "all": [
    {"field": "content", "op": "contains", "value": "免费"},
    {"any": [
      {"field": "risk_score", "op": "gte", "value": 0.8},
      {"field": "category", "op": "in", "value": ["fraud"]}
    ]},
    {"not": {"field": "sender_ref", "op": "in", "value": ["trusted.bot"]}}
  ]
}
```

- 逻辑节点：`all` / `any` / `not`，最大嵌套深度 5，最大节点数 64。
- 字段白名单：`content`、`content_hash`、`channel`、`language`、`sender_ref`、`server_ref`、`alliance_id`、`risk_level`、`risk_score`、`confidence`、`rate_count`、`content_length`、`category`、`category_score`。
- 操作符白名单：`eq`、`ne`、`in`、`not_in`、`contains`、`not_contains`、`regex`、`gte`、`gt`、`lte`、`lt`、`exists`。
- 正则限制：长度 ≤ 200，禁止 lookaround 与反向引用，编译期校验。
- 支持字段别名：`text→content`、`player_ref→sender_ref`、`server→server_ref`、`alliance→alliance_id`、`level→risk_level`。

无效定义抛出 `PolicyValidationError`，不会进入存储或运行时。

## 3. 作用范围

`target_scope` 支持 `players`、`alliances`、`servers`、`channels`、`languages` 五个维度，均为非空字符串列表。任一维度非空时，消息必须命中该维度的某个值；多维度为 AND 关系。

`specificity()` 定义：有 players = 4，alliances = 3，servers = 2，其他 = 1。范围越具体，在优先级相同时越优先。

## 4. 版本与回滚

- 每次创建、修改、启停、回滚都生成新的 `policy_version` 行。
- `(policy_id, version)` 唯一；历史版本只读保留。
- `rollback_policy(target_version=N)` 从历史版本复制内容，生成 `version=N+1` 的新版本，不覆盖历史。
- `compare_versions(policy_id, left, right)` 返回 `changed` 字段差异与 `identical` 标记。
- 版本号用于评估快照哈希，策略变更会改变后续评估结果。

## 5. 命中计数与缓存

- 策略命中次数持久化在 `policy.hit_count`，仅在评估首次创建时递增，重复评估不重复计数。
- Redis 缓存生效策略快照，TTL 来自 `governance.policy_cache_ttl_seconds`（默认 60 秒）。
- 创建、更新、启停、回滚都会主动失效策略缓存；Redis 不可用时回退 PostgreSQL，不中断业务。

## 6. 策略测试（Playground）

`PolicyService.playground()` 接受消息内容、风险分、等级、置信度及上下文，可选传入一个未保存的候选策略定义：

- 校验候选策略，但不写入数据库；
- 列出命中与未命中策略、满足/不满足的条件；
- 给出冲突、优先级排序结果、最终动作；
- 不执行任何处置。

UI 的 Policy Center 提供对应交互入口。Playground 中候选策略字段缺失时使用已校验的默认值，不会因缺省键崩溃。

## 7. 冲突检测

`find_policy_conflicts()` 扫描所有启用策略：作用范围重叠、emergency 相同、priority 相同且动作不同即为 `priority_tie` 冲突。评估时在 `policy_evaluation.conflicts` 中保留本次实际命中策略之间的冲突，并在解释中给出最终选择依据。

## 8. 默认策略

`ensure_default_policy()` 创建带 `is_default` 标记的策略。无策略命中时按风险等级应用默认动作：normal/low → ALLOW，medium → WARN，high/critical → REVIEW。默认动作表可通过 `PolicyEvaluationService(default_actions=...)` 覆盖。
