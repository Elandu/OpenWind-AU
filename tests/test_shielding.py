"""Tests for preliminary shielding-sector analysis."""

from __future__ import annotations

import json
import math

import pytest

import openwind_au.shielding as shielding_module
from openwind_au.errors import ServiceNotReadyError
from openwind_au.geo import EARTH_RADIUS_M
from openwind_au.models import SiteLocation
from openwind_au.obstructions import build_obstruction_records
from openwind_au.shielding import (
    footprint_breadth_normal_to_wind,
    run_shielding_sector_analysis,
)
from openwind_au.standard_calculations import (
    ms_from_shielding_parameter,
    shielding_reduction_height_limit_m,
)
from openwind_au.standard_lookup_tables import (
    MS_DATA_FILE,
    MS_EXPECTED_SHA256_ENV,
    MS_TABLE_ENV,
    canonical_values_sha256,
    load_packaged_lookup_data,
)

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


def rotated_rectangle_footprint(
    source_id: str,
    center_east_m: float,
    center_north_m: float,
    length_m: float,
    width_m: float,
    rotation_deg: float,
    height_m: float,
) -> dict:
    half_length = length_m / 2
    half_width = width_m / 2
    theta = math.radians(rotation_deg)
    corners = [
        (-half_length, -half_width),
        (half_length, -half_width),
        (half_length, half_width),
        (-half_length, half_width),
        (-half_length, -half_width),
    ]
    ring = []
    for along, across in corners:
        east = center_east_m + along * math.cos(theta) - across * math.sin(theta)
        north = center_north_m + along * math.sin(theta) + across * math.cos(theta)
        ring.append(local_to_lonlat(east, north))
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
    assert north.total_obstructions_in_sector == 2
    assert north.usable_height_count == 2
    assert north.rejected_height_below_z_count == 1
    assert north.rejected_height_missing_count == 0
    assert north.ns == 1
    assert north.included_obstruction_ids == ["north-valid"]
    assert north.average_hs_m == pytest.approx(12)
    assert north.average_bs_m == pytest.approx(20, abs=0.2)
    assert north.ls_m == pytest.approx(150)
    assert north.s == pytest.approx(150 / math.sqrt(12 * 20), rel=0.01)
    assert 0.9 < north.indicative_ms < 1.0


def test_cardinal_and_intercardinal_sector_orientation_points_upwind() -> None:
    placements = {
        "N": (0, 100),
        "NE": (70, 70),
        "E": (100, 0),
        "SE": (70, -70),
        "S": (0, -100),
        "SW": (-70, -70),
        "W": (-100, 0),
        "NW": (-70, 70),
    }
    records = build_obstruction_records(
        [
            rectangle_footprint(direction, east, north, 12, 12, 15)
            for direction, (east, north) in placements.items()
        ],
        site_latitude=SITE_LAT,
        site_longitude=SITE_LON,
        radius_m=300,
    )

    sectors = run_shielding_sector_analysis(site(), records, subject_height_m=10)

    for direction in placements:
        sector = next(item for item in sectors if item.direction == direction)
        assert sector.included_obstruction_ids == [direction]
        assert sector.ns == 1


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


def test_selected_estimated_height_is_usable_for_preliminary_shielding() -> None:
    records = build_obstruction_records(
        [rectangle_footprint("north-estimated", 0, 100, 20, 10, 5)],
        site_latitude=SITE_LAT,
        site_longitude=SITE_LON,
        radius_m=300,
    )
    records[0] = records[0].model_copy(
        update={
            "height_m": None,
            "selected_height_m": 12,
            "height_source": "ESTIMATED",
            "confidence": "low",
            "review_required": True,
            "manual_review_required": True,
        }
    )

    sectors = run_shielding_sector_analysis(site(), records, subject_height_m=10)
    north = next(sector for sector in sectors if sector.direction == "N")

    assert north.ns == 1
    assert north.average_hs_m == pytest.approx(12)
    assert north.overall_confidence == "low"
    assert any("Estimated or DSM-DTM heights" in warning for warning in north.warnings)


def test_vegetation_is_not_permitted_to_provide_shielding() -> None:
    records = build_obstruction_records(
        [rectangle_footprint("tree-row", 0, 100, 30, 10, 12)],
        site_latitude=SITE_LAT,
        site_longitude=SITE_LON,
        radius_m=300,
    )
    records[0] = records[0].model_copy(
        update={
            "classification": "vegetation",
            "height_source": "DSM_DTM",
            "confidence": "low",
            "review_required": True,
            "manual_review_required": True,
        }
    )

    sectors = run_shielding_sector_analysis(site(), records, subject_height_m=10)
    north = next(sector for sector in sectors if sector.direction == "N")

    assert north.ns == 0
    assert north.indicative_ms == 1.0
    assert north.included_obstruction_ids == []
    assert north.rejection_reason_counts == {"vegetation_not_permitted": 1}


def test_structure_over_25_m_has_no_shielding_reduction() -> None:
    records = build_obstruction_records(
        [rectangle_footprint("tower", 0, 100, 30, 20, 40)],
        site_latitude=SITE_LAT,
        site_longitude=SITE_LON,
        radius_m=600,
    )

    sectors = run_shielding_sector_analysis(site(), records, subject_height_m=26)
    north = next(sector for sector in sectors if sector.direction == "N")

    assert north.ns == 0
    assert north.indicative_ms == 1.0
    assert any("greater than 25 m" in warning for warning in north.warnings)


def test_steep_slope_building_below_subject_top_is_rejected() -> None:
    records = build_obstruction_records(
        [rectangle_footprint("steep-low", 0, 40, 20, 10, 10)],
        site_latitude=SITE_LAT,
        site_longitude=SITE_LON,
        radius_m=300,
    )
    records[0] = records[0].model_copy(update={"ground_rl_m": -10.0})

    sectors = run_shielding_sector_analysis(site(), records, subject_height_m=10)
    north = next(sector for sector in sectors if sector.direction == "N")

    assert north.ns == 0
    assert north.rejection_reason_counts == {"steep_upwind_ground_gradient": 1}


def test_steep_slope_building_above_subject_top_is_retained_for_review() -> None:
    records = build_obstruction_records(
        [rectangle_footprint("steep-tall", 0, 40, 20, 10, 30)],
        site_latitude=SITE_LAT,
        site_longitude=SITE_LON,
        radius_m=300,
    )
    records[0] = records[0].model_copy(update={"ground_rl_m": -10.0})

    sectors = run_shielding_sector_analysis(site(), records, subject_height_m=10)
    north = next(sector for sector in sectors if sector.direction == "N")

    assert north.ns == 1
    assert north.rejection_reason_counts == {}
    assert any("common datum exceeds the subject building" in warning for warning in north.warnings)


def test_steep_slope_building_equal_to_subject_top_is_rejected() -> None:
    records = build_obstruction_records(
        [rectangle_footprint("steep-equal", 0, 40, 20, 10, 20)],
        site_latitude=SITE_LAT,
        site_longitude=SITE_LON,
        radius_m=300,
    )
    records[0] = records[0].model_copy(update={"ground_rl_m": -10.0})

    sectors = run_shielding_sector_analysis(site(), records, subject_height_m=10)
    north = next(sector for sector in sectors if sector.direction == "N")

    assert north.ns == 0
    assert north.rejection_reason_counts == {"steep_upwind_ground_gradient": 1}


def test_reviewed_surface_rl_controls_steep_slope_common_datum_check() -> None:
    records = build_obstruction_records(
        [rectangle_footprint("steep-surface", 0, 40, 20, 10, 30)],
        site_latitude=SITE_LAT,
        site_longitude=SITE_LON,
        radius_m=300,
    )
    records[0] = records[0].model_copy(
        update={
            "ground_rl_m": -10.0,
            "surface_rl_m": 8.0,
            "height_source": "DSM_DTM",
            "selected_height_m": 18.0,
        }
    )

    sectors = run_shielding_sector_analysis(site(), records, subject_height_m=10)
    north = next(sector for sector in sectors if sector.direction == "N")

    assert north.ns == 0
    assert north.rejection_reason_counts == {"steep_upwind_ground_gradient": 1}


def test_missing_height_rejection_is_reported() -> None:
    records = build_obstruction_records(
        [rectangle_footprint("missing", 0, 100, 20, 10, 5)],
        site_latitude=SITE_LAT,
        site_longitude=SITE_LON,
        radius_m=300,
    )
    records[0] = records[0].model_copy(
        update={
            "height_m": None,
            "selected_height_m": None,
            "height_source": "missing",
            "confidence": "unknown",
        }
    )

    sectors = run_shielding_sector_analysis(site(), records, subject_height_m=10)
    north = next(sector for sector in sectors if sector.direction == "N")

    assert north.ns == 0
    assert north.indicative_ms == 1.0
    assert north.rejected_height_missing_count == 1
    assert north.rejection_reason_counts == {"height_missing": 1}
    assert north.rejected_obstructions[0]["obstruction_id"] == "missing"


def test_dense_low_rise_suburb_subject_8_5_gets_estimated_shielding_candidates() -> None:
    records = build_obstruction_records(
        [
            rectangle_footprint(f"house-{index}", east, north, 18, 10, 1)
            for index, (east, north) in enumerate(
                [(0, 80), (30, 90), (-30, 90), (70, 70), (-70, 70)],
                start=1,
            )
        ],
        site_latitude=SITE_LAT,
        site_longitude=SITE_LON,
        radius_m=300,
    )
    records = [
        record.model_copy(
            update={
                "classification": "residential",
                "height_m": None,
                "selected_height_m": 9.0,
                "height_source": "ESTIMATED",
                "confidence": "low",
            }
        )
        for record in records
    ]
    sectors = run_shielding_sector_analysis(site(), records, subject_height_m=8.5)

    assert any(sector.ns > 0 for sector in sectors)
    assert any(sector.indicative_ms < 1.0 for sector in sectors)


def test_low_rise_suburb_subject_20_rejects_estimated_low_heights() -> None:
    records = build_obstruction_records(
        [
            rectangle_footprint(f"house-{index}", east, north, 18, 10, 1)
            for index, (east, north) in enumerate([(0, 80), (30, 90), (-30, 90)], start=1)
        ],
        site_latitude=SITE_LAT,
        site_longitude=SITE_LON,
        radius_m=500,
    )
    records = [
        record.model_copy(
            update={
                "classification": "residential",
                "height_m": None,
                "selected_height_m": 9.0,
                "height_source": "ESTIMATED",
                "confidence": "low",
            }
        )
        for record in records
    ]
    sectors = run_shielding_sector_analysis(site(), records, subject_height_m=20)

    north = next(sector for sector in sectors if sector.direction == "N")
    assert north.ns == 0
    assert north.indicative_ms == 1.0
    assert north.rejected_height_below_z_count == 3


def test_breadth_uses_footprint_projection_normal_to_wind() -> None:
    parallel_to_north_wind = rectangle_footprint("parallel", 0, 100, 5, 30, 12)
    normal_to_north_wind = rectangle_footprint("normal", 0, 100, 30, 5, 12)
    diagonal_to_north_wind = rotated_rectangle_footprint("diagonal", 0, 100, 30, 10, 45, 12)

    assert footprint_breadth_normal_to_wind(
        parallel_to_north_wind["footprint_geometry"],
        SITE_LAT,
        SITE_LON,
        0,
    ) == pytest.approx(5, abs=0.2)
    assert footprint_breadth_normal_to_wind(
        normal_to_north_wind["footprint_geometry"],
        SITE_LAT,
        SITE_LON,
        0,
    ) == pytest.approx(30, abs=0.2)
    assert footprint_breadth_normal_to_wind(
        diagonal_to_north_wind["footprint_geometry"],
        SITE_LAT,
        SITE_LON,
        0,
    ) == pytest.approx((30 + 10) / math.sqrt(2), abs=0.3)


def test_ms_interpolation_thresholds() -> None:
    assert ms_from_shielding_parameter(0.0) == pytest.approx(0.7)
    assert ms_from_shielding_parameter(1.5) == pytest.approx(0.7)
    assert ms_from_shielding_parameter(3.0) == pytest.approx(0.8)
    assert ms_from_shielding_parameter(4.5) == pytest.approx(0.85)
    assert ms_from_shielding_parameter(6.0) == pytest.approx(0.9)
    assert ms_from_shielding_parameter(12.0) == pytest.approx(1.0)
    assert ms_from_shielding_parameter(20.0) == pytest.approx(1.0)
    assert shielding_reduction_height_limit_m() == pytest.approx(25.0)
    with pytest.raises(ValueError, match="finite"):
        ms_from_shielding_parameter(float("nan"))
    with pytest.raises(ValueError, match="finite"):
        ms_from_shielding_parameter(float("inf"))
    with pytest.raises(ValueError, match="not be negative"):
        ms_from_shielding_parameter(-0.1)


def test_shielding_analysis_uses_one_lookup_snapshot(monkeypatch) -> None:
    lookup = load_packaged_lookup_data(MS_DATA_FILE)
    load_count = 0

    def counted_loader():
        nonlocal load_count
        load_count += 1
        return lookup

    monkeypatch.setattr(shielding_module, "load_ms_table", counted_loader)

    sectors = run_shielding_sector_analysis(site(), [], subject_height_m=10)

    assert load_count == 1
    assert len(sectors) == 8


def test_ms_uses_validated_environment_override(monkeypatch, tmp_path) -> None:
    data = load_packaged_lookup_data(MS_DATA_FILE)
    data["values"]["points"][1]["ms"] = 0.81
    data["values_sha256"] = canonical_values_sha256(data)
    path = tmp_path / "ms.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(MS_TABLE_ENV, str(path))
    monkeypatch.setenv(MS_EXPECTED_SHA256_ENV, data["values_sha256"])

    assert ms_from_shielding_parameter(3.0) == pytest.approx(0.81)


def test_ms_rejects_lookup_with_stale_digest(monkeypatch, tmp_path) -> None:
    data = load_packaged_lookup_data(MS_DATA_FILE)
    data["values"]["points"][1]["ms"] = 0.81
    path = tmp_path / "ms.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(MS_TABLE_ENV, str(path))

    with pytest.raises(ServiceNotReadyError, match="values_sha256"):
        ms_from_shielding_parameter(3.0)
