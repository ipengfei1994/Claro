# Phase 06 测试报告

本报告中的所有数字来自一次完整执行：

```powershell
scripts\run_tests.ps1 -Suite all -Coverage
```

**结果：308 passed，0 failed，1 warning，耗时 103.32 秒，总覆盖率 79%。**

工具自报数据，没有估算、没有"预期通过"。`.coverage` 与 HTML 报告在 `runtime/coverage/`（已 gitignore）。

---

## 1. 测试环境

| 项目 | 值 |
| --- | --- |
| 操作系统 | Windows 11（10.0.26340） |
| Python | 3.12.10（`.venv`） |
| PostgreSQL | 18.3（`postgresql-x64-18`，真实连接） |
| Kafka | 3.9.2 KRaft 单节点（真实 produce/consume） |
| Redis | 8.10.3（真实连接） |
| pytest | 见 `pip show pytest`；`-m "integration or not integration"` |
| 数据集 | `phase-02-synthetic-s20261125-p5000-m50000`（50,016 条消息）+ `phase-06-demo-s20261125` |

集成测试**不是**跳过状态：`-Suite all` 会显式覆盖 `pyproject.toml` 里
`addopts = "-m 'not integration'"` 的默认筛选（这个筛选是为了让 `pytest` 单独运行保持快速）。

---

## 2. 结果总览

| 套件 | 内容 | 用例数 | 结果 |
| --- | --- | --- | --- |
| 单元 | 领域逻辑、融合、策略表达式、指标口径、格式化、CLI 入口 | 240 | 全通过 |
| 集成 | 真实 PostgreSQL / Kafka / Redis，仓储、幂等、outbox、治理链路、分析服务、页面渲染 | 51 | 全通过 |
| UI 冒烟 | 15 个页面在 `AppTest` 里真实渲染（含 2 个结构性断言） | 17 | 全通过 |
| **合计** | | **308** | **308 passed** |

> 240 + 51 + 17 = 308。集成用例里包含 6 个参数化的"每个分析页都能渲染"用例和
> 5 个报告导出用例，因此数量与 Phase 05 的 46 不同。

---

## 3. 覆盖率（按包）

| 包 | 语句数 | 未覆盖 | 覆盖率 | 说明 |
| --- | --- | --- | --- | --- |
| `domain` | 171 | 0 | 100% | 纯领域对象与枚举 |
| `analytics` | 776 | 40 | 94.8% | 29 条具名 SQL 与指标服务 |
| `data_generation` | 463 | 27 | 94.2% | 合成数据生成器 |
| `config` | 246 | 17 | 93.1% | 设置校验与脱敏 |
| `data_access` | 2,167 | 263 | 87.9% | 仓储层（最大的包） |
| `risk_engine` | 1,427 | 180 | 87.4% | 规则、模型、融合、评估 |
| `infrastructure` | 408 | 52 | 87.3% | Kafka / Redis / 日志适配器 |
| `governance` | 585 | 79 | 86.5% | 政策求值、决策、处置 |
| `ui` | 2,092 | 602 | 71.2% | 15 个页面 + 主题 + 图表 |
| `application` | 2,095 | 606 | 71.1% | 编排服务 |
| `claro`（根） | 892 | 565 | 36.7% | `cli.py` 26%、`bootstrap.py` 93% |
| **TOTAL** | **11,322** | **2,431** | **79%** | |

覆盖率低的地方都是**交互分支与命令行参数组合**，不是核心业务逻辑：

* `cli.py`（26%）：只测了入口可执行、`_print_json` 序列化、命令注册；具体子命令的行为
  由 PowerShell 脚本与集成测试间接覆盖，没有逐个 mock。
* `ui/screens/*`：按钮点击后的写路径（提交审核、覆盖决定、下发处置）在浏览器里手工验证，
  没有用 `AppTest` 模拟点击后再断言数据库。这是已知的测试空缺，写在 `KNOWN_LIMITATIONS.md`。
* `application/processing_service.py`（40%）：正常路径由 `demo-run` 与 200 条基准样本反复执行，
  但异常分支（publish 失败、detect 失败）只有单元级覆盖。

---

## 4. 分层测试清单

| 层 | 是否覆盖 | 具体内容 |
| --- | --- | --- |
| 单元测试 | ✅ | 240 条：分类体系、融合权重与阈值、策略表达式白名单、指标口径与低样本抑制、格式化函数、CLI 入口与序列化 |
| 数据库集成 | ✅ | 33 张表的写入/读取、唯一约束冲突、`inbox_event` 幂等、`outbox` 去重、事务回滚 |
| Kafka 集成 | ✅ | 生产者发布、消费者解析、`(topic, partition, offset)` 唯一性、DLQ 落库 |
| Redis 集成 | ✅ | 敏感词缓存、失效、不可用时回落 PostgreSQL |
| Hive / 数仓 | ❌ 阻塞 | Hive / Hadoop / Beeline 未安装。`warehouse-export` 能生成 CSV 与 ODS SQL，但执行链路不可测，本报告不给"通过" |
| API / CLI | 部分 | CLI 入口与序列化有自动化测试；子命令行为由集成测试与脚本验证 |
| 业务场景（14 个） | ✅ | `scripts\run_demo.ps1` 的 14 步：7 个场景进流水线、认领、驳回、禁言、临时封禁、解除、反馈、策略回归 |
| UI 冒烟（框架级） | ✅ | `tests/ui/test_screens_smoke.py`，15 页 × `AppTest` |
| UI 冒烟（真实浏览器） | ✅ 手工 | `tests/ui/browser_smoke.py`，Chrome 真实渲染 15 页 × 明/暗两套配色，检查渲染错误、traceback、控制台错误、侧栏完整性 |
| 端到端 | ✅ | 消息 → 检测 → 决策 → 案例 → 处置 → 审计 → 分析，同一 `trace_id` 可串起来 |

---

## 5. Phase 01–05 能力回归

| 能力 | 回归方式 | 结果 |
| --- | --- | --- |
| 数据生成与校验 | `check-data` + 单元测试 | 通过 |
| 规则检测 | 22 条 YAML 规则、63 行规则历史，规则命中用例 | 通过 |
| ML 检测 | 模型加载、预测、评估指标持久化 | 通过（模型由 `models/README.md` 说明其局限） |
| 融合与分级 | 加权 noisy-OR、层级阈值、动作映射 | 通过 |
| 政策求值 | 声明式白名单、版本比较、回滚 | 通过 |
| 人工审核 | 认领、提交结论、SLA 逾期判定 | 通过 |
| 处置执行（模拟） | 禁言/封禁/解除、状态查询、过期清理 | 通过 |
| 反馈与审计 | 反馈统计、错误分类、审计日志检索 | 通过 |
| 分析层 | 29 条具名 SQL、KPI 口径 `phase-05.2`、低样本抑制 | 通过 |
| 报告与导出 | 5 类报告，Markdown + CSV | 通过 |

---

## 6. 可靠性 / 安全检查

```powershell
.venv\Scripts\python.exe scripts\check_reliability.py
```

**7/7 PASS**：

1. 未知的 `CLARO_*` 环境变量被拒绝（防止拼错静默生效）。
2. `full` 模式拒绝 SQLite。
3. `.env` 中的密码占位符未替换时报错退出。
4. 日志脱敏：`[REDACTED]` 出现，明文口令不出现。
5. SQL 注入无效：3 种 payload 均返回 0 行，表数据保持 50,018 条。
6. 代码中没有 `eval(` / `exec(` 调用（正则排除 `obj.eval(` 这类误报）。
7. `.env` 未被 git 跟踪。

---

## 7. 性能

见 [`docs/PHASE_06_PERFORMANCE.md`](PHASE_06_PERFORMANCE.md)。摘要：单条流水线 p95
150–216 ms，批量写入 62–81 行/秒，仪表盘热载 0.53–1.06 s。

---

## 8. 本轮发现并修复的测试缺陷（如实记录）

| 问题 | 现象 | 处理 |
| --- | --- | --- |
| UI 冒烟一开始"通过"却什么都没测 | `AppTest.from_function` 只重新执行函数体，函数里用到的 `importlib` / `get_container` 在裸命名空间里不存在，15 个用例全红 | 把 import 放进函数体；现在 15 页真的跑起来了 |
| `-Suite all` 其实没跑集成 | `pyproject.toml` 的 `-m 'not integration'` 默认值把集成用例排除了，输出只说 "46 deselected" | `run_tests.ps1` 按套件显式传 `-m`，`all` 传 `integration or not integration` |
| 分析页集成测试仍在点单选框 | Phase 06 把导航换成 `st.navigation`，`app.radio[0]` 已不存在，`AppTest.switch_page` 也不接受 `st.navigation` 的 url_path | 改为从 `NAVIGATION` 表发现页面，逐页用 `AppTest.from_function` 渲染 |
| `python -m claro.cli` 什么都不执行 | `cli.py` 缺少 `if __name__ == "__main__"` 守卫，`run_demo.ps1` 与 `generate_demo_data.ps1` 静默失效 | 补上守卫；新增 `tests/unit/test_cli_entry.py` 用子进程锁住这个行为 |
| `demo-status` 崩溃 | `_print_json` 直接 `json.dumps`，遇到 `UUID` 抛 `TypeError` | 增加 ISO 序列化器，并为它写了单元测试 |
| 浏览器巡检曾"假通过" | 深链接 404 时 Streamlit 会回落到默认页，正文检查自然通过 | 把 `does not seem to exist` 加入失败标记，并把 `/overview` 改为根路径 `/` |

---

## 9. 未做的测试（明确列出）

* Hive / Hadoop 链路：环境未安装，不能测，不伪造。
* 并发与容量测试：只做了单进程串行基准，没有并发用户模型，因此不报告 QPS 上限。
* UI 写路径自动化：审核、覆盖决定、处置下发靠浏览器手工验证，未做"点击后查库"的自动化断言。
* 负载下的 Kafka lag / 重启恢复演练：未做。
* 跨浏览器：Chrome 与 Edge（同内核）之外未验证。

---

## 10. 复现

```powershell
scripts\check_environment.ps1          # 六个组件应 Healthy
scripts\check_services.ps1             # PostgreSQL / Redis / Kafka 应为 True
scripts\run_migrations.ps1             # 确认 schema 在 head
scripts\run_tests.ps1 -Suite all -Coverage
.venv\Scripts\python.exe scripts\check_reliability.py
.venv\Scripts\python.exe tests\ui\browser_smoke.py     # 需先 start_app.ps1
```
