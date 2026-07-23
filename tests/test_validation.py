"""Tests for qualitative validation framework."""

from __future__ import annotations

from openwind_au.dem import DEMProvider
from openwind_au.models import SiteAnalysisRequest
from openwind_au.report_lineage import CALCULATION_BASIS_URL
from openwind_au.validation import (
    DEFAULT_VALIDATION_CASES,
    ValidationCase,
    evaluate_validation_case,
    render_validation_report_html,
    run_validation_cases,
    validation_report_to_json,
)


class FlatDEM(DEMProvider):
    def elevation(self, latitude: float, longitude: float) -> float:
        return 100.0


class RidgeDEM(DEMProvider):
    def __init__(self, origin_latitude: float, origin_longitude: float) -> None:
        self.origin_latitude = origin_latitude
        self.origin_longitude = origin_longitude

    def elevation(self, latitude: float, longitude: float) -> float:
        east_m = (longitude - self.origin_longitude) * 111_320
        if 300 <= east_m <= 500:
            return 130.0
        return 100.0


def validation_case(
    expected_feature_types: tuple[str, ...],
    case_id: str = "test-case",
) -> ValidationCase:
    return ValidationCase(
        case_id=case_id,
        site_name="Test validation case",
        latitude=-33.86,
        longitude=151.21,
        building_height_m=10,
        expected_general_terrain_description="Broad test terrain.",
        expected_topographic_behaviour="Broad test behaviour.",
        notes="Synthetic validation test.",
        source_reference="Synthetic test fixture.",
        expected_feature_types=expected_feature_types,
    )


def test_default_validation_cases_cover_required_examples() -> None:
    assert len(DEFAULT_VALIDATION_CASES) >= 5
    assert {case.case_id for case in DEFAULT_VALIDATION_CASES} >= {
        "au-flat-suburban-blacktown-nsw",
        "au-coastal-escarpment-stanwell-tops-nsw",
        "au-hilltop-mount-coot-tha-qld",
        "au-valley-kangaroo-valley-nsw",
        "au-inland-flat-hay-nsw",
    }
    assert all(case.source_reference for case in DEFAULT_VALIDATION_CASES)
    assert all(case.expected_general_terrain_description for case in DEFAULT_VALIDATION_CASES)
    assert all(case.expected_topographic_behaviour for case in DEFAULT_VALIDATION_CASES)


def test_validation_runner_executes_cases_and_renders_reports() -> None:
    cases = [validation_case(("no significant feature",))]

    report = run_validation_cases(cases=cases, dem_provider=FlatDEM(), radius_m=500)
    data = validation_report_to_json(report)
    html = render_validation_report_html(report)

    assert report.summary == {"pass": 1, "warn": 0, "fail": 0}
    assert data["results"][0]["status"] == "pass"
    assert "not proof of AS/NZS 1170.2 compliance" in data["disclaimer"]
    assert "Validation Report" in html
    assert CALCULATION_BASIS_URL in html
    assert "pass" in html
    assert "Warning" in html
    assert "Fail" in html


def test_validation_flags_expected_feature_pass() -> None:
    case = validation_case(("ridge",))
    analysis = run_validation_cases(
        cases=[case],
        dem_provider=RidgeDEM(case.latitude, case.longitude),
        radius_m=500,
        sample_interval_m=100,
    ).results[0]

    assert analysis.status == "pass"
    assert "ridge" in analysis.detected_feature_types
    assert analysis.candidate_feature_count > 0


def test_validation_flags_warning_for_unexpected_low_relief_flat_case() -> None:
    case = validation_case(("no significant feature",))
    analysis = SiteAnalysisRequest(
        latitude=case.latitude,
        longitude=case.longitude,
        building_height_m=case.building_height_m,
        radius_m=500,
        sample_interval_m=100,
    )
    result = run_validation_cases(
        cases=[case],
        dem_provider=RidgeDEM(analysis.latitude, analysis.longitude),
        radius_m=500,
        sample_interval_m=100,
    ).results[0]

    assert result.status in {"warn", "fail"}
    assert result.candidate_feature_count > 0


def test_validation_flags_fail_when_expected_feature_is_missing() -> None:
    report = run_validation_cases(
        cases=[validation_case(("escarpment",))],
        dem_provider=FlatDEM(),
        radius_m=500,
    )

    assert report.results[0].status == "fail"
    assert report.summary["fail"] == 1


def test_evaluate_validation_case_can_warn_on_type_mismatch() -> None:
    case = validation_case(("valley",))
    report = run_validation_cases(
        cases=[validation_case(("ridge",))],
        dem_provider=RidgeDEM(case.latitude, case.longitude),
        radius_m=500,
        sample_interval_m=100,
    )
    result = evaluate_validation_case(case, report.results[0].analysis)

    assert result.status == "warn"
    assert result.detected_feature_types != ["no significant feature"]
