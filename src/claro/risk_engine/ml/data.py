from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from claro.risk_engine.preprocessing import preprocess


@dataclass(frozen=True, slots=True)
class TrainingExample:
    message_id: str
    player_ref: str
    content: str
    content_hash: str
    label: str
    category: str | None
    split: str

    def __post_init__(self) -> None:
        if self.label not in {"normal", "boundary", "risk"}:
            raise ValueError(f"unknown ground-truth label: {self.label}")
        if self.label == "risk" and not self.category:
            raise ValueError("risk examples must carry a category")


def example_from_row(row: dict[str, Any]) -> TrainingExample:
    return TrainingExample(
        message_id=str(row["message_id"]),
        player_ref=str(row["player_ref"]),
        content=str(row["content"]),
        content_hash=str(row["content_hash"]),
        label=str(row["label"]),
        category=str(row["category"]) if row.get("category") else None,
        split=str(row["split"]),
    )


def split_examples(
    examples: Sequence[TrainingExample],
) -> dict[str, list[TrainingExample]]:
    grouped: dict[str, list[TrainingExample]] = {}
    for example in examples:
        grouped.setdefault(example.split, []).append(example)
    return grouped


def model_text(content: str) -> str:
    return preprocess(content).ml_text


def labels_matrix(
    examples: Sequence[TrainingExample], labels: Sequence[str]
) -> tuple[list[str], np.ndarray]:
    index = {label: position for position, label in enumerate(labels)}
    texts: list[str] = []
    matrix = np.zeros((len(examples), len(labels)), dtype=int)
    for row, example in enumerate(examples):
        texts.append(model_text(example.content))
        if example.label == "risk":
            if example.category not in index:
                raise ValueError(f"unknown training category: {example.category}")
            matrix[row, index[example.category]] = 1
    return texts, matrix


def risk_targets(matrix: np.ndarray) -> np.ndarray:
    return (np.asarray(matrix).sum(axis=1) > 0).astype(int)


def leakage_report(
    train: Iterable[TrainingExample], test: Iterable[TrainingExample]
) -> dict[str, Any]:
    train_rows = list(train)
    test_rows = list(test)
    train_hashes = {item.content_hash for item in train_rows}
    overlapping = [item for item in test_rows if item.content_hash in train_hashes]
    train_players = {item.player_ref for item in train_rows}
    player_overlap = sorted({item.player_ref for item in test_rows} & train_players)
    return {
        "train_messages": len(train_rows),
        "test_messages": len(test_rows),
        "duplicate_content_test_messages": len(overlapping),
        "duplicate_content_ratio": (
            round(len(overlapping) / len(test_rows), 4) if test_rows else 0.0
        ),
        "player_overlap_count": len(player_overlap),
        "label_distribution": {
            split: dict(sorted(Counter(item.label for item in rows).items()))
            for split, rows in (
                ("train", train_rows),
                ("test", test_rows),
            )
        },
    }


def content_disjoint_subset(
    train: Sequence[TrainingExample], test: Sequence[TrainingExample]
) -> list[TrainingExample]:
    train_hashes = {item.content_hash for item in train}
    return [item for item in test if item.content_hash not in train_hashes]
