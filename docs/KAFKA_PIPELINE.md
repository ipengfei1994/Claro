# Claro Phase 02 — Kafka 流水线

## 1. Topic 与链路

```text
Synthetic Generator
  → game.messages.raw
  → Consumer
  → PostgreSQL Inbox + Message + ProcessingEvent + AuditEvent
  → game.messages.processed
```

辅助 Topic：

- `game.risk.events`
- `game.moderation.events`
- `game.messages.retry`
- `game.messages.dead-letter`

实际 topic 名以 `config/default.yaml` 和模式配置为准。

## 2. 投递语义

- Producer 使用 `acks=all` 和幂等生产。
- Consumer 关闭自动提交/自动存储，业务成功后才提交源 offset。
- Retry/DLQ 发布成功后才提交源 offset。
- PostgreSQL `inbox_event` 同时以 event ID 和 `(source_topic, source_partition, source_offset)` 保证去重。
- Message、Inbox、ProcessingEvent、AuditEvent 在一个事务内写入。
- processed 发布失败视为可重试；重复 Inbox 投递会再次发布 processed 事件。
- 因此链路是 at-least-once，不声称 exactly-once。

## 3. 命令

```powershell
# 创建/列出 Topic
.\.venv\Scripts\python.exe -m claro kafka-topics

# 独立生产 100 条原始消息
.\.venv\Scripts\python.exe -m claro kafka-produce --messages 100 --topic game.messages.raw.smoke

# 独立消费，并持久化到 PostgreSQL
.\.venv\Scripts\python.exe -m claro kafka-consume --topic game.messages.raw.smoke --persist --max-messages 100

# 持续运行，由 PowerShell 管理 PID 和日志
.\.venv\Scripts\python.exe -m claro kafka-consume --topic game.messages.raw --persist --continuous --group claro.pipeline.v1

# 检查 Group 状态、已提交 offset 和 lag
.\.venv\Scripts\python.exe -m claro kafka-group --group claro.pipeline.v1
```

`--idle-timeout` 仅在非 continuous 模式生效；continuous 模式会一直等待。Retry 耗尽后进入 DLQ，永久 schema 错误不会无限重试。

## 4. 重试与错误头

- `x-claro-origin-topic`
- `x-claro-origin-partition`
- `x-claro-origin-offset`
- `x-claro-origin-received-at`
- `x-claro-retry-count`
- `x-claro-error-code`
- `x-claro-error-detail`

DLQ 保留原 EventEnvelope 和源坐标，便于审计和人工恢复。

## 5. 已验证链路

- 100 条真实端到端消息及 10 条重复投递验证通过。
- CLI 500 条生产/消费持久化链路通过。
- Retry、DLQ、手动提交、Inbox 去重、Group lag 检查通过。
- PowerShell 隔离冒烟：10 条消息、10 processing events、10 audit events、10 inbox events，Group lag=0，重复启动保护和安全停止通过。

## 6. 历史消息注意事项

默认 raw topic 保留 Phase 02 早期 12 条旧 schema 冒烟消息。默认业务 Group 尚未消费；直接以 `earliest` 启动会把它们路由到 DLQ。生产验收应使用新 topic，或在确认旧消息处理策略后再启动默认 Group。

测试 Topic 被保留，因为 Windows broker 在即时删除 Topic 时曾发生文件锁和崩溃。PostgreSQL 测试数据清理不会删除 Kafka Topic 中的消息。
