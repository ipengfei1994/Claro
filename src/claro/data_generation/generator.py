from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from claro.domain.enums import (
    DatasetSplit,
    DecisionAction,
    GroundTruthLabel,
    RiskCategory,
    RiskSeverity,
    RuleStatus,
    RuleType,
)

SYNTHETIC_NOTICE = "All records are synthetic and generated for local verification."
RISK_CATEGORIES = tuple(category.value for category in RiskCategory)
CATEGORY_WEIGHTS = (0.27, 0.06, 0.05, 0.11, 0.19, 0.21, 0.03, 0.08)
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "harassment": ("垃圾", "闭嘴", "嘲讽"),
    "hate_speech": ("驱逐", "劣等", "仇恨"),
    "sexual_content": ("色情", "裸聊", "成人资源"),
    "violence": ("堵他", "动手", "威胁"),
    "fraud": ("领取金币", "免费代充", "充值优惠"),
    "spam": ("限时广告", "重复刷屏", "推广链接"),
    "self_harm": ("不想活", "结束一切", "伤害自己"),
    "other": ("违规交易", "外挂", "账号共享"),
}
NORMAL_TEMPLATES = (
    "Synthetic: 今晚八点公会战，请大家提前集合。",
    "Synthetic: 感谢盟主今天的资源支援，已完成城防建设。",
    "Synthetic: 新版本更新后，步兵阵容应该如何搭配？",
    "Synthetic: 副本通关奖励已领取，欢迎组队挑战下一层。",
    "Synthetic: 低价收集中级材料，价格合理再谈。",
    "Synthetic: 服务器维护期间无法登录，请稍后再试。",
    "Synthetic: 恭喜 {alliance} 赢得本周联盟排名。",
    "Synthetic: 有人在 {server} 看到稀有刷新点吗？",
    "Synthetic: 我已提交战报，指挥今晚复盘。",
    "Synthetic: 萌新求一份新手任务流程，谢谢。",
    "Synthetic: 城墙耐久不足，请求联盟成员增援。",
    "Synthetic: 这次活动奖励不错，但体力消耗有点高。",
)
BOUNDARY_TEMPLATES: dict[str, tuple[str, ...]] = {
    "harassment": (
        "Synthetic: 你这操作真让人无语，建议再看一遍教程。",
        "Synthetic: 队友连续失误，能不能认真一点？",
    ),
    "hate_speech": (
        "Synthetic: 游戏里讨论历史冲突时请注意措辞。",
        "Synthetic: 如何区分正常争论与群体仇恨言论？",
    ),
    "sexual_content": (
        "Synthetic: 请举报带有成人暗示的头像和简介。",
        "Synthetic: 这段剧情台词是否属于成人内容？",
    ),
    "violence": (
        "Synthetic: 游戏里击败对手和现实威胁有什么区别？",
        "Synthetic: 举报：有人在世界频道发表暴力威胁。",
    ),
    "fraud": (
        "Synthetic: 有人发布领取金币链接，请勿相信。",
        "Synthetic: 官方充值优惠公告在哪里查看？",
    ),
    "spam": (
        "Synthetic: 公会招募信息每天最多可以发送几次？",
        "Synthetic: 这段重复广告是否应该被折叠？",
    ),
    "self_harm": (
        "Synthetic: 看到令人沮丧的游戏消息时应该如何寻求帮助？",
        "Synthetic: 请把这条情绪求助消息转给安全管理员。",
    ),
    "other": (
        "Synthetic: 玩家之间交换账号是否违反服务器规则？",
        "Synthetic: 外挂举报需要提供哪些证据？",
    ),
}
RISK_TEMPLATES: dict[str, tuple[str, ...]] = {
    "harassment": (
        "Synthetic: 你个废物，闭嘴别再来丢人。",
        "Synthetic: 我要连续嘲讽你，直到你退出游戏。",
    ),
    "hate_speech": (
        "Synthetic: 某个群体都该被驱逐，不配留在服务器。",
        "Synthetic: 针对某群体的仇恨口号再次出现。",
    ),
    "sexual_content": (
        "Synthetic: 私聊发送色情资源，点击 [synthetic-link] 获取。",
        "Synthetic: 出售成人内容访问权限，价格私聊。",
    ),
    "violence": (
        "Synthetic: 我要去堵住他并动手，让他后悔。",
        "Synthetic: 不答应条件，我就威胁你的人身安全。",
    ),
    "fraud": (
        "Synthetic: 点击 [synthetic-link] 领取游戏金币。",
        "Synthetic: 免费代充，限时优惠，先付款后发货。",
    ),
    "spam": (
        "Synthetic: 限时广告！限时广告！重复刷屏推广链接。",
        "Synthetic: 立即点击 [synthetic-link]，错过今天再等一年。",
    ),
    "self_harm": (
        "Synthetic: 我不想活了，今天就想结束一切。",
        "Synthetic: 我准备伤害自己，你们不要拦我。",
    ),
    "other": (
        "Synthetic: 出售外挂和共享账号，违规交易私聊。",
        "Synthetic: 低价出售高等级账号，绕过官方交易。",
    ),
}
PROFILE_WEIGHTS = (
    ("typical", 0.58),
    ("new_player", 0.16),
    ("competitive", 0.14),
    ("merchant", 0.08),
    ("repeat_offender", 0.04),
)
HOUR_WEIGHTS = (
    0.35,
    0.22,
    0.12,
    0.08,
    0.07,
    0.09,
    0.25,
    0.55,
    0.95,
    1.05,
    1.0,
    1.2,
    1.4,
    1.15,
    1.05,
    1.25,
    1.55,
    1.95,
    2.2,
    2.0,
    1.6,
    1.15,
    0.75,
    0.45,
)
CHANNEL_WEIGHTS = (
    ("world", 0.44),
    ("alliance", 0.25),
    ("private", 0.16),
    ("guild", 0.1),
    ("system", 0.05),
)


@dataclass(frozen=True, slots=True)
class GenerationSpec:
    seed: int = 20261125
    players: int = 5000
    servers: int = 10
    alliances: int = 500
    messages: int = 50_000
    policy_rules: int = 40
    start_time: datetime = datetime(2026, 1, 1, tzinfo=UTC)
    days: int = 31
    name: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("players", "servers", "alliances", "messages", "policy_rules", "days"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.alliances < self.servers:
            raise ValueError("alliances must be at least the number of servers")
        if not 0 <= self.seed <= 2**31 - 1:
            raise ValueError("seed must be between 0 and 2147483647")
        if self.start_time.tzinfo is None:
            raise ValueError("start_time must include a timezone")
        if self.name is not None and not self.name.strip():
            raise ValueError("name must not be empty")

    @property
    def dataset_name(self) -> str:
        if self.name:
            return self.name
        return f"phase-02-synthetic-s{self.seed}-p{self.players}-m{self.messages}"

    @property
    def namespace(self) -> UUID:
        return uuid5(NAMESPACE_URL, f"claro:phase-02:{self.dataset_name}")

    def stable_id(self, label: str) -> UUID:
        return uuid5(self.namespace, label)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start_time"] = self.start_time.isoformat()
        payload["dataset_name"] = self.dataset_name
        payload["notice"] = SYNTHETIC_NOTICE
        return payload


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    id: UUID
    name: str
    seed: int
    generation_params: dict[str, Any]
    is_synthetic: bool = True


@dataclass(frozen=True, slots=True)
class ServerRecord:
    id: UUID
    dataset_id: UUID
    server_ref: str
    name: str
    region: str
    is_synthetic: bool = True


@dataclass(frozen=True, slots=True)
class AllianceRecord:
    id: UUID
    dataset_id: UUID
    server_id: UUID
    server_ref: str
    alliance_ref: str
    name: str
    is_synthetic: bool = True


@dataclass(frozen=True, slots=True)
class PlayerRecord:
    id: UUID
    dataset_id: UUID
    player_ref: str
    display_name: str
    server_id: UUID
    server_ref: str
    alliance_id: UUID | None
    alliance_ref: str | None
    behavior_profile: str
    risk_propensity: float
    activity_factor: float
    chattiness: float
    account_created_at: datetime
    is_synthetic: bool = True


@dataclass(frozen=True, slots=True)
class PolicyRecord:
    id: UUID
    dataset_id: UUID
    policy_key: str
    version: int
    definition: dict[str, Any]
    status: str
    effective_from: datetime
    is_synthetic: bool = True


@dataclass(frozen=True, slots=True)
class PolicyRuleRecord:
    id: UUID
    dataset_id: UUID
    policy_id: UUID
    detection_rule_id: UUID
    rule_key: str
    category: str
    rule_type: str
    priority: int
    threshold: float
    action: str
    definition: dict[str, Any]
    status: str
    effective_from: datetime
    is_synthetic: bool = True


@dataclass(frozen=True, slots=True)
class GameMessageRecord:
    id: UUID
    dataset_id: UUID
    dataset_name: str
    dataset_seed: int
    external_message_id: str
    trace_id: str
    player_id: UUID
    player_ref: str
    server_id: UUID
    server_ref: str
    alliance_id: UUID | None
    alliance_ref: str | None
    channel: str
    content: str
    content_hash: str
    language: str
    occurred_at: datetime
    is_synthetic: bool = True

    def raw_payload(self) -> dict[str, Any]:
        return {
            "synthetic": self.is_synthetic,
            "dataset_id": str(self.dataset_id),
            "dataset_name": self.dataset_name,
            "dataset_seed": self.dataset_seed,
            "message_id": str(self.id),
            "external_message_id": self.external_message_id,
            "trace_id": self.trace_id,
            "player_ref": self.player_ref,
            "server_ref": self.server_ref,
            "alliance_ref": self.alliance_ref,
            "channel": self.channel,
            "content": self.content,
            "content_hash": self.content_hash,
            "language": self.language,
            "occurred_at": self.occurred_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class MessageLabelRecord:
    id: UUID
    dataset_id: UUID
    message_id: UUID
    label: str
    risk_category: str | None
    split: str
    annotator_type: str
    annotator_ref: str
    confidence: float
    rationale: str
    labeled_at: datetime
    is_synthetic: bool = True


@dataclass(frozen=True, slots=True)
class RiskEventRecord:
    id: UUID
    dataset_id: UUID
    message_id: UUID
    rule_id: UUID
    category: str
    event_type: str
    risk_score: float
    confidence: float
    severity: str
    occurred_at: datetime
    details: dict[str, Any]
    is_synthetic: bool = True


@dataclass(frozen=True, slots=True)
class PolicyDecisionRecord:
    id: UUID
    dataset_id: UUID
    message_id: UUID
    policy_id: UUID
    action: str
    risk_score: float
    reason_codes: tuple[str, ...]
    decided_at: datetime
    is_synthetic: bool = True


@dataclass(frozen=True, slots=True)
class ModerationRecord:
    id: UUID
    dataset_id: UUID
    message_id: UUID
    action: str
    actor_type: str
    actor_ref: str
    risk_score: float
    reason_codes: tuple[str, ...]
    note: str
    occurred_at: datetime
    is_synthetic: bool = True


@dataclass(frozen=True, slots=True)
class GeneratedDataset:
    spec: GenerationSpec
    dataset: DatasetRecord
    servers: list[ServerRecord]
    alliances: list[AllianceRecord]
    players: list[PlayerRecord]
    policies: list[PolicyRecord]
    policy_rules: list[PolicyRuleRecord]
    messages: list[GameMessageRecord]
    labels: list[MessageLabelRecord]
    risk_events: list[RiskEventRecord]
    policy_decisions: list[PolicyDecisionRecord]
    moderation_records: list[ModerationRecord]

    def summary(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset.name,
            "seed": self.spec.seed,
            "synthetic": True,
            "notice": SYNTHETIC_NOTICE,
            "counts": {
                "players": len(self.players),
                "servers": len(self.servers),
                "alliances": len(self.alliances),
                "messages": len(self.messages),
                "message_labels": len(self.labels),
                "risk_events": len(self.risk_events),
                "policy_decisions": len(self.policy_decisions),
                "moderation_records": len(self.moderation_records),
                "policies": len(self.policies),
                "policy_rules": len(self.policy_rules),
            },
            "label_distribution": dict(sorted(Counter(item.label for item in self.labels).items())),
            "risk_category_distribution": dict(
                sorted(Counter(item.category for item in self.risk_events).items())
            ),
            "split_distribution": dict(sorted(Counter(item.split for item in self.labels).items())),
            "channel_distribution": dict(
                sorted(Counter(item.channel for item in self.messages).items())
            ),
            "moderation_action_distribution": dict(
                sorted(Counter(item.action for item in self.moderation_records).items())
            ),
            "fingerprint": self.fingerprint(),
        }

    def fingerprint(self) -> str:
        payload = {
            "spec": self.spec.to_dict(),
            "servers": [(item.server_ref, item.name, item.region) for item in self.servers],
            "alliances": [
                (item.alliance_ref, item.server_ref, item.name) for item in self.alliances
            ],
            "players": [
                (
                    item.player_ref,
                    item.server_ref,
                    item.alliance_ref,
                    item.behavior_profile,
                    item.risk_propensity,
                    item.activity_factor,
                    item.chattiness,
                )
                for item in self.players
            ],
            "policies": [(item.policy_key, item.definition, item.status) for item in self.policies],
            "policy_rules": [
                (item.rule_key, item.category, item.rule_type, item.threshold, item.action)
                for item in self.policy_rules
            ],
            "messages": [
                (
                    item.external_message_id,
                    item.player_ref,
                    item.server_ref,
                    item.alliance_ref,
                    item.channel,
                    item.content,
                    item.occurred_at.isoformat(),
                )
                for item in self.messages
            ],
            "labels": [
                (str(item.message_id), item.label, item.risk_category, item.split)
                for item in self.labels
            ],
            "risk_events": [
                (str(item.message_id), item.category, item.risk_score, item.severity)
                for item in self.risk_events
            ],
            "policy_decisions": [
                (str(item.message_id), item.action, item.risk_score, item.reason_codes)
                for item in self.policy_decisions
            ],
            "moderation_records": [
                (str(item.message_id), item.action, item.actor_type, item.reason_codes)
                for item in self.moderation_records
            ],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
        return hashlib.sha256(encoded).hexdigest()

    def validate(self) -> None:
        expected = {
            "servers": self.spec.servers,
            "alliances": self.spec.alliances,
            "players": self.spec.players,
            "messages": self.spec.messages,
            "message_labels": self.spec.messages,
            "policy_decisions": self.spec.messages,
            "policy_rules": self.spec.policy_rules,
        }
        actual = {
            "servers": len(self.servers),
            "alliances": len(self.alliances),
            "players": len(self.players),
            "messages": len(self.messages),
            "message_labels": len(self.labels),
            "policy_decisions": len(self.policy_decisions),
            "policy_rules": len(self.policy_rules),
        }
        if actual != expected:
            raise ValueError(
                f"generated counts do not match spec: expected {expected}, got {actual}"
            )

        server_ids = {item.id for item in self.servers}
        alliance_by_id = {item.id: item for item in self.alliances}
        player_by_id = {item.id: item for item in self.players}
        message_by_id = {item.id: item for item in self.messages}
        message_ids = set(message_by_id)
        policy_ids = {item.id for item in self.policies}
        detection_rule_ids = {item.detection_rule_id for item in self.policy_rules}
        if len(server_ids) != len(self.servers) or len(alliance_by_id) != len(self.alliances):
            raise ValueError("duplicate server or alliance id")
        if len(player_by_id) != len(self.players) or len(message_ids) != len(self.messages):
            raise ValueError("duplicate player or message id")
        if len({item.external_message_id for item in self.messages}) != len(self.messages):
            raise ValueError("duplicate external message id")
        if not self.dataset.is_synthetic:
            raise ValueError("dataset must be synthetic")

        for alliance in self.alliances:
            if alliance.server_id not in server_ids or not alliance.is_synthetic:
                raise ValueError("alliance has an invalid server or synthetic marker")
        for player in self.players:
            if player.server_id not in server_ids or not player.is_synthetic:
                raise ValueError("player has an invalid server or synthetic marker")
            if player.alliance_id is not None:
                alliance = alliance_by_id.get(player.alliance_id)
                if alliance is None or alliance.server_id != player.server_id:
                    raise ValueError("player alliance does not belong to the same server")
        for message in self.messages:
            player = player_by_id.get(message.player_id)
            if player is None or player.server_id != message.server_id or not message.is_synthetic:
                raise ValueError("message has an invalid player/server relationship")
            if message.alliance_id != player.alliance_id:
                raise ValueError("message alliance does not match its player")
        if any(item.message_id not in message_ids for item in self.labels):
            raise ValueError("message label references an unknown message")
        if any(item.message_id not in message_ids for item in self.risk_events):
            raise ValueError("risk event references an unknown message")
        if any(item.message_id not in message_ids for item in self.moderation_records):
            raise ValueError("moderation record references an unknown message")
        if any(item.message_id not in message_ids for item in self.policy_decisions):
            raise ValueError("policy decision references an unknown message")
        if any(item.policy_id not in policy_ids for item in self.policy_rules):
            raise ValueError("policy rule references an unknown policy")
        if any(item.rule_id not in detection_rule_ids for item in self.risk_events):
            raise ValueError("risk event references an unknown detection rule")

        player_splits: dict[UUID, str] = {}
        for label in self.labels:
            message = message_by_id[label.message_id]
            previous = player_splits.setdefault(message.player_id, label.split)
            if previous != label.split:
                raise ValueError("a player appears in more than one dataset split")
        if any(not item.is_synthetic for item in self.labels + self.risk_events):
            raise ValueError("labels and risk events must be synthetic")


def _weighted_choice(
    rng: random.Random, values: tuple[str, ...], weights: tuple[float, ...]
) -> str:
    return str(rng.choices(values, weights=weights, k=1)[0])


def _profile_parameters(profile: str, rng: random.Random) -> tuple[float, float, float]:
    distributions = {
        "typical": (1.4, 9.0),
        "new_player": (1.8, 10.0),
        "competitive": (2.8, 7.5),
        "merchant": (3.5, 7.0),
        "repeat_offender": (7.0, 3.0),
    }
    alpha, beta = distributions[profile]
    risk_propensity = min(0.95, rng.betavariate(alpha, beta))
    activity_factor = round(min(3.0, max(0.2, rng.lognormvariate(0.0, 0.55))), 4)
    chattiness = round(min(5.0, max(0.15, rng.lognormvariate(0.0, 0.7))), 4)
    return round(risk_propensity, 4), activity_factor, chattiness


def _split_for_player(player_ref: str) -> str:
    digest = hashlib.sha256(f"claro:split:{player_ref}".encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    if bucket < 70:
        return DatasetSplit.TRAIN.value
    if bucket < 80:
        return DatasetSplit.VALIDATION.value
    if bucket < 90:
        return DatasetSplit.TEST.value
    return DatasetSplit.HOLDOUT.value


def _message_time(rng: random.Random, spec: GenerationSpec) -> datetime:
    day_weights = [
        1.35 if (spec.start_time + timedelta(days=index)).weekday() >= 4 else 1.0
        for index in range(spec.days)
    ]
    day = rng.choices(range(spec.days), weights=day_weights, k=1)[0]
    hour = rng.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]
    return spec.start_time + timedelta(
        days=day,
        hours=hour,
        minutes=rng.randrange(60),
        seconds=rng.randrange(60),
    )


def _severity(score: float) -> str:
    if score >= 0.9:
        return RiskSeverity.CRITICAL.value
    if score >= 0.7:
        return RiskSeverity.HIGH.value
    if score >= 0.4:
        return RiskSeverity.MEDIUM.value
    return RiskSeverity.LOW.value


def _action_for_score(score: float) -> str:
    if score >= 0.9:
        return DecisionAction.BLOCK.value
    if score >= 0.7:
        return DecisionAction.REVIEW.value
    if score >= 0.4:
        return DecisionAction.WARN.value
    return DecisionAction.ALLOW.value


def _make_policy_rules(
    spec: GenerationSpec,
) -> tuple[list[PolicyRecord], list[PolicyRuleRecord], dict[str, PolicyRuleRecord]]:
    policy_keys = ("standard", "community", "commerce", "high-risk", "enforcement")
    policies = [
        PolicyRecord(
            id=spec.stable_id(f"policy-{key}"),
            dataset_id=spec.stable_id("dataset"),
            policy_key=f"{spec.dataset_name}-{key}-policy",
            version=1,
            definition={
                "synthetic": True,
                "default_action": "allow",
                "review_threshold": 0.7,
                "block_threshold": 0.9,
            },
            status=RuleStatus.ACTIVE.value,
            effective_from=spec.start_time,
        )
        for key in policy_keys
    ]
    thresholds = (0.35, 0.55, 0.75, 0.9, 0.97)
    actions = ("warn", "review", "block", "block", "restrict")
    rules: list[PolicyRuleRecord] = []
    for index in range(spec.policy_rules):
        category = RISK_CATEGORIES[index % len(RISK_CATEGORIES)]
        variant = index // len(RISK_CATEGORIES)
        rule_type = RuleType.KEYWORD.value if variant % 2 == 0 else RuleType.REGEX.value
        keywords = CATEGORY_KEYWORDS[category]
        pattern = "(?i)(" + "|".join(re.escape(term) for term in keywords) + ")"
        definition: dict[str, Any] = {
            "synthetic": True,
            "category": category,
            "keywords": list(keywords),
            "case_sensitive": False,
            "threshold": thresholds[variant],
            "action": actions[variant],
        }
        if rule_type == RuleType.REGEX.value:
            definition["pattern"] = pattern
        rules.append(
            PolicyRuleRecord(
                id=spec.stable_id(f"policy-rule-{index:03d}"),
                dataset_id=spec.stable_id("dataset"),
                policy_id=policies[index % len(policies)].id,
                detection_rule_id=spec.stable_id(f"detection-rule-{index:03d}"),
                rule_key=f"{spec.dataset_name}-{category}-v{variant + 1}",
                category=category,
                rule_type=rule_type,
                priority=variant + 1,
                threshold=thresholds[variant],
                action=actions[variant],
                definition=definition,
                status=RuleStatus.DRAFT.value
                if index > 0 and index % 11 == 0
                else RuleStatus.ACTIVE.value,
                effective_from=spec.start_time,
            )
        )
    active_by_category: dict[str, PolicyRuleRecord] = {}
    for category in RISK_CATEGORIES:
        matching = [rule for rule in rules if rule.category == category]
        if matching:
            active_by_category[category] = next(
                (rule for rule in matching if rule.status == RuleStatus.ACTIVE.value),
                matching[0],
            )
    return policies, rules, active_by_category


def generate_synthetic_dataset(spec: GenerationSpec | None = None) -> GeneratedDataset:
    resolved = spec or GenerationSpec()
    rng = random.Random(resolved.seed)
    dataset = DatasetRecord(
        id=resolved.stable_id("dataset"),
        name=resolved.dataset_name,
        seed=resolved.seed,
        generation_params=resolved.to_dict(),
    )
    regions = ("cn-east", "cn-south", "cn-north", "ap-southeast", "eu-west")
    servers = [
        ServerRecord(
            id=resolved.stable_id(f"server-{index:03d}"),
            dataset_id=dataset.id,
            server_ref=f"synthetic-server-{index + 1:03d}",
            name=f"Synthetic Server {index + 1:02d}",
            region=regions[index % len(regions)],
        )
        for index in range(resolved.servers)
    ]
    alliances = [
        AllianceRecord(
            id=resolved.stable_id(f"alliance-{index:04d}"),
            dataset_id=dataset.id,
            server_id=servers[index % resolved.servers].id,
            server_ref=servers[index % resolved.servers].server_ref,
            alliance_ref=f"synthetic-alliance-{index + 1:04d}",
            name=f"Synthetic Alliance {index + 1:04d}",
        )
        for index in range(resolved.alliances)
    ]
    alliances_by_server: dict[UUID, list[AllianceRecord]] = {server.id: [] for server in servers}
    for alliance in alliances:
        alliances_by_server[alliance.server_id].append(alliance)

    players: list[PlayerRecord] = []
    for index in range(resolved.players):
        server = servers[index % resolved.servers]
        alliance = rng.choice(alliances_by_server[server.id]) if rng.random() < 0.82 else None
        profile = _weighted_choice(
            rng,
            tuple(item[0] for item in PROFILE_WEIGHTS),
            tuple(item[1] for item in PROFILE_WEIGHTS),
        )
        risk_propensity, activity_factor, chattiness = _profile_parameters(profile, rng)
        player_ref = f"synthetic-player-{index + 1:05d}"
        players.append(
            PlayerRecord(
                id=resolved.stable_id(f"player-{index:05d}"),
                dataset_id=dataset.id,
                player_ref=player_ref,
                display_name=f"Synthetic Player {index + 1:05d}",
                server_id=server.id,
                server_ref=server.server_ref,
                alliance_id=alliance.id if alliance else None,
                alliance_ref=alliance.alliance_ref if alliance else None,
                behavior_profile=profile,
                risk_propensity=risk_propensity,
                activity_factor=activity_factor,
                chattiness=chattiness,
                account_created_at=resolved.start_time - timedelta(days=rng.randrange(30, 901)),
            )
        )

    policies, policy_rules, active_rules = _make_policy_rules(resolved)
    player_weights = [item.activity_factor * item.chattiness for item in players]
    selected_players = rng.choices(players, weights=player_weights, k=resolved.messages)
    dataset_token = hashlib.sha256(resolved.dataset_name.encode()).hexdigest()[:12]
    messages: list[GameMessageRecord] = []
    labels: list[MessageLabelRecord] = []
    risk_events: list[RiskEventRecord] = []
    policy_decisions: list[PolicyDecisionRecord] = []
    moderation_records: list[ModerationRecord] = []

    for index, player in enumerate(selected_players, start=1):
        risk_probability = min(0.7, 0.01 + player.risk_propensity * 0.55)
        boundary_probability = 0.1 + player.risk_propensity * 0.25
        draw = rng.random()
        if draw < risk_probability:
            label = GroundTruthLabel.RISK.value
        elif draw < risk_probability + boundary_probability:
            label = GroundTruthLabel.BOUNDARY.value
        else:
            label = GroundTruthLabel.NORMAL.value

        category = str(rng.choices(RISK_CATEGORIES, weights=CATEGORY_WEIGHTS, k=1)[0])
        if label == GroundTruthLabel.RISK.value:
            content = rng.choice(RISK_TEMPLATES[category])
            ground_truth_category: str | None = category
            confidence = round(rng.uniform(0.88, 0.99), 4)
            rationale = "Synthetic ground-truth risk example."
        elif label == GroundTruthLabel.BOUNDARY.value:
            content = rng.choice(BOUNDARY_TEMPLATES[category])
            ground_truth_category = None
            confidence = round(rng.uniform(0.65, 0.9), 4)
            rationale = "Synthetic context-dependent boundary example."
        else:
            content = rng.choice(NORMAL_TEMPLATES).format(
                alliance=player.alliance_ref or "Synthetic Alliance",
                server=player.server_ref,
            )
            ground_truth_category = None
            confidence = round(rng.uniform(0.9, 0.99), 4)
            rationale = "Synthetic normal gameplay example."

        occurred_at = _message_time(rng, resolved)
        message_id = resolved.stable_id(f"message-{index:07d}")
        trace_id = resolved.stable_id(f"trace-{index:07d}").hex
        channel = _weighted_choice(
            rng,
            tuple(item[0] for item in CHANNEL_WEIGHTS),
            tuple(item[1] for item in CHANNEL_WEIGHTS),
        )
        if channel in {"alliance", "guild"} and player.alliance_id is None:
            channel = "world"
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        messages.append(
            GameMessageRecord(
                id=message_id,
                dataset_id=dataset.id,
                dataset_name=dataset.name,
                dataset_seed=dataset.seed,
                external_message_id=(f"synthetic-{resolved.seed}-{dataset_token}-{index:07d}"),
                trace_id=trace_id,
                player_id=player.id,
                player_ref=player.player_ref,
                server_id=player.server_id,
                server_ref=player.server_ref,
                alliance_id=player.alliance_id,
                alliance_ref=player.alliance_ref,
                channel=channel,
                content=content,
                content_hash=content_hash,
                language="zh-CN",
                occurred_at=occurred_at,
            )
        )
        labels.append(
            MessageLabelRecord(
                id=resolved.stable_id(f"label-{index:07d}"),
                dataset_id=dataset.id,
                message_id=message_id,
                label=label,
                risk_category=ground_truth_category,
                split=_split_for_player(player.player_ref),
                annotator_type="synthetic_generator",
                annotator_ref="claro-phase-02",
                confidence=confidence,
                rationale=rationale,
                labeled_at=occurred_at + timedelta(minutes=5),
            )
        )

        should_emit_risk = (
            label == GroundTruthLabel.RISK.value
            or (label == GroundTruthLabel.BOUNDARY.value and rng.random() < 0.35)
            or (label == GroundTruthLabel.NORMAL.value and rng.random() < 0.01)
        )
        if not should_emit_risk:
            risk_score = round(rng.uniform(0.02, 0.2), 4)
            selected_rule = active_rules.get(category, active_rules[RISK_CATEGORIES[0]])
            policy_decisions.append(
                PolicyDecisionRecord(
                    id=resolved.stable_id(f"decision-{index:07d}"),
                    dataset_id=dataset.id,
                    message_id=message_id,
                    policy_id=selected_rule.policy_id,
                    action=DecisionAction.ALLOW.value,
                    risk_score=risk_score,
                    reason_codes=("synthetic_below_threshold",),
                    decided_at=occurred_at + timedelta(minutes=2),
                )
            )
            continue

        if label == GroundTruthLabel.RISK.value:
            risk_score = round(
                min(0.999, rng.uniform(0.55, 0.98) + player.risk_propensity * 0.02), 4
            )
        elif label == GroundTruthLabel.BOUNDARY.value:
            risk_score = round(rng.uniform(0.28, 0.72), 4)
        else:
            risk_score = round(rng.uniform(0.05, 0.35), 4)
        selected_rule = active_rules.get(category, active_rules[RISK_CATEGORIES[0]])
        risk_events.append(
            RiskEventRecord(
                id=resolved.stable_id(f"risk-event-{index:07d}"),
                dataset_id=dataset.id,
                message_id=message_id,
                rule_id=selected_rule.detection_rule_id,
                category=category,
                event_type="detected",
                risk_score=risk_score,
                confidence=round(rng.uniform(0.75, 0.99), 4),
                severity=_severity(risk_score),
                occurred_at=occurred_at + timedelta(seconds=30),
                details={
                    "synthetic": True,
                    "detector": "synthetic-rule-engine",
                    "detector_version": "1.0.0",
                    "matched_text": rng.choice(CATEGORY_KEYWORDS[category]),
                },
            )
        )
        action = _action_for_score(risk_score)
        reason_codes = (
            f"synthetic_{category}",
            f"synthetic_threshold_{action}",
        )
        policy_decisions.append(
            PolicyDecisionRecord(
                id=resolved.stable_id(f"decision-{index:07d}"),
                dataset_id=dataset.id,
                message_id=message_id,
                policy_id=selected_rule.policy_id,
                action=action,
                risk_score=risk_score,
                reason_codes=reason_codes,
                decided_at=occurred_at + timedelta(minutes=2),
            )
        )
        if action != DecisionAction.ALLOW.value:
            actor_type = "human" if rng.random() < 0.35 else "system"
            moderation_records.append(
                ModerationRecord(
                    id=resolved.stable_id(f"moderation-{index:07d}"),
                    dataset_id=dataset.id,
                    message_id=message_id,
                    action=action,
                    actor_type=actor_type,
                    actor_ref=f"synthetic-moderator-{index % 25:02d}",
                    risk_score=risk_score,
                    reason_codes=reason_codes,
                    note="Synthetic moderation record for local verification.",
                    occurred_at=occurred_at + timedelta(minutes=8),
                )
            )

    messages.sort(key=lambda item: (item.occurred_at, item.external_message_id))
    result = GeneratedDataset(
        spec=resolved,
        dataset=dataset,
        servers=servers,
        alliances=alliances,
        players=players,
        policies=policies,
        policy_rules=policy_rules,
        messages=messages,
        labels=labels,
        risk_events=risk_events,
        policy_decisions=policy_decisions,
        moderation_records=moderation_records,
    )
    result.validate()
    return result
