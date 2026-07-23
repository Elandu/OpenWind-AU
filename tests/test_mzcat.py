"""Tests for indicative Mz,cat evidence assessment."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import openwind_au.mzcat as mzcat_module
from openwind_au.api import create_app
from openwind_au.errors import ServiceNotReadyError
from openwind_au.models import (
    ObstructionInventoryRequest,
    SiteAnalysisRequest,
    SiteLocation,
    TerrainCategoryDirectionEvidence,
    TerrainCategoryScoreComponents,
    WindRegionAssessment,
)
from openwind_au.mzcat import (
    category_bounds,
    direction_mzcat_assessment,
    indicative_mzcat,
    run_mzcat_assessment,
)
from openwind_au.obstructions import run_obstruction_inventory
from openwind_au.reports import render_terrain_category_report_html
from openwind_au.standard_lookup_tables import (
    MZCAT_DATA_FILE,
    MZCAT_EXPECTED_SHA256_ENV,
    MZCAT_TABLE_ENV,
    canonical_values_sha256,
    load_packaged_lookup_data,
)
from openwind_au.terrain_category import run_terrain_category_evidence
from tests.test_terrain_category import footprint, site_result

SITE_LAT = -33.86
SITE_LON = 151.21


def evidence(
    *,
    suggested_range: str = "TC2.5-TC3",
    confidence: str = "medium",
    height_coverage: float = 90,
    obstruction_count: int = 12,
) -> TerrainCategoryDirectionEvidence:
    return TerrainCategoryDirectionEvidence(
        direction="NW",
        azimuth_deg=315,
        sector_start_deg=292.5,
        sector_end_deg=337.5,
        directional_fetch_distance_m=850,
        assessment_radius_m=850,
        built_up_area_percentage=42,
        vegetation_area_percentage=18,
        open_terrain_percentage=40,
        average_obstruction_height_m=8,
        median_obstruction_height_m=8,
        maximum_obstruction_height_m=12,
        obstruction_density_per_km2=650,
        average_obstruction_spacing_m=45,
        vegetation_density_per_km2=120,
        obstruction_count=obstruction_count,
        vegetation_count=3,
        height_coverage_percentage=height_coverage,
        shielding_confidence="medium",
        evidence_scores=TerrainCategoryScoreComponents(
            open_exposure_score=40,
            vegetation_score=27,
            urban_density_score=80,
            obstruction_height_score=53,
        ),
        suggested_category_range=suggested_range,
        confidence=confidence,  # type: ignore[arg-type]
    )


def test_category_range_mapping_and_indicative_values() -> None:
    assert category_bounds("TC2.5-TC3") == ("TC2.5", "TC3")
    assert category_bounds("TC3.5-TC4") == ("TC4", "TC4")
    assert indicative_mzcat("TC2.5", 10) == pytest.approx(0.92)
    assert indicative_mzcat("TC3", 10) == pytest.approx(0.83)

    assessment = direction_mzcat_assessment(evidence(), 10)

    assert assessment.controlling_category_range == "TC2.5-TC3"
    assert assessment.lower_indicative_mzcat == pytest.approx(0.83)
    assert assessment.upper_indicative_mzcat == pytest.approx(0.92)
    assert assessment.confidence == "medium"
    assert "Engineer review required." in assessment.warnings
    assert "built-up coverage 42.0%" in assessment.reasoning


def test_mzcat_assessment_uses_one_lookup_snapshot_and_records_provenance(monkeypatch) -> None:
    lookup = load_packaged_lookup_data(MZCAT_DATA_FILE)
    load_count = 0

    def counted_loader():
        nonlocal load_count
        load_count += 1
        return lookup

    monkeypatch.setattr(mzcat_module, "load_mzcat_table", counted_loader)
    request = SiteAnalysisRequest(
        latitude=SITE_LAT,
        longitude=SITE_LON,
        building_height_m=10,
        radius_m=500,
    )
    result = run_mzcat_assessment(
        request=request,
        site=SiteLocation(
            latitude=SITE_LAT,
            longitude=SITE_LON,
            ground_elevation_m=10,
            source="test",
        ),
        directions=[evidence(), evidence().model_copy(update={"direction": "N"})],
    )

    assert load_count == 1
    assert result.lookup_provenance.values_sha256 == lookup["values_sha256"]
    assert result.lookup_provenance.schema_version == lookup["schema_version"]
    assert result.lookup_provenance.independent_review_recorded is False


def test_mzcat_confidence_drops_for_weak_evidence() -> None:
    assessment = direction_mzcat_assessment(
        evidence(confidence="low", height_coverage=30, obstruction_count=2),
        10,
    )

    assert assessment.confidence == "low"
    assert "Significant uncertainty in obstruction coverage." in assessment.warnings


def test_high_confidence_narrow_range_gets_recommendation() -> None:
    assessment = direction_mzcat_assessment(
        evidence(suggested_range="TC2-TC2.5", confidence="high", height_coverage=95),
        10,
    )

    assert assessment.recommended_terrain_category == "TC2"
    assert assessment.recommended_mzcat == pytest.approx(1.0)
    assert assessment.recommendation_confidence == "high"
    assert assessment.review_status == "unreviewed"
    assert assessment.final_mzcat is None


def test_best_estimate_mode_selects_upper_category_bound() -> None:
    assessment = direction_mzcat_assessment(
        evidence(suggested_range="TC2-TC2.5", confidence="high", height_coverage=95),
        10,
        recommendation_mode="best_estimate",
    )

    assert assessment.recommendation_mode == "best_estimate"
    assert assessment.recommended_terrain_category == "TC2.5"
    assert assessment.recommended_mzcat == pytest.approx(0.92)


def test_mzcat_uses_linear_height_interpolation() -> None:
    assert indicative_mzcat("TC3", 12.5) == pytest.approx(0.86)


def test_mzcat_uses_linear_category_interpolation() -> None:
    assert indicative_mzcat("TC1.5", 10) == pytest.approx(1.04)


def test_mzcat_uses_combined_height_and_category_interpolation() -> None:
    assert indicative_mzcat("TC1.5", 12.5) == pytest.approx(1.0625)


def test_mzcat_clamps_height_at_lower_table_limit() -> None:
    assert indicative_mzcat("TC4", 1) == pytest.approx(0.75)


def test_mzcat_rejects_height_above_standard_scope() -> None:
    with pytest.raises(ValueError, match="200 m scope"):
        indicative_mzcat("TC4", 200.1)


def test_region_a0_uses_tc2_to_100_m_and_1_24_above() -> None:
    assert indicative_mzcat("TC4", 10, wind_region="A0") == pytest.approx(1.00)
    assert indicative_mzcat("TC1", 100, wind_region="A0") == pytest.approx(1.24)
    assert indicative_mzcat("TC1", 150, wind_region="A0") == pytest.approx(1.24)


def test_direction_evidence_applies_region_a0_rule_consistently() -> None:
    assessment = direction_mzcat_assessment(
        evidence(suggested_range="TC3-TC4", confidence="high"),
        10,
        wind_region="A0",
    )

    assert assessment.lower_indicative_mzcat == pytest.approx(1.0)
    assert assessment.upper_indicative_mzcat == pytest.approx(1.0)
    assert assessment.recommended_mzcat == pytest.approx(1.0)
    assert any("Region A0" in warning for warning in assessment.warnings)
    assert any(
        "Region A0 overrides terrain category" in item
        for item in assessment.recommendation_reasoning
    )


def test_mzcat_assessment_resolves_wind_region_before_building_evidence(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        mzcat_module,
        "assess_wind_region",
        lambda _site: WindRegionAssessment(
            latitude=SITE_LAT,
            longitude=SITE_LON,
            wind_region="A0",
            source="A0 regression fixture",
            confidence="high",
        ),
    )
    request = SiteAnalysisRequest(
        latitude=SITE_LAT,
        longitude=SITE_LON,
        building_height_m=10,
        radius_m=500,
    )

    result = run_mzcat_assessment(
        request=request,
        site=SiteLocation(
            latitude=SITE_LAT,
            longitude=SITE_LON,
            ground_elevation_m=10,
            source="test",
        ),
        directions=[evidence(suggested_range="TC3-TC4")],
    )

    assert result.directions[0].recommended_mzcat == pytest.approx(1.0)
    assert result.directions[0].lower_indicative_mzcat == pytest.approx(1.0)
    assert result.directions[0].upper_indicative_mzcat == pytest.approx(1.0)
    assert any("Region A0" in warning for warning in result.warnings)


def test_mzcat_rejects_unknown_wind_region() -> None:
    with pytest.raises(ValueError, match="Unsupported Australian wind region"):
        indicative_mzcat("TC3", 10, wind_region="ZZ")


def test_mzcat_rejects_ambiguous_generic_region_a() -> None:
    with pytest.raises(ValueError, match="confirm A0, A1, A2, A3, A4, or A5"):
        indicative_mzcat("TC3", 10, wind_region="A")


def test_mzcat_rejects_invalid_category_even_when_a0_rule_is_category_independent() -> None:
    with pytest.raises(ValueError, match="Unsupported terrain category"):
        indicative_mzcat("invalid", 150, wind_region="A0")


def test_mzcat_uses_validated_environment_override(monkeypatch, tmp_path) -> None:
    data = load_packaged_lookup_data(MZCAT_DATA_FILE)
    data["values"]["rows"][2][3] = 0.84
    data["values_sha256"] = canonical_values_sha256(data)
    path = tmp_path / "mzcat.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(MZCAT_TABLE_ENV, str(path))
    monkeypatch.setenv(MZCAT_EXPECTED_SHA256_ENV, data["values_sha256"])

    assert indicative_mzcat("TC3", 10) == pytest.approx(0.84)


def test_mzcat_rejects_lookup_with_stale_digest(monkeypatch, tmp_path) -> None:
    data = load_packaged_lookup_data(MZCAT_DATA_FILE)
    data["values"]["rows"][2][3] = 0.84
    path = tmp_path / "mzcat.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(MZCAT_TABLE_ENV, str(path))

    with pytest.raises(ServiceNotReadyError, match="values_sha256"):
        indicative_mzcat("TC3", 10)


@pytest.mark.parametrize("height", [0, -1, float("nan"), float("inf")])
def test_mzcat_rejects_invalid_height(height: float) -> None:
    with pytest.raises(ValueError, match="finite number greater than zero"):
        indicative_mzcat("TC3", height)


def test_medium_confidence_gets_auto_recommendation_without_final_review_fields() -> None:
    assessment = direction_mzcat_assessment(
        evidence(suggested_range="TC2-TC2.5", confidence="medium", height_coverage=90),
        10,
    )

    assert assessment.recommended_terrain_category == "TC2"
    assert assessment.recommended_mzcat == pytest.approx(1.0)
    assert assessment.recommendation_confidence == "medium"
    assert assessment.final_terrain_category is None
    assert assessment.final_mzcat is None
    assert assessment.review_status == "unreviewed"


def test_accepted_recommendation_sets_final_fields() -> None:
    assessment = direction_mzcat_assessment(
        evidence(suggested_range="TC2-TC2.5", confidence="high", height_coverage=95),
        10,
    ).model_copy(
        update={
            "final_terrain_category": "TC2",
            "final_mzcat": 1.0,
            "reviewed_by": "Engineer A",
            "review_notes": "Accepted after site review.",
            "review_status": "accepted",
        }
    )

    assert assessment.review_status == "accepted"
    assert assessment.final_terrain_category == assessment.recommended_terrain_category
    assert assessment.final_mzcat == assessment.recommended_mzcat


def test_overridden_recommendation_sets_final_fields() -> None:
    assessment = direction_mzcat_assessment(
        evidence(suggested_range="TC2-TC2.5", confidence="high", height_coverage=95),
        10,
    ).model_copy(
        update={
            "final_terrain_category": "TC2.5",
            "final_mzcat": 0.96,
            "reviewed_by": "Engineer B",
            "review_notes": "Sheltered exposure accepted from site imagery.",
            "review_status": "overridden",
        }
    )

    assert assessment.review_status == "overridden"
    assert assessment.final_terrain_category == "TC2.5"
    assert assessment.final_mzcat == pytest.approx(0.96)


def test_terrain_category_evidence_embeds_mzcat_assessment() -> None:
    from openwind_au.models import ObstructionInventoryRequest
    from openwind_au.obstructions import run_obstruction_inventory

    obstructions = run_obstruction_inventory(
        ObstructionInventoryRequest(
            latitude=SITE_LAT,
            longitude=SITE_LON,
            radius_m=500,
            building_height_m=10,
        ),
        footprints=[
            footprint("north-house-1", 0, 120, 60, {"building": "house", "height": "6"}),
            footprint("north-house-2", 15, 180, 50, {"building": "house", "height": "8"}),
            footprint("north-park", -15, 220, 80, {"natural": "wood", "height": "10"}),
        ],
    )

    result = run_terrain_category_evidence(site_result(), obstructions)

    assert len(result.mzcat_assessment) == 8
    assert all(
        item.lower_indicative_mzcat <= item.upper_indicative_mzcat
        for item in result.mzcat_assessment
    )
    assert "not calculate final Mz,cat design values" in result.disclaimer


def test_terrain_category_report_includes_mzcat_summary() -> None:
    from openwind_au.models import ObstructionInventoryRequest
    from openwind_au.obstructions import run_obstruction_inventory

    obstructions = run_obstruction_inventory(
        ObstructionInventoryRequest(latitude=SITE_LAT, longitude=SITE_LON, radius_m=500),
        footprints=[],
    )
    result = run_terrain_category_evidence(site_result(), obstructions)

    html = render_terrain_category_report_html(result)

    assert "Directional Mz,cat Summary" in html
    assert "Indicative evidence only" in html
    assert "not final" in html


def test_report_distinguishes_recommended_and_final_values() -> None:
    obstructions = run_obstruction_inventory(
        ObstructionInventoryRequest(latitude=SITE_LAT, longitude=SITE_LON, radius_m=500),
        footprints=[],
    )
    result = run_terrain_category_evidence(site_result(), obstructions)
    accepted = direction_mzcat_assessment(
        evidence(suggested_range="TC2-TC2.5", confidence="high", height_coverage=95),
        10,
    ).model_copy(
        update={
            "final_terrain_category": "TC2",
            "final_mzcat": 1.0,
            "reviewed_by": "Engineer A",
            "review_notes": "Accepted recommendation.",
            "review_status": "accepted",
        }
    )
    unreviewed = direction_mzcat_assessment(
        evidence(suggested_range="TC2.5-TC3", confidence="medium", height_coverage=90),
        10,
    )
    result = result.model_copy(update={"mzcat_assessment": [accepted, unreviewed]})

    html = render_terrain_category_report_html(result)

    assert "Recommended TC" in html
    assert "Engineer-selected Final Mz,cat" in html
    assert "Accepted recommendation." in html
    assert "hidden until engineer review" in html


def test_mzcat_api_endpoint_returns_all_directions(monkeypatch) -> None:
    import openwind_au.api as api_module

    synthetic = run_terrain_category_evidence(
        site_result(),
        run_obstruction_inventory(
            ObstructionInventoryRequest(
                latitude=SITE_LAT,
                longitude=SITE_LON,
                radius_m=500,
            ),
            footprints=[],
        ),
    )
    monkeypatch.setattr(
        api_module,
        "_run_terrain_category_workflow",
        lambda request: (None, None, synthetic),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/mzcat/assessment",
        json={
            "latitude": SITE_LAT,
            "longitude": SITE_LON,
            "building_height_m": 10,
            "radius_m": 500,
            "sample_interval_m": 100,
            "obstruction_radius_m": 500,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["directions"]) == 8
    assert "final design wind speeds" in body["disclaimer"]
