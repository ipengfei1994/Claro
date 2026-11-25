from enum import StrEnum


class MessageStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    DECIDED = "decided"
    CLOSED = "closed"


class ProcessingStage(StrEnum):
    INGESTION = "ingestion"
    PREPROCESSING = "preprocessing"
    DETECTION = "detection"
    POLICY = "policy"
    MODERATION = "moderation"
    ENFORCEMENT = "enforcement"
    ANALYTICS = "analytics"


class ProcessingStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class RuleType(StrEnum):
    KEYWORD = "keyword"
    REGEX = "regex"
    URL_PATTERN = "url_pattern"
    BLACKLIST = "blacklist"
    REPETITION = "repetition"


class RuleStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"


class RiskCategory(StrEnum):
    HARASSMENT = "harassment"
    HATE_SPEECH = "hate_speech"
    SEXUAL_CONTENT = "sexual_content"
    VIOLENCE = "violence"
    FRAUD = "fraud"
    SPAM = "spam"
    SELF_HARM = "self_harm"
    OTHER = "other"


class DecisionAction(StrEnum):
    ALLOW = "allow"
    WARN = "warn"
    FLAG = "flag"
    REVIEW = "review"
    BLOCK = "block"
    MUTE = "mute"
    TEMP_BAN = "temp_ban"
    PERM_BAN = "perm_ban"
    RESTRICT = "restrict"


class DatasetSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
    HOLDOUT = "holdout"


class GroundTruthLabel(StrEnum):
    NORMAL = "normal"
    BOUNDARY = "boundary"
    RISK = "risk"


class RiskSeverity(StrEnum):
    NORMAL = "normal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CaseStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    PENDING = "pending"
    APPROVED = "approved"
    ESCALATED = "escalated"
    SECOND_REVIEW = "second_review"
    FINALIZED = "finalized"


class EnforcementStatus(StrEnum):
    PENDING = "pending"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RELEASED = "released"
    EXPIRED = "expired"


class PolicyType(StrEnum):
    KEYWORD = "keyword"
    REGEX = "regex"
    RISK_THRESHOLD = "risk_threshold"
    CATEGORY = "category"
    PLAYER = "player"
    SERVER = "server"
    ALLIANCE = "alliance"
    WHITELIST = "whitelist"
    BLACKLIST = "blacklist"
    RATE_LIMIT = "rate_limit"
    COMPOSITE = "composite"


class PolicyTargetScope(StrEnum):
    GLOBAL = "global"
    SERVER = "server"
    ALLIANCE = "alliance"
    PLAYER = "player"


class GovernanceDecisionStatus(StrEnum):
    AUTO_DECIDED = "auto_decided"
    PENDING_REVIEW = "pending_review"
    HUMAN_REVIEWED = "human_reviewed"
    OVERRIDDEN = "overridden"
    CANCELLED = "cancelled"


class ModerationAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    OVERRIDE = "override"
    ESCALATE = "escalate"
    REQUEST_SECOND_REVIEW = "request_second_review"
    REOPEN = "reopen"


class EnforcementTargetType(StrEnum):
    MESSAGE = "message"
    PLAYER = "player"
    PLAYER_SERVER = "player_server"


class FeedbackType(StrEnum):
    CORRECT = "correct"
    FALSE_POSITIVE = "false_positive"
    FALSE_NEGATIVE = "false_negative"
    CATEGORY_ERROR = "category_error"
    LEVEL_ERROR = "level_error"
    ACTION_INAPPROPRIATE = "action_inappropriate"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    OTHER = "other"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"


class MessageDisplayStatus(StrEnum):
    VISIBLE = "visible"
    BLOCKED = "blocked"
