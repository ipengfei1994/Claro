from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

ZERO_WIDTH_PATTERN = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")
URL_PATTERN = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s<>\"'，。！？；：、）】\]\[（\u4e00-\u9fff]+"
)
EMAIL_PATTERN = re.compile(r"(?i)(?<![\w.-])[\w.+-]{2,}@[\w-]{2,}(?:\.[\w-]{2,})+")
PHONE_PATTERN = re.compile(r"(?<![0-9])1[3-9][0-9]{9}(?![0-9])")
CONTACT_PATTERN = re.compile(
    r"(?i)(?:微信|wechat|vx|v信|qq|telegram|飞机)\s*[:：]?\s*[a-z0-9_-]{5,20}"
)
SEPARATOR_PATTERN = re.compile(r"[\s*._·•|\\/\-—–~^]+")
SEGMENT_PATTERN = re.compile(r"[^\w\u4e00-\u9fff]+")
REPEAT_RUN_PATTERN = re.compile(r"(.)\1{2,}")
WHITESPACE_PATTERN = re.compile(r"\s+")
TOKEN_PATTERN = re.compile(r"\[synthetic-link\]", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class TextFeatures:
    urls: tuple[str, ...]
    url_hosts: tuple[str, ...]
    emails: tuple[str, ...]
    phones: tuple[str, ...]
    contact_mentions: tuple[str, ...]
    repeated_segments: tuple[str, ...]
    repeated_segment_counts: dict[str, int]
    zero_width_removed: int
    had_fullwidth_characters: bool
    max_repeat_run: int
    synthetic_link_token: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "urls": list(self.urls),
            "url_hosts": list(self.url_hosts),
            "emails": list(self.emails),
            "phones": list(self.phones),
            "contact_mentions": list(self.contact_mentions),
            "repeated_segments": list(self.repeated_segments),
            "repeated_segment_counts": dict(self.repeated_segment_counts),
            "zero_width_removed": self.zero_width_removed,
            "had_fullwidth_characters": self.had_fullwidth_characters,
            "max_repeat_run": self.max_repeat_run,
            "synthetic_link_token": self.synthetic_link_token,
        }


@dataclass(frozen=True, slots=True)
class PreprocessedText:
    original: str
    normalized: str
    compact: str
    squashed: str
    ml_text: str
    language: str
    features: TextFeatures
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "normalized": self.normalized,
            "compact": self.compact,
            "ml_text": self.ml_text,
            "language": self.language,
            "features": self.features.to_dict(),
            "metadata": dict(self.metadata),
        }


def preprocess(text: str, language: str = "zh-CN") -> PreprocessedText:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")

    zero_width = len(ZERO_WIDTH_PATTERN.findall(text))
    without_zero_width = ZERO_WIDTH_PATTERN.sub("", text)
    normalized = unicodedata.normalize("NFKC", without_zero_width).lower()
    normalized = WHITESPACE_PATTERN.sub(" ", normalized).strip()
    compact = SEPARATOR_PATTERN.sub("", normalized)
    squashed = REPEAT_RUN_PATTERN.sub(r"\1", compact)

    urls = _unique(_trim_url(match.group(0)) for match in URL_PATTERN.finditer(without_zero_width))
    hosts = tuple(_host(url) for url in urls)
    emails = _unique(match.group(0).lower() for match in EMAIL_PATTERN.finditer(normalized))
    phones = _unique(match.group(0) for match in PHONE_PATTERN.finditer(normalized))
    contacts = _unique(
        WHITESPACE_PATTERN.sub("", match.group(0)).lower()
        for match in CONTACT_PATTERN.finditer(normalized)
    )
    segments, counts = _repeated_segments(normalized)
    max_run = max(
        (len(match.group(0)) for match in REPEAT_RUN_PATTERN.finditer(compact)), default=0
    )

    ml_text = normalized
    for url in sorted(urls, key=len, reverse=True):
        ml_text = ml_text.replace(url.lower(), " <url> ")
    ml_text = EMAIL_PATTERN.sub(" <email> ", ml_text)
    ml_text = PHONE_PATTERN.sub(" <phone> ", ml_text)
    ml_text = WHITESPACE_PATTERN.sub(" ", ml_text).strip()

    features = TextFeatures(
        urls=urls,
        url_hosts=hosts,
        emails=emails,
        phones=phones,
        contact_mentions=contacts,
        repeated_segments=segments,
        repeated_segment_counts=counts,
        zero_width_removed=zero_width,
        had_fullwidth_characters=any("\uff01" <= char <= "\uff5e" for char in text),
        max_repeat_run=max_run,
        synthetic_link_token=bool(TOKEN_PATTERN.search(text)),
    )
    metadata = {
        "steps": [
            "unicode_nfkc",
            "zero_width_removal",
            "lowercase",
            "whitespace_collapse",
            "separator_removal",
            "repeat_squash",
            "entity_extraction",
        ],
        "original_length": len(text),
        "normalized_length": len(normalized),
        "compact_length": len(compact),
    }
    return PreprocessedText(
        original=text,
        normalized=normalized,
        compact=compact,
        squashed=squashed,
        ml_text=ml_text,
        language=language,
        features=features,
        metadata=metadata,
    )


def _unique(values: Any) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        if value:
            seen.setdefault(value, None)
    return tuple(seen)


def _trim_url(value: str) -> str:
    return value.rstrip(".,;:!?)]}。，；：！？）】")


def _host(url: str) -> str:
    candidate = url if "://" in url else f"http://{url}"
    try:
        return (urlsplit(candidate).hostname or "").lower()
    except ValueError:
        return ""


def _repeated_segments(text: str) -> tuple[tuple[str, ...], dict[str, int]]:
    segments = [
        segment for segment in SEGMENT_PATTERN.split(text) if len(segment) >= 2 and segment.strip()
    ]
    counts = Counter(segments)
    repeated = {segment: count for segment, count in counts.items() if count >= 2}
    ordered = tuple(sorted(repeated, key=lambda segment: (-repeated[segment], -len(segment)))[:20])
    return ordered, dict(sorted(repeated.items(), key=lambda item: -item[1])[:20])
