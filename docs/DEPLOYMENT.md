# Claro Phase 02 — Windows 原生部署

## 1. 支持范围

- Windows 11 + Python 3.12
- PostgreSQL 18 Windows 原生服务
- Redis 8.10.3 Windows 原生进程
- Apache Kafka 3.9.2 + Microsoft OpenJDK 17，单节点 KRaft
- 本机 Streamlit UI

不使用 Docker、Docker Compose、容器化或 WSL。Redis/Kafka 仅监听本地回环地址，Kafka 单节点配置不构成生产高可用方案。

## 2. 安装与检查

```powershell
cd D:\桌面\Claro
.\scripts\claro.ps1 install
.\scripts\check_environment.ps1
```

环境检查覆盖 Python 3.12、PostgreSQL 工具、Redis、Kafka/Java、配置与预期端口占用。端口所有者必须匹配预期进程；不会仅凭端口开放就接管未知进程。

## 3. 启动与状态

```powershell
.\scripts\start_services.ps1 -Service PostgreSQL
.\scripts\start_services.ps1 -Service Redis
.\scripts\start_services.ps1 -Service Kafka
.\scripts\start_services.ps1 -Service All

.\scripts\check_services.ps1
.\scripts\check_services.ps1 -IncludePipeline
```

- 重复启动会识别已有服务并跳过。
- PostgreSQL 必须匹配唯一的 `postgresql-x64-*` 服务；可用 `-PostgreSQLServiceName` 明确指定。
- Redis/Kafka 使用 PID 文件并校验进程名与命令行，不停止无关进程。
- Redis 配置使用项目相对路径，兼容 Windows Redis 的 Cygwin 路径解析。
- Kafka Topic 由启动流程确保存在。

## 4. 数据库初始化

```powershell
.\scripts\init_database.ps1 -WhatIf
.\scripts\init_database.ps1 -Seed
```

脚本读取 `CLARO_DB_PASSWORD` 或安全提示输入，密码至少 12 位；随后执行初始化 SQL、`alembic upgrade head`、`alembic current`，可选 Phase 01 seed。

应用连接 URL 不包含明文密码；本机使用 `%APPDATA%\postgresql\pgpass.conf`。初始化脚本会修改角色/数据库，已仅执行 `-WhatIf`，未重新初始化现有数据库。

## 5. 数据与流水线

```powershell
.\scripts\generate_data.ps1 -Messages 1000 -Output runtime\summary.json
.\scripts\generate_data.ps1 -Load

.\scripts\start_pipeline.ps1
.\scripts\start_pipeline.ps1 -Topic game.messages.raw.smoke -ConsumerGroup claro-smoke-v1 -WithUi
.\scripts\check_services.ps1 -IncludePipeline
```

`start_pipeline.ps1` 启动前要求 PostgreSQL、Redis、Kafka 全部健康。Consumer 和 Streamlit 分别记录 PID 与 stdout/stderr 日志。

## 6. 停止

```powershell
# 预览，不执行
.\scripts\stop_services.ps1 -WhatIf

# 仅停止 Consumer/UI
.\scripts\stop_services.ps1 -Service Pipeline

# 停止 Redis/Kafka，不停止 PostgreSQL
.\scripts\stop_services.ps1 -Service Redis
.\scripts\stop_services.ps1 -Service Kafka
```

停止操作仅作用于已验证所有权的 PID/命令行或指定的 PostgreSQL Windows 服务。Redis/Kafka 的安全停止和重启已实际验证；PostgreSQL stop/start 未实际执行。

## 7. 运行文件

```text
runtime/
├── redis.pid
├── kafka.pid
├── pipeline-consumer.pid
└── streamlit.pid
logs/
├── redis.stdout.log / redis.stderr.log
├── kafka.stdout.log / kafka.stderr.log
├── pipeline-consumer.stdout.log / pipeline-consumer.stderr.log
└── streamlit.stdout.log / streamlit.stderr.log
```

`.env`、数据库文件、日志和运行目录不纳入 Git。服务配置不得硬编码密钥。

## 8. 已验证状态

- PostgreSQL/Redis/Kafka 状态均为 true。
- 重复启动保护通过。
- Redis/Kafka 停止后重启保留预期状态与 Kafka Topic 元数据。
- 隔离 Pipeline 10 条消息消费、lag=0、重复启动保护及 PID 安全停止通过。
- Streamlit 已在 Phase 01 通过浏览器冒烟；Phase 02 的原生服务脚本保持该启动入口。
