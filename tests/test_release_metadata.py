"""Release metadata consistency tests."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from openwind_au import __version__

REPO_ROOT = Path(__file__).parents[1]


def test_release_versions_are_consistent() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    citation = (REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8")

    citation_match = re.search(r'^version: "([^"]+)"$', citation, flags=re.MULTILINE)
    assert citation_match is not None
    locked_project_versions = [
        package["version"] for package in lock["package"] if package.get("name") == "openwind-au"
    ]

    assert pyproject["project"]["version"] == __version__
    assert citation_match.group(1) == __version__
    assert locked_project_versions == [__version__]
