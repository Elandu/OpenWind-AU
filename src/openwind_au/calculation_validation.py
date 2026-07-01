"""Deterministic calculation validation for shielding and topographic screening."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from openwind_au.geo import EARTH_RADIUS_M
from openwind_au.models import ObstructionRecord, SiteLocation, TerrainPoint, TerrainProfile
from openwind_au.shielding import (
    footprint_breadth_normal_to_wind,
    ms_from_shielding_parameter,
    run_shielding_sector_analysis,
)
from openwind_au.topography import analyse_profile_topography

CalculationValidationStatus = Literal["pass", "fail"]

SITE_LAT = -33.86
SITE_LON = 151.21


class CalculationValidationCheck(BaseModel):
    """One deterministic calculation check within a validation case."""

    field: str
    expected: Any
    actual: Any
    tolerance: float | None = None
    status: CalculationValidationStatus


class CalculationValidationCaseResult(BaseModel):
    """Result for one deterministic calculation validation case."""

    case_id: str
    calculation_area: Literal["shielding", "topography"]
    description: str
    status: CalculationValidationStatus
    checks: list[CalculationValidationCheck] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CalculationValidationReport(BaseModel):
    """Complete deterministic calculation validation report."""

    generated_at_utc: str
    disclaimer: str
    summary: dict[str, int]
    results: list[CalculationValidationCaseResult]


CALCULATION_VALIDATION_DISCLAIMER = (
    "Calculation validation cases use synthetic geometry and terrain profiles with known "
    "expected outputs. Passing these checks verifies implementation consistency for the "
    "covered formulas only; it does not certify AS/NZS 1170.2 compliance or public dataset "
    "accuracy."
)


def run_calculation_validation_cases() -> CalculationValidationReport:
    """Run deterministic shielding and topographic calculation checks."""

    results = [
        _shielding_ms_interpolation_case(),
        _shielding_sector_reference_case(),
        _shielding_height_rejection_case(),
        _topography_flat_threshold_case(),
        _topography_ridge_reference_case(),
        _topography_escarpment_reference_case(),
        _topography_valley_reference_case(),
        _topography_hill_reference_case(),
    ]
    summary = {"pass": 0, "fail": 0}
    for result in results:
        summary[result.status] += 1
    return CalculationValidationReport(
        generated_at_utc=datetime.now(UTC).isoformat(),
        disclaimer=CALCULATION_VALIDATION_DISCLAIMER,
        summary=summary,
        results=results,
    )


def calculation_validation_report_to_json(report: CalculationValidationReport) -> dict:
    """Convert a calculation validation report into JSON-serialisable data."""

    return json.loads(report.model_dump_json())


def _shielding_ms_interpolation_case() -> CalculationValidationCaseResult:
    checks = [
        _check_close("Ms at s=1.0", ms_from_shielding_parameter(1.0), 0.7),
        _check_close("Ms at s=3.0", ms_from_shielding_parameter(3.0), 0.8),
        _check_close("Ms at s=4.5", ms_from_shielding_parameter(4.5), 0.85),
        _check_close("Ms at s=12.0", ms_from_shielding_parameter(12.0), 1.0),
    ]
    return _case_result(
        case_id="shielding-ms-table-interpolation",
        calculation_area="shielding",
        description="Validates piecewise-linear indicative Ms interpolation thresholds.",
        checks=checks,
    )


def _shielding_sector_reference_case() -> CalculationValidationCaseResult:
    records = [_obstruction_record("north-reference", 0, 100, 20, 10, 12)]
    north = next(
        sector
        for sector in run_shielding_sector_analysis(_site(), records, subject_height_m=10)
        if sector.direction == "N"
    )
    expected_s = 150.0 / math.sqrt(12.0 * 20.0)
    expected_ms = ms_from_shielding_parameter(expected_s)
    breadth = footprint_breadth_normal_to_wind(
        records[0].footprint_geometry,
        SITE_LAT,
        SITE_LON,
        0.0,
    )
    checks = [
        _check_equal("included obstruction count ns", north.ns, 1),
        _check_equal("included IDs", north.included_obstruction_ids, ["north-reference"]),
        _check_close("average shielding height hs", north.average_hs_m, 12.0),
        _check_close("average breadth normal to wind bs", north.average_bs_m, 20.0, 0.25),
        _check_close("direct breadth projection", breadth, 20.0, 0.25),
        _check_close("spacing length ls", north.ls_m, 150.0),
        _check_close("shielding parameter s", north.s, expected_s, 0.01),
        _check_close("indicative Ms", north.indicative_ms, expected_ms, 0.001),
    ]
    return _case_result(
        case_id="shielding-single-obstruction-reference",
        calculation_area="shielding",
        description=(
            "Validates sector inclusion, hs, bs, ls, s, and indicative Ms for one known "
            "north-sector obstruction."
        ),
        checks=checks,
    )


def _shielding_height_rejection_case() -> CalculationValidationCaseResult:
    records = [
        _obstruction_record("north-low", 0, 90, 20, 10, 8),
        _obstruction_record("north-missing", 5, 110, 20, 10, 5),
    ]
    records[1] = records[1].model_copy(
        update={"height_m": None, "selected_height_m": None, "height_source": "missing"}
    )
    north = next(
        sector
        for sector in run_shielding_sector_analysis(_site(), records, subject_height_m=10)
        if sector.direction == "N"
    )
    checks = [
        _check_equal("included obstruction count ns", north.ns, 0),
        _check_equal("height below subject rejections", north.rejected_height_below_z_count, 1),
        _check_equal("missing height rejections", north.rejected_height_missing_count, 1),
        _check_equal(
            "rejection reason counts",
            north.rejection_reason_counts,
            {"height_below_subject": 1, "height_missing": 1},
        ),
        _check_close("empty-sector indicative Ms", north.indicative_ms, 1.0),
    ]
    return _case_result(
        case_id="shielding-height-rejection-reference",
        calculation_area="shielding",
        description="Validates low-height and missing-height rejection accounting.",
        checks=checks,
    )


def _topography_flat_threshold_case() -> CalculationValidationCaseResult:
    feature = analyse_profile_topography(_profile([100, 101, 104.9, 101, 100]), 100)
    checks = [
        _check_equal("feature type", feature.feature_type, "no significant feature"),
        _check_close("reported H", feature.h_m, 0.0),
        _check_close("reported Lu", feature.lu_m, 0.0),
    ]
    return _case_result(
        case_id="topography-relief-threshold-reference",
        calculation_area="topography",
        description="Validates that sub-5 m local relief is screened out.",
        checks=checks,
    )


def _topography_ridge_reference_case() -> CalculationValidationCaseResult:
    feature = analyse_profile_topography(_profile([100, 105, 125, 105, 100]), 100)
    checks = [
        _check_equal("feature type", feature.feature_type, "ridge"),
        _check_close("crest RL", feature.crest_rl_m, 125.0),
        _check_close("base RL", feature.base_rl_m, 100.0),
        _check_close("H", feature.h_m, 25.0),
        _check_close("Lu", feature.lu_m, 200.0),
        _check_close("average upwind slope", feature.average_upwind_slope, 0.125),
    ]
    return _case_result(
        case_id="topography-ridge-reference",
        calculation_area="topography",
        description="Validates ridge candidate geometry on a symmetric synthetic profile.",
        checks=checks,
    )


def _topography_escarpment_reference_case() -> CalculationValidationCaseResult:
    feature = analyse_profile_topography(_profile([100, 100, 130, 132, 132]), 100)
    checks = [
        _check_equal("feature type", feature.feature_type, "escarpment"),
        _check_close("H", feature.h_m, 30.0),
        _check_close("Lu", feature.lu_m, 100.0),
        _check_close("average upwind slope", feature.average_upwind_slope, 0.3),
        _check_equal("confidence", feature.confidence, "medium"),
    ]
    return _case_result(
        case_id="topography-escarpment-reference",
        calculation_area="topography",
        description="Validates steep adjacent-sample escarpment detection.",
        checks=checks,
    )


def _topography_valley_reference_case() -> CalculationValidationCaseResult:
    feature = analyse_profile_topography(_profile([120, 110, 90, 110, 120]), 100)
    checks = [
        _check_equal("feature type", feature.feature_type, "valley"),
        _check_close("base RL", feature.base_rl_m, 90.0),
        _check_close("crest RL", feature.crest_rl_m, 120.0),
        _check_close("H", feature.h_m, 30.0),
        _check_close("x", feature.x_m, 200.0),
    ]
    return _case_result(
        case_id="topography-valley-reference",
        calculation_area="topography",
        description="Validates valley candidate geometry on a symmetric synthetic profile.",
        checks=checks,
    )


def _topography_hill_reference_case() -> CalculationValidationCaseResult:
    feature = analyse_profile_topography(_profile([100, 105, 112, 122, 135]), 100)
    checks = [
        _check_equal("feature type", feature.feature_type, "hill"),
        _check_close("crest RL", feature.crest_rl_m, 135.0),
        _check_close("base RL", feature.base_rl_m, 100.0),
        _check_close("H", feature.h_m, 35.0),
        _check_close("Lu", feature.lu_m, 400.0),
        _check_close("crest x", feature.crest_x_m, 400.0),
    ]
    return _case_result(
        case_id="topography-hill-reference",
        calculation_area="topography",
        description="Validates endpoint-rising hill candidate geometry.",
        checks=checks,
    )


def _case_result(
    *,
    case_id: str,
    calculation_area: Literal["shielding", "topography"],
    description: str,
    checks: list[CalculationValidationCheck],
) -> CalculationValidationCaseResult:
    status: CalculationValidationStatus = (
        "pass" if all(check.status == "pass" for check in checks) else "fail"
    )
    return CalculationValidationCaseResult(
        case_id=case_id,
        calculation_area=calculation_area,
        description=description,
        status=status,
        checks=checks,
    )


def _check_equal(field: str, actual: Any, expected: Any) -> CalculationValidationCheck:
    status: CalculationValidationStatus = "pass" if actual == expected else "fail"
    return CalculationValidationCheck(
        field=field,
        expected=expected,
        actual=actual,
        status=status,
    )


def _check_close(
    field: str,
    actual: float | None,
    expected: float,
    tolerance: float = 1e-9,
) -> CalculationValidationCheck:
    if actual is None:
        status: CalculationValidationStatus = "fail"
    else:
        status = "pass" if abs(actual - expected) <= tolerance else "fail"
    return CalculationValidationCheck(
        field=field,
        expected=expected,
        actual=actual,
        tolerance=tolerance,
        status=status,
    )


def _site() -> SiteLocation:
    return SiteLocation(
        latitude=SITE_LAT,
        longitude=SITE_LON,
        ground_elevation_m=0.0,
        source="calculation validation synthetic site",
    )


def _profile(elevations: list[float], direction: str = "N") -> TerrainProfile:
    points = [
        TerrainPoint(
            distance_m=float(index * 100),
            latitude=SITE_LAT,
            longitude=SITE_LON,
            elevation_m=elevation,
        )
        for index, elevation in enumerate(elevations)
    ]
    return TerrainProfile(
        direction=direction,  # type: ignore[arg-type]
        azimuth_deg=0.0,
        radius_m=int(points[-1].distance_m),
        endpoint_latitude=points[-1].latitude,
        endpoint_longitude=points[-1].longitude,
        points=points,
        min_elevation_m=min(elevations),
        max_elevation_m=max(elevations),
        average_slope=(elevations[-1] - elevations[0]) / max(points[-1].distance_m, 1),
    )


def _rectangle_footprint(
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
        _local_to_lonlat(center_east_m - half_east, center_north_m - half_north),
        _local_to_lonlat(center_east_m + half_east, center_north_m - half_north),
        _local_to_lonlat(center_east_m + half_east, center_north_m + half_north),
        _local_to_lonlat(center_east_m - half_east, center_north_m + half_north),
        _local_to_lonlat(center_east_m - half_east, center_north_m - half_north),
    ]
    return {
        "source_id": source_id,
        "footprint_geometry": {"type": "Polygon", "coordinates": [ring]},
        "tags": {"height": str(height_m)},
    }



def _obstruction_record(
    obstruction_id: str,
    center_east_m: float,
    center_north_m: float,
    width_east_m: float,
    width_north_m: float,
    height_m: float,
) -> ObstructionRecord:
    geometry = _rectangle_footprint(
        obstruction_id,
        center_east_m,
        center_north_m,
        width_east_m,
        width_north_m,
        height_m,
    )["footprint_geometry"]
    centroid_longitude, centroid_latitude = _local_to_lonlat(center_east_m, center_north_m)
    distance_m = math.hypot(center_east_m, center_north_m)
    bearing_deg = (math.degrees(math.atan2(center_east_m, center_north_m)) + 360.0) % 360.0
    return ObstructionRecord(
        obstruction_id=obstruction_id,
        source_id=obstruction_id,
        footprint_geometry=geometry,
        centroid_latitude=centroid_latitude,
        centroid_longitude=centroid_longitude,
        distance_m=distance_m,
        bearing_deg=bearing_deg,
        height_m=height_m,
        selected_height_m=height_m,
        raw_source_height_m=height_m,
        raw_source_height_source="OSM_HEIGHT",
        estimated_height_m=None,
        ground_rl_m=None,
        surface_rl_m=None,
        obstruction_height_m=None,
        building_levels=None,
        height_source="OSM_HEIGHT",
        confidence="medium",
        enrichment_method=None,
        manual_review_required=False,
        review_required=False,
        footprint_source="OSM",
    )

def _local_to_lonlat(east_m: float, north_m: float) -> tuple[float, float]:
    latitude = SITE_LAT + math.degrees(north_m / EARTH_RADIUS_M)
    longitude = SITE_LON + math.degrees(
        east_m / (EARTH_RADIUS_M * math.cos(math.radians(SITE_LAT)))
    )
    return longitude, latitude
