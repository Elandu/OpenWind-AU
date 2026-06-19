"""Tests for indicative Mz,cat evidence assessment."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openwind_au.api import create_app
from openwind_au.models import (
    ObstructionInventoryRequest,
    TerrainCategoryDirectionEvidence,
    TerrainCategoryScoreComponents,
)
from openwind_au.mzcat import category_bounds, direction_mzcat_assessment, indicative_mzcat
from openwind_au.obstructions import run_obstruction_inventory
from openwind_au.reports import render_terrain_category_report_html
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
    assert indicative_mzcat("TC2.5", 10) == pytest.approx(0.96)
    assert indicative_mzcat("TC3", 10) == pytest.approx(0.91)

    assessment = direction_mzcat_assessment(evidence(), 10)

    assert assessment.controlling_category_range == "TC2.5-TC3"
    assert assessment.lower_indicative_mzcat == pytest.approx(0.91)
    assert assessment.upper_indicative_mzcat == pytest.approx(0.96)
    assert assessment.confidence == "medium"
    assert "Engineer review required." in assessment.warnings
    assert "built-up coverage 42.0%" in assessment.reasoning


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
    assert assessment.recommended_mzcat == pytest.approx(0.96)


def test_medium_confidence_has_no_final_or_auto_recommendation() -> None:
    assessment = direction_mzcat_assessment(
        evidence(suggested_range="TC2-TC2.5", confidence="medium", height_coverage=90),
        10,
    )

    assert assessment.recommended_terrain_category == "review required"
    assert assessment.recommended_mzcat is None
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
