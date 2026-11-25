# Claro Phase 04 — 人工审核工作流

## 1. 审核队列

`ModerationService.queue()` 支持按状态、风险等级、负责人、超时、关键词筛选。`open_queue()` 只返回开放状态：`pending`、`in_review`、`escalated`、`second_review`。

UI 展示待审核数量、超时数量、审核操作总数与当前模拟身份，并按风险等级绘制队列分布图。筛选条件全部通过服务层传入仓储，不在 UI 中拼接 SQL。

## 2. 状态机

状态转移在 `governance/moderation.py::CASE_TRANSITIONS` 显式定义：

```text
pending / open → in_review
in_review → approved / rejected / escalated / second_review / finalized
escalated → in_review / second_review / finalized / rejected
second_review → approved / rejected / finalized / in_review
approved / rejected / finalized / resolved → in_review（重新打开）
```

动作到目标状态的映射：

| 动作 | 目标状态 |
|---|---|
| APPROVE | approved |
| REJECT | rejected |
| OVERRIDE | finalized |
| ESCALATE | escalated |
| REQUEST_SECOND_REVIEW | second_review |
| REOPEN | in_review |

所有转移经过 `validate_review_action()` 合法性检查。非法转移抛出 `ModerationWorkflowError`，不会写库。

## 3. 审核详情

审核人员可查看：原始与归一化消息、玩家与服务器/联盟信息、玩家历史风险、风险分类与置信度、规则与 ML 证据、策略匹配与命中条件、系统建议动作、关联决策解释、历史审核记录、关联处置与反馈、审计轨迹。

界面明确区分系统判断（风险引擎与策略引擎输出）与人工判断（审核动作与最终结论）。

## 4. 审核操作与校验

每次提交必须提供至少 3 字符的理由。`OVERRIDE` 额外要求 `final_action` 与 `final_level`。`ESCALATE` 与 `REQUEST_SECOND_REVIEW` 要求高级审核员或管理员角色。

`REJECT` 表示确认误杀，最终动作解析为 ALLOW；`APPROVE` 保留系统建议；`OVERRIDE` 使用人工给出的最终类别/等级/动作。

提交时若同时提供 `feedback_type`，服务层会在同一业务流程内写入 `governance_feedback`，保留原始预测、原始风险、人工结论与差异原因。

## 5. 并发保护

- `claim_case()` 与 `review_case()` 使用 `SELECT ... FOR UPDATE` 行锁与 `lock_version` 乐观锁。
- 若传入的 `expected_lock_version` 与当前值不一致，抛出 `ModerationConflictError`，提示重新加载。
- 工单已分配给其他审核员时，非持有人不能提交。
- 二次复核不能由申请二次复核的同一人完成。
- 审核提交在数据库事务内完成，审核记录、状态变更、审计与 Outbox 事件原子写入。

## 6. 二次复核与重新打开

`REQUEST_SECOND_REVIEW` 将工单转入 `second_review`，`FINALIZED` 作为终审状态。已完成的工单可通过 `REOPEN` 重新进入 `in_review`，历史审核记录保留，不覆盖原记录。工单的 `reopened_count` 与 `required_second_review` 字段记录复核要求。

## 7. 超时

`GovernanceSettings.review_sla_hours`（默认 24）决定审核工单的 `due_at`。队列筛选 `overdue=true` 只返回超时任务，UI 的「仅看超时」复选框使用该筛选。

## 8. 模拟身份

单人本地演示通过 UI 身份选择器切换 `moderator`、`senior_moderator`、`admin`、`auditor`。这是**模拟身份认证**，不是生产级登录或 RBAC；界面明确标注。角色只约束业务动作权限，不提供真实身份保证。
