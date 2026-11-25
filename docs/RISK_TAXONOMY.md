# Claro Phase 03 — 风险分类体系

## 1. 作用与权威来源

风险分类体系（taxonomy）是检测、融合、标注和评估共享的语义契约。权威文件是
[`config/risk_taxonomy.yaml`](../config/risk_taxonomy.yaml)。代码不会在运行时臆造分类；
加载时执行结构校验，非法配置直接抛出 `TaxonomyError`。

当前版本：`version: 1`。包含 7 个领域、19 个分类，其中 18 个风险分类，1 个 `normal`。

每个分类包含：

- 稳定 `id`，用于规则、模型标签和 ML 真值。
- 数据库映射 `db_category`；`normal` 为 `null`，不进入风险指标。
- 领域 `domain`、名称、定义。
- 纳入标准 `inclusion_criteria` 与排除标准 `exclusion_criteria`。
- 正例、负例和边界例。
- 默认严重度 `severity`。
- 标注指南 `annotation_guidelines`。

## 2. 与数据库分类的关系

Phase 02 的 `RiskCategory` 只有 8 个风险分类。Phase 03 保留完整 19 类语义，但在
`risk_result` 与 `risk_finding` 按数据库分类聚合。映射如下：

| taxonomy id | 数据库分类 | 严重度 | 领域 |
|---|---|---|---|
| `spam_advertising` | `spam` | medium | advertising_spam |
| `spam_repetition` | `spam` | medium | advertising_spam |
| `spam_junk` | `spam` | low | advertising_spam |
| `external_link` | `spam` | high | external_traffic |
| `external_contact` | `spam` | medium | external_traffic |
| `external_community_invite` | `spam` | medium | external_traffic |
| `fraud_fake_trade` | `fraud` | high | fraud_scams |
| `fraud_fake_reward` | `fraud` | high | fraud_scams |
| `fraud_phishing` | `fraud` | critical | fraud_scams |
| `account_sale` | `other` | high | account_trading |
| `account_boosting` | `other` | medium | account_trading |
| `virtual_asset_trading` | `other` | high | account_trading |
| `harassment_personal` | `harassment` | medium | harassment_abuse |
| `harassment_group` | `hate_speech` | critical | harassment_abuse |
| `harassment_threat` | `violence` | critical | harassment_abuse |
| `sexual_content` | `sexual_content` | high | inappropriate_content |
| `self_harm` | `self_harm` | critical | inappropriate_content |
| `violation_expression` | `other` | high | inappropriate_content |
| `normal` | —（null） | normal | normal |

注意：`account_sale`、`account_boosting`、`virtual_asset_trading` 和
`violation_expression` 聚合到 `other`，是因为数据库枚举尚未拆分。检测证据中仍保留
taxonomy id，评估按 8 个数据库分类计算，因此这 4 类目前无法在 ML 指标中单独评估。

## 3. 领域

| 领域 | 中文 | 覆盖分类 |
|---|---|---|
| `advertising_spam` | 广告与垃圾信息 | 广告、重复刷屏、乱码刷屏 |
| `external_traffic` | 站外导流 | 外链、站外联系方式、外部社群邀请 |
| `fraud_scams` | 欺诈与诈骗 | 虚假交易、虚假奖励、钓鱼 |
| `account_trading` | 账号与虚拟资产交易 | 账号买卖、代练、资产交易 |
| `harassment_abuse` | 骚扰与攻击 | 人身攻击、群体攻击、威胁 |
| `inappropriate_content` | 不当内容 | 色情、自残、其他违规表达 |
| `normal` | 正常内容 | 正常聊天 |

## 4. 分类标准与示例

| id | 纳入标准（摘要） | 排除标准（摘要） | 正例 | 负例 |
|---|---|---|---|---|
| `spam_advertising` | 明确促销、引导点击或交易话术 | 官方公告、玩家正常组队或讨论 | 限时广告，立即点击领取 | 官方活动公告请查看游戏内邮件 |
| `spam_repetition` | 同一短语在单条消息内至少重复三次，或短时间重复发送相同内容 | 正常强调、歌词、引用 | 加群加群加群 | 大家快来看这个新活动 |
| `spam_junk` | 无意义字符洪水、连续重复符号 | 正常表情、少量重复标点 | 哈哈哈哈哈哈哈哈 | 哈哈，太强了 |
| `external_link` | 指向非白名单域名的链接 | 官方域名、游戏内帮助链接 | 打开 https://scam-reward.invalid/x | 帮助见 https://claro.example/help |
| `external_contact` | 微信、QQ、Telegram 账号或手机号 | 举报、提醒、规则讨论 | 加微信 abc12345 详聊 | 看到这类联系方式请举报 |
| `external_community_invite` | 邀请加入站外群组或外部社群 | 游戏内联盟招募、询问规则 | 加入外部战队群领取福利 | 我们联盟还缺人，游戏内申请 |
| `fraud_fake_trade` | 先付款、异常折扣、免费代充等交易诱导 | 官方充值说明、风险提醒 | 免费代充，先付款后发货 | 官方充值请走游戏内商城 |
| `fraud_fake_reward` | 声称免费领取金币、兑换码或福利 | 官方活动、防诈骗提醒 | 免费领取金币，点击兑换码 | 请勿相信免费领取金币的私聊 |
| `fraud_phishing` | 索要账号密码、验证码或登录验证 | 账号安全提醒、举报 | 输入密码完成账号验证 | 官方不会索要验证码，请举报 |
| `account_sale` | 买卖、租借或共享游戏账号 | 讨论账号安全或规则 | 出售高等级账号，价格私聊 | 账号交易是否违反规则？ |
| `account_boosting` | 付费代练、代打、冲榜 | 正常组队或讨论代练规则 | 专业代练，包上分 | 找队友一起冲榜 |
| `virtual_asset_trading` | 站外交易金币、资源或账号资产 | 游戏内正常交易、规则咨询 | 低价出售金币，绕过官方 | 游戏内交易行怎么用？ |
| `harassment_personal` | 直接侮辱、贬低或命令他人闭嘴 | 观点争论、游戏内正常对抗 | 你这个废物，闭嘴 | 这波团战打得不好 |
| `harassment_group` | 对群体的排斥、劣等或仇恨表达 | 讨论差异、举报仇恨言论 | 劣等群体不配留在服务器 | 如何举报仇恨言论？ |
| `harassment_threat` | 人身威胁、线下伤害或人肉威胁 | 游戏内战术威胁、规则讨论 | 我知道你住哪，让你后悔 | 游戏里堵住他，别让他发育 |
| `sexual_content` | 色情资源、成人服务或性骚扰 | 性教育、举报或规则讨论 | 出售成人资源，私聊 | 如何举报色情内容？ |
| `self_harm` | 明确自残或自杀意图 | 求助、支持资源、报道 | 不想活了，想结束一切 | 如何寻求心理帮助？ |
| `violation_expression` | 外挂、私服、卡 bug 等违规推广 | 举报外挂、讨论规则 | 出售外挂和加速脚本 | 发现外挂请举报 |
| `normal` | 正常交流、游戏讨论、官方信息 | 命中任一风险分类 | 今晚八点一起打城战 | 免费代充，先付款后发货 |

完整正例、负例、边界例和标注指南以 YAML 为准；本表是人工阅读摘要。

## 5. 标注指南原则

1. 先判断是否存在真实意图或可执行信息，再判断严重度。单纯讨论、举报或求助通常
   不构成风险表达。
2. 多分类并存时全部保留，不强行选一个；例如“卖号并引导到外部群”同时命中
   `account_sale` 与 `external_community_invite`。
3. 边界例必须标注为 `boundary`，不进入训练集和 precision/recall 计算。
4. 引用、截图或转述风险内容时，按“是否在传播或鼓励”判断，不按关键词数量判断。
5. 不确定时记录理由与缺失信息，不用猜测填满标签。
6. 标注与检测器输出隔离：标注不得参考模型分数、规则命中或策略动作。

## 6. 变更管理

- 分类 id 一旦用于训练标签，不应重命名；需要重命名时新增分类并迁移数据。
- 新增分类必须同时提供完整标准、示例、严重度和数据库映射。
- 只允许一个 `normal` 分类，且其 `db_category` 必须为 `null`。
- 修改 YAML 后运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_risk_taxonomy.py tests/unit/test_risk_rules.py -q
.\.venv\Scripts\claro.exe risk-status
```

`risk-status` 会重新加载并校验 taxonomy、规则和融合配置。
