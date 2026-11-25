from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

import pytest

from claro.data_generation.generator import GenerationSpec, generate_synthetic_dataset


def _spec(messages: int = 1_000) -> GenerationSpec:
    return GenerationSpec(
        seed=20261125,
        players=120,
        servers=4,
        alliances=20,
        messages=messages,
        policy_rules=16,
    )


def test_generator_is_reproducible_for_the_same_seed_and_scale() -> None:
    first = generate_synthetic_dataset(_spec())
    second = generate_synthetic_dataset(_spec())

    assert first.summary() == second.summary()
    assert first.fingerprint() == second.fingerprint()
    assert first.messages[0] == second.messages[0]
    assert first.labels[-1] == second.labels[-1]


def test_generator_counts_relationships_and_synthetic_markers() -> None:
    generated = generate_synthetic_dataset(_spec(messages=2_000))
    generated.validate()
    summary = generated.summary()

    assert summary["synthetic"] is True
    assert summary["counts"] == {
        "players": 120,
        "servers": 4,
        "alliances": 20,
        "messages": 2_000,
        "message_labels": 2_000,
        "policy_decisions": 2_000,
        "policy_rules": 16,
        "policies": 5,
        "risk_events": summary["counts"]["risk_events"],
        "moderation_records": summary["counts"]["moderation_records"],
    }
    assert generated.dataset.is_synthetic
    assert all(item.is_synthetic for item in generated.players)
    assert all(item.is_synthetic for item in generated.messages)
    assert all(item.is_synthetic for item in generated.labels)
    assert all(item.is_synthetic for item in generated.risk_events)
    assert all(item.is_synthetic for item in generated.moderation_records)
    assert all(item.is_synthetic for item in generated.policy_rules)
    assert len({item.external_message_id for item in generated.messages}) == 2_000


def test_generator_has_realistic_labels_categories_and_player_level_splits() -> None:
    generated = generate_synthetic_dataset(_spec(messages=4_000))
    label_counts: dict[str, int] = defaultdict(int)
    split_counts: dict[str, int] = defaultdict(int)
    player_splits: dict[str, set[str]] = defaultdict(set)
    message_by_id = {item.id: item for item in generated.messages}

    for label in generated.labels:
        label_counts[label.label] += 1
        split_counts[label.split] += 1
        player_splits[message_by_id[label.message_id].player_ref].add(label.split)

    assert label_counts["normal"] > label_counts["boundary"] > label_counts["risk"] > 0
    assert set(split_counts) == {"train", "validation", "test", "holdout"}
    assert all(len(splits) == 1 for splits in player_splits.values())
    assert set(generated.summary()["risk_category_distribution"]) == {
        "harassment",
        "hate_speech",
        "sexual_content",
        "violence",
        "fraud",
        "spam",
        "self_harm",
        "other",
    }
    assert generated.messages[0].occurred_at <= generated.messages[-1].occurred_at
    assert all(
        generated.spec.start_time
        <= item.occurred_at
        < generated.spec.start_time + timedelta(days=generated.spec.days)
        for item in generated.messages
    )


def test_raw_message_payload_does_not_leak_labels_or_risk_outputs() -> None:
    generated = generate_synthetic_dataset(_spec(messages=100))
    for message in generated.messages:
        payload = message.raw_payload()
        assert payload["synthetic"] is True
        assert not {"label", "risk_category", "split", "risk_score", "action"} & payload.keys()


def test_different_seed_changes_the_fingerprint() -> None:
    first = generate_synthetic_dataset(_spec(messages=100))
    second = generate_synthetic_dataset(
        GenerationSpec(
            seed=20261126,
            players=120,
            servers=4,
            alliances=20,
            messages=100,
            policy_rules=16,
        )
    )

    assert first.fingerprint() != second.fingerprint()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("players", 0),
        ("servers", -1),
        ("alliances", 1),
        ("messages", 0),
        ("policy_rules", 0),
        ("days", 0),
        ("seed", -1),
    ],
)
def test_generator_rejects_invalid_scale(field: str, value: int) -> None:
    values = {
        "players": 10,
        "servers": 2,
        "alliances": 4,
        "messages": 10,
        "policy_rules": 8,
        "days": 2,
        "seed": 1,
    }
    values[field] = value
    with pytest.raises(ValueError):
        GenerationSpec(**values)
