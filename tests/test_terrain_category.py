"""Tests for terrain category evidence calculations."""

from __future__ import annotations

import math

import pytest

from openwind_au.geo import EARTH_RADIUS_M
from openwind_au.models import ObstructionInventoryRequest, SiteAnalysisRequest, SiteAnalysisResult
from openwind_au.obstructions import run_obstruction_inventory
from openwind_au.terrain import generate_standard_terrain_profiles
from openwind_au.terrain_category import (
    confidence_from_evidence,
    polygon_area_m2,
    run_terrain_category_evidence,
    suggested_category_range,
    terrain_category_scores,
)
from openwind_au.terrain_category_validation import (
    DEFAULT_TERRAIN_CATEGORY_VALIDATION_CASES,
    run_terrain_category_validation_cases,
)
from openwind_au.topography import analyse_topography

SITE_LAT = -33.86
SITE_LON = 151.21


class FlatDEM:
    def elevation(self, latitude: float, longitude: float) -> float:
        return 50.0


def local_to_lonlat(east_m: float, north_m: float) -> tuple[float, float]:
    latitude = SITE_LAT + math.degrees(north_m / EARTH_RADIUS_M)
    longitude = SITE_LON + math.degrees(
        east_m / (EARTH_RADIUS_M * math.cos(math.radians(SITE_LAT)))
    )
    return longitude, latitude


def footprint(
    source_id: str,
    center_east_m: float,
    center_north_m: float,
    width_m: float,
    tags: dict,
) -> dict:
    half = width_m / 2
    ring = [
        local_to_lonlat(center_east_m - half, center_north_m - half),
        local_to_lonlat(center_east_m + half, center_north_m - half),
        local_to_lonlat(center_east_m + half, center_north_m + half),
        local_to_lonlat(center_east_m - half, center_north_m + half),
        local_to_lonlat(center_east_m - half, center_north_m - half),
    ]
    return {
        "source_id": source_id,
        "footprint_geometry": {"type": "Polygon", "coordinates": [ring]},
        "tags": tags,
    }


def site_result() -> SiteAnalysisResult:
    request = SiteAnalysisRequest(
        latitude=SITE_LAT,
        longitude=SITE_LON,
        building_height_m=10,
        radius_m=500,
        sample_interval_m=100,
    )
    profiles = generate_standard_terrain_profiles(
        latitude=SITE_LAT,
        longitude=SITE_LON,
        dem_provider=FlatDEM(),
        radius_m=500,
        sample_interval_m=100,
    )
    return SiteAnalysisResult(
        input=request,
        site=run_obstruction_inventory(
            ObstructionInventoryRequest(latitude=SITE_LAT, longitude=SITE_LON),
            footprints=[],
        ).site,
        profiles=profiles,
        features=analyse_topography(profiles, 50),
        assumptions=[],
        limitations=[],
    )


def test_polygon_area_uses_local_projection() -> None:
    geometry = footprint("area", 0, 100, 20, {"building": "yes"})["footprint_geometry"]

    assert polygon_area_m2(geometry, SITE_LAT, SITE_LON) == pytest.approx(400, rel=0.03)


def test_directional_evidence_metrics_and_range_generation() -> None:
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
            footprint("east-house", 150, 0, 40, {"building": "house", "height": "6"}),
        ],
    )

    evidence = run_terrain_category_evidence(site_result(), obstructions)
    north = next(direction for direction in evidence.directions if direction.direction == "N")
    south = next(direction for direction in evidence.directions if direction.direction == "S")

    assert len(evidence.directions) == 8
    assert north.obstruction_count == 3
    assert north.built_up_area_percentage > 0
    assert north.vegetation_area_percentage > 0
    assert north.open_terrain_percentage < 100
    assert north.average_obstruction_height_m == pytest.approx(8)
    assert north.median_obstruction_height_m == pytest.approx(8)
    assert north.maximum_obstruction_height_m == pytest.approx(10)
    assert north.obstruction_density_per_km2 > 0
    assert north.average_obstruction_spacing_m is not None
    assert north.directional_fetch_distance_m == pytest.approx(500)
    assert north.suggested_category_range.startswith("TC")
    assert north.confidence in {"high", "medium", "low"}
    assert "Terrain category requires engineer confirmation." in north.warnings
    assert south.obstruction_count == 0
    assert south.confidence == "low"


def test_scoring_confidence_and_validation_examples() -> None:
    open_scores = terrain_category_scores(
        built_up_area_percentage=2,
        vegetation_area_percentage=3,
        open_terrain_percentage=95,
        obstruction_density_per_km2=10,
        average_obstruction_height_m=3,
    )
    urban_scores = terrain_category_scores(
        built_up_area_percentage=70,
        vegetation_area_percentage=5,
        open_terrain_percentage=25,
        obstruction_density_per_km2=2000,
        average_obstruction_height_m=25,
    )

    assert suggested_category_range(open_scores, 2, 10) == "TC1.5-TC2"
    assert suggested_category_range(urban_scores, 70, 2000) == "TC3-TC4"
    assert (
        confidence_from_evidence(
            obstruction_count=6,
            height_coverage_percentage=100,
            obstruction_result_status="ok",
            sources={"DSM_DTM", "manual_verified"},
        )
        == "high"
    )
    assert (
        confidence_from_evidence(
            obstruction_count=2,
            height_coverage_percentage=100,
            obstruction_result_status="ok",
            sources={"DSM_DTM"},
        )
        == "low"
    )

    results = run_terrain_category_validation_cases()
    assert len(DEFAULT_TERRAIN_CATEGORY_VALIDATION_CASES) == 6
    assert {result.case.case_id for result in results} == {
        "tc-coastal-open-terrain",
        "tc-suburban-housing",
        "tc-dense-suburban",
        "tc-industrial-estate",
        "tc-cbd",
        "tc-rural-vegetation",
    }
    assert all(result.status == "pass" for result in results)
