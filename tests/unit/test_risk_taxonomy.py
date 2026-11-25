from __future__ import annotations

from pathlib import Path

import pytest

from claro.domain.enums import RiskCategory
from claro.risk_engine.taxonomy import TaxonomyError, load_taxonomy

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def project_root() -> Path:
    return PROJECT_ROOT


def test_loads_project_taxonomy_with_complete_metadata() -> None:
    taxonomy = load_taxonomy(project_root() / "config" / "risk_taxonomy.yaml")
    assert taxonomy.version == 1
    assert len(taxonomy.domains) == 7
    assert len(taxonomy.categories) == 19
    assert len(taxonomy.risk_categories) == 18
    assert taxonomy.has("normal")
    assert taxonomy.category("normal").db_category is None
    assert set(taxonomy.db_categories) == {item.value for item in RiskCategory}

    domain_ids = {domain.id for domain in taxonomy.domains}
    for category in taxonomy.risk_categories:
        assert category.inclusion_criteria
        assert category.exclusion_criteria
        assert category.positive_examples
        assert category.negative_examples
        assert category.annotation_guidelines
        assert category.domain in domain_ids


def test_rejects_unknown_database_category(tmp_path: Path) -> None:
    source = (project_root() / "config" / "risk_taxonomy.yaml").read_text(encoding="utf-8")
    invalid = source.replace("db_category: spam", "db_category: not_a_category", 1)
    target = tmp_path / "taxonomy.yaml"
    target.write_text(invalid, encoding="utf-8")

    with pytest.raises(TaxonomyError, match="unknown database category"):
        load_taxonomy(target)


def test_rejects_missing_normal_category(tmp_path: Path) -> None:
    source = (project_root() / "config" / "risk_taxonomy.yaml").read_text(encoding="utf-8")
    invalid = source.replace("db_category: null", "db_category: spam")
    target = tmp_path / "taxonomy.yaml"
    target.write_text(invalid, encoding="utf-8")

    with pytest.raises(TaxonomyError, match="normal"):
        load_taxonomy(target)
