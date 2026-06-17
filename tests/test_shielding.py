"""Tests for preliminary shielding-sector analysis."""

from __future__ import annotations

import math

import pytest

from openwind_au.geo import EARTH_RADIUS_M
from openwind_au.models import SiteLocation
from openwind_au.obstructions import build_obstruction_records
from openwind_au.shielding import ms_from_shielding_parameter, run_shielding_sector_analysis

SITE_LAT = -33.86
SITE_LON = 151.21


def local_to_lonlat(east_m: float, north_m: float) -> tuple[float, float]:
    latitude = SITE_LAT + math.degrees(north_m / EARTH_RADIUS_M)
    longitude = SITE_LON + math.degrees(
        east_m / (EARTH_RADIUS_M * math.cos(math.radians(SITE_LAT)))
    )
    return longitude, latitude


def rectangle_footprint(
    source_id: str,
    center_east_m: float,
    center_north_m: float,
    width_east_m: float,
    width_north_m: float,
    height_m: float,
) -> dict:
    half_east = width_east_m / 2
    half_north = width_north_m / 2
    ring = [
        local_to_lonlat(center_east_m - half_east, center_north_m - half_north),
        local_to_lonlat(center_east_m + half_east, center_north_m - half_north),
        local_to_lonlat(center_east_m + half_east, center_north_m + half_north),
        local_to_lonlat(center_east_m - half_east, center_north_m + half_north),
        local_to_lonlat(center_east_m - half_east, center_north_m - half_north),
    ]
    return {
        "source_id": source_id,
        "footprint_geometry": {"type": "Polygon", "coordinates": [ring]},
        "tags": {"height": str(height_m)},
    }


def site() -> SiteLocation:
    return SiteLocation(
        latitude=SITE_LAT,
        longitude=SITE_LON,
        ground_elevation_m=0,
        source="test",
    )


def test_shielding_sector_filters_by_direction_radius_and_height() -> None:
    records = build_obstruction_records(
        [
            rectangle_footprint("north-valid", 0, 100, 20, 10, 12),
            rectangle_footprint("north-low", 0, 90, 20, 10, 8),
            rectangle_footprint("north-too-far", 0, 250, 20, 10, 12),
            rectangle_footprint("north-east-outside-sector", 100, 100, 20, 10, 12),
        ],
        site_latitude=SITE_LAT,
        site_longitude=SITE_LON,
        radius_m=300,
    )

    sectors = run_shielding_sector_analysis(site(), records, subject_height_m=10)
    north = next(sector for sector in sectors if sector.direction == "N")

    assert north.sector_radius_m == pytest.approx(200)
    assert north.sector_start_deg == pytest.approx(337.5)
    assert north.sector_end_deg == pytest.approx(22.5)
    assert north.ns == 1
    assert north.included_obstruction_ids == ["north-valid"]
    assert north.average_hs_m == pytest.approx(12)
    assert north.average_bs_m == pytest.approx(20, abs=0.2)
    assert north.ls_m == pytest.approx(150)
    assert north.s == pytest.approx(150 / math.sqrt(12 * 20), rel=0.01)
    assert 0.9 < north.indicative_ms < 1.0


def test_empty_sector_reports_ms_one() -> None:
    sectors = run_shielding_sector_analysis(site(), [], subject_height_m=10)

    assert all(sector.ns == 0 for sector in sectors)
    assert all(sector.indicative_ms == 1.0 for sector in sectors)


def test_sector_confidence_counts_estimated_and_unknown_heights() -> None:
    records = build_obstruction_records(
        [
            rectangle_footprint("north-high", 0, 100, 20, 10, 12),
            rectangle_footprint("north-estimated", 5, 120, 20, 10, 14),
            rectangle_footprint("north-unknown", -5, 140, 20, 10, 5),
        ],
        site_latitude=SITE_LAT,
        site_longitude=SITE_LON,
        radius_m=300,
    )
    records[0] = records[0].model_copy(
        update={
            "height_source": "DSM_DTM",
            "confidence": "high",
            "review_required": False,
            "manual_review_required": False,
        }
    )
    records[1] = records[1].model_copy(
        update={
            "height_source": "ESTIMATED",
            "confidence": "low",
            "review_required": True,
            "manual_review_required": True,
        }
    )
    records[2] = records[2].model_copy(
        update={
            "height_m": None,
            "selected_height_m": None,
            "height_source": "missing",
            "confidence": "unknown",
        }
    )

    sectors = run_shielding_sector_analysis(site(), records, subject_height_m=10)
    north = next(sector for sector in sectors if sector.direction == "N")

    assert north.ns == 2
    assert north.high_confidence_count == 1
    assert north.estimated_height_count == 1
    assert north.unknown_height_count == 1
    assert north.overall_confidence == "low"
    assert any("estimated obstruction heights" in warning for warning in north.warnings)
    assert any("unknown heights" in warning for warning in north.warnings)


def test_ms_interpolation_thresholds() -> None:
    assert ms_from_shielding_parameter(1.0) == pytest.approx(0.7)
    assert ms_from_shielding_parameter(3.0) == pytest.approx(0.8)
    assert ms_from_shielding_parameter(4.5) == pytest.approx(0.85)
    assert ms_from_shielding_parameter(12.0) == pytest.approx(1.0)
