# Windows 原生部署（Deployment on Windows）

Claro 只支持 **Windows 11 原生**运行：PostgreSQL、Kafka、Redis 都作为本机进程/服务安装，不使用 Docker、Docker Compose 或 WSL。这不是省事的选择，而是项目的硬约束——目标是证明这套系统在没有容器编排的单机环境下也能被完整复现和操作。

## 1. 依赖清单

| 组件 | 版本 | 安装形态 | 端口 |
|---|---|---|---|
| Python | 3.12.10 | `.venv` 虚拟环境 | — |
| PostgreSQL | 18.3 | Windows 服务 `postgresql-x64-18` | 5432 |
| Apache Kafka | 3.9.2（KRaft 单节点） | 本地目录 `deploy/kafka` | 9092（客户端）/ 9093（控制器） |
| Redis | 8.10.3（Windows 分支版 taizod1024） | 本地进程，配置 `deploy/redis/redis.conf` | 6379 |
| JDK | 17 | `JAVA_HOME` 指向 JDK 根目录 | — |
| Streamlit | 1.67.0 | 随 Python 依赖安装 | 8501 |
| Hive / Hadoop | — | **未安装** | — |

## 2. 首次部署

```powershell
# 1) 创建虚拟环境并安装依赖（uv 管理）
scripts\claro.ps1 install

# 2) 配置
Copy-Item .env.example .env
notepad .env                # 填写 CLARO_DATABASE__URL 等

# 3) 自检：任何 Missing / Incompatible 都会让脚本返回非零
scripts\check_environment.ps1

# 4) 启动服务
scripts\start_services.ps1

# 5) 建库与迁移
scripts\init_database.ps1
scripts\run_migrations.ps1

# 6) 装载数据（二选一）
scripts\generate_demo_data.ps1     # 演示用 5,000 条
scripts\claro.ps1 generate -Load   # 完整 50,000 条基线

# 7) 启动应用
scripts\start_app.ps1
```

浏览器打开 <http://127.0.0.1:8501>。

## 3. 一键启停

```powershell
scripts\start_claro.ps1      # 环境检查 → 服务 → 迁移 → 应用
scripts\stop_claro.ps1       # 应用 → 消费者 → Kafka → Redis（PostgreSQL 默认保留）
scripts\stop_claro.ps1 -Force -IncludePostgreSQL
```

`start_claro.ps1` 的四步顺序是有意的：**先检查环境，再起服务，再确认迁移到 head，最后起应用**。任何一步失败都会中止，不会留下"服务起了一半、应用连不上库"的状态。

## 4. 脚本清单

| 脚本 | 作用 | 关键行为 |
|---|---|---|
| `check_environment.ps1` | 六态环境报告 | 输出 `Healthy/Running/Installed/NotConfigured/Incompatible/Missing`；阻塞项返回 1 |
| `check_services.ps1` | 三个服务是否在跑 | `-IncludePipeline` 连消费者一起检查 |
| `start_services.ps1` | 启动 PostgreSQL / Redis / Kafka | `-Service Kafka` 可单独启动 |
| `stop_services.ps1` | 停止服务 | 只停本项目启动的进程 |
| `start_app.ps1` | 启动 Streamlit | 写 `runtime\app.pid`，轮询健康检查直到 200 |
| `stop_app.ps1` | 停止 Streamlit | 校验命令行后才 `Stop-Process` |
| `init_database.ps1` | 建库与角色 | 幂等 |
| `run_migrations.ps1` | Alembic 升级 | 打印升级前后 revision；`-Sql` 只预览 |
| `generate_demo_data.ps1` | 生成并加载演示数据集 | 固定 seed，可重复 |
| `run_demo.ps1` | 跑 14 步端到端演示 | `-Status` 查看、`-Clean` 清理（需确认） |
| `run_tests.ps1` | 跑测试 | `-Suite unit|integration|ui|all`，`-Coverage` 出覆盖率 |
| `start_claro.ps1` | 全栈启动 | 四步串行，失败即停 |
| `stop_claro.ps1` | 全栈停止 | 反序停止，默认保留 PostgreSQL |

## 5. PID 与进程安全

所有长驻进程都写入 `runtime\*.pid`：

| 文件 | 进程 |
|---|---|
| `runtime\app.pid` | Streamlit |
| `runtime\kafka.pid` | Kafka broker |
| `runtime\redis.pid` | Redis |
| `runtime\pipeline-consumer.pid` | Kafka 消费者 |

停止逻辑遵循同一条规则：**读 PID → 取命令行 → 与预期模式比对 → 匹配才停止**。不匹配就抛错并拒绝操作，绝不按端口或进程名盲杀。这避免了"误杀同事的 Python"或"停掉系统里另一个 Kafka"。

启动逻辑同样保守：如果端口已被占用但找不到对应的 PID 文件，脚本会**拒绝接管**并提示，而不是假定那是自己的进程。

## 6. 端口与外部访问

| 端口 | 用途 | 默认绑定 |
|---|---|---|
| 8501 | Streamlit | 127.0.0.1 |
| 9092 | Kafka 客户端 | 127.0.0.1 |
| 9093 | Kafka 控制器 | 127.0.0.1 |
| 6379 | Redis | 127.0.0.1 |
| 5432 | PostgreSQL | 127.0.0.1 |

默认全部只监听回环地址。若确实需要局域网访问，请显式修改 `deploy/kafka/server.properties`、`deploy/redis/redis.conf` 与 Streamlit 启动参数，并自行承担网络暴露风险——本项目的定位是单机演示，没有做传输加密与访问控制。

## 7. 日志

| 路径 | 内容 |
|---|---|
| `logs\claro.jsonl` | 应用结构化日志（JSON Lines，10 MB 轮转，保留 5 份） |
| `logs\app.stdout.log` / `app.stderr.log` | Streamlit |
| `logs\kafka.stdout.log` / `kafka.stderr.log` | Kafka |
| `logs\redis.stdout.log` / `redis.stderr.log` | Redis |
| `logs\pipeline-consumer.*.log` | 消费者 |

日志目录由 `CLARO_LOGGING__DIRECTORY` 控制，默认 `logs/`，已在 `.gitignore` 中排除。

## 8. 配置项

配置来自三层，优先级从高到低：环境变量 → `.env` → `config/*.yaml` 默认值。

```ini
CLARO_APP__MODE=full
CLARO_DATABASE__URL=postgresql+psycopg://claro@127.0.0.1:5432/claro
CLARO_DATABASE__POOL_SIZE=5
CLARO_DATABASE__MAX_OVERFLOW=10
CLARO_REDIS__ENABLED=true
CLARO_REDIS__URL=redis://127.0.0.1:6379/0
CLARO_KAFKA__ENABLED=true
CLARO_KAFKA__BOOTSTRAP_SERVERS=127.0.0.1:9092
CLARO_UI__PORT=8501
CLARO_UI__THEME=system
CLARO_LOGGING__LEVEL=INFO
```

规则：

* 嵌套字段用**双下划线**（`CLARO_DATABASE__URL`）。
* 未知的 `CLARO_*` 变量会让启动**直接失败**，防止拼写错误被静默忽略。
* `full` 模式强制要求 PostgreSQL URL、启用 Redis、启用 Kafka，并拒绝 `replace-me` 占位口令。

## 9. 升级与回滚

```powershell
git pull
scripts\claro.ps1 install          # 依赖可能变化
scripts\run_migrations.ps1 -Sql    # 先看 SQL
scripts\run_migrations.ps1
scripts\run_tests.ps1 -Suite unit
scripts\stop_app.ps1; scripts\start_app.ps1
```

Alembic 的 `downgrade()` 保留了实现，但**没有在含真实数据的库上演练过**，因此不承诺可回滚。需要回退时优先用数据库备份恢复。

## 10. 已知不可用能力

`scripts\check_environment.ps1` 会明确打印：

```
Hive/Beeline   Missing   offline warehouse analytics unavailable;
                          PostgreSQL serves the same metrics instead.
```

这是有意的：没装的东西就写没装。`claro warehouse-export` 仍可导出 CSV 与 `load_ods.sql`，但执行 Hive 查询会失败并报错，不会返回假成功。
