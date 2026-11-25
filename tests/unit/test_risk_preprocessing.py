from __future__ import annotations

import pytest

from claro.risk_engine.preprocessing import preprocess


def test_normalizes_fullwidth_and_case() -> None:
    text = preprocess("限時 ＡＤ 立即點擊")
    assert text.normalized == "限時 ad 立即點擊"


def test_removes_zero_width_characters() -> None:
    text = preprocess("诈\u200b骗\ufeff信息")
    assert text.normalized == "诈骗信息"
    assert text.features.zero_width_removed == 2


def test_builds_compact_and_squashed_views() -> None:
    text = preprocess("加 群 领 福 利 啊 啊 啊 啊")
    assert text.compact == "加群领福利啊啊啊啊"
    assert text.squashed == "加群领福利啊"
    assert text.features.max_repeat_run == 4


def test_extracts_entities_and_keeps_cjk_out_of_url() -> None:
    text = preprocess("看 https://scam.example/a 这个，邮箱 a.b@example.com 手机 13800138000")
    assert text.features.urls == ("https://scam.example/a",)
    assert text.features.url_hosts == ("scam.example",)
    assert text.features.emails == ("a.b@example.com",)
    assert text.features.phones == ("13800138000",)


def test_url_hosts_align_with_urls() -> None:
    text = preprocess("https://one.example/x 和 www.two.example/y")
    assert len(text.features.urls) == len(text.features.url_hosts)
    assert text.features.url_hosts == ("one.example", "www.two.example")


def test_ml_text_replaces_entities_with_placeholders() -> None:
    text = preprocess("联系 ab@bb.com 或 13800138000 或 https://x.example/y")
    assert "<email>" in text.ml_text
    assert "<phone>" in text.ml_text
    assert "<url>" in text.ml_text
    assert "ab@bb.com" not in text.ml_text


def test_detects_repeated_segments() -> None:
    text = preprocess("加群 加群 加群")
    assert text.features.repeated_segment_counts.get("加群") == 3


def test_rejects_empty_text() -> None:
    with pytest.raises(ValueError):
        preprocess("   ")
