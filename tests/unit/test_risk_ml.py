from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from claro.risk_engine.evaluation.runner import evaluate_predictor
from claro.risk_engine.ml.data import TrainingExample
from claro.risk_engine.ml.predictor import ModelPredictor
from claro.risk_engine.ml.trainer import (
    TrainingConfig,
    TrainingError,
    train_risk_model,
)
from claro.risk_engine.preprocessing import preprocess

LABELS = ("spam", "fraud", "harassment")


def example(
    player: str,
    index: int,
    *,
    label: str = "normal",
    category: str | None = None,
    split: str,
    content: str | None = None,
) -> TrainingExample:
    if content is None:
        content = f"今天组队打副本很开心 编号{index}"
    return TrainingExample(
        message_id=f"m-{player}-{index}",
        player_ref=player,
        content=content,
        content_hash=f"hash-{player}-{index}",
        label=label,
        category=category,
        split=split,
    )


def dataset() -> list[TrainingExample]:
    rows: list[TrainingExample] = []
    for player, split in (
        ("p0", "train"),
        ("p1", "train"),
        ("p2", "validation"),
        ("p3", "validation"),
        ("p4", "test"),
        ("p5", "test"),
    ):
        base = int(player[1:]) * 10
        rows.extend(
            [
                example(player, base, split=split),
                example(player, base + 1, split=split),
                example(
                    player,
                    base + 2,
                    label="risk",
                    category="spam",
                    split=split,
                    content=f"限时广告立即点击领取福利 编号{base + 2}",
                ),
                example(
                    player,
                    base + 3,
                    label="risk",
                    category="fraud",
                    split=split,
                    content=f"免费代充先付款后发货 编号{base + 3}",
                ),
                example(
                    player,
                    base + 4,
                    label="risk",
                    category="harassment",
                    split=split,
                    content=f"你这个废物闭嘴丢人 编号{base + 4}",
                ),
                example(
                    player,
                    base + 5,
                    label="risk",
                    category="spam",
                    split=split,
                    content=f"优惠出售套餐秒发货 编号{base + 5}",
                ),
            ]
        )
        if split == "test":
            rows.append(
                example(
                    player,
                    base + 6,
                    label="boundary",
                    split=split,
                    content=f"想问一下代充算违规吗 编号{base + 6}",
                )
            )
    return rows


def training_config() -> TrainingConfig:
    return TrainingConfig(
        algorithm="logistic_regression",
        c_values=(1.0,),
        min_df=1,
        max_features=2_000,
        ngram_min=1,
        ngram_max=3,
        dataset_name="unit-test-dataset",
        model_version=1,
    )


def test_trains_serializes_and_predicts(tmp_path: Path) -> None:
    outcome = train_risk_model(
        dataset(),
        LABELS,
        training_config(),
        tmp_path / "models",
        project_root=None,
    )

    assert outcome.bundle_path.is_file()
    assert outcome.metadata_path.is_file()
    assert outcome.model_id.startswith("logistic_regression-")
    assert Path(outcome.artifact_path).is_absolute()
    assert outcome.metadata["synthetic_dataset"] is True
    assert set(outcome.thresholds) == set(LABELS)
    assert outcome.metadata["feature_config"]["vocabulary_size"] > 0
    assert outcome.metadata["split_sizes"] == {
        "train": 12,
        "validation": 12,
        "test": 12,
        "boundary_test": 2,
    }
    assert outcome.test_metrics["leakage"]["duplicate_content_test_messages"] == 0
    assert outcome.test_metrics["content_disjoint"]["messages"] == 12
    assert outcome.test_metrics["boundary"]["messages"] == 2

    predictor = ModelPredictor.from_metadata_file(outcome.metadata_path)
    prediction = predictor.predict(preprocess("限时广告立即点击领取福利 编号999"))
    assert prediction.model_id == outcome.model_id
    assert set(prediction.probabilities) == set(LABELS)
    assert 0 <= prediction.risk_probability <= 1
    assert prediction.is_risk == any(
        prediction.probabilities[label] >= prediction.thresholds[label] for label in LABELS
    )


def test_evaluation_runner_reports_disjoint_and_boundary(tmp_path: Path) -> None:
    rows = dataset()
    outcome = train_risk_model(
        rows,
        LABELS,
        training_config(),
        tmp_path / "models",
        project_root=None,
    )
    predictor = ModelPredictor.from_path(outcome.bundle_path)
    train_rows = [item for item in rows if item.split == "train"]
    test_rows = [item for item in rows if item.split == "test"]

    evaluation = evaluate_predictor(predictor, test_rows, LABELS, None, train_examples=train_rows)
    assert evaluation.message_count == len(test_rows)
    assert evaluation.metrics["binary"]["samples"] == 12
    assert evaluation.metrics["boundary"]["messages"] == 2
    assert evaluation.metrics["content_disjoint"]["messages"] == 12
    assert evaluation.case_counts["borderline"] == 2


def test_rejects_player_leakage(tmp_path: Path) -> None:
    rows = [
        example("same", 1, split="train"),
        example("other", 2, split="validation"),
        example("same", 3, split="test"),
        example("other", 4, split="test"),
    ]
    with pytest.raises(TrainingError, match="player leakage"):
        train_risk_model(rows, LABELS, training_config(), tmp_path / "models")


def test_rejects_unknown_algorithm(tmp_path: Path) -> None:
    config = replace(training_config(), algorithm="unsupported")
    with pytest.raises(TrainingError, match="unsupported algorithm"):
        train_risk_model(dataset(), LABELS, config, tmp_path / "models")
