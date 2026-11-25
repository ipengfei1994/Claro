# Claro Phase 02 — 合成数据生成器

## 1. 默认参数

| 参数 | 默认值 |
|---|---:|
| seed | `20261125` |
| players | `5000` |
| servers | `10` |
| alliances | `500` |
| messages | `50000` |
| policy_rules | `40` |
| days | `31` |
| start_time | `2026-01-01T00:00:00Z`（Python 默认） |

所有规模必须为正整数，`alliances >= servers`，seed 范围为 `0..2147483647`。默认名称为 `phase-02-synthetic-s20261125-p5000-m50000`。

## 2. 生成内容

- 服务器、联盟、玩家、消息及全部关联记录。
- 5 套策略及 keyword/regex 规则。
- 正常、风险、语境边界三类消息模板。
- `MessageLabel`、`RiskEvent`、`PolicyDecision`、`ModerationRecord`。
- synthetic 标记、生成参数、内容哈希、trace ID 和稳定 UUID。
- 按玩家活跃度与健谈度加权采样消息。
- 玩家 beta 风险倾向、lognormal 活跃度、周末/小时权重和非均匀渠道分布。

## 3. 可重复性与标签隔离

生成器仅使用本地 `random.Random(seed)`；主键和外部消息 ID 使用 UUID5。同一规格与代码版本产生相同内容和 fingerprint。

标签在生成阶段独立采样，检测风险事件是另一随机过程。split 由玩家引用哈希确定，同一玩家的所有消息必须处于同一 split，比例目标为 70/10/10/10，避免玩家级泄漏。当前规则集不单独划分训练/验证 split，后续建模时应显式设计规则级隔离。

raw 和 processed Kafka payload 均不包含 label、split、risk_score 或 action。

## 4. 命令

```powershell
# 只生成，不访问数据库
.\.venv\Scripts\python.exe -m claro generate-data --messages 1000 --output runtime\summary.json

# 全量生成并加载 PostgreSQL
.\.venv\Scripts\python.exe -m claro load-data

# 自定义小规模数据集
.\.venv\Scripts\python.exe -m claro generate-data --seed 42 --players 100 --servers 2 --alliances 20 --messages 500 --policy-rules 16 --days 7

# 定向质量检查
.\.venv\Scripts\python.exe -m claro check-data --dataset phase-02-synthetic-s20261125-p5000-m50000

# 仅清理受保护的 Phase 02 synthetic 数据集
.\.venv\Scripts\python.exe -m claro clean-data --dataset phase-02-synthetic-s20261125-p5000-m50000
```

PowerShell 入口：

```powershell
.\scripts\generate_data.ps1 -Messages 1000 -Output runtime\summary.json
.\scripts\generate_data.ps1 -Load
.\scripts\generate_data.ps1 -Name phase-02-synthetic-smoke -Players 100 -Servers 2 -Alliances 20 -Messages 500 -Load
```

PowerShell 入口使用 `-Name` 指定数据集名称；独立 `clean-data` 命令用于定向清理。

## 5. 加载语义

- 默认 batch size 为 1000，按外键顺序批量写入。
- 相同 fingerprint 的重复加载保持幂等。
- 同名但 fingerprint 改变时拒绝加载；只有显式 `--clean` 才替换该数据集。
- Phase 01 数据集受到删除保护。
- 清理仅接受 `phase-02-synthetic-*` 名称或 `template_version=2` 的数据集。

## 6. 已验证结果

默认数据集真实写入 PostgreSQL：

- 50,000 messages / labels / policy decisions
- 250,000 processing events
- 8,856 risk findings/events
- 4,035 moderation cases、7,770 moderation records
- 1,206 enforcement actions
- 全部质量检查通过，重复加载保持幂等。
