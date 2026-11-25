# Claro Phase 04 — 测试报告

日期：2026-11-25
环境：Windows 11 原生，Python 3.12.10，PostgreSQL 5432、Redis 6379、Kafka 9092 真实服务。
数据：全部为合成数据（synthetic），测试创建的数据集在 teardown 中清理。

## 1. 实际执行命令与结果

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/unit -q` | **216 passed** |
| `python -m pytest tests/integration -q -o addopts=""` | **22 passed**, 1 DeprecationWarning（Alembic 配置提示） |
| `python -m ruff check src tests` | **All checks passed** |
| `python -m compileall -q src/claro tests` | 通过 |
| `python tests/ui/governance_pages_smoke.py` | **6/6 页面通过**真实浏览器渲染 |
| `python -m alembic current` | `c79ffc3a04ff (head)` |
| `python -m claro governance-seed-policies` | 通过，目录 42 条，本次新增 0（已存在） |
| `python -m claro governance-evaluate --message <id>` | 通过，命中 `gov-critical-risk-review` 并给出解释 |
| `python -m claro governance-expire-enforcements` | 通过，`expired=2` |
| `python -m claro governance-dispatch-outbox` | 通过，`fetched=137, published=137, failed=0` |

## 2. 测试构成

新增测试文件：

| 文件 | 覆盖 |
|---|---|
| `tests/unit/test_governance_policy.py` | 条件校验、字段白名单、正则安全、优先级、范围具体性、确定性排序、白名单边界、默认动作、快照哈希 |
| `tests/unit/test_governance_decision.py` | 自动决策、高严重度低置信度降级、自定义阈值、优先级、输入校验 |
| `tests/unit/test_governance_moderation.py` | 认领校验、状态机、理由与覆盖校验、二次复核、重开 |
| `tests/unit/test_governance_enforcement.py` | 处置计划、目标/时长约束、到期、目标校验 |
| `tests/unit/test_governance_scenarios.py` | 15 个业务场景 |
| `tests/integration/test_governance_postgres.py` | 策略版本/回滚、评估/决策幂等、审核并发与反馈、处置状态与失败、反馈与审计 |
| `tests/integration/test_governance_redis.py` | 策略缓存失效、限流计数缓存、玩家状态缓存失效 |
| `tests/integration/test_governance_kafka.py` | 风险事件消费与 Outbox、真实 Kafka 发布/消费、风险结果持久化 |
| `tests/ui/governance_pages_smoke.py` | 六个治理页面浏览器冒烟测试 |

## 3. 业务场景覆盖

以下 15 个场景均有对应测试：

1. 正常消息 → ALLOW
2. 轻度违规 → WARN
3. 明确广告垃圾 → BLOCK
4. 高风险诈骗 → REVIEW 或按明确授权策略处置
5. 高严重程度、低置信度 → REVIEW
6. 多条策略同时命中 → 确定性冲突解决
7. 白名单玩家 → 在明确豁免范围内处理
8. 高频刷屏 → 命中 RATE LIMIT 条件
9. 人工审核推翻系统判断 → 保留反馈
10. 人工确认漏判/误杀 → 生成错误案例
11. MUTE → 模拟禁言状态
12. TEMP_BAN → 模拟临时封禁与到期
13. 重复消费同一事件 → 不产生重复处罚（唯一键 + 幂等键）
14. 策略回滚 → 历史版本仍保留，新版本生成
15. 审核并发 → 乐观锁拒绝过期提交

## 4. 测试过程中发现并修复的缺陷

测试不是一次通过。实际发现并修复如下问题：

| # | 缺陷 | 修复 |
|---|---|---|
| 1 | `PolicyService.playground()` 用 `.get()` 取默认值却又用 `[]` 索引必填键，候选策略缺键时 KeyError | 先解析局部变量再构造快照 |
| 2 | `EnforcementService._invalidate()` 将 `target_type` 与 `DecisionAction.BLOCK` 比较，条件恒假 | 改为与 `EnforcementTargetType.MESSAGE` 比较 |
| 3 | `override_decision()` 在数据库更新后才校验 action，非法输入已产生脏写 | 校验前置到更新前 |
| 4 | 审核提交假设 `risk_snapshot.categories` 为字典列表，实际是字符串列表，导致 `AttributeError` | 兼容字符串与字典两种结构 |
| 5 | 新建 `PlayerEnforcementState` 的 `warn_count` 在 flush 前为 None，WARN 处置崩溃 | 使用 `(warn_count or 0) + 1` |
| 6 | 解除/到期后缓存只按 `*` 作用域失效，服务器作用域仍显示受限 | 同时失效 `*` 与 `server_ref` 作用域 |
| 7 | 治理流水线用 strict 模型直接校验 JSON 字符串载荷，所有风险事件被判永久错误 | 新增 `RiskAssessedPayload.from_json_mapping()`，与既有事件约定一致 |
| 8 | `governance-dispatch-outbox` 独立运行时治理 Topic 不存在，事件投递失败 | 分发前确保治理 Topic 已创建 |
| 9 | 审核工作台 UI 读取 `case["id"]`，详情实际返回 `case_id`，页面渲染失败 | 兼容两种键名并对缺失数据给出提示 |
| 10 | Streamlit 将 `ui/pages/` 识别为多页应用，侧边栏出现重复导航 | `showSidebarNavigation = false` |

## 5. 未验证 / 阻塞项

- Hive 引擎未安装，Hive SQL 仍未执行；本阶段不声称 Hive 验证通过。
- 语义检测器仍为显式不可用占位；LLM 顾问默认关闭，未对真实端点验证。
- UI 身份为模拟身份，未实现生产级身份认证与 RBAC。
- 未连接真实游戏服务器，所有处罚均为内部模拟。
