from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from claro.application.events import EventEnvelope
from claro.application.message_events import (
    RAW_GAME_MESSAGE_EVENT,
    MessageSerializationError,
    RawGameMessagePayload,
    decode_event,
    encode_event,
    parse_raw_game_message,
)


def _payload() -> dict[str, object]:
    content = "测试消息：今晚八点集结。"
    return {
        "synthetic": True,
        "dataset_id": str(uuid4()),
        "dataset_name": "phase-02-kafka-test",
        "dataset_seed": 20261125,
        "message_id": str(uuid4()),
        "external_message_id": "synthetic-0000001",
        "trace_id": uuid4().hex,
        "player_ref": "synthetic-player-1",
        "server_ref": "server-1",
        "alliance_ref": None,
        "channel": "world",
        "content": content,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "language": "zh-CN",
        "occurred_at": datetime(2026, 1, 1, 8, tzinfo=UTC).isoformat(),
    }


def test_raw_message_round_trip_preserves_send_time_and_identity() -> None:
    sent_at = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
    payload = RawGameMessagePayload.from_json_mapping(_payload())
    event = payload.to_event(sent_at=sent_at)

    decoded = decode_event(encode_event(event))
    parsed = parse_raw_game_message(decoded)

    assert decoded.event_id == payload.message_id
    assert decoded.occurred_at == sent_at
    assert parsed == payload
    assert parsed.synthetic is True


def test_raw_message_rejects_label_fields_and_hash_mismatch() -> None:
    leaked = _payload()
    leaked["ground_truth_label"] = "risk"
    with pytest.raises(MessageSerializationError, match="extra_forbidden"):
        RawGameMessagePayload.from_json_mapping(leaked)

    corrupted = _payload()
    corrupted["content"] = "内容被篡改"
    with pytest.raises(MessageSerializationError, match="content_hash"):
        RawGameMessagePayload.from_json_mapping(corrupted)


def test_decode_event_rejects_unknown_fields_and_naive_timestamp() -> None:
    event = EventEnvelope(event_type="synthetic.test", payload={})
    data = event.to_dict()
    data["unexpected"] = True
    with pytest.raises(MessageSerializationError, match="fields"):
        decode_event(json.dumps(data))

    data = event.to_dict()
    data["occurred_at"] = "2026-01-01T08:00:00"
    with pytest.raises(MessageSerializationError, match="timezone-aware"):
        decode_event(json.dumps(data))


def test_raw_parser_rejects_event_identity_mismatch() -> None:
    payload = RawGameMessagePayload.from_json_mapping(_payload())
    event = EventEnvelope(
        event_id=uuid4(),
        event_type=RAW_GAME_MESSAGE_EVENT,
        payload=payload.model_dump(mode="json"),
        trace_id=payload.trace_id,
    )
    with pytest.raises(MessageSerializationError, match="event_id"):
        parse_raw_game_message(event)
