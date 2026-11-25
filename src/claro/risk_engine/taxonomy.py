from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from claro.domain.enums import RiskCategory, RiskSeverity


class TaxonomyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TaxonomyDomain:
    id: str
    name: str
    name_zh: str
    definition: str


@dataclass(frozen=True, slots=True)
class TaxonomyCategory:
    id: str
    db_category: str | None
    domain: str
    name: str
    definition: str
    inclusion_criteria: tuple[str, ...]
    exclusion_criteria: tuple[str, ...]
    positive_examples: tuple[str, ...]
    negative_examples: tuple[str, ...]
    borderline_examples: tuple[str, ...]
    severity: str
    annotation_guidelines: str


class RiskTaxonomy:
    def __init__(
        self,
        *,
        version: int,
        default_risk_level: str,
        domains: tuple[TaxonomyDomain, ...],
        categories: tuple[TaxonomyCategory, ...],
        db_category_names: dict[str, str] | None = None,
    ) -> None:
        self.version = version
        self.default_risk_level = default_risk_level
        self.domains = domains
        self.categories = categories
        self.db_category_names = db_category_names or {}
        self._by_id = {category.id: category for category in categories}

    def category(self, category_id: str) -> TaxonomyCategory:
        try:
            return self._by_id[category_id]
        except KeyError as error:
            raise KeyError(f"unknown taxonomy category: {category_id}") from error

    def has(self, category_id: str) -> bool:
        return category_id in self._by_id

    @property
    def db_categories(self) -> tuple[str, ...]:
        values = {item.db_category for item in self.categories if item.db_category}
        return tuple(sorted(values))

    @property
    def risk_categories(self) -> tuple[TaxonomyCategory, ...]:
        return tuple(item for item in self.categories if item.db_category is not None)

    def category_ids_for_db(self, db_category: str) -> tuple[str, ...]:
        return tuple(item.id for item in self.categories if item.db_category == db_category)

    def db_category_name(self, db_category: str) -> str:
        return self.db_category_names.get(db_category, db_category.replace("_", " ").title())


def load_taxonomy(path: Path) -> RiskTaxonomy:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise TaxonomyError(f"taxonomy file is unreadable: {path}") from error
    except yaml.YAMLError as error:
        raise TaxonomyError(f"taxonomy file is not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise TaxonomyError("taxonomy root must be a mapping")

    version = raw.get("version")
    if not isinstance(version, int) or version < 1:
        raise TaxonomyError("taxonomy version must be a positive integer")
    default_level = str(raw.get("default_risk_level", "medium"))
    if default_level not in {item.value for item in RiskSeverity}:
        raise TaxonomyError(f"unknown default risk level: {default_level}")

    domains = tuple(_parse_domain(item, index) for index, item in enumerate(_list(raw, "domains")))
    domain_ids = {domain.id for domain in domains}
    if len(domain_ids) != len(domains):
        raise TaxonomyError("taxonomy domain ids must be unique")

    categories = tuple(
        _parse_category(item, index) for index, item in enumerate(_list(raw, "categories"))
    )
    category_ids = {item.id for item in categories}
    if len(category_ids) != len(categories):
        raise TaxonomyError("taxonomy category ids must be unique")
    db_values = {item.value for item in RiskCategory}
    for category in categories:
        if category.domain not in domain_ids:
            raise TaxonomyError(f"category {category.id} references unknown domain")
        if category.db_category is not None and category.db_category not in db_values:
            raise TaxonomyError(
                f"category {category.id} maps to unknown database category {category.db_category}"
            )
        if category.severity not in {item.value for item in RiskSeverity}:
            raise TaxonomyError(f"category {category.id} has unknown severity")
    normal_categories = [item for item in categories if item.db_category is None]
    if len(normal_categories) != 1 or normal_categories[0].id != "normal":
        raise TaxonomyError("taxonomy requires exactly one 'normal' category without db mapping")

    raw_names = raw.get("db_category_names", {})
    if not isinstance(raw_names, dict) or not all(
        isinstance(key, str) and isinstance(value, str) and value.strip()
        for key, value in raw_names.items()
    ):
        raise TaxonomyError("db_category_names must map strings to non-empty strings")
    for key in raw_names:
        if key not in db_values:
            raise TaxonomyError(f"db_category_names references unknown category {key}")

    return RiskTaxonomy(
        version=version,
        default_risk_level=default_level,
        domains=domains,
        categories=categories,
        db_category_names={key: value.strip() for key, value in raw_names.items()},
    )


def _list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key)
    if not isinstance(value, list) or not value:
        raise TaxonomyError(f"taxonomy field '{key}' must be a non-empty list")
    for item in value:
        if not isinstance(item, dict):
            raise TaxonomyError(f"taxonomy field '{key}' must contain mappings")
    return value


def _text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TaxonomyError(f"taxonomy field '{key}' must be a non-empty string")
    return value.strip()


def _strings(data: dict[str, Any], key: str, *, required: bool = True) -> tuple[str, ...]:
    value = data.get(key)
    if value is None and not required:
        return ()
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise TaxonomyError(f"taxonomy field '{key}' must be a non-empty string list")
    return tuple(item.strip() for item in value)


def _parse_domain(data: dict[str, Any], index: int) -> TaxonomyDomain:
    try:
        return TaxonomyDomain(
            id=_text(data, "id"),
            name=_text(data, "name"),
            name_zh=_text(data, "name_zh"),
            definition=_text(data, "definition"),
        )
    except TaxonomyError as error:
        raise TaxonomyError(f"invalid domain at index {index}: {error}") from error


def _parse_category(data: dict[str, Any], index: int) -> TaxonomyCategory:
    try:
        db_category = data.get("db_category")
        if db_category is not None and not isinstance(db_category, str):
            raise TaxonomyError("db_category must be a string or null")
        return TaxonomyCategory(
            id=_text(data, "id"),
            db_category=db_category,
            domain=_text(data, "domain"),
            name=_text(data, "name"),
            definition=_text(data, "definition"),
            inclusion_criteria=_strings(data, "inclusion_criteria"),
            exclusion_criteria=_strings(data, "exclusion_criteria"),
            positive_examples=_strings(data, "positive_examples"),
            negative_examples=_strings(data, "negative_examples"),
            borderline_examples=_strings(data, "borderline_examples", required=False),
            severity=_text(data, "severity"),
            annotation_guidelines=_text(data, "annotation_guidelines"),
        )
    except TaxonomyError as error:
        raise TaxonomyError(f"invalid category at index {index}: {error}") from error
