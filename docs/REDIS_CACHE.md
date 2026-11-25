# Claro Phase 02 — Redis 缓存层

## 1. 权威存储

PostgreSQL 是业务和审计唯一权威来源。Redis 仅保存可重建缓存、计数器和原子限流状态，不作为黑名单或审计的唯一存储。

## 2. 缓存能力

| 能力 | 数据来源 | 默认 TTL |
|---|---|---:|
| 敏感词 | active keyword DetectionRule | 300 秒 |
| 策略配置 | active Policy | 300 秒 |
| 黑名单 | `player_blacklist_entry` | 60 秒 |
| 黑名单负缓存 | PostgreSQL 未命中 | 30 秒 |
| 玩家风险计数 | PostgreSQL RiskEvent 聚合 | 配置 TTL |
| 原子限流 | Redis Lua | 请求窗口 |

键格式：

```text
claro:cache:v1:<kind>:<sha256(scope)>
```

玩家引用等敏感标识不直接出现在键中。

## 3. 读路径与一致性

- 先读 Redis，命中后校验 payload；损坏 payload 记录 warning 并回源。
- 缓存缺失或 Redis 不可用时读取 PostgreSQL。
- Redis 写失败只记录 warning，不阻断业务读取。
- 黑名单 block/unblock 先提交 PostgreSQL 和 AuditEvent，再失效缓存。
- 显式 `invalidate_sensitive_words`、`invalidate_policy` 支持规则或策略更新后的失效。
- 风险计数按时间窗口聚合；限流使用 Lua 原子 `INCR + EXPIRE`。

## 4. 服务接口

`SafetyCacheService` 提供：

- `sensitive_words` / `invalidate_sensitive_words`
- `active_policy` / `invalidate_policy`
- `blacklist_entry` / `is_blacklisted`
- `block_player` / `unblock_player`
- `player_risk_count`
- `check_rate_limit`

输入校验包括非空且有长度上限的引用、正数窗口/TTL、带时区的未来封禁截止时间。

## 5. 配置与模式

- development：不装配 Redis 业务缓存，`AppContainer.safety_cache=None`。
- full：使用真实 Redis，并复用 PostgreSQL session factory。
- Redis URL 从 `.env` 读取；连接失败会在 full 模式健康检查中明确失败。

## 6. 验证

- 10 个单元测试覆盖缓存命中/失效、负缓存、封禁过期、写后失效、窗口、计数和损坏缓存回退。
- 真实 PostgreSQL/Redis 集成测试验证 TTL、敏感词/策略失效、黑名单与审计、风险计数和原子限流。
- Redis 真实 PING=PONG，AOF 已启用。
- 测试仅清理自身创建的 synthetic 记录，不执行全局 FLUSH。
