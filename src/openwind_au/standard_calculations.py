"""Lightweight, deterministic AS/NZS 1170.2 calculation primitives."""

from __future__ import annotations

import logging
import math
from typing import Any

from openwind_au.errors import ServiceNotReadyError
from openwind_au.standard_lookup_tables import (
    MD_DATA_FILE,
    MD_TABLE_ENV,
    MS_DATA_FILE,
    MS_EXPECTED_SHA256_ENV,
    MS_TABLE_ENV,
    TRUSTED_PACKAGED_VALUES_SHA256,
    finite_lookup_number,
    load_lookup_data,
    lookup_metadata_warnings,
    lookup_provenance_issues,
    source_reference,
    trusted_values_sha256,
)

DIRECTIONS: tuple[str, ...] = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
SUPPORTED_AU_WIND_REGIONS: tuple[str, ...] = (
    "A",
    "A0",
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "B",
    "B1",
    "B2",
    "C",
    "D",
)
REGIONAL_WIND_SPEED_EQUATIONS: dict[str, tuple[float, float]] = {
    "A": (67.0, 41.0),
    "B": (106.0, 92.0),
    "C": (122.0, 104.0),
    "D": (156.0, 142.0),
}
REGIONAL_WIND_SPEED_V1: dict[str, float] = {
    "A": 30.0,
    "B": 26.0,
    "C": 23.0,
    "D": 23.0,
}
MS_METADATA_WARNING = "Ms lookup table does not have complete independent reviewer/date metadata."
LOGGER = logging.getLogger(__name__)
MS_SOURCE_CLAUSE = "Clause 4.3"
MS_STANDARD_REFERENCE = "AS/NZS 1170.2:2021 Clause 4.3, Table 4.2"
EXPECTED_SHIELDING_PARAMETER_NODES: tuple[float, ...] = (1.5, 3.0, 6.0, 12.0)
EXPECTED_SHIELDING_REDUCTION_HEIGHT_LIMIT_M = 25.0


def table_region_key(region: str, tables: dict[str, Any]) -> str:
    """Return the most specific available table key for a wind-region label."""

    if region in tables:
        return region
    if region.startswith("A") and "A" in tables:
        return "A"
    if region.startswith("B") and "B" in tables:
        return "B"
    return region


def regional_wind_speed(region: str, ari_years: int) -> float:
    """Calculate Australian VR from AS/NZS 1170.2:2021 Table 3.1(A).

    The regional equations apply for R >= 5 years and the result is rounded
    to the nearest 1 m/s. The R=1 row is an explicit table value.
    """

    if region not in SUPPORTED_AU_WIND_REGIONS:
        raise ValueError(f"Unsupported Australian wind region: {region}")
    if ari_years < 1:
        raise ValueError("Annual recurrence interval must be at least 1 year.")
    base_region = table_region_key(region, REGIONAL_WIND_SPEED_EQUATIONS)
    if base_region not in REGIONAL_WIND_SPEED_EQUATIONS:
        raise ValueError(f"Unsupported Australian wind region: {region}")
    if ari_years == 1:
        return REGIONAL_WIND_SPEED_V1[base_region]
    if ari_years < 5:
        raise ValueError(
            "AS/NZS 1170.2:2021 Table 3.1(A) defines V1 and the regional equation for R >= 5; "
            "R must be 1 or at least 5 years."
        )
    constant, coefficient = REGIONAL_WIND_SPEED_EQUATIONS[base_region]
    unrounded = constant - coefficient * ari_years**-0.1
    return float(math.floor(unrounded + 0.5))


def direction_multiplier_values(region: str) -> dict[str, float]:
    """Load the configured Table 3.2(A) direction multipliers for a region."""

    if region not in SUPPORTED_AU_WIND_REGIONS:
        raise ValueError(f"Unsupported Australian wind region: {region}")
    data = load_lookup_data(MD_TABLE_ENV, MD_DATA_FILE)
    table_key = table_region_key(region, data.get("tables", {}))
    row = data.get("tables", {}).get(table_key)
    if not row:
        raise ValueError(f"Unsupported Australian wind region: {region}")
    return {direction: float(row[direction]) for direction in DIRECTIONS}


def ms_from_shielding_parameter(
    s: float,
    data: dict[str, Any] | None = None,
) -> float:
    """Return Ms by linear interpolation from AS/NZS 1170.2:2021 Table 4.2."""

    if not math.isfinite(s):
        raise ValueError("Shielding parameter s must be finite.")
    if s < 0:
        raise ValueError("Shielding parameter s must not be negative.")
    lookup = data if data is not None else load_ms_table()
    issues = shielding_lookup_issues(lookup, require_reviewed=False)
    if issues:
        raise ValueError(f"Invalid Table 4.2 lookup data: {'; '.join(issues)}")
    points = [(float(point["s"]), float(point["ms"])) for point in lookup["values"]["points"]]
    if s <= points[0][0]:
        return points[0][1]
    if s >= points[-1][0]:
        return points[-1][1]
    for (s0, ms0), (s1, ms1) in zip(points, points[1:], strict=True):
        if s <= s1:
            ratio = (s - s0) / (s1 - s0)
            return ms0 + ratio * (ms1 - ms0)
    return points[-1][1]


def load_ms_table() -> dict[str, Any]:
    """Load editable shielding-multiplier lookup data."""

    data = load_lookup_data(MS_TABLE_ENV, MS_DATA_FILE)
    issues = shielding_lookup_issues(data, require_reviewed=False)
    if issues:
        LOGGER.error("Configured Table 4.2 lookup is invalid: %s", "; ".join(issues))
        raise ServiceNotReadyError(f"Invalid Table 4.2 lookup data: {'; '.join(issues)}")
    return data


def shielding_reduction_height_limit_m(data: dict[str, Any] | None = None) -> float:
    """Return the Table 4.2 shielding-reduction building-height limit."""

    lookup = data if data is not None else load_ms_table()
    issues = shielding_lookup_issues(lookup, require_reviewed=False)
    if issues:
        raise ValueError(f"Invalid Table 4.2 lookup data: {'; '.join(issues)}")
    return float(lookup["values"]["maximum_reduction_building_height_m"])


def shielding_lookup_warnings(data: dict[str, Any] | None = None) -> list[str]:
    """Return source-review warnings for the active Table 4.2 lookup."""

    lookup = data if data is not None else load_ms_table()
    return lookup_metadata_warnings(lookup, MS_METADATA_WARNING)


def shielding_source_reference(data: dict[str, Any] | None = None) -> str:
    """Return the active Table 4.2 source reference."""

    lookup = data if data is not None else load_ms_table()
    return source_reference(lookup)


def shielding_lookup_issues(
    data: dict[str, Any],
    *,
    require_reviewed: bool = True,
) -> list[str]:
    """Return Table 4.2 structure and provenance validation failures."""

    try:
        expected_digest = trusted_values_sha256(
            package_file=MS_DATA_FILE,
            expected_digest_env=MS_EXPECTED_SHA256_ENV,
        )
    except ValueError as exc:
        issues = [str(exc)]
        expected_digest = TRUSTED_PACKAGED_VALUES_SHA256[MS_DATA_FILE]
    else:
        issues = []
    issues.extend(
        lookup_provenance_issues(
            data,
            expected_clause=MS_SOURCE_CLAUSE,
            expected_standard_reference=MS_STANDARD_REFERENCE,
            expected_table="Table 4.2",
            expected_values_sha256=expected_digest,
            require_reviewed=require_reviewed,
        )
    )
    values = data.get("values")
    if not isinstance(values, dict):
        return [*issues, "values must be an object"]
    if values.get("below_first_point") != "use_first_ms":
        issues.append("below_first_point must be use_first_ms")
    if values.get("above_last_point") != "use_last_ms":
        issues.append("above_last_point must be use_last_ms")
    if values.get("interpolation") != "linear":
        issues.append("interpolation must be linear")
    limit = values.get("maximum_reduction_building_height_m")
    if limit != EXPECTED_SHIELDING_REDUCTION_HEIGHT_LIMIT_M:
        issues.append("maximum_reduction_building_height_m must be the normative 25 m")
    raw_points = values.get("points")
    if not isinstance(raw_points, list) or len(raw_points) != len(
        EXPECTED_SHIELDING_PARAMETER_NODES
    ):
        return [*issues, "points must contain the four normative Table 4.2 rows"]
    points: list[tuple[float, float]] = []
    for index, point in enumerate(raw_points):
        if not isinstance(point, dict):
            issues.append(f"points[{index}] must be an object")
            continue
        s_value = point.get("s")
        ms_value = point.get("ms")
        if not finite_lookup_number(s_value, minimum=0, minimum_inclusive=True):
            issues.append(f"points[{index}].s must be finite and non-negative")
            continue
        if not finite_lookup_number(ms_value, minimum=0, maximum=1):
            issues.append(f"points[{index}].ms must be finite and between 0 and 1")
            continue
        points.append((float(s_value), float(ms_value)))
    if len(points) == len(raw_points):
        if tuple(point[0] for point in points) != EXPECTED_SHIELDING_PARAMETER_NODES:
            issues.append("shielding parameter points must use the normative Table 4.2 nodes")
        if any(
            current[0] >= following[0]
            for current, following in zip(points, points[1:], strict=False)
        ):
            issues.append("shielding parameter points must be strictly increasing")
        if any(
            current[1] > following[1]
            for current, following in zip(points, points[1:], strict=False)
        ):
            issues.append("Ms values must be non-decreasing")
    return issues


def site_wind_speed(vr: float, md: float, mzcat: float, ms: float, mt: float) -> float:
    """Calculate Vsit,b from five selected site-wind inputs."""

    inputs = {"VR": vr, "Md": md, "Mz,cat": mzcat, "Ms": ms, "Mt": mt}
    invalid = [name for name, value in inputs.items() if not finite_lookup_number(value, minimum=0)]
    if invalid:
        raise ValueError(f"Site-wind inputs must be positive and finite: {', '.join(invalid)}")
    return float(vr) * float(md) * float(mzcat) * float(ms) * float(mt)
