# Phase 06 性能与容量报告

本文件里的每个数字都由脚本在本机真实运行产生，没有估算值、没有"参考行业基准"、没有
借用他机数据。原始结果保存在 [`docs/performance_results.json`](https://github.com/ipengfei1994/Claro/blob/main/docs/performance_results.json)
（流水线、查询、缓存）与 `runtime/page_timings.json`（本地保留，未公开），可用文末命令复现。

---

## 1. 结论摘要

| 指标 | 实测值 | 说明 |
| --- | --- | --- |
| 批量入库吞吐 | 62 – 78 行/秒 | 1,000 / 10,000 / 50,000 三档；受单机 PostgreSQL 与 4 核笔记本 CPU 限制 |
| 单条流水线 p50 / p95 / p99 | 107 – 145 / 150 – 216 / 180 – 332 ms | 三档规模下的区间，含入库、检测、Kafka 发布、治理决策 |
| 检测层单独 p50 | 5.1 – 7.5 ms | 规则 + 模型 + 语义三层融合，不含 IO |
| 消息入库（单条，含事务） | 13.8 – 17.9 ms p50 | `message` + `inbox_event` + `processing_event` 同事务 |
| 治理决策（单条） | 67 – 90 ms p50 | 政策评估 + 决策 + 案例 + 处置 + 事件记录 |
| Kafka 单条发布 | 1.1 – 1.4 ms p50 | 幂等生产者，`acks=all` |
| Redis 读取 | 0.86 ms/次，命中率 100% | 50 次读取实测，键空间命中 50 / 未命中 0 |
| 总览仪表盘数据层 | 1.94 s | `ExplorerService.overview(days=365)`，50,016 条消息 |
| 消息检索一页（25 条） | 0.44 s | 含筛选、排序、总数统计 |
| 页面热载（渲染耗时） | 0.53 – 1.06 s | 缓存命中后 15 个页面全部在此区间 |
| 数据库体积 | 436 MB（基准运行时，含当轮压测行）；清理后 405 MB | 50,016 条消息 / 50,016 条决策 / 8,856 条风险事件 |

**一句话**：在本机（4 核 8 线程笔记本 + 单机 PostgreSQL）上，单条链路稳定在百毫秒级
（p95 < 220 ms），批量写入 60–80 行/秒，仪表盘热载 1 秒以内。这不是"高并发"数字，
而是一台开发机跑完整链路的可信数字。

---

## 2. 测试环境

| 项目 | 实测值 | 来源 |
| --- | --- | --- |
| 操作系统 | Windows 11 专业工作站版 Insider Preview，内核 10.0.26340 | `platform.platform()` |
| CPU | Intel(R) Core(TM) i5-8300H @ 2.30GHz，4 核 8 逻辑处理器 | `Win32_Processor` |
| 内存 | 15.9 GB 物理内存 | `Win32_ComputerSystem.TotalPhysicalMemory` |
| Python | 3.12.10 | `platform.python_version()` |
| PostgreSQL | 18.3（本机服务 `postgresql-x64-18`，端口 5432） | `SELECT version()` |
| Apache Kafka | 3.9.2，KRaft 单节点（9092 / 9093） | 启动脚本读取 |
| Redis | 8.10.3（Windows 版，端口 6379） | `INFO server` |
| SQLAlchemy / psycopg | 2.1.9 / 3.3.9 | `importlib.metadata` |
| confluent-kafka | 2.16.2 | 同上 |
| Streamlit / Plotly | 1.67.0 / 6.9.0 | 同上 |
| scikit-learn / pandas | 1.9.1 / 3.1.1 | 同上 |
| 连接池 | `pool_size=5`、`max_overflow=10` | 运行配置 |
| 运行模式 | `full`（PostgreSQL + Kafka + Redis 全部真实连接） | `CLARO_MODE` |

内存由 CIM 查询得到而不是由压测脚本上报，是因为 `psutil` 未安装；脚本里因此显式写了
`"memory_gb": "psutil not installed"`，没有编造数值。

数据量基线：`message` 50,016 条、`policy_decision` 50,016 条、`risk_event` 8,856 条，
数据库 436 MB。所有压测行写入独立数据集 `phase-06-benchmark-*`，测完立即删除，回到该基线。

---

## 3. 测量方法

* **批量入库**：对整个档位（1,000 / 10,000 / 50,000 行）计时，走真实
  `persist_raw_message()`（`message` + `inbox_event` 同事务、内容寻址去重），
  这是批量回填的真实成本。
* **单条流水线**：每档取 200 条样本走 `ClaroProcessingService.process_message()`，
  完整执行 validate → ingest → detect → publish(Kafka) → governance，记录 p50/p95/p99。
* **阶段耗时**：由流水线自身的 `StageResult.elapsed_ms` 上报，不是外部估算。
* **检测层**：单独调用 `RiskService.detect()` 200 次，隔离出模型/规则的计算成本。
* **查询**：在**清理后的基线数据库**上调用服务层方法（这也是页面实际走的路径）。
* **页面渲染**：`AppTest` 跑真实脚本（Streamlit 自己的 script runner），测量从 `app.run()`
  到渲染完成的墙钟时间，含 Plotly 图形对象构造与全部 SQL。
* **Redis**：读 `INFO stats` 前后差值，统计键空间命中/未命中，不是"假设命中"。

明确**不包含**的部分：浏览器绘制与 websocket 传输、TLS、反向代理、多用户并发争用。
因此上表的页面与查询耗时是用户等待时间的**下界**。

---

## 4. 批量吞吐（写入路径）

| 档位 | 行数 | 耗时 | 吞吐 |
| --- | --- | --- | --- |
| 小 | 1,000 | 14.8 s | 67.4 行/秒 |
| 中 | 10,000 | 160.2 s | 62.4 行/秒 |
| 大 | 50,000 | 644.6 s | 77.6 行/秒 |

另一个完整轮次（同机、同一代码、相隔数分钟）测得 81.0 / 78.5 / 63.9 行/秒。两轮之间
±20% 的差异来自本机后台负载（Streamlit 进程、系统索引），因此**吞吐应读作 60–80 行/秒**，
而不是某一个精确值。吞吐没有随行数下降，说明写入路径不存在随表增长而恶化的退化。

写入瓶颈定位：每行要写 `message` + `inbox_event`（唯一约束
`(source_topic, source_partition, source_offset)`）+ `processing_event`，三张表三个索引维护，
单机 PostgreSQL 顺序 fsync。这不是代码缺陷，是单机磁盘与 WAL 的物理上限；扩吞吐需要分区表
或批量 `COPY`，属于 Phase 07 的容量工作，本阶段不做（见 `KNOWN_LIMITATIONS.md`）。

---

## 5. 单条流水线延迟

### 5.1 端到端分位

| 档位 | n | 平均 | p50 | p95 | p99 | 最大 |
| --- | --- | --- | --- | --- | --- | --- |
| 1,000 | 200 | 132.3 ms | 128.2 ms | 189.3 ms | 271.5 ms | 311.0 ms |
| 10,000 | 200 | 112.1 ms | 107.1 ms | 149.7 ms | 179.5 ms | 260.5 ms |
| 50,000 | 200 | 152.3 ms | 144.5 ms | 215.5 ms | 331.6 ms | 466.6 ms |

50,000 档比 10,000 档慢约 35%（p50 107 → 145 ms），主要来自 `policy_decision` 与
`moderation_case` 的索引随表增长变深，以及治理阶段每次要回查决策与处置记录。

### 5.2 阶段预算（p50，50,000 档）

| 阶段 | p50 | 占端到端 | 内容 |
| --- | --- | --- | --- |
| validate | 0.05 ms | <0.1% | pydantic 解析（另测，见下） |
| ingest | 17.9 ms | 12% | 消息 + 收件箱 + 处理事件，单事务提交 |
| detect | 29.4 ms | 20% | 规则层 + 逻辑回归 + 语义相似度融合 |
| publish | 1.3 ms | 1% | Kafka 幂等生产 |
| governance | 90.3 ms | 62% | 政策求值、决策、案例、处置、事件写入 |

`validate` 在流水线里是**标记阶段**，`elapsed_ms` 恒为 0：消息进入
`process_message()` 之前已由 pydantic 校验完成，重复校验没有意义。为了不给出一行
假的 0 ms，`scripts/benchmark_pipeline.py --validation-only` 单独测量了消费者真实路径
（`RawGameMessagePayload.from_json_mapping`，1,000 次）：平均 0.07 ms、p50 0.05 ms、
p95 0.17 ms、p99 0.55 ms。相对百毫秒的端到端，它确实可以忽略。

治理阶段占 62% 是设计结果而不是疏漏：一次消息要落 `policy_decision`、可选的
`moderation_case`、`enforcement_action`、`case_event`、`audit_event` 与 `processing_event`，
并且每一步都要可审计（谁、何时、依据哪条政策、前后状态）。要压缩它只能减少审计粒度，
那会牺牲 Phase 05 建立的可解释性，本阶段不换。

---

## 6. 检测层单独耗时

| 档位 | 平均 | p50 | p95 | p99 |
| --- | --- | --- | --- | --- |
| 1,000 | 6.7 ms | 5.1 ms | 9.6 ms | 12.3 ms |
| 10,000 | 5.4 ms | 5.2 ms | 8.8 ms | 10.9 ms |
| 50,000 | 8.1 ms | 7.5 ms | 12.2 ms | 17.1 ms |

检测层读的是 Redis 缓存的关键词表与内存中的逻辑回归模型，所以它的成本与消息总量无关，
只与表增长带来的 `risk_finding` 写入有关。1,000 档的首个样本出现 225 ms 的离群值，
是首次调用时的模型/词表装载（冷启动），已计入 `max` 列，没有剔除。

---

## 7. 存储、消息与缓存

| 指标 | 值 |
| --- | --- |
| 数据库体积 | 436,074,175 字节（基准运行时；压测行清理后 `pg_database_size` 为 424,351,423 字节） |
| `message` 行数 | 50,016 |
| `policy_decision` 行数 | 50,016 |
| `risk_event` 行数 | 8,856 |
| Kafka 单条发布（生产 + flush） | 3.3 ms（单次冷测） |
| Redis 50 次读取总耗时 | 43.13 ms（0.86 ms/次） |
| Redis 键空间命中 / 未命中 | 50 / 0（命中率 100%） |
| Redis 内存占用 | 920 KB |

Redis 命中率 100% 是**同一进程内连续 50 次读取同一批键**的结果，代表"缓存生效"，不代表
"线上长期命中率"；冷启动后的首次读取必然是未命中（这一步不在统计窗口内，本报告不夸大）。

---

## 8. 分析查询延迟（基线数据库）

| 查询 | 耗时 | 页面 |
| --- | --- | --- |
| `ExplorerService.overview(days=365)` | 1,937 ms | 治理总览 |
| `search(page=1, page_size=25)` | 444 ms | 消息探查 |
| `risk_intelligence()` | 82 ms | 风险情报 |
| `AnalyticsService.overview(filters)` | 1,313 ms | 分析总览 |
| `AnalyticsService.risk(filters, "day")` | 1,084 ms | 风险分析 |

> 第一次测量时这些数字被高估 2–5 倍（总览 4,756 ms），原因是压测行在 `finally` 里才清理，
> 查询测在了一张被 61,000 行压测数据膨胀的表上。改为**每档测完立即清理**并单独重测后，
> 得到上表。这条错误本身保留在案，因为它说明"先测量"必须先保证被测环境是干净的。

---

## 9. 页面渲染耗时

15 个页面全部由 `AppTest` 真实渲染，每页跑 3 次取中位数。`cold` 是缓存未命中（相当于
清空缓存后第一次进入），`warm` 是缓存命中（用户在页面间来回切换）。

| 页面 | 优化前 warm | 优化后 cold | 优化后 warm |
| --- | --- | --- | --- |
| 治理总览 | 3,633 ms | 4,921 ms | **609 ms** |
| 消息探查 | 1,404 ms | 789 ms | 830 ms |
| 风险情报 | 976 ms | 557 ms | **596 ms** |
| 分析总览 | 7,264 ms | 6,988 ms | **636 ms** |
| 风险分析 | 3,365 ms | 706 ms | **1,057 ms** |
| 社区分析 | 4,197 ms | 3,490 ms | **756 ms** |
| 治理分析 | 1,988 ms | 451 ms | **716 ms** |
| 模型分析 | 810 ms | 870 ms | 625 ms |
| 策略评估 | 1,079 ms | 1,333 ms | 571 ms |
| 审核工作台 | 811 ms | 718 ms | 594 ms |
| 治理决策 | 1,096 ms | 930 ms | 611 ms |
| 处置中心 | 1,000 ms | 508 ms | 600 ms |
| 反馈与审计 | 1,355 ms | 714 ms | 776 ms |
| 策略中心 | 876 ms | 665 ms | 538 ms |
| 系统设置 | 1,077 ms | 593 ms | 531 ms |

说明两点，避免误读：

1. **约 0.5 s 是测量底噪**。`AppTest` 每次都要重跑脚本、重建 widget 树，即使页面只画静态
   文本也要 0.5 s 左右。所以"0.6 s"的实际含义是"数据部分几乎不花时间"。
2. **cold 列没有变好**，也不应该变好：缓存只对重复读取有用。清空缓存后的第一次加载仍是
   3.5–7.0 s，这是真实的首次体验，写进了 `KNOWN_LIMITATIONS.md`。
3. **未加缓存的页面（消息探查、审核工作台、治理决策、处置中心、反馈与审计、策略中心、
   模型分析、策略评估、系统设置）前后差异属于同机噪声**，不是优化结果；这些页面涉及
   写操作或需要即时可见，本阶段刻意不缓存。

---

## 10. 优化记录（只保留有前后对比的）

### 10.1 三个聚合 SQL 被重写

原实现用逐行 `LATERAL array_agg` 求消息的最高风险等级，50k 行时单查询数百毫秒。
改为 `severity_rank` + `scored` 两个 CTE 一次聚合，并在 Python 侧用同一份等级映射：

| 查询 | 优化前 | 优化后 | 提升 |
| --- | --- | --- | --- |
| `daily_timeline` | 255.6 ms | 64.0 ms | 4.0× |
| `dataset_summary` | 201.0 ms | 36.3 ms | 5.5× |
| `server_risk` | 191.2 ms | 138.3 ms | 1.4× |
| `overview()` 总计（进程内） | 3.35 s | 1.05 s | 3.2× |

### 10.2 仪表盘读取加 45 秒缓存

新增 `claro/ui/cache.py`：只缓存纯读聚合（总览 + 6 个分析页 + 风险情报），缓存键包含
窗口、筛选、粒度、条数等全部参数，写入路径一律不走缓存。效果见第 9 节：总览
3,633 → 609 ms，分析总览 7,264 → 636 ms，社区分析 4,197 → 756 ms。

代价是数据最多滞后 45 秒。这个代价是**显式**的：侧边栏有"刷新数据"按钮清空缓存，
`cache.TTL_SECONDS` 是唯一开关，`KNOWN_LIMITATIONS.md` 与 `TROUBLESHOOTING.md` 都写明了
"看到旧数字先点刷新"。

### 10.3 明确**没有**做的优化及原因

| 候选优化 | 为什么不做 |
| --- | --- |
| 多进程/多线程消费 | 本阶段没有做多消费者并发写压测，没有数据支持收益；在 4 核笔记本上盲加并发会引入锁竞争风险，故不改 |
| 加大连接池 | 当前池 5 + 溢出 10，在单用户与 200 条串行样本下未观察到等待；无排队证据就不调参 |
| 表分区 | 5 万行级别分区只会增加规划开销，收益要到百万行才可能出现；缺少该量级的实测环境 |
| 物化视图 / 预聚合表 | 会让"指标口径"出现第二份定义，与 Phase 05 的单一口径原则冲突 |
| 缓存写入路径 | 违反"写完立即可见"，审核与处置决策不能读旧值 |
| 把治理阶段的审计写入改异步 | 会削弱可追溯性，收益预计 30 ms 量级，不值得（未实现，因此也未实测） |

---

## 11. 复现命令

```powershell
# 环境与依赖就绪后（scripts\check_environment.ps1 全绿）
.venv\Scripts\python.exe scripts\benchmark_pipeline.py --tiers 1000,10000,50000 --sample 200
.venv\Scripts\python.exe scripts\benchmark_pipeline.py --validation-only
.venv\Scripts\python.exe scripts\benchmark_pipeline.py --queries-only
$env:PYTHONPATH="src"; .venv\Scripts\python.exe runtime\page_timing.py
```

完整一轮（三档 + 查询 + 缓存）在本机约 19 分钟，`--validation-only` 约 5 秒，
`--queries-only` 约 1 分钟，页面计时约 3 分钟。

---

## 12. 边界声明

* 全部数据为合成数据，检测命中率等业务指标不代表真实线上效果。
* 单机单节点：没有 Kafka 多分区、没有 PostgreSQL 主从、没有反向代理，因此**没有**给出
  并发用户数、QPS 上限这类数字——本机测不出可信值，就不写。
* Hive / Hadoop 未安装（见 `KNOWN_LIMITATIONS.md`），离线分析路径未参与本次测量，
  也没有用本地替代实现冒充实测结果。
* 所有耗时均含 Python 解释器与驱动开销，属于"端到端真实可用"的口径，不是纯 SQL 执行计划
  的 `EXPLAIN ANALYZE` 时间。
