"""Tests for deterministic shielding and topographic calculation validation."""

from __future__ import annotations

import pytest

from openwind_au.calculation_validation import run_calculation_validation_cases


def test_calculation_validation_cases_pass() -> None:
    report = run_calculation_validation_cases()

    assert report.summary == {"pass": 12, "fail": 0}
    assert {result.calculation_area for result in report.results} == {
        "shielding",
        "topography",
        "wind_inputs",
    }
    assert all(result.status == "pass" for result in report.results)
    assert all(result.checks for result in report.results)


def test_calculation_validation_includes_reference_formula_checks() -> None:
    report = run_calculation_validation_cases()
    by_id = {result.case_id: result for result in report.results}

    shielding = by_id["shielding-single-obstruction-reference"]
    assert any(check.field == "shielding parameter s" for check in shielding.checks)
    assert any(check.field == "indicative Ms" for check in shielding.checks)

    wind = by_id["modos-04625-a2-serviceability-reference"]
    assert any(check.field == "serviceability VR" and check.actual == 37.0 for check in wind.checks)

    mzcat = by_id["terrain-height-table-interpolation"]
    assert any(
        check.field == "TC1.5 at 12.5 m" and check.actual == 1.0625 for check in mzcat.checks
    )

    site_wind = by_id["site-wind-speed-full-precision-product"]
    assert any(
        check.field == "reported Vsit,b at 3 decimals" and check.actual == 32.079
        for check in site_wind.checks
    )

    multiplier = by_id["topographic-multiplier-clause-4-4-reference"]
    assert any(
        check.field == "A4 elevation factor" and check.actual == 1.09 for check in multiplier.checks
    )

    ridge = by_id["topography-ridge-reference"]
    assert any(check.field == "H" and check.actual == 25.0 for check in ridge.checks)
    assert any(check.field == "Lu" and check.actual == 62.5 for check in ridge.checks)
    assert any(
        check.field == "Mt geometry resolved" and check.actual is True for check in ridge.checks
    )


def test_calculation_validation_api() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from openwind_au.api import app

    client = TestClient(app)

    response = client.get("/api/calculation-validation")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"pass": 12, "fail": 0}
    assert "certify AS/NZS 1170.2 compliance" in body["disclaimer"]
    assert {result["calculation_area"] for result in body["results"]} == {
        "shielding",
        "topography",
        "wind_inputs",
    }


def test_reference_calc_7989_validation_api_uses_bundled_fixture(monkeypatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import openwind_au.obstructions as obstructions_module
    from openwind_au.api import app

    def fail_live_query(*_args, **_kwargs):
        raise AssertionError(
            "live Overpass should not be used by fixed reference calculation validation"
        )

    monkeypatch.setattr(
        obstructions_module,
        "query_building_footprints_with_debug",
        fail_live_query,
    )
    client = TestClient(app)

    response = client.get("/api/reference-validation/7989")
    overridden = client.get("/api/reference-validation/7989?apply_reference_overrides=true")

    assert response.status_code == 200
    assert overridden.status_code == 200
    assert response.json()["summary"]["not_available"] == 0
    assert overridden.json()["summary"] == {"match": 24, "mismatch": 0, "not_available": 0}
