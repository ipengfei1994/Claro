"""Deterministic demonstration scenarios for the Claro platform.

The demo is intentionally small: seven messages that exercise every detection
outcome the current rule + ML stack can produce, followed by governance actions
that the bulk Phase 02 dataset cannot show (review, override, enforcement,
release, feedback, replay).

Design rules:

* fixed seed and fixed UUIDv5 identifiers, so re-running produces the same ids;
* every record carries the ``phase-06-demo`` dataset, so it can be removed
  without touching the 50,000-message evaluation dataset;
* the text is authored to hit specific rules; the expected outcome recorded here
  was verified by running the detectors, not assumed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL as UUID_NAMESPACE
from uuid import UUID, uuid5

DEMO_DATASET_NAME = "phase-06-demo-s20261125"
DEMO_SEED = 20261125
DEMO_PREFIX = "demo06"
# Fixed anchor for scenario timestamps: keeps hashes stable across runs.
DEMO_ANCHOR = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def demo_uuid(kind: str, key: str) -> UUID:
    """Return a stable UUID for a demo object."""
    return uuid5(UUID_NAMESPACE, f"claro:demo:{kind}:{key}")


@dataclass(frozen=True, slots=True)
class DemoScenario:
    key: str
    order: int
    title: str
    channel: str
    player_ref: str
    server_ref: str
    content: str
    expected: str
    covers: str

    @property
    def message_id(self) -> UUID:
        return demo_uuid("message", self.key)

    @property
    def external_message_id(self) -> str:
        return f"{DEMO_PREFIX}-{self.order:02d}-{self.key}"

    @property
    def trace_id(self) -> str:
        return f"{DEMO_PREFIX}-trace-{self.order:02d}"


# Expected outcomes recorded from a detector run at the time of authoring.
SCENARIOS: tuple[DemoScenario, ...] = (
    DemoScenario(
        key="normal-coordination",
        order=1,
        title="正常联盟协作消息",
        channel="alliance",
        player_ref="demo-player-01",
        server_ref="server-1",
        content="今晚八点联盟集合，先把北门资源点拿下来，注意补兵。",
        expected="allow / auto_decided",
        covers="正常消息不产生风险，直接放行",
    ),
    DemoScenario(
        key="advertising-spam",
        order=2,
        title="代练广告刷屏",
        channel="world",
        player_ref="demo-player-02",
        server_ref="server-2",
        content="限时广告：代练套餐五折优惠出售，立即点击下单秒发货。",
        expected="high / block",
        covers="广告垃圾（规则 + ML 双命中）",
    ),
    DemoScenario(
        key="external-diversion",
        order=3,
        title="外部社群导流",
        channel="world",
        player_ref="demo-player-03",
        server_ref="server-3",
        content="想玩得更爽？加群 8899001 外部社群，群号每天更新。",
        expected="low / warn",
        covers="外部导流（低风险观察）",
    ),
    DemoScenario(
        key="fraud-reward",
        order=4,
        title="虚假福利诈骗",
        channel="world",
        player_ref="demo-player-04",
        server_ref="server-1",
        content="免费领取金币福利码，加微信 vx888999 领取奖励。",
        expected="medium / review",
        covers="诈骗风险，进入人工审核",
    ),
    DemoScenario(
        key="harassment-abuse",
        order=5,
        title="人身辱骂",
        channel="world",
        player_ref="demo-player-05",
        server_ref="server-2",
        content="你就是个废物，闭嘴吧，别在这里丢人。",
        expected="high / block",
        covers="骚扰辱骂（规则 + ML 双命中）",
    ),
    DemoScenario(
        key="self-harm-signal",
        order=6,
        title="自伤风险信号",
        channel="private",
        player_ref="demo-player-06",
        server_ref="server-3",
        content="真的不想活了，想结束一切。",
        expected="critical / restrict",
        covers="最高等级风险与限制动作",
    ),
    DemoScenario(
        key="multi-signal-trade",
        order=7,
        title="多类别叠加的违规交易",
        channel="world",
        player_ref="demo-player-07",
        server_ref="server-1",
        content="低价出售金币，走外部渠道，绕过官方，先付款后发货。",
        expected="medium / review",
        covers="多类别命中与策略冲突",
    ),
)

SCENARIO_BY_KEY = {item.key: item for item in SCENARIOS}


def scenario_payloads(*, dataset_id: UUID, base_time: datetime | None = None) -> list[dict]:
    """Return raw payload dictionaries ready for ``RawGameMessagePayload``.

    Content hashes are computed from the scenario text so the model's integrity
    validator accepts them.

    Timestamps step one minute per scenario so the demo has a deterministic,
    readable ordering independent of the wall clock time of the run.
    """
    # A fixed anchor keeps message ids, timestamps and hashes identical across
    # runs, which is what makes the demo idempotent and reproducible.
    anchor = base_time or DEMO_ANCHOR
    return [
        {
            "synthetic": True,
            "dataset_id": dataset_id,
            "dataset_name": DEMO_DATASET_NAME,
            "dataset_seed": DEMO_SEED,
            "message_id": item.message_id,
            "external_message_id": item.external_message_id,
            "trace_id": item.trace_id,
            "player_ref": item.player_ref,
            "server_ref": item.server_ref,
            "alliance_ref": None,
            "channel": item.channel,
            "content": item.content,
            "content_hash": hashlib.sha256(item.content.encode("utf-8")).hexdigest(),
            "language": "zh-CN",
            "occurred_at": anchor - timedelta(minutes=len(SCENARIOS) - item.order),
        }
        for item in SCENARIOS
    ]


def scenario_table() -> list[dict[str, str]]:
    """Human-readable scenario list used by the CLI and the Settings page."""
    return [
        {
            "order": str(item.order),
            "key": item.key,
            "title": item.title,
            "expected": item.expected,
            "covers": item.covers,
        }
        for item in SCENARIOS
    ]
