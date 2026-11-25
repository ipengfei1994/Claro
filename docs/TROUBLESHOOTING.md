# 故障排查（Troubleshooting）

按"症状 → 先看哪里 → 怎么修"的顺序组织。所有命令都在项目根目录执行，使用 PowerShell。

## 0. 先跑一次自检

```powershell
scripts\check_environment.ps1
scripts\check_services.ps1
```

`check_environment.ps1` 会给出六种状态之一：`Healthy` / `Running` / `Installed` / `NotConfigured` / `Incompatible` / `Missing`。看到 `Incompatible` 优先处理——它通常意味着"端口被别的进程占了"或"Python 版本不对"。

---

## 1. 配置类

### `1 validation error for ClaroSettings — Extra inputs are not permitted`

拼错的 `CLARO_*` 环境变量会被拒绝，这是有意的。检查变量名，例如 `CLARO_UI_PORT` 应为 `CLARO_UI__PORT`（双下划线表示嵌套）。

```powershell
python -m claro.cli check-config
```

### `full mode requires CLARO_DATABASE__URL with a postgresql+psycopg:// URL`

`.env` 里 `CLARO_APP__MODE=full` 但数据库 URL 还是 SQLite。修正：

```ini
CLARO_APP__MODE=full
CLARO_DATABASE__URL=postgresql+psycopg://claro@127.0.0.1:5432/claro
CLARO_REDIS__ENABLED=true
CLARO_REDIS__URL=redis://127.0.0.1:6379/0
CLARO_KAFKA__ENABLED=true
CLARO_KAFKA__BOOTSTRAP_SERVERS=127.0.0.1:9092
```

### `replace the database password placeholder in .env`

`CLARO_DATABASE__URL` 里还留着 `replace-me`。填真实口令，或使用本机的信任认证（`claro@127.0.0.1`）。

---

## 2. 服务类

### PostgreSQL 起不来

```powershell
Get-Service postgresql*            # 看服务状态
scripts\start_services.ps1 -Service PostgreSQL
& "C:\Program Files\PostgreSQL\18\bin\pg_isready.exe" -h 127.0.0.1 -p 5432
```

服务名不是默认值时：`scripts\start_services.ps1 -Service PostgreSQL -PostgreSQLServiceName <名字>`。

### Kafka 启动报 `系统找不到指定的文件`

历史上这是 JDK 路径被解析成 `<jdk>\bin` 导致的（会拼成 `bin\bin\java.exe`）。Phase 06 已修复；如果仍出现，确认：

```powershell
$env:JAVA_HOME
Test-Path "$env:JAVA_HOME\bin\java.exe"
```

`JAVA_HOME` 必须指向 JDK 根目录，而不是 `bin`。

### `Start-Process : 已添加项。字典中的关键字:"HTTPS_PROXY"`

Windows PowerShell 5.1 在环境变量大小写重复时会抛这个错（`HTTPS_PROXY` 与 `https_proxy` 并存）。Phase 06 在 `scripts/service_common.ps1` 里加了 `Reset-ClaroDuplicateEnvironment` 做归一化。若在自定义脚本里遇到，先调用该函数。

### 端口被占用

```powershell
Get-NetTCPConnection -LocalPort 8501,9092,9093,6379,5432 -State Listen |
  Select-Object LocalPort, OwningProcess
```

脚本只会停止 `runtime\*.pid` 里记录、且命令行与预期匹配的进程；发现占用者是"别的程序"时会拒绝接管并报错，此时要么停掉它，要么改端口：

```powershell
$env:CLARO_UI__PORT = "8502"; scripts\start_app.ps1
```

---

## 3. 应用类

### 页面空白 / 只有侧栏

1. 打开浏览器控制台，看是否有 Streamlit 的 `Script error`。
2. 看 `logs\app.stderr.log`。
3. 若侧栏连导航都没有：检查 `.streamlit/config.toml` 的 `[client] showSidebarNavigation` 是否为 `true`（设为 `false` 会连 `st.navigation` 一起藏掉）。

### `页面渲染失败：...` 且带 traceback

页面级异常会被捕获并显示，不会白屏。展开"错误详情"即可看到真实堆栈。常见原因：

| 报错 | 原因 | 处理 |
|---|---|---|
| `Invalid height value: None` | `st.dataframe(height=None)` 不被允许 | 已修复（`common.data_table` 只在有值时传 height） |
| `tz_convert() takes exactly 2 positional arguments` | 对 `pandas.Timestamp` 直接调 `astimezone()` | 已修复（`common._to_local` 先转 `datetime`） |
| `字段 xxx 不存在` | SQL 与 schema 漂移 | 检查迁移是否到 head：`scripts\run_migrations.ps1` |

### 主题切换后文字看不清

确认 `.streamlit/config.toml` 里有 `[theme.light]` 与 `[theme.dark]` 两段，并且**没有**在代码里覆盖 Streamlit 的 CSS 变量。当前实现只注入 `.claro-*` 自有类名。

### 图表是空白框

说明查询返回空集合。总览默认"近 1 年"，如果数据库里没有该窗口的数据，会显示明确的空状态文案而不是空框。

### 页面数字是旧的 / 刚审核完但总数没变

仪表盘的纯读聚合有 45 秒缓存（`src/claro/ui/cache.py`，`TTL_SECONDS = 45`）。点侧栏"刷新数据"立即清空缓存并重跑页面；等 45 秒也会自动过期。写入类页面（审核工作台、治理决策、处置中心、策略中心、反馈与审计）不走缓存，写完读到的就是新值。

### 第一次打开很慢（3–7 秒）

缓存未命中的首次加载就是慢：分析总览约 7.0 s、治理总览约 4.9 s（50,016 条消息的基线库）。之后切页在 0.6–1.1 s。数字与测量方法见 `PHASE_06_PERFORMANCE.md`，不要在慢机器上把这当成故障。

---

## 4. 数据与流水线

### `no messages match the replay filters`

回放按 `message.occurred_at` 过滤。演示数据锚定在 2026-11-25，如果用手写的时间窗对不上就查不到。用 `claro strategy-replay --start ... --end ...` 时把窗口覆盖到该日期。

### `event_id was reused with a different payload`

同一 `event_id` 提交了不同内容。检查是不是在重放时改了消息体却复用了 ID。演示脚本用固定 ID，重复运行是安全的（返回 `duplicate`）。

### `dataset name is already registered with a different ID`

同一数据集名称配了不同 UUID。用 `claro demo-clean --yes` 清掉演示数据集，或换一个数据集名。

### `Kafka source offset was reused by a different event`

同一 `(topic, partition, offset)` 对应了不同消息。批量导入脚本要给每个 tier/批次用独立 topic 或独立 offset 区间。

### 演示数据跑完，总览还是空的

总览按 `message.occurred_at` 过滤。演示消息发生在 `2026-11-25`，如果当前系统时间与之相差超过一年，把时间窗切到"近 1 年"或更宽。

---

## 5. 测试类

### `pytest: unrecognized arguments: --timeout`

没装 `pytest-timeout`。用 `scripts\run_tests.ps1 -Suite unit`，它不使用该参数。

### 集成测试全红

集成测试需要真实服务。先 `scripts\check_services.ps1`，再 `scripts\run_tests.ps1 -Suite integration`。注意：集成测试会创建自己的数据集，不会污染演示库。

### UI 测试超时

首个页面要等数据库与缓存预热。`tests/ui/test_screens_smoke.py` 的 `default_timeout=300`，机器很慢时可以临时调高。

---

## 6. 日志位置

| 文件 | 内容 |
|---|---|
| `logs\claro.jsonl` | 应用结构化日志（JSON，敏感字段已脱敏为 `[REDACTED]`） |
| `logs\app.stdout.log` / `app.stderr.log` | Streamlit 进程输出 |
| `logs\kafka.stdout.log` / `kafka.stderr.log` | Kafka broker |
| `logs\redis.stdout.log` / `redis.stderr.log` | Redis |
| `logs\pipeline-consumer.*.log` | Kafka 消费进程 |

日志中不会出现口令、Token、API Key——`redact_sensitive` 处理器会对 `password` / `token` / `secret` / `authorization` / `api_key` 字段及其嵌套值做替换。如果你在日志里看到了明文凭据，那是一个需要立即修复的缺陷。
