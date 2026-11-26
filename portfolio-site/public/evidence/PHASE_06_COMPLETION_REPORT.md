# Phase 06 完成报告（Productization & Final Delivery）

本报告只写**已经发生**的事。状态词严格区分：

| 状态 | 含义 |
| --- | --- |
| **Implemented** | 代码已写好并能运行 |
| **Executed** | 在本机真实执行过（有命令、有输出） |
| **Tested** | 有自动化测试覆盖并通过 |
| **Verified** | 在真实界面/真实数据上人工核对过 |
| **Designed** | 只有设计，未实现 |
| **Not Implemented** | 明确不做 |
| **Blocked** | 环境不具备，无法完成，且不伪装 |

环境：Windows 11（10.0.26340）· Intel Core i5-8300H · 15.9 GB · Python 3.12.10 ·
PostgreSQL 18.3 · Kafka 3.9.2（KRaft 单节点）· Redis 8.10.3。**无 Docker / WSL / MySQL。**

---

## 1. 系统审计先行

**状态：Executed**

改动任何代码前完成了全量审计，产出 `docs/PHASE_06_SYSTEM_AUDIT.md`：架构、业务流程、
集成、可靠性、安全五个维度，问题分 P0/P1/P2/P3。

* P0：1 项（Kafka 启动时 JDK home 被解析成 `bin` 目录，导致 `bin\bin\java.exe`）——先修它。
* P1：11 项（含 `Start-Process` 大小写重复环境变量、缺少统一 E2E 入口、总览页不是产品仪表盘、
  导航是 12 项扁平单选、图表硬编码白底、时间数字未格式化、无演示数据集、脚本不全、
  无性能基线、模型未入库）。
* P2：5 项；P3：3 项（明确不改）。

每一项都写了证据（命令输出、截图文件名、代码位置）与处置结论，没有"待定"。

---

## 2. 统一端到端流水线

**状态：Implemented · Executed · Tested**

`ClaroProcessingService.process_message()` 一次调用串起：
validate → ingest（`message` + `inbox_event` + `processing_event` 同事务）→ detect（规则 + ML + 语义融合）
→ publish（Kafka）→ governance（政策求值、决策、案例、处置、事件、审计）。

* 幂等：`inbox_event` 以 `event_id` 为键，`(source_topic, source_partition, source_offset)` 唯一，
  再加内容寻址 `payload_hash`；重复提交返回 `duplicate` 而不是写第二份。
* 单条 / 批量 / 重试：`process_batch()` 对 `failed`/`partial` 结果重入一次同样幂等的阶段。
* 状态与追踪：`ProcessingOutcome.status ∈ {processed, duplicate, partial, failed}`，
  每阶段带 `elapsed_ms` 与 `status`，`trace_id` 贯穿消息 → 风险 → 决策 → 处置 → 审计。
* Outbox + DLQ：事件先落 `outbox`（`dedupe_key` 去重）再由 dispatcher 发送；发送失败进
  `dead_letter`，不静默丢弃。
* 命令入口：`claro process-message`、`claro demo-run`、`claro demo-status`、`claro demo-clean`。
* 验证：`tests/integration/` 覆盖幂等、outbox、DLQ、状态转移；`scripts\run_demo.ps1` 重复执行全部返回
  `duplicate`（幂等的可现场演示证据）。

一条消息的处理轨迹可在「消息探查 → 处理轨迹」看到，含每阶段耗时与结论。

---

## 3. 演示数据（14 个场景，固定种子，可清理）

**状态：Implemented · Executed · Verified**

* `claro demo-run` 执行 14 步：7 个风险场景进流水线（垃圾广告、欺诈、辱骂、仇恨、自伤、
  色情、暴力/正常对照），再走认领 → 人工结论 → 覆盖决定 → 禁言 → 临时封禁 → 解除 → 反馈 →
  策略回归。
* 固定 `seed=20261125`、固定 message id（uuid5），重复运行完全幂等。
* 隔离：数据集名 `phase-06-demo-s20261125`，与 50,016 条评估数据集互不影响。
* 清理：`scripts\run_demo.ps1 -Clean`（需输入 `yes`），只删该数据集及其依赖行。
* 现场核实：`claro demo-status` 返回 `messages=7, risk=7, cases=3, feedback=1`。

---

## 4. 产品导航与总览仪表盘

**状态：Implemented · Executed · Verified · Tested**

* 导航：15 个页面分 5 组（监控 / 处置 / 策略与情报 / 分析 / 审计与配置），`st.navigation`。
  侧栏保留 Streamlit 自带的 System / Light / Dark 切换。
* 总览页全部数字来自真实查询（`ExplorerService` + `AnalyticsService`），包括 8 个 KPI 卡片、
  趋势折线（消息/风险/高风险）、风险构成（类别环图、等级、动作、服务器对比）、
  活动流、数据集概览与口径说明。
* 低样本规则：分母 < 30 的比率显示"不可计算"并说明样本量，不显示 0% 或 100%。
* 口径单一来源：`phase-05.2`，页面只展示不自算。
* 新增页面：消息探查（筛选 + 证据链三标签）、风险情报（检测覆盖、检测层命中、规则目录含 0 命中的规则、
  模型资产与最近评估）、系统设置（依赖健康、连接与阈值、演示数据管理、已知限制）。
* 验证：`tests/ui/test_screens_smoke.py` 15 页全绿；真实浏览器 15 页 × 明暗两套配色全绿。

---

## 5. UI/UX 与设计系统

**状态：Implemented · Verified**

* `ui/theme.py`：`ThemeTokens` 冻结数据类（文本/次要文本/网格/表面/边框/强调色），
  明暗两套；语义色映射（严重度、状态、类别、域），未知类别用 sha256 派生稳定颜色，
  保证任何新增枚举都不会掉成黑色。
* 原生主题：`.streamlit/config.toml` 使用 `[theme.light]` / `[theme.dark]`，
  让 `st.dataframe`、输入框、按钮、菜单真正跟随配色（不是给 Streamlit 变量打补丁）。
* 图表：`ui/charts.py` 全部由 token 驱动；空数据画"空状态图"而不是空框；
  千分位分隔；横条图留出标签空间（`cliponaxis=False` 在 trace 上）；时间轴用本地日期格式。
* 图表诚实性：低样本时间桶（分母 < 30）剔除并写明剔除了几个；日期断层不连线，
  避免把"没有数据"画成"风险归零"。
* 一致性：标题、区块标题、空状态、徽章、KPI 卡片、表格统一走 `common.py` 与 `theme.py`；
  文案统一中文，数字统一千分位，时间统一本地 `YYYY-MM-DD HH:mm`。
* 交互反馈：写操作有确认（覆盖决定、下发处置、清理演示数据需输入 `yes`）、成功/失败有 flash 提示。
* 可访问性：正文与背景对比度按明暗两套分别取色（深色下用 `#E5E7EB` 而非纯白、次要文本用
  `#94A3B8`），状态色不单独承担语义（同时有文字标签），表格有列名与单位。

---

## 6. 可靠性

**状态：Implemented · Executed · Tested**

* 配置：`.env` + `.env.example` + `.env.full.example`；未知 `CLARO_*` 变量被 pydantic
  `extra="forbid"` 拒绝；`full` 模式拒绝 SQLite；占位口令被拒绝；日志脱敏
  （`password`/`token`/`secret`/`authorization`/`api_key` 一律 `[REDACTED]`，`database_url` 抹掉口令）。
* 数据库：连接池 `pool_size=5 / max_overflow=10`；每个请求一个显式 session 上下文，
  业务写操作单事务提交；异常回滚并记录。
* Kafka：幂等生产者；发布失败不丢已提交的风险结果（阶段标记 `failed`，整体 `partial`）；
  失败事件进 DLQ；`(topic, partition, offset)` 唯一约束防重放。
* Redis：TTL 缓存敏感词与限流计数；不可用时自动回落 PostgreSQL 并在页面标注降级。
* 安全：策略条件是声明式白名单（关键词/正则/阈值/类别/玩家/服务器/联盟/黑白名单/限流/组合），
  **不支持任意 Python/SQL/Shell**；代码中无 `eval(`/`exec(`；SQL 走参数绑定，
  三种注入 payload 实测返回 0 行、表数据不变。
* RBAC：**模拟**。侧栏身份只写入审计记录，不参与授权，界面明确标注"模拟身份认证，非生产级登录"。
* 自动化检查：`scripts\check_reliability.py` 7/7 PASS。

---

## 7. 性能（先测量，再优化，只保留有对比的优化）

**状态：Executed（含优化前后对比）**

| 项目 | 实测 |
| --- | --- |
| 批量入库（1k / 10k / 50k） | 67.4 / 62.4 / 77.6 行/秒；另一轮 81.0 / 78.5 / 63.9 |
| 单条流水线 p50 / p95 / p99 | 128 / 189 / 272 ms（1k）；107 / 150 / 180 ms（10k）；145 / 216 / 332 ms（50k） |
| 检测层 p50 | 5.1 – 7.5 ms |
| Redis 读取 | 0.86 ms/次，50 次命中率 100% |
| 页面热载 | 0.53 – 1.06 s（缓存命中）；首次 3.5 – 7.0 s |

优化（有前后对比才保留）：

| 优化 | 前 | 后 |
| --- | --- | --- |
| `daily_timeline` 改 CTE 聚合 | 255.6 ms | 64.0 ms |
| `dataset_summary` 去 LATERAL | 201.0 ms | 36.3 ms |
| `server_risk` 改 severity_rank + scored | 191.2 ms | 138.3 ms |
| 总览 `overview()`（进程内） | 3.35 s | 1.05 s |
| 仪表盘 45 秒读缓存 | 总览 3,633 ms / 分析总览 7,264 ms | 609 ms / 636 ms |

明细、方法、未采用的优化及原因见 [`docs/PHASE_06_PERFORMANCE.md`](PHASE_06_PERFORMANCE.md)。
代价（数据最多滞后 45 秒）写进了 `KNOWN_LIMITATIONS.md`，侧栏有"刷新数据"按钮。

---

## 8. Windows 原生部署脚本

**状态：Implemented · Executed**

| 脚本 | 作用 | 验证 |
| --- | --- | --- |
| `check_environment.ps1` | 六态报告：Healthy / Running / Installed / NotConfigured / Incompatible / Missing | 执行过，输出六态表 |
| `start_services.ps1` / `stop_services.ps1` | 启停 PostgreSQL（系统服务）、Kafka（KRaft）、Redis | 执行过 |
| `check_services.ps1` | 服务是否在跑（含 PipelineConsumer / Streamlit） | 执行过：PG/Redis/Kafka = True |
| `start_app.ps1` / `stop_app.ps1` | 启动/停止 Streamlit，PID 记录在 `runtime\app.pid`，只停自己启动的进程 | 执行过：`Claro UI is ready ... (PID 26508)` |
| `init_database.ps1` / `run_migrations.ps1` | 建库与迁移；迁移脚本打印前后 revision | 执行过 |
| `generate_demo_data.ps1` | 生成并装载演示背景数据，再跑 `check-data` | 执行过 |
| `run_demo.ps1` | 14 步演示；`-Status` 查看、`-Clean` 清理（需 `yes`） | 执行过：`demo-status` 返回 7/7/3/1 |
| `run_tests.ps1` | `-Suite unit\|integration\|ui\|all`、`-Keyword`、`-Coverage` | 执行过：308 passed |
| `start_claro.ps1` / `stop_claro.ps1` | 一条命令按序启动/反向停止 | 执行过 |
| `benchmark_pipeline.py` / `check_reliability.py` | 性能基准 / 可靠性安全检查 | 执行过 |

安全约束：不杀无关进程（PID 文件 + 命令行匹配，端口已被非本应用占用时明确拒绝接管），
超时与日志目录固定（`logs\`、`runtime\`），危险操作需确认，Hive 不可用以状态形式显式输出。

---

## 9. 自动化测试

**状态：Tested**

`scripts\run_tests.ps1 -Suite all -Coverage` → **308 passed, 0 failed, 79% 覆盖率**，103 秒。
分层：单元 240 / 集成 51 / UI 冒烟 17。另有一项手工真实浏览器巡检 `tests/ui/browser_smoke.py`
（15 页 × 明暗 = 30 次渲染，检查渲染错误、traceback、控制台错误、侧栏完整性）。

覆盖率短板如实列出（`cli.py` 26%、页面写路径未做点击后断言），详见
[`docs/PHASE_06_TEST_REPORT.md`](PHASE_06_TEST_REPORT.md)。测试过程中发现并修复的 6 个测试缺陷
（含"假通过"和 `python -m claro.cli` 不执行）也在该文件中逐条记录。

---

## 10. 文档

**状态：Implemented**

| 文件 | 内容 |
| --- | --- |
| `README.md` | 产品定位、能力、架构、快速开始、脚本表、实测数字、限制、文档索引 |
| `docs/ARCHITECTURE.md` | 分层架构（含 Phase 06 增补）与关键设计取舍 |
| `docs/DATA_FLOW.md` | 消息从接入到分析的完整数据流（Mermaid） |
| `docs/EVENT_FLOW.md` | 事件与 topic、幂等键、outbox、DLQ（Mermaid） |
| `docs/DATABASE_SCHEMA.md` | 33 张表分组说明与 ER 图（Mermaid） |
| `docs/RISK_INTELLIGENCE.md` | 规则体系、融合算法、模型资产与指标局限 |
| `docs/CONTENT_GOVERNANCE.md` | 政策表达、决策、案例、处置、审计 |
| `docs/ANALYTICS.md` | KPI 口径、29 条具名 SQL、低样本抑制 |
| `docs/DEPLOYMENT_WINDOWS.md` | 原生部署（含"没有容器路径"的说明） |
| `docs/TROUBLESHOOTING.md` | 症状 → 先看哪里 → 怎么修 |
| `docs/KNOWN_LIMITATIONS.md` | 按环境/安全/检测/治理/数据/界面/工程分类的限制 |
| `docs/PHASE_06_SYSTEM_AUDIT.md` | 审计与 P0–P3 处置 |
| `docs/PHASE_06_PERFORMANCE.md` | 性能方法与实测 |
| `docs/PHASE_06_TEST_REPORT.md` | 测试与覆盖率 |
| `docs/PORTFOLIO_CASE_STUDY.md` | 作品集案例（8 节） |
| `docs/DEMO_SCRIPT.md` | 10–15 分钟演示脚本（8 部分） |
| `models/README.md` | 模型产物来源与指标的正确读法 |

全部链接经脚本校验，无死链（README 与其他文档的 17 个相对链接全部存在）。

---

## 11. 开发者体验

**状态：Implemented**

* 一条命令起全栈：`scripts\start_claro.ps1`（环境 → 服务 → 迁移 → 应用）；`stop_claro.ps1` 反向停止。
* 一条命令验质量：`run_tests.ps1 -Suite all -Coverage`、`check_reliability.py`、`benchmark_pipeline.py`。
* `claro` CLI 30+ 子命令覆盖生成、装载、检测、治理、分析、导出、演示。
* `ruff`（E/F/I/UP/B，line-length 100）全绿，`ruff format` 全绿。
* 依赖用 `uv` 管理（`pyproject.toml`），虚拟环境 `.venv`。

---

## 12. 作品集材料

**状态：Implemented**

* `docs/PORTFOLIO_CASE_STUDY.md`：背景与问题、目标与硬约束、方案与关键取舍、实现难点、结果、
  反思、如果重做、技术栈。难点全部是真实事故：`event_id` 带时间戳导致幂等失效、
  `reject → allow` 的策略默认值错误、`pandas.Timestamp.astimezone` 崩溃、PowerShell
  `HTTPS_PROXY` 大小写重复键、JDK `bin\bin\java.exe`、以及三个被实测证明的 SQL 重写。
* 真实截图：`docs/screenshots/` 30 张（15 个页面 × 明/暗），由 `tests/ui/browser_smoke.py`
  用真实 Chrome 生成，不是设计稿。

---

## 13. 演示流程

**状态：Implemented · Executed**

`docs/DEMO_SCRIPT.md` 分 8 部分、10–15 分钟：开场（不假装的约束）→ 总览 → 消息探查（一条消息的
一生）→ 风险情报（检测层长什么样）→ 审核工作台（人会推翻机器）→ 处置中心（模拟但不含糊）→
分析（数字的可信度）→ 设置与收尾。每一段都写了"说什么 / 点什么 / 万一被问到"。

演示前脚本里的 `run_demo.ps1` 已实测可重复执行（第二次全部 `duplicate`）。

---

## 14. 仓库卫生

**状态：Executed**

* 无密钥：`.env` 被 gitignore；`.env.example` 只有占位符；`check_reliability.py` 验证日志脱敏。
* 无真实用户数据：全部数据合成，`synthetic=true` 落在库里，界面标注"合成数据演示"。
* 无临时产物：`runtime/`、`logs/`、`.venv/`、`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`.coverage` 全部忽略。
* 无容器残留：删除了 Phase 01 遗留的 `docker-compose.yml`（项目明确禁止容器）。
* 模型：112 KB 的合成训练模型**有意入库**，附 `models/README.md` 说明来源、训练命令与指标局限
  （`test` F1 = 1.0 是模板重复导致的，内容不重叠子集 F1 = 0.0，两者都写在元数据里）。
* 旧脚本：删除了两个已失效的 Playwright 冒烟脚本（点英文菜单项，导航已改中文），
  由 `tests/ui/browser_smoke.py` 取代。
* LICENSE：保留原文件未改动（未做兼容性变更，因此无需判断兼容性）。

---

## 15. 验收清单

**状态：Verified**

| 验收项 | 结论 | 证据 |
| --- | --- | --- |
| 无 Docker / WSL / MySQL | 通过 | 无 `docker-compose.yml`；服务均为 Windows 原生 |
| 未重建项目、未推翻既有架构 | 通过 | 分层与目录沿用 Phase 01–05，仅新增 `screens/`、`cache.py` |
| 无静态假页面 | 通过 | 15 页全部读真实表；`AppTest` 与真实浏览器双验证 |
| 无 mock 顶替 Kafka/Redis/PostgreSQL | 通过 | 集成测试连真实服务；缓存不可用时有显式降级 |
| 无伪造测试结果/性能数据 | 通过 | 数字均来自 `pytest` 输出与 `performance_results.json` |
| 未完成项未标记为完成 | 通过 | Hive 链路、并发压测、UI 写路径自动化均在报告中标为未完成/阻塞 |
| 配置与环境变量保留 | 通过 | `.env` 沿用，新增变量全部有默认值 |
| 一条命令能起、能停 | 通过 | `start_claro.ps1` / `stop_claro.ps1` |

---

## 16. 明确未完成 / 阻塞

**状态：Blocked / Not Implemented（不掩藏）**

| 项 | 状态 | 为什么 |
| --- | --- | --- |
| Hive / Hadoop / Beeline 离线数仓 | **Blocked** | 本机未安装。SQL 与导出器已实现，执行器会明确失败；不伪造成功 |
| LLM 顾问层真实调用 | **Blocked** | 无真实端点与凭据；测试只用伪造传输；默认关闭 |
| 语义检测器 | **Not Implemented** | 当前是占位，返回"不可用"，融合层按剩余层归一化 |
| 并发用户容量 / QPS 上限 | **Not Implemented** | 只有单进程串行基准，没有并发模型，不编数字 |
| UI 写路径点击后断言 | **Not Implemented** | 审核/覆盖/处置靠浏览器手工验证 |
| 真实 RBAC 与登录 | **Not Implemented** | 模拟身份，界面已标注 |
| 处置下发到游戏服务器 | **Not Implemented** | 模拟执行，`simulated=true` |
| Excel / PDF 报告导出 | **Not Implemented** | 只有 Markdown + CSV |
| Kafka / PostgreSQL 高可用 | **Not Implemented** | 单机单节点 |
| ReDoS 静态检查 | **Not Implemented** | 规则来自受控 YAML，未做正则复杂度分析 |

---

## 17. 本轮发现并修复的缺陷（补充清单）

除了 `PHASE_06_TEST_REPORT.md` 第 8 节的 6 个测试缺陷，本轮还修了：

| 缺陷 | 影响 | 修复 |
| --- | --- | --- |
| `stop_app.ps1` 在无 PID 文件时抛错 | 干净环境下停应用会失败 | 删除前判断存在性（环境的删除钩子是 fail-closed） |
| `check_services.ps1` 输出被格式化打断 | 人读困难 | `Format-Table ... \| Out-String \| Write-Output` |
| 消息探查"分数"列显示 `None` | 未评分消息显示字符串 `None` | 该列 `pd.to_numeric(errors="coerce")`，空值渲染为空白 |
| 分析页时间轴是英文月份、轴标题是字段名 | 产品一致性差 | 轴标签映射 + `%m-%d` 本地格式 + 比率轴百分比刻度 |
| 趋势图把数据空档画成下跌 | 会误读为风险归零 | 超过 3 天断线并加说明；低样本桶剔除并报告剔除数 |

---

## 18. 下一阶段建议（不在本阶段执行）

1. **容量**：分区表 + 批量 `COPY` 把写入吞吐从 60–80 行/秒提到可测的更高量级，并补并发模型。
2. **检测**：把语义检测器接上真实编码器；用非模板语料重训模型，给出可信的泛化指标。
3. **测试**：为 15 个页面的写路径补 `AppTest` 点击 + 数据库断言；为 `cli.py` 补子命令级测试。
4. **可观测**：Kafka lag、outbox 积压、DLQ 数量进入仪表盘与告警。
5. **Hive**：在具备 Hadoop 的环境里跑通 ODS→DWD→DWS→ADS，替换当前的"导出 + 明确失败"。

---

**Phase 06 到此结束。** 本项目未开始新的开发阶段。
