"""Documentation smoke tests."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
CALCULATION_BASIS_PATH = REPO_ROOT / "docs" / "calculation-basis.md"
CALCULATION_BASIS_LINK = "docs/calculation-basis.md"


def test_calculation_basis_document_exists() -> None:
    content = CALCULATION_BASIS_PATH.read_text(encoding="utf-8")

    assert CALCULATION_BASIS_PATH.exists()
    assert "# Calculation Basis and Data Lineage" in content
    assert "## Data Provenance" in content
    assert "OpenWind-AU is not a certification tool." in content


def test_readme_references_calculation_basis_document() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert CALCULATION_BASIS_LINK in readme


def test_roadmap_references_calculation_basis_document() -> None:
    roadmap = (REPO_ROOT / "ROADMAP.md").read_text(encoding="utf-8")

    assert CALCULATION_BASIS_LINK in roadmap
