from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from claro.application.policy_service import PolicyService
from claro.domain.enums import DecisionAction, PolicyType, RiskSeverity

#: Governance policy catalog. Every entry is synthetically authored and clearly
#: labelled as such. Priorities are deliberately distinct so that selection is
#: deterministic; ``emergency`` policies always outrank normal policies.
SEED_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "policy_key": "gov-emergency-fraud-ban",
        "name": "应急-诈骗高危封禁",
        "description": "紧急策略：诈骗类别且风险分很高时直接处置，优先于一切常规策略。",
        "policy_type": PolicyType.COMPOSITE.value,
        "target_scope": {},
        "conditions": {
            "all": [
                {"field": "category", "op": "in", "value": ["fraud"]},
                {"field": "risk_score", "op": "gte", "value": 0.9},
            ]
        },
        "action": DecisionAction.TEMP_BAN.value,
        "priority": 1000,
        "emergency": True,
    },
    {
        "policy_key": "gov-emergency-violence-block",
        "name": "应急-暴力威胁拦截",
        "description": "紧急策略：暴力威胁类别且高风险时直接拦截消息。",
        "policy_type": PolicyType.COMPOSITE.value,
        "target_scope": {},
        "conditions": {
            "all": [
                {"field": "category", "op": "in", "value": ["violence"]},
                {"field": "risk_level", "op": "in", "value": ["high", "critical"]},
            ]
        },
        "action": DecisionAction.BLOCK.value,
        "priority": 990,
        "emergency": True,
    },
    {
        "policy_key": "gov-critical-risk-review",
        "name": "极高风险-强制人工审核",
        "description": "critical 风险等级一律进入人工审核。",
        "policy_type": PolicyType.COMPOSITE.value,
        "target_scope": {},
        "conditions": {"field": "risk_level", "op": "eq", "value": RiskSeverity.CRITICAL.value},
        "action": DecisionAction.REVIEW.value,
        "priority": 950,
        "emergency": False,
    },
    {
        "policy_key": "gov-high-risk-review",
        "name": "高风险-人工审核",
        "description": "high 风险等级进入人工审核。",
        "policy_type": PolicyType.COMPOSITE.value,
        "target_scope": {},
        "conditions": {"field": "risk_level", "op": "eq", "value": RiskSeverity.HIGH.value},
        "action": DecisionAction.REVIEW.value,
        "priority": 940,
        "emergency": False,
    },
    {
        "policy_key": "gov-score-092-block",
        "name": "风险分-高置信拦截",
        "description": "风险分 >= 0.92 且置信度达标时拦截消息。",
        "policy_type": PolicyType.RISK_THRESHOLD.value,
        "target_scope": {},
        "conditions": {
            "all": [
                {"field": "risk_score", "op": "gte", "value": 0.92},
                {"field": "confidence", "op": "gte", "value": 0.7},
            ]
        },
        "action": DecisionAction.BLOCK.value,
        "priority": 900,
        "emergency": False,
    },
    {
        "policy_key": "gov-score-085-mute",
        "name": "风险分-禁言",
        "description": "风险分 >= 0.85 的持续风险内容，模拟禁言发送者。",
        "policy_type": PolicyType.RISK_THRESHOLD.value,
        "target_scope": {},
        "conditions": {"field": "risk_score", "op": "gte", "value": 0.85},
        "action": DecisionAction.MUTE.value,
        "priority": 880,
        "emergency": False,
    },
    {
        "policy_key": "gov-score-070-review",
        "name": "风险分-进入审核",
        "description": "风险分 >= 0.70 进入人工审核。",
        "policy_type": PolicyType.RISK_THRESHOLD.value,
        "target_scope": {},
        "conditions": {"field": "risk_score", "op": "gte", "value": 0.70},
        "action": DecisionAction.REVIEW.value,
        "priority": 870,
        "emergency": False,
    },
    {
        "policy_key": "gov-score-045-warn",
        "name": "风险分-警告",
        "description": "风险分 0.45 至 0.70 之间给出警告。",
        "policy_type": PolicyType.RISK_THRESHOLD.value,
        "target_scope": {},
        "conditions": {
            "all": [
                {"field": "risk_score", "op": "gte", "value": 0.45},
                {"field": "risk_score", "op": "lt", "value": 0.70},
            ]
        },
        "action": DecisionAction.WARN.value,
        "priority": 860,
        "emergency": False,
    },
    {
        "policy_key": "gov-category-fraud-review",
        "name": "类别-诈骗进入审核",
        "description": "命中诈骗类别时进入人工审核。",
        "policy_type": PolicyType.CATEGORY.value,
        "target_scope": {},
        "conditions": {"field": "category", "op": "in", "value": ["fraud"]},
        "action": DecisionAction.REVIEW.value,
        "priority": 850,
        "emergency": False,
    },
    {
        "policy_key": "gov-category-spam-flag",
        "name": "类别-广告标记观察",
        "description": "命中广告垃圾类别时标记观察。",
        "policy_type": PolicyType.CATEGORY.value,
        "target_scope": {},
        "conditions": {"field": "category", "op": "in", "value": ["spam"]},
        "action": DecisionAction.FLAG.value,
        "priority": 840,
        "emergency": False,
    },
    {
        "policy_key": "gov-category-harassment-warn",
        "name": "类别-骚扰警告",
        "description": "命中骚扰类别时警告发送者。",
        "policy_type": PolicyType.CATEGORY.value,
        "target_scope": {},
        "conditions": {"field": "category", "op": "in", "value": ["harassment"]},
        "action": DecisionAction.WARN.value,
        "priority": 830,
        "emergency": False,
    },
    {
        "policy_key": "gov-category-hate-review",
        "name": "类别-仇恨言论审核",
        "description": "命中群体仇恨类别时进入人工审核。",
        "policy_type": PolicyType.CATEGORY.value,
        "target_scope": {},
        "conditions": {"field": "category", "op": "in", "value": ["hate_speech"]},
        "action": DecisionAction.REVIEW.value,
        "priority": 835,
        "emergency": False,
    },
    {
        "policy_key": "gov-category-sexual-review",
        "name": "类别-色情低俗审核",
        "description": "命中色情内容类别时进入人工审核。",
        "policy_type": PolicyType.CATEGORY.value,
        "target_scope": {},
        "conditions": {"field": "category", "op": "in", "value": ["sexual_content"]},
        "action": DecisionAction.REVIEW.value,
        "priority": 834,
        "emergency": False,
    },
    {
        "policy_key": "gov-category-selfharm-review",
        "name": "类别-自伤内容审核",
        "description": "命中自伤类别时进入人工审核并优先处理。",
        "policy_type": PolicyType.CATEGORY.value,
        "target_scope": {},
        "conditions": {"field": "category", "op": "in", "value": ["self_harm"]},
        "action": DecisionAction.REVIEW.value,
        "priority": 845,
        "emergency": False,
    },
    {
        "policy_key": "gov-keyword-gold-selling",
        "name": "关键词-金币代充",
        "description": "消息包含金币代充、低价充值等营销词时拦截。",
        "policy_type": PolicyType.KEYWORD.value,
        "target_scope": {},
        "conditions": {
            "field": "content",
            "op": "contains",
            "value": ["金币代充", "低价充值", "代充值", "充值折扣"],
        },
        "action": DecisionAction.BLOCK.value,
        "priority": 800,
        "emergency": False,
    },
    {
        "policy_key": "gov-keyword-account-trade",
        "name": "关键词-账号交易",
        "description": "消息涉及账号买卖时进入审核。",
        "policy_type": PolicyType.KEYWORD.value,
        "target_scope": {},
        "conditions": {
            "field": "content",
            "op": "contains",
            "value": ["出售账号", "买号", "卖号", "账号交易"],
        },
        "action": DecisionAction.REVIEW.value,
        "priority": 790,
        "emergency": False,
    },
    {
        "policy_key": "gov-keyword-cheat-tool",
        "name": "关键词-外挂脚本",
        "description": "消息推广外挂或脚本时拦截。",
        "policy_type": PolicyType.KEYWORD.value,
        "target_scope": {},
        "conditions": {
            "field": "content",
            "op": "contains",
            "value": ["外挂", "脚本辅助", "自动挂机", "秒升"],
        },
        "action": DecisionAction.BLOCK.value,
        "priority": 795,
        "emergency": False,
    },
    {
        "policy_key": "gov-keyword-betting",
        "name": "关键词-博彩导流",
        "description": "消息包含博彩导流词时进入审核。",
        "policy_type": PolicyType.KEYWORD.value,
        "target_scope": {},
        "conditions": {
            "field": "content",
            "op": "contains",
            "value": ["博彩", "押注", "下注平台", "返水"],
        },
        "action": DecisionAction.REVIEW.value,
        "priority": 780,
        "emergency": False,
    },
    {
        "policy_key": "gov-keyword-insult",
        "name": "关键词-辱骂挑衅",
        "description": "消息包含常见侮辱词时警告。",
        "policy_type": PolicyType.KEYWORD.value,
        "target_scope": {},
        "conditions": {
            "field": "content",
            "op": "contains",
            "value": ["废物", "垃圾队友", "滚开", "找死"],
        },
        "action": DecisionAction.WARN.value,
        "priority": 700,
        "emergency": False,
    },
    {
        "policy_key": "gov-keyword-real-world-trade",
        "name": "关键词-现实交易",
        "description": "消息涉及现实货币交易时标记观察。",
        "policy_type": PolicyType.KEYWORD.value,
        "target_scope": {},
        "conditions": {
            "field": "content",
            "op": "contains",
            "value": ["微信转账", "支付宝收款", "银行卡", "私聊付款"],
        },
        "action": DecisionAction.FLAG.value,
        "priority": 690,
        "emergency": False,
    },
    {
        "policy_key": "gov-regex-contact-info",
        "name": "正则-联系方式",
        "description": "消息中出现手机号或社交账号时进入审核。",
        "policy_type": PolicyType.REGEX.value,
        "target_scope": {},
        "conditions": {
            "field": "content",
            "op": "regex",
            "value": r"(1[3-9]\d{9}|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
        },
        "action": DecisionAction.REVIEW.value,
        "priority": 680,
        "emergency": False,
    },
    {
        "policy_key": "gov-regex-external-link",
        "name": "正则-外部链接",
        "description": "消息中出现外部网址时标记观察。",
        "policy_type": PolicyType.REGEX.value,
        "target_scope": {},
        "conditions": {
            "field": "content",
            "op": "regex",
            "value": r"(https?://|www\.)\S+",
        },
        "action": DecisionAction.FLAG.value,
        "priority": 670,
        "emergency": False,
    },
    {
        "policy_key": "gov-regex-repeated-chars",
        "name": "正则-重复刷屏",
        "description": "消息出现大量重复字符时警告，疑似刷屏。",
        "policy_type": PolicyType.REGEX.value,
        "target_scope": {},
        "conditions": {"field": "content", "op": "regex", "value": r"[!！?？~～。\.]{6,}"},
        "action": DecisionAction.WARN.value,
        "priority": 660,
        "emergency": False,
    },
    {
        "policy_key": "gov-regex-qq-group",
        "name": "正则-群号导流",
        "description": "消息中出现 QQ 群号导流时进入审核。",
        "policy_type": PolicyType.REGEX.value,
        "target_scope": {},
        "conditions": {
            "field": "content",
            "op": "regex",
            "value": r"(群号?[:：]?\s*\d{5,12}|QQ群\s*\d{5,12})",
        },
        "action": DecisionAction.REVIEW.value,
        "priority": 665,
        "emergency": False,
    },
    {
        "policy_key": "gov-rate-flood-20",
        "name": "限流-高频刷屏",
        "description": "窗口内消息数 >= 20 时限制发送者。",
        "policy_type": PolicyType.RATE_LIMIT.value,
        "target_scope": {},
        "conditions": {"field": "rate_count", "op": "gte", "value": 20},
        "action": DecisionAction.MUTE.value,
        "priority": 650,
        "emergency": False,
    },
    {
        "policy_key": "gov-rate-burst-12",
        "name": "限流-突发高频",
        "description": "窗口内消息数 >= 12 时警告并观察。",
        "policy_type": PolicyType.RATE_LIMIT.value,
        "target_scope": {},
        "conditions": {"field": "rate_count", "op": "gte", "value": 12},
        "action": DecisionAction.WARN.value,
        "priority": 640,
        "emergency": False,
    },
    {
        "policy_key": "gov-rate-ads-08",
        "name": "限流-广告高频",
        "description": "消息数 >= 8 且命中广告类别时标记观察。",
        "policy_type": PolicyType.COMPOSITE.value,
        "target_scope": {},
        "conditions": {
            "all": [
                {"field": "rate_count", "op": "gte", "value": 8},
                {"field": "category", "op": "in", "value": ["spam"]},
            ]
        },
        "action": DecisionAction.FLAG.value,
        "priority": 630,
        "emergency": False,
    },
    {
        "policy_key": "gov-player-blacklist",
        "name": "玩家-黑名单处置",
        "description": "指定高风险模拟玩家直接进入审核。",
        "policy_type": PolicyType.PLAYER.value,
        "target_scope": {},
        "conditions": {
            "field": "sender_ref",
            "op": "in",
            "value": [
                "synthetic-player-00042",
                "synthetic-player-00108",
                "synthetic-player-00256",
            ],
        },
        "action": DecisionAction.REVIEW.value,
        "priority": 620,
        "emergency": False,
    },
    {
        "policy_key": "gov-player-repeat-offender",
        "name": "玩家-累犯从严",
        "description": "高风险等级且属于观察名单玩家时禁言。",
        "policy_type": PolicyType.PLAYER.value,
        "target_scope": {},
        "conditions": {
            "all": [
                {"field": "sender_ref", "op": "in", "value": ["synthetic-player-00777"]},
                {"field": "risk_level", "op": "in", "value": ["high", "critical"]},
            ]
        },
        "action": DecisionAction.MUTE.value,
        "priority": 625,
        "emergency": False,
    },
    {
        "policy_key": "gov-server-s1-strict",
        "name": "服务器-1 区严格策略",
        "description": "1 区执行更严格的审核阈值。",
        "policy_type": PolicyType.SERVER.value,
        "target_scope": {"servers": ["synthetic-server-1"]},
        "conditions": {
            "all": [
                {"field": "server_ref", "op": "eq", "value": "synthetic-server-1"},
                {"field": "risk_score", "op": "gte", "value": 0.5},
            ]
        },
        "action": DecisionAction.REVIEW.value,
        "priority": 600,
        "emergency": False,
    },
    {
        "policy_key": "gov-server-s2-warn",
        "name": "服务器-2 区警告策略",
        "description": "2 区中低风险统一给出警告。",
        "policy_type": PolicyType.SERVER.value,
        "target_scope": {"servers": ["synthetic-server-2"]},
        "conditions": {
            "all": [
                {"field": "server_ref", "op": "eq", "value": "synthetic-server-2"},
                {"field": "risk_level", "op": "eq", "value": RiskSeverity.MEDIUM.value},
            ]
        },
        "action": DecisionAction.WARN.value,
        "priority": 590,
        "emergency": False,
    },
    {
        "policy_key": "gov-server-s3-newcomer",
        "name": "服务器-3 区新手保护",
        "description": "3 区低风险内容走观察而非处置。",
        "policy_type": PolicyType.SERVER.value,
        "target_scope": {"servers": ["synthetic-server-3"]},
        "conditions": {
            "all": [
                {"field": "server_ref", "op": "eq", "value": "synthetic-server-3"},
                {"field": "risk_level", "op": "eq", "value": RiskSeverity.LOW.value},
            ]
        },
        "action": DecisionAction.FLAG.value,
        "priority": 585,
        "emergency": False,
    },
    {
        "policy_key": "gov-alliance-top-spam",
        "name": "联盟-头部联盟广告治理",
        "description": "头部联盟内广告内容提高处置等级。",
        "policy_type": PolicyType.ALLIANCE.value,
        "target_scope": {},
        "conditions": {
            "all": [
                {"field": "alliance_id", "op": "in", "value": ["1", "2", "3", "4", "5"]},
                {"field": "category", "op": "in", "value": ["spam"]},
            ]
        },
        "action": DecisionAction.FLAG.value,
        "priority": 575,
        "emergency": False,
    },
    {
        "policy_key": "gov-whitelist-verified",
        "name": "白名单-认证玩家豁免",
        "description": "认证玩家在低风险范围内豁免处置（高风险与极高风险不豁免）。",
        "policy_type": PolicyType.WHITELIST.value,
        "target_scope": {"players": ["synthetic-player-00001", "synthetic-player-00002"]},
        "conditions": {
            "all": [
                {
                    "field": "sender_ref",
                    "op": "in",
                    "value": ["synthetic-player-00001", "synthetic-player-00002"],
                },
                {"field": "risk_score", "op": "lt", "value": 0.5},
            ]
        },
        "action": DecisionAction.ALLOW.value,
        "priority": 570,
        "emergency": False,
    },
    {
        "policy_key": "gov-whitelist-official",
        "name": "白名单-官方账号",
        "description": "官方公告账号在低风险范围内豁免处置。",
        "policy_type": PolicyType.WHITELIST.value,
        "target_scope": {"players": ["synthetic-player-00003"]},
        "conditions": {
            "all": [
                {"field": "sender_ref", "op": "eq", "value": "synthetic-player-00003"},
                {"field": "risk_score", "op": "lt", "value": 0.6},
            ]
        },
        "action": DecisionAction.ALLOW.value,
        "priority": 565,
        "emergency": False,
    },
    {
        "policy_key": "gov-blacklist-pattern",
        "name": "黑名单-已知作弊话术",
        "description": "消息包含已知作弊话术指纹时拦截。",
        "policy_type": PolicyType.BLACKLIST.value,
        "target_scope": {},
        "conditions": {
            "field": "content",
            "op": "contains",
            "value": ["内部渠道出金", "包解封", "技术代打保证"],
        },
        "action": DecisionAction.BLOCK.value,
        "priority": 760,
        "emergency": False,
    },
    {
        "policy_key": "gov-blacklist-phishing",
        "name": "黑名单-钓鱼话术",
        "description": "消息包含钓鱼诱导话术时进入审核。",
        "policy_type": PolicyType.BLACKLIST.value,
        "target_scope": {},
        "conditions": {
            "field": "content",
            "op": "contains",
            "value": ["点击链接领取", "官方补偿链接", "验证码发送给我"],
        },
        "action": DecisionAction.REVIEW.value,
        "priority": 755,
        "emergency": False,
    },
    {
        "policy_key": "gov-composite-scam-lowconf",
        "name": "组合-低置信诈骗转审核",
        "description": "诈骗类别在置信度不足时不自动处置，转人工审核。",
        "policy_type": PolicyType.COMPOSITE.value,
        "target_scope": {},
        "conditions": {
            "all": [
                {"field": "category", "op": "in", "value": ["fraud"]},
                {"field": "confidence", "op": "lt", "value": 0.6},
            ]
        },
        "action": DecisionAction.REVIEW.value,
        "priority": 745,
        "emergency": False,
    },
    {
        "policy_key": "gov-composite-world-channel",
        "name": "组合-世界频道从严",
        "description": "世界频道内中风险以上内容进入审核。",
        "policy_type": PolicyType.COMPOSITE.value,
        "target_scope": {"channels": ["world"]},
        "conditions": {
            "all": [
                {"field": "channel", "op": "eq", "value": "world"},
                {"field": "risk_score", "op": "gte", "value": 0.6},
            ]
        },
        "action": DecisionAction.REVIEW.value,
        "priority": 735,
        "emergency": False,
    },
    {
        "policy_key": "gov-composite-long-spam",
        "name": "组合-长文本广告",
        "description": "长文本且命中广告类别时拦截。",
        "policy_type": PolicyType.COMPOSITE.value,
        "target_scope": {},
        "conditions": {
            "all": [
                {"field": "content_length", "op": "gte", "value": 120},
                {"field": "category", "op": "in", "value": ["spam"]},
            ]
        },
        "action": DecisionAction.BLOCK.value,
        "priority": 725,
        "emergency": False,
    },
    {
        "policy_key": "gov-low-risk-observe",
        "name": "低风险-观察",
        "description": "低风险等级内容标记观察。",
        "policy_type": PolicyType.COMPOSITE.value,
        "target_scope": {},
        "conditions": {"field": "risk_level", "op": "eq", "value": RiskSeverity.LOW.value},
        "action": DecisionAction.FLAG.value,
        "priority": 400,
        "emergency": False,
    },
    {
        "policy_key": "gov-normal-allow",
        "name": "正常内容-放行",
        "description": "normal 风险等级内容直接放行。",
        "policy_type": PolicyType.COMPOSITE.value,
        "target_scope": {},
        "conditions": {"field": "risk_level", "op": "eq", "value": RiskSeverity.NORMAL.value},
        "action": DecisionAction.ALLOW.value,
        "priority": 300,
        "emergency": False,
    },
)


def seed_governance_policies(
    policy_service: PolicyService,
    *,
    actor_ref: str = "governance-seed",
    change_reason: str = "seed governance policy catalog",
) -> dict[str, Any]:
    """Create the default policy and the governance catalog if they are missing.

    Existing policies are never overwritten: seeding is idempotent and only adds
    policies whose ``policy_key`` is not already present.
    """
    default = policy_service.ensure_default_policy()
    existing = {item["policy_key"] for item in policy_service.list_policies()}
    created: list[str] = []
    skipped: list[str] = []
    effective_until = datetime.now(UTC) + timedelta(days=365)
    for definition in SEED_POLICIES:
        key = str(definition["policy_key"])
        if key in existing:
            skipped.append(key)
            continue
        policy_service.create_policy(
            policy_key=key,
            name=str(definition["name"]),
            description=str(definition["description"]),
            policy_type=str(definition["policy_type"]),
            target_scope=dict(definition["target_scope"]),
            conditions=dict(definition["conditions"]),
            action=str(definition["action"]),
            priority=int(definition["priority"]),
            emergency=bool(definition.get("emergency", False)),
            effective_from=datetime.now(UTC),
            effective_until=effective_until,
            created_by=actor_ref,
            change_reason=change_reason,
        )
        created.append(key)
    return {
        "default_policy_key": default["policy_key"],
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "total_catalog": len(SEED_POLICIES),
    }
