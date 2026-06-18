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
