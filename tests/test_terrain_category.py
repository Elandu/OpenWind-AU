"""Tests for terrain category evidence calculations."""

from __future__ import annotations

import math

import geopandas as gpd
import numpy as np
import pyproj
import pytest
from affine import Affine
from shapely.geometry import Point, Polygon

from openwind_au.geo import EARTH_RADIUS_M
from openwind_au.models import ObstructionInventoryRequest, SiteAnalysisRequest, SiteAnalysisResult
from openwind_au.obstructions import run_obstruction_inventory
from openwind_au.terrain import generate_standard_terrain_profiles
from openwind_au.terrain_category import (
    classify_terrain_category,
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
MOUNT_ARCHER_LAT = -23.333456
MOUNT_ARCHER_LON = 150.571578


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


def empty_osm_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"category": [], "height_m": []}, geometry=[], crs="EPSG:4326")


def local_utm_for(point: Point) -> tuple[pyproj.CRS, pyproj.Transformer, pyproj.Transformer]:
    zone = int((point.x + 180) // 6) + 1
    epsg = (32600 if point.y >= 0 else 32700) + zone
    crs = pyproj.CRS.from_epsg(epsg)
    return (
        crs,
        pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True),
        pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True),
    )


def local_polygon_gdf(
    site: Point,
    records: list[tuple[float, float, float, str, float]],
) -> gpd.GeoDataFrame:
    _crs, to_local, to_wgs84 = local_utm_for(site)
    site_x, site_y = to_local.transform(site.x, site.y)
    rows = []
    geometries = []
    for east_m, north_m, width_m, category, height_m in records:
        half = width_m / 2
        corners = [
            (site_x + east_m - half, site_y + north_m - half),
            (site_x + east_m + half, site_y + north_m - half),
            (site_x + east_m + half, site_y + north_m + half),
            (site_x + east_m - half, site_y + north_m + half),
        ]
        geometries.append(Polygon([to_wgs84.transform(x, y) for x, y in corners]))
        rows.append({"category": category, "height_m": height_m})
    return gpd.GeoDataFrame(rows, geometry=geometries, crs="EPSG:4326")


def local_landcover_raster(
    site: Point,
    raster: np.ndarray,
    resolution_m: float = 10.0,
) -> tuple[np.ndarray, Affine, pyproj.CRS]:
    crs, to_local, _to_wgs84 = local_utm_for(site)
    site_x, site_y = to_local.transform(site.x, site.y)
    height, width = raster.shape
    west = site_x - (width * resolution_m) / 2
    north = site_y + (height * resolution_m) / 2
    transform = Affine.translation(west, north) * Affine.scale(resolution_m, -resolution_m)
    return raster, transform, crs


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
        features=analyse_topography(profiles, 50, average_roof_height_m=10.0),
        assumptions=[],
        limitations=[],
    )


def test_polygon_area_uses_local_projection() -> None:
    geometry = footprint("area", 0, 100, 20, {"building": "yes"})["footprint_geometry"]

    assert polygon_area_m2(geometry, SITE_LAT, SITE_LON) == pytest.approx(400, rel=0.03)


def test_classify_terrain_category_empty_sources_returns_tc1() -> None:
    site = Point(SITE_LON, SITE_LAT)

    result = classify_terrain_category(
        site,
        empty_osm_gdf(),
        None,
        None,
        None,
        {},
    )

    assert result.terrain_class == "TC1"
    assert result["class"] == "TC1"
    assert result.source_coverage == "none"
    assert set(result.per_direction.values()) == {"TC1"}


def test_classify_terrain_category_osm_only_dense_suburban_buildings() -> None:
    site = Point(SITE_LON, SITE_LAT)
    buildings = [(0, 25 + index * 4, 8, "building", 8.0) for index in range(30)]

    result = classify_terrain_category(
        site,
        local_polygon_gdf(site, buildings),
        None,
        None,
        None,
        {},
        radius_m=180,
    )

    assert result.terrain_class == "TC3"
    assert result.source_coverage == "osm_only"
    assert result.obstruction_density_per_ha >= 8
    assert result.average_obstruction_height_m == pytest.approx(8)


def test_classify_terrain_category_raster_only_built_up_with_river() -> None:
    site = Point(SITE_LON, SITE_LAT)
    raster = np.full((50, 50), 50, dtype=np.uint8)
    raster[:, 20:30] = 80
    raster, transform, crs = local_landcover_raster(site, raster)

    result = classify_terrain_category(
        site,
        empty_osm_gdf(),
        raster,
        transform,
        crs,
        {},
        radius_m=250,
    )

    assert result.terrain_class in {"TC3", "TC4"}
    assert result.source_coverage == "raster_only"
    assert result.built_fraction > 0
    assert result.water_fraction > 0


def test_classify_terrain_category_mount_archer_fixture_shape() -> None:
    site = Point(MOUNT_ARCHER_LON, MOUNT_ARCHER_LAT)
    raster = np.full((50, 50), 50, dtype=np.uint8)
    raster[0:10, :] = 10
    raster[:, 0:5] = 10
    raster, transform, crs = local_landcover_raster(site, raster)
    buildings = [
        (-80, 90, 12, "building", 8.0),
        (-40, 120, 12, "building", 8.0),
        (0, 140, 12, "building", 8.0),
        (40, 120, 12, "building", 8.0),
        (80, 90, 12, "building", 8.0),
        (90, -80, 12, "building", 8.0),
        (120, -40, 12, "building", 8.0),
        (-120, -40, 12, "building", 8.0),
    ]

    result = classify_terrain_category(
        site,
        local_polygon_gdf(site, buildings),
        raster,
        transform,
        crs,
        {},
        radius_m=250,
    )

    assert result.terrain_class == "TC3"
    assert result.source_coverage == "osm+raster"
    assert set(result.per_direction) == {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}
    assert "worst=TC3" in result.reasoning


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
