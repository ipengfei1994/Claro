# Claro — 关键论点证据索引

本文件服务于 [claro-case-study.md](claro-case-study.md) 的事实核验，不替代作品集正文。它区分代码事实、原始运行产物、项目文档、负责人陈述和“仓库中未发现实现”，避免把设计目标、单次运行或截图当成已验证的生产能力。

## 1. 证据口径

| 标记 | 含义 | 可支持的表述 |
| --- | --- | --- |
| `CODE` | 当前源码、配置或迁移可直接验证 | “已实现某逻辑/约束/接口” |
| `RAW` | 仓库保留原始 JSON、日志、模型元数据等运行产物 | “在某次保留运行中观察到某结果” |
| `DOC` | 阶段报告或项目文档记录，未必保留对应原始日志 | “项目记录显示”，不能升级为独立复核 |
| `TEST` | 测试代码或测试运行结果 | “在测试条件与样本范围内成立” |
| `OWNER` | 项目负责人明确提供的个人角色与工作方式 | 可用于第一人称案例，需说明来源 |
| `ABSENCE` | 对当前仓库的源码、引用和配置检索后未发现 | “当前仓库未实现/未接入”，不推断仓库外状态 |

**基线**：`HEAD = 6a78879`，分支 `main`。本次仅修改 `portfolio/` 作品集材料，没有修改业务源码、数据库结构、README、现有技术文档或项目功能，没有重新运行服务/测试，没有提交 Git Commit。

## 2. 项目定位与个人角色

| ID | 案例论点 | 证据 | 等级 | 使用边界 |
| --- | --- | --- | --- | --- |
| E01 | Claro 是本地优先、使用合成数据的 SLG 治理原型 | [README.zh-CN.md](https://github.com/ipengfei1994/Claro/blob/main/README.zh-CN.md)；[app.py:85-103](https://github.com/ipengfei1994/Claro/blob/main/src/claro/ui/app.py#L85) | CODE / DOC | 不宣称企业落地或真实运营 |
| E02 | 用户独立主导整体，AI 承担大部分代码实现 | 负责人在任务中明确陈述 | OWNER | 不写成用户逐行编写全部代码 |
| E03 | 用户负责目标、Phase、任务、Prompt、本地检查、修正和验收 | 负责人在任务中明确陈述；阶段计划与验收报告提供部分旁证 | OWNER / DOC | 工作方式可用第一人称；具体过程没有完整 Prompt 记录 |
| E04 | 不虚构原始 Prompt、AI 对话、效率比例或逐行审查 | 当前仓库检索未发现完整开发 Prompt / 对话 transcript | ABSENCE | `AGENTS.md` 是工程合同；`llm.py` 是产品运行时提示词 |
| E05 | 项目不接真实游戏服务器，处置均为模拟 | [enforcement.py:45-107](https://github.com/ipengfei1994/Claro/blob/main/src/claro/governance/enforcement.py#L45) | CODE | `simulated=True` 是处置计划默认值 |
| E06 | 不声称真实业务验证 | `runtime/demo_report.json:551-558`（本地保留，未公开）；[README.zh-CN.md](https://github.com/ipengfei1994/Claro/blob/main/README.zh-CN.md) | RAW / DOC | 合成演示、测试和回放不能外推到真实玩家 |

## 3. SLG 载体与风险覆盖

| ID | 案例论点 | 证据 | 等级 | 使用边界 |
| --- | --- | --- | --- | --- |
| E07 | 游戏聊天是端到端实现的主载体 | [message_events.py:24-55](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/message_events.py#L24)；[message.py:10-24](https://github.com/ipengfei1994/Claro/blob/main/src/claro/domain/message.py#L10) | CODE | 通用消息模型，不是专用聊天产品 |
| E08 | `private / system` 等是频道字符串，不自动等于邮件/公告 | [generator.py:151-157](https://github.com/ipengfei1994/Claro/blob/main/src/claro/data_generation/generator.py#L151)；payload `channel: str` | CODE | 不能按频道名推断实体能力 |
| E09 | 联盟上下文和策略范围部分实现 | [policy.py:20-58](https://github.com/ipengfei1994/Claro/blob/main/src/claro/governance/policy.py#L20)；[policy.py:65-82](https://github.com/ipengfei1994/Claro/blob/main/src/claro/governance/policy.py#L65) | CODE | 没有独立联盟帖子、公告板或审批流 |
| E10 | 玩家邮件未实现 | payload 无 recipient/subject/thread；消息模型无信箱实体 | ABSENCE | `private` 只代表采样频道 |
| E11 | 游戏公告未实现 | 无公告实体、受众、发布审批或专用审核链路 | ABSENCE | `system` 采样不等于公告审核 |
| E12 | 玩家昵称未进入检测 | [models.py:160-190](https://github.com/ipengfei1994/Claro/blob/main/src/claro/data_access/models.py#L160)；检测服务分析 `message.content` | CODE / ABSENCE | `display_name` 是档案字段，不是已治理载体 |
| E13 | 风险分类法有 7 域、19 细类 | [risk_taxonomy.yaml:22-52](https://github.com/ipengfei1994/Claro/blob/main/config/risk_taxonomy.yaml#L22) 及后续分类定义 | CODE | 细类不等于模型标签数 |
| E14 | 数据库/模型有 8 个落库类别 | [risk_taxonomy.yaml:53-421](https://github.com/ipengfei1994/Claro/blob/main/config/risk_taxonomy.yaml#L53) 的 `db_category_names` | CODE | 账号交易等类别可映射到 `other` |
| E15 | 22 条规则覆盖广告、导流、欺诈、交易、骚扰、色情、自伤等 | [detection_rules.yaml:14-296](https://github.com/ipengfei1994/Claro/blob/main/config/detection_rules.yaml#L14) | CODE | 规则存在不等于真实业务覆盖率 |
| E16 | 政治/通用政治敏感类别与规则未实现 | 分类法和规则文件未发现对应类别/规则 | ABSENCE | 只能写“色情已实现，政治敏感未实现” |
| E17 | 账号出售、代练、站外资产交易有规则 | [detection_rules.yaml:14-296](https://github.com/ipengfei1994/Claro/blob/main/config/detection_rules.yaml#L14) | CODE | 不是真实黑市数据或专门黑市实体模型 |
| E18 | 5 个风险等级与检测动作阈值分离配置 | [risk_thresholds.yaml:8-38](https://github.com/ipengfei1994/Claro/blob/main/config/risk_thresholds.yaml#L8) | CODE | `restrict` 是检测建议，不是可执行处置动作 |

## 4. 检测、融合与证据链

| ID | 案例论点 | 证据 | 等级 | 使用边界 |
| --- | --- | --- | --- | --- |
| E19 | 规则与 ML 独立产生证据，检测不直接执行处置 | [fusion.py:185-303](https://github.com/ipengfei1994/Claro/blob/main/src/claro/risk_engine/fusion.py#L185) | CODE | 检测输出 `suggested_action` |
| E20 | 融合公式为加权 noisy-OR，总分取最高类别分 | [fusion.py:256-302](https://github.com/ipengfei1994/Claro/blob/main/src/claro/risk_engine/fusion.py#L256)；[risk_thresholds.yaml](https://github.com/ipengfei1994/Claro/blob/main/config/risk_thresholds.yaml) | CODE | 权重手工设定，非统计校准 |
| E21 | 每类贡献、公式、阈值和冲突被保留 | [fusion.py:273-285](https://github.com/ipengfei1994/Claro/blob/main/src/claro/risk_engine/fusion.py#L273) | CODE | 可解释性是保留计算过程，不是模型自身可解释 |
| E22 | 缺层不重新归一化，也不把缺失当零分 | 融合只累计实际贡献项；[risk_thresholds.yaml](https://github.com/ipengfei1994/Claro/blob/main/config/risk_thresholds.yaml) | CODE | 当前主要有效层为 rule + ML |
| E23 | 自伤示例检测建议 `restrict`，治理最终 `review` | `runtime/demo_report.json:350-417`（本地保留，未公开） | RAW | 单条合成样例，不是普遍阈值效果 |
| E24 | 多信号交易示例检测建议 `review`，治理最终 `warn` | `runtime/demo_report.json:419-491`（本地保留，未公开） | RAW | 证明职责分离，不证明策略最优 |
| E25 | 语义检测是显式占位，返回 `None` | [semantic.py:35-46](https://github.com/ipengfei1994/Claro/blob/main/src/claro/risk_engine/semantic.py#L35) | CODE | 不得描述为已实现语义检测 |
| E26 | LLM 有 HTTP 适配器但默认关闭、仅顾问 | [llm.py:66-128](https://github.com/ipengfei1994/Claro/blob/main/src/claro/risk_engine/llm.py#L66)；[settings.py:87-100](https://github.com/ipengfei1994/Claro/blob/main/src/claro/config/settings.py#L87) | CODE / TEST | 测试使用 fake transport；无真实凭证端点证据 |

## 5. 策略、审核、处置与反馈

| ID | 案例论点 | 证据 | 等级 | 使用边界 |
| --- | --- | --- | --- | --- |
| E27 | 默认 normal/low 允许，medium 警告，high/critical 送审 | [policy.py:20-58](https://github.com/ipengfei1994/Claro/blob/main/src/claro/governance/policy.py#L20) | CODE | 默认映射可被匹配策略改变 |
| E28 | 限制性动作低置信度降级；高风险低置信度也转审核 | [decision.py:24-104](https://github.com/ipengfei1994/Claro/blob/main/src/claro/governance/decision.py#L24) | CODE | 默认门槛为 0.55 / 0.70；高风险分支不限于限制性动作 |
| E29 | 策略支持玩家、联盟、服务器、频道、语言范围 | [policy.py:20-82](https://github.com/ipengfei1994/Claro/blob/main/src/claro/governance/policy.py#L20) | CODE | 联盟是上下文范围，不是独立内容实体 |
| E30 | 策略条件为声明式白名单，排序确定 | [policy.py](https://github.com/ipengfei1994/Claro/blob/main/src/claro/governance/policy.py)；[PHASE_04_COMPLETION_REPORT.md:44-73](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_04_COMPLETION_REPORT.md#L44) | CODE / DOC | 不接受任意 Python 表达式 |
| E31 | 策略快照与 SHA-256 哈希支持版本追溯 | [policy.py:148-171](https://github.com/ipengfei1994/Claro/blob/main/src/claro/governance/policy.py#L148) | CODE | 回滚创建新版本，不删除历史 |
| E32 | 策略中心支持 CRUD、版本、比较、回滚、Playground | [policy_center.py:108-401](https://github.com/ipengfei1994/Claro/blob/main/src/claro/ui/screens/policy_center.py#L108) | CODE | 是策略管理，不是独立敏感词全生命周期 |
| E33 | `expected_version` 是应用层检查，不是数据库 CAS | [policy_repository.py:132-225](https://github.com/ipengfei1994/Claro/blob/main/src/claro/data_access/repositories/policy_repository.py#L132) | CODE | 不把它写成强数据库并发保证 |
| E34 | 审核使用状态机、`FOR UPDATE` 和 `lock_version` | [governance_repository.py:822-995](https://github.com/ipengfei1994/Claro/blob/main/src/claro/data_access/repositories/governance_repository.py#L822) | CODE | 模拟身份不等于生产 RBAC |
| E35 | 审核拒绝表示不处置；限制玩家需显式 override | [moderation state-machine SVG](../assets/03-moderation-state-machine.svg)；[PHASE_04_COMPLETION_REPORT.md:75-85](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_04_COMPLETION_REPORT.md#L75) | CODE / DOC | override 要求最终动作与等级 |
| E36 | 五类处置全部模拟 | [enforcement.py:8-107](https://github.com/ipengfei1994/Claro/blob/main/src/claro/governance/enforcement.py#L8) | CODE | `review / flag / restrict` 不是直接执行动作 |
| E37 | 反馈记录误杀、漏判、类别/等级/动作错误，但不自动重训 | [feedback_audit_service.py:29-93](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/feedback_audit_service.py#L29) | CODE | 反馈是复盘输入，不是在线学习闭环 |
| E38 | 追加式审计不是防篡改存储 | 审计通过应用仓储写入；无 cryptographic tamper-proof 证据 | CODE / ABSENCE | 使用“应用层追加记录”而非“不可篡改” |
| E39 | 敏感词/玩家黑名单有部分基础设施，未完整接入主产品链 | [safety_repository.py:23-139](https://github.com/ipengfei1994/Claro/blob/main/src/claro/data_access/repositories/safety_repository.py#L23)；[safety_cache.py](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/safety_cache.py)；[bootstrap.py:151](https://github.com/ipengfei1994/Claro/blob/main/src/claro/bootstrap.py#L151) | CODE / ABSENCE | 不宣称完整敏感词 CRUD 与主链路联动 |

## 6. 架构、基础设施与数据链路

| ID | 案例论点 | 证据 | 等级 | 使用边界 |
| --- | --- | --- | --- | --- |
| E40 | 模块化单体与两种运行模式 | [bootstrap.py:115-235](https://github.com/ipengfei1994/Claro/blob/main/src/claro/bootstrap.py#L115) | CODE | development 用内存总线；full 连接真实基础设施 |
| E41 | PostgreSQL 是权威数据源 | [bootstrap.py:118-169](https://github.com/ipengfei1994/Claro/blob/main/src/claro/bootstrap.py#L118)；[database/session repositories](https://github.com/ipengfei1994/Claro/blob/main/src/claro/data_access/) | CODE | 全文统一使用 PostgreSQL 口径 |
| E42 | Redis 在主治理链路承担规则/策略缓存与计数缓存 | [rules.py:433-461](https://github.com/ipengfei1994/Claro/blob/main/src/claro/risk_engine/rules.py#L433)；[policy_service.py:269-288](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/policy_service.py#L269)；[governance_cache.py:42-61](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/governance_cache.py#L42)；[policy_evaluation_service.py:47-65](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/policy_evaluation_service.py#L47) | CODE | `rate_count` 由 PostgreSQL 查询后写入 Redis 缓存，不是 Redis 原子限流结果 |
| E43 | 统一入口执行五个阶段 | [processing_service.py:187-321](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/processing_service.py#L187) | CODE | 实际为 validate → ingest → detect → publish → governance |
| E44 | 直接路径发布风险事件后进程内调用治理 | [processing_service.py](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/processing_service.py)；[event SVG](../assets/04-event-and-idempotency.svg) | CODE | 不等于等待 Kafka 消费者回调 |
| E45 | Kafka 消费链关闭自动提交，成功/路由后提交 offset | [kafka.py:461-641](https://github.com/ipengfei1994/Claro/blob/main/src/claro/infrastructure/kafka.py#L461) | CODE | at-least-once，不声称 exactly-once |
| E46 | 可重试错误进 retry，永久错误/耗尽进 DLQ | [kafka.py:597-641](https://github.com/ipengfei1994/Claro/blob/main/src/claro/infrastructure/kafka.py#L597) | CODE | 这是 Kafka consumer 路径，不是 Outbox DLQ |
| E47 | Outbox 只覆盖选定治理写入 | [governance_repository.py](https://github.com/ipengfei1994/Claro/blob/main/src/claro/data_access/repositories/governance_repository.py)；[outbox_dispatcher.py:56-96](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/outbox_dispatcher.py#L56) | CODE | 不是全链路统一事务机制 |
| E48 | evaluation 在评估提交后入 Outbox | [governance_pipeline_service.py:55-90](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/governance_pipeline_service.py#L55) | CODE | 不与 evaluation 同事务 |
| E49 | Outbox 耗尽停在 `failed`，没有自动 DLQ | [governance_repository.py:1585-1620](https://github.com/ipengfei1994/Claro/blob/main/src/claro/data_access/repositories/governance_repository.py#L1585) | CODE | 不能沿用文档中“exhausted → DLQ”的宽泛表述 |
| E50 | 5 个治理 topic 已发布，但仓库内无业务消费者 | [settings.py:114-128](https://github.com/ipengfei1994/Claro/blob/main/src/claro/config/settings.py#L114)；consumer 引用检索 | CODE / ABSENCE | 可写“事件发布端”，不写“下游闭环已接通” |
| E51 | 两条入口当前都包含 `occurred_at`；直接路径注释与实现不一致 | [processing_service.py:369-394](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/processing_service.py#L369) 的 `stable_envelope=payload.model_dump()`；[kafka_repository.py:303-305](https://github.com/ipengfei1994/Claro/blob/main/src/claro/data_access/repositories/kafka_repository.py#L303)；[kafka_ingestion.py:40-68](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/kafka_ingestion.py#L40) | CODE | 直接路径注释声称排除发送时间，但完整 payload 含该字段；重放需保持时间一致 |
| E52 | 三层幂等：inbox、risk result、治理确定性键 | [event SVG](../assets/04-event-and-idempotency.svg)；相关 repository 唯一约束 | CODE | 幂等吸收重复，不等于端到端 exactly-once |
| E53 | `trace_id` 未统一覆盖所有治理记录 | 风险/消息事件有 trace；治理记录主要依赖 entity IDs 和关联 | CODE / ABSENCE | 用“实体关联可追溯”，不写“所有记录同 trace_id” |
| E54 | 逐阶段耗时没有全部持久化到 `processing_event` | [processing_service.py](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/processing_service.py)；risk result timings | CODE | 返回对象有阶段耗时，不代表每阶段都有处理事件 |
| E55 | UI 有 15 页、5 组，页面不直接执行 SQL | [app.py:42-68](https://github.com/ipengfei1994/Claro/blob/main/src/claro/ui/app.py#L42)；[app.py:85-128](https://github.com/ipengfei1994/Claro/blob/main/src/claro/ui/app.py#L85) | CODE | 页面数量不是业务成熟度 |
| E56 | Light / Dark / System 与 45 秒纯读缓存 | [theme.py](https://github.com/ipengfei1994/Claro/blob/main/src/claro/ui/theme.py)；[cache.py](https://github.com/ipengfei1994/Claro/blob/main/src/claro/ui/cache.py)；[app.py:95-101](https://github.com/ipengfei1994/Claro/blob/main/src/claro/ui/app.py#L95) | CODE | 写操作不走纯读缓存 |
| E57 | Hive SQL/CSV 存在，但执行 Blocked | [run_warehouse.ps1:16-22](https://github.com/ipengfei1994/Claro/blob/main/warehouse/hive/run_warehouse.ps1#L16)；[HIVE_OFFLINE_ANALYTICS.md](https://github.com/ipengfei1994/Claro/blob/main/docs/HIVE_OFFLINE_ANALYTICS.md) | CODE / DOC | 未安装 Hive/Hadoop/Beeline，不描述为已贯通 |

## 7. AI 辅助开发与阶段纠偏

| ID | 案例论点 | 证据 | 等级 | 使用边界 |
| --- | --- | --- | --- | --- |
| E58 | Phase 04 主体实现早于该阶段，阶段重点是集成审查、测试和修复 | [PHASE_04_COMPLETION_REPORT.md:7-23](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_04_COMPLETION_REPORT.md#L7) | DOC | 不把 Phase 04 写成全部从零实现 |
| E59 | Phase 04 验收关注策略影响真实决策、审核关联风险、处置可追溯 | 负责人本地阶段记录（未纳入 Git）；Phase 04 报告为结果旁证 | OWNER / DOC | 本地记录未纳入 Git，不能伪装成公开仓库证据 |
| E60 | Phase 05 曾判定“不可接受”，修复 6 个实质问题后可接受 | [PHASE_05_ACCEPTANCE_REVIEW.md:9-119](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_05_ACCEPTANCE_REVIEW.md#L9) | DOC | 是阶段验收记录，不是真实业务 KPI |
| E61 | 回放样本池曾排除正常消息，导致 TN/FN 结构性缺失 | [PHASE_05_ACCEPTANCE_REVIEW.md:168-174](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_05_ACCEPTANCE_REVIEW.md#L168) | DOC | 修复后样本含 83 risk-event + 417 no-risk-event |
| E62 | 500 条回放证明命中更多不等于策略更好 | [PHASE_05_ACCEPTANCE_REVIEW.md:149-166](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_05_ACCEPTANCE_REVIEW.md#L149) | DOC | 合成回放，不证明线上收益 |
| E63 | 回放隔离升级为 9 表内容级 SHA-256 | [PHASE_05_ACCEPTANCE_REVIEW.md:178-209](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_05_ACCEPTANCE_REVIEW.md#L178) | DOC / TEST | 比单纯行数比较更强，但不是生产隔离认证 |
| E64 | Phase 06 修复多种“假绿”测试工具问题 | [PHASE_06_TEST_REPORT.md:133-142](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_06_TEST_REPORT.md#L133) | DOC | 具体问题有记录；不虚构对话原文 |
| E65 | `-Suite all` 曾排除集成测试 | [PHASE_06_TEST_REPORT.md:138](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_06_TEST_REPORT.md#L138) | DOC | 说明测试范围需要核验 |
| E66 | 浏览器巡检曾把默认页回退误判为成功 | [PHASE_06_TEST_REPORT.md:142](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_06_TEST_REPORT.md#L142) | DOC | 当前保留浏览器日志仍有失败，不能声称最新浏览器全通过 |
| E67 | 没有量化 AI 提效、团队评审或逐行审查证据 | 仓库记录检索 | ABSENCE | 不写“效率提升 X%”“代码逐行审过” |

## 8. 演示、测试、模型、性能与回放

| ID | 案例论点 | 证据 | 等级 | 使用边界 |
| --- | --- | --- | --- | --- |
| E68 | 7 条演示消息全部 processed，8 组操作步骤全部 ok | `runtime/demo_report.json:493-558`（本地保留，未公开） | RAW | 不是 50k 全链路执行证据 |
| E69 | 演示覆盖 claim、override、模拟禁言/封禁、解除、反馈和回放 | `runtime/demo_report.json:502-549`（本地保留，未公开） | RAW | 7 条样本回放为低样本探索 |
| E70 | 最终保留测试为 308 passed / 1 warning / 103.32s | `runtime/tests_final.log:127-129`（本地保留，未公开） | RAW | 本次没有重跑；1 warning 不可省略 |
| E71 | 最终整体语句覆盖率 79% | `runtime/tests_final.log:127-129`（本地保留，未公开） | RAW | 不是分支覆盖率 |
| E72 | `processing_service.py` 覆盖率仅 40% | `runtime/tests_final.log:49`（本地保留，未公开） | RAW | 不能用总体 79% 掩盖关键路径不足 |
| E73 | 240 unit + 51 integration + 17 UI smoke 的阶段分组 | [PHASE_06_TEST_REPORT.md:3-42](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_06_TEST_REPORT.md#L3) | DOC | 最终 raw log 未完整独立显示该拆分 |
| E74 | 可靠性 7/7 为文档记录 | [PHASE_06_TEST_REPORT.md:108-124](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_06_TEST_REPORT.md#L108) | DOC | 未找到对应完整原始执行日志 |
| E75 | 保留浏览器日志为连接拒绝，不能支持成功声明 | `runtime/browser_smoke.log:34`（本地保留，未公开） | RAW | 截图存在不等于浏览器自动化通过 |
| E76 | 普通模型测试指标全部 1.0 | `models/risk_ml/.../metadata.json:182-204,312-327`（本地保留，未公开）；[MODEL_EVALUATION.md:75-91](https://github.com/ipengfei1994/Claro/blob/main/docs/MODEL_EVALUATION.md#L75) | RAW / DOC | 不能作为生产准确率 |
| E77 | 玩家级隔离成立，内容重复率 99.47% | `models/risk_ml/.../metadata.json:329-347`（本地保留，未公开） | RAW | 内容级泛化未建立 |
| E78 | 内容不相交子集 27 条且全为 normal | `models/risk_ml/.../metadata.json:348-490`（本地保留，未公开）；[MODEL_EVALUATION.md:117-132](https://github.com/ipengfei1994/Claro/blob/main/docs/MODEL_EVALUATION.md#L117) | RAW / DOC | accuracy 1.0 无意义，不能估计风险泛化 |
| E79 | 8 个模型阈值全部为 0.20 | [MODEL_EVALUATION.md:57-73](https://github.com/ipengfei1994/Claro/blob/main/docs/MODEL_EVALUATION.md#L57) | DOC | 是困难样本不足的警示 |
| E80 | 流水线 p50/p95/p99 为 128.2/189.32/271.54、107.1/149.69/179.5、144.51/215.5/331.59 ms | [performance_results.json:28-259](https://github.com/ipengfei1994/Claro/blob/main/docs/performance_results.json#L28) | RAW | 每档 200 条，单进程串行 |
| E81 | 600 条流水线样本全部 processed | [performance_results.json](https://github.com/ipengfei1994/Claro/blob/main/docs/performance_results.json) | RAW | 不代表 50k 历史全链路 |
| E82 | 批量入库 62.4–77.6 行/秒 | [performance_results.json](https://github.com/ipengfei1994/Claro/blob/main/docs/performance_results.json)；[PHASE_06_PERFORMANCE.md:76-91](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_06_PERFORMANCE.md#L76) | RAW / DOC | 不是完整治理吞吐或生产 QPS |
| E83 | 纯分析基准调用 `RiskService.analyze_text()` | [benchmark_pipeline.py:287-293](https://github.com/ipengfei1994/Claro/blob/main/scripts/benchmark_pipeline.py#L287) | CODE | 不应写成完整 `RiskService.detect()` |
| E84 | 性能不含浏览器/TLS/代理/并发 | [PHASE_06_PERFORMANCE.md:57-72](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_06_PERFORMANCE.md#L57) | DOC | 只能作为本机串行基线 |
| E85 | JSON 是合并产物，不是单次快照 | [performance_results.json:2,298](https://github.com/ipengfei1994/Claro/blob/main/docs/performance_results.json#L2) | RAW | `generated_at` 早于 `validation_measured_at`；“Round B”是文档标签 |
| E86 | Redis 50 次同键读取命中率 100% | [performance_results.json](https://github.com/ipengfei1994/Claro/blob/main/docs/performance_results.json)；[PHASE_06_PERFORMANCE.md:19](https://github.com/ipengfei1994/Claro/blob/main/docs/PHASE_06_PERFORMANCE.md#L19) | RAW / DOC | 不代表长期生产命中率 |
| E87 | 历史 50,016 消息 / 8,856 risk event / 50,016 decision | [performance_results.json:284-289](https://github.com/ipengfei1994/Claro/blob/main/docs/performance_results.json#L284) | RAW / DOC | risk event 主要是批量原子证据 |
| E88 | 完整融合结果数量随采集时点为 7/15/17 | 风险情报截图与阶段证据报告 | RAW / DOC | 不可把 8,856 risk events 当成完整融合数 |
| E89 | KPI 版本 `phase-05.2`，分母 <30 不发布比率，回放 <100 为探索性 | [definitions.py:15-53](https://github.com/ipengfei1994/Claro/blob/main/src/claro/analytics/definitions.py#L15) | CODE | 不是所有比率都自动有统计显著性 |
| E90 | 回放使用评估时刻策略，不是历史时刻重建；限流计数为 0 | [strategy.py:136-156](https://github.com/ipengfei1994/Claro/blob/main/src/claro/analytics/strategy.py#L136)；[strategy.py:301-343](https://github.com/ipengfei1994/Claro/blob/main/src/claro/analytics/strategy.py#L301) | CODE | 只可比较同输入下的策略差异 |
| E91 | 7 条截图与 `docs/screenshots/` 源文件曾逐字节一致 | 前次核验记录；本次未重新计算哈希 | RAW / DOC | 截图证明界面状态，不证明最新运行成功 |
| E92 | 合成标签与批量 `risk_event` 由同一生成器依据标签/类别产生 | [generator.py:782-910](https://github.com/ipengfei1994/Claro/blob/main/src/claro/data_generation/generator.py#L782)：标签概率、模板选择、`annotator_type=synthetic_generator`、`should_emit_risk` 与 `RiskEventRecord` | CODE | 历史检测召回/漏判只反映合成数据内部一致，不是独立人工标注或真实检测效果 |
| E93 | Lua `INCR + EXPIRE` 限流适配器存在，但未接入主治理调用链 | [redis.py:7-38](https://github.com/ipengfei1994/Claro/blob/main/src/claro/infrastructure/redis.py#L7)；[safety_cache.py:178-198](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/safety_cache.py#L178)；`check_rate_limit()` 仅测试与独立服务引用；主评估走 [governance_cache.py:42-61](https://github.com/ipengfei1994/Claro/blob/main/src/claro/application/governance_cache.py#L42) | CODE / ABSENCE | 可写“独立原子限流能力”，不能写成主消息治理已使用 Redis 原子限流 |

## 9. 已纠正的容易误读点

| 主题 | 不采用的表述 | 案例采用的表述 |
| --- | --- | --- |
| Redis | “黑名单、敏感词和原子限流已完整接入治理” | 主链路使用规则/策略缓存与 PostgreSQL 计数缓存；黑名单和 Lua 原子限流适配器存在但未接主治理调用链 |
| 合成指标 | “历史检测召回率高、漏判为零，说明漏放治理有效” | 标签与批量风险事件由同一生成器产生，只说明合成数据内部一致，不能估计真实漏放 |
| 载体 | “聊天、联盟、邮件、公告、昵称均已实现” | 通用聊天完整；联盟为上下文；邮件、公告、昵称未实现 |
| 政治敏感 | “敏感内容识别已完成” | 色情规则/标签存在；政治或通用政治敏感识别不存在 |
| Trace | “所有阶段和记录共享同一 trace_id” | 消息/风险事件有 trace；治理追溯还依赖实体关联 |
| Outbox | “所有消息与 Kafka 发布都在同一事务” | 选定治理写入使用 Outbox；evaluation 提交后入队；Outbox 无自动 DLQ |
| 内容哈希 | “直接路径排除发送时间” | 当前 `stable_envelope` 使用完整 payload，包含 `occurred_at`；注释与实现不一致，Kafka envelope 也包含该字段 |
| 模型 | “F1 1.0 证明模型准确率” | 模板可分，但 99.47% 内容重复；真实泛化未验证 |
| 数据量 | “50,016 条消息全部完成治理” | 50k 是历史基线；完整融合证据有限，核心链路主要为演示与基准样本 |
| 性能 | “系统达到 X QPS” | 单机单进程串行延迟与批量入库基线，不含并发争用 |
| AI 开发 | “AI 独立完成项目”或“我逐行实现全部代码” | 我主导目标、任务、Prompt、验证、修正与验收；AI 承担大部分编码 |
| 浏览器 | “现有截图证明浏览器自动化全部通过” | 截图可证明界面状态；保留浏览器日志有连接拒绝 |

## 10. 核验方法与未覆盖范围

- 载体和风险覆盖通过 payload、领域模型、生成器、分类法、规则和 UI 调用链交叉检查。
- 基础设施结论通过 bootstrap 装配、adapter、repository 和 consumer 引用检查，不只看 README。
- 演示、测试、模型和性能优先使用保留的原始 JSON/log/metadata；文档只承担补充解释。
- 个人角色与工作方式使用负责人陈述，并与 Phase 记录交叉印证；缺失的 Prompt 和对话不补写。
- 未执行数据库变更、服务启动、测试重跑、浏览器重测、Hive 安装或任何整改/重构。
- `ABSENCE` 只表示当前仓库未发现实现，不构成对仓库外系统或未来版本的判断。
