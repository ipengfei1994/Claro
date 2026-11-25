# Claro Phase 04 — 处置模拟引擎

## 1. 模拟边界

所有处置记录必须设置 `simulated=true`。系统不连接真实游戏服务器，不修改真实玩家数据，不调用任何外部游戏接口。`BLOCK` 仅将本地 `message.display_status` 设为 `blocked`；`MUTE` / `TEMP_BAN` / `PERM_BAN` 只写入 `player_enforcement_state` 模拟状态。

## 2. 支持动作与目标

| 动作 | 默认目标 | 时长 | 到期 |
|---|---|---|---|
| WARN | player | 无 | 无 |
| BLOCK | message | 不接受时长 | 无 |
| MUTE | player / player_server | 默认 3600 秒，上限 86400 秒 | `expires_at` |
| TEMP_BAN | player / player_server | 默认 86400 秒，上限 2592000 秒 | `expires_at` |
| PERM_BAN | player / player_server | 无时长 | 无到期 |

`plan_enforcement()` 在纯领域层校验动作、目标、时长组合；`validate_target_ref()` 保证 BLOCK 的目标等于消息 ID，玩家类处置目标不等于消息 ID。违反约束抛出 `EnforcementValidationError` / `GovernanceValidationError`，不会写库。

## 3. 幂等与重复保护

幂等键为 `enforcement:{decision_id}:{action}:{target_ref}`，数据库唯一约束保证重复消费同一决策/动作/目标只产生一条记录。重复调用返回已有记录并带 `created=false`。

处置动作必须匹配对应决策的 `action`，或匹配已审核工单的 `final_action`；不匹配时拒绝执行。

## 4. 玩家模拟状态

`player_enforcement_state` 以 `(player_ref, scope_ref)` 唯一，记录 `mute_until`、`ban_until`、`permanent_ban`、`warn_count`。`scope_ref` 默认为消息所属服务器；UI 查询时需使用相同作用域。

`EnforcementService.is_player_restricted()` 汇总当前是否受限，分别给出 `muted` 与 `banned`。状态可从 Redis 缓存读取，TTL 为 30 秒；PostgreSQL 仍是权威来源。

释放或到期时会同时清除 `*` 与服务器作用域的缓存键，避免界面显示过期状态。

## 5. 到期与解除

- `expire_due_enforcements()` 将到期且仍为 `executed` 的处置标记为 `expired`，并清除对应的模拟状态。
- `release_enforcement()` 将处置标记为 `released`，记录操作人、时间与原因，清除模拟状态。
- 已释放/到期/取消的处置不能重复释放，抛出 `GovernanceValidationError`。
- CLI：`governance-expire-enforcements --limit 500`。

## 6. 失败记录

`force_failure=true` 用于演示处置失败：记录状态为 `failed`，`executed_at` 为空，`details` 中写明失败原因，并发布失败事件到 Outbox。失败不会伪造成功状态。

## 7. 审计与事件

处置执行、失败、释放、到期均写入 `audit_event`，并在事务内写入 `outbox_event`。关键事件：

- `game.governance.enforcement.executed.v1`
- `game.governance.enforcement.failed.v1`
- `game.governance.enforcement.released.v1`

所有 payload 都标记 `synthetic=true` 与 `simulated_only=true`。
