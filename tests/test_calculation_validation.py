"""Tests for deterministic shielding and topographic calculation validation."""

from __future__ import annotations

import pytest

from openwind_au.calculation_validation import run_calculation_validation_cases


def test_calculation_validation_cases_pass() -> None:
    report = run_calculation_validation_cases()

    assert report.summary == {"pass": 8, "fail": 0}
    assert {result.calculation_area for result in report.results} == {
        "shielding",
        "topography",
    }
    assert all(result.status == "pass" for result in report.results)
    assert all(result.checks for result in report.results)


def test_calculation_validation_includes_reference_formula_checks() -> None:
    report = run_calculation_validation_cases()
    by_id = {result.case_id: result for result in report.results}

    shielding = by_id["shielding-single-obstruction-reference"]
    assert any(check.field == "shielding parameter s" for check in shielding.checks)
    assert any(check.field == "indicative Ms" for check in shielding.checks)

    ridge = by_id["topography-ridge-reference"]
    assert any(check.field == "H" and check.actual == 25.0 for check in ridge.checks)
    assert any(check.field == "Lu" and check.actual == 200.0 for check in ridge.checks)


def test_calculation_validation_api() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from openwind_au.api import app

    client = TestClient(app)

    response = client.get("/api/calculation-validation")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"pass": 8, "fail": 0}
    assert "certify AS/NZS 1170.2 compliance" in body["disclaimer"]
    assert {result["calculation_area"] for result in body["results"]} == {
        "shielding",
        "topography",
    }
