"""Preliminary shielding-sector calculations from reviewed obstruction records."""

from __future__ import annotations

import math
from typing import Any

from openwind_au.geo import EARTH_RADIUS_M, destination_point
from openwind_au.models import ObstructionRecord, ShieldingSectorResult, SiteLocation
from openwind_au.standard_calculations import (
    load_ms_table,
    ms_from_shielding_parameter,
    shielding_lookup_issues,
    shielding_reduction_height_limit_m,
)

DIRECTION_AZIMUTHS: tuple[tuple[str, float], ...] = (
    ("N", 0.0),
    ("NE", 45.0),
    ("E", 90.0),
    ("SE", 135.0),
    ("S", 180.0),
    ("SW", 225.0),
    ("W", 270.0),
    ("NW", 315.0),
)
SECTOR_WIDTH_DEG = 45.0


def run_shielding_sector_analysis(
    site: SiteLocation,
    obstructions: list[ObstructionRecord],
    subject_height_m: float,
    *,
    subject_base_rl_m: float | None = None,
    lookup_data: dict[str, Any] | None = None,
) -> list[ShieldingSectorResult]:
    """Calculate preliminary 45-degree upwind shielding sectors."""

    lookup = lookup_data if lookup_data is not None else load_ms_table()
    issues = shielding_lookup_issues(lookup, require_reviewed=False)
    if issues:
        raise ValueError(f"Invalid Table 4.2 lookup data: {'; '.join(issues)}")
    sector_radius_m = 20.0 * subject_height_m
    return [
        shielding_sector_result(
            direction=direction,
            wind_direction_deg=azimuth,
            site=site,
            obstructions=obstructions,
            subject_height_m=subject_height_m,
            sector_radius_m=sector_radius_m,
            subject_base_rl_m=subject_base_rl_m,
            lookup_data=lookup,
        )
        for direction, azimuth in DIRECTION_AZIMUTHS
    ]


def shielding_sector_result(
    direction: str,
    wind_direction_deg: float,
    site: SiteLocation,
    obstructions: list[ObstructionRecord],
    subject_height_m: float,
    sector_radius_m: float,
    subject_base_rl_m: float | None = None,
    lookup_data: dict[str, Any] | None = None,
) -> ShieldingSectorResult:
    """Calculate shielding quantities for one wind direction."""

    lookup = lookup_data if lookup_data is not None else load_ms_table()
    issues = shielding_lookup_issues(lookup, require_reviewed=False)
    if issues:
        raise ValueError(f"Invalid Table 4.2 lookup data: {'; '.join(issues)}")
    half_width = SECTOR_WIDTH_DEG / 2
    resolved_subject_base_rl_m = (
        subject_base_rl_m if subject_base_rl_m is not None else site.ground_elevation_m
    )
    subject_top_rl_m = resolved_subject_base_rl_m + subject_height_m
    subject_rl_source = (
        "reviewed_base_rl" if subject_base_rl_m is not None else "site_ground_elevation"
    )
    sector_candidates = [
        obstruction
        for obstruction in obstructions
        if _is_in_sector(obstruction, wind_direction_deg, sector_radius_m, half_width)
    ]
    height_limit_m = shielding_reduction_height_limit_m(lookup)
    if subject_height_m > height_limit_m:
        warning = (
            "AS/NZS 1170.2:2021 Clause 4.3.1 requires Ms = 1.0 for structures "
            f"greater than {height_limit_m:g} m high."
        )
        return ShieldingSectorResult(
            direction=direction,  # type: ignore[arg-type]
            wind_direction_deg=wind_direction_deg,
            sector_start_deg=_normalise_bearing(wind_direction_deg - half_width),
            sector_end_deg=_normalise_bearing(wind_direction_deg + half_width),
            sector_radius_m=sector_radius_m,
            subject_height_m=subject_height_m,
            subject_base_rl_m=resolved_subject_base_rl_m,
            subject_top_rl_m=subject_top_rl_m,
            subject_rl_source=subject_rl_source,
            total_obstructions_in_sector=len(sector_candidates),
            ns=0,
            indicative_ms=1.0,
            overall_confidence="high",
            notes=[warning],
            warnings=[warning],
        )
    included: list[ObstructionRecord] = []
    rejected: list[dict[str, Any]] = []
    rejection_reason_counts: dict[str, int] = {}
    usable_height_count = 0
    ground_gradient_unchecked: list[str] = []
    steep_gradient_exception_ids: list[str] = []
    for obstruction in sector_candidates:
        if (
            obstruction.obstruction_source_type == "vegetation"
            or obstruction.classification == "vegetation"
        ):
            _record_rejection(
                rejected,
                rejection_reason_counts,
                obstruction,
                "vegetation_not_permitted",
            )
            continue
        height = shielding_height_m(obstruction)
        if height is None:
            _record_rejection(
                rejected,
                rejection_reason_counts,
                obstruction,
                "height_missing",
            )
            continue
        usable_height_count += 1
        if height < subject_height_m:
            _record_rejection(
                rejected,
                rejection_reason_counts,
                obstruction,
                "height_below_subject",
                height,
            )
            continue
        if obstruction.ground_rl_m is None:
            ground_gradient_unchecked.append(obstruction.obstruction_id)
        elif obstruction.distance_m > 0:
            average_ground_gradient = (
                abs(obstruction.ground_rl_m - site.ground_elevation_m) / obstruction.distance_m
            )
            if average_ground_gradient > 0.2:
                obstruction_top_rl_m = shielding_top_rl_m(obstruction, height)
                if obstruction_top_rl_m is None or obstruction_top_rl_m <= subject_top_rl_m:
                    _record_rejection(
                        rejected,
                        rejection_reason_counts,
                        obstruction,
                        "steep_upwind_ground_gradient",
                        height,
                    )
                    continue
                steep_gradient_exception_ids.append(obstruction.obstruction_id)
        included.append(obstruction)
    ns = len(included)
    unknown_height_count = rejection_reason_counts.get("height_missing", 0)
    estimated_height_count = sum(
        obstruction.height_source == "ESTIMATED" for obstruction in included
    )
    high_confidence_count = sum(obstruction.confidence == "high" for obstruction in included)
    notes = [
        (
            "Preliminary only: sector uses obstruction centroids, available footprint geometry, "
            "and reviewed or tagged heights."
        )
    ]
    if ns == 0:
        notes.append("No upwind obstructions with hs >= subject building height were found.")
        return ShieldingSectorResult(
            direction=direction,  # type: ignore[arg-type]
            wind_direction_deg=wind_direction_deg,
            sector_start_deg=_normalise_bearing(wind_direction_deg - half_width),
            sector_end_deg=_normalise_bearing(wind_direction_deg + half_width),
            sector_radius_m=sector_radius_m,
            subject_height_m=subject_height_m,
            subject_base_rl_m=resolved_subject_base_rl_m,
            subject_top_rl_m=subject_top_rl_m,
            subject_rl_source=subject_rl_source,
            total_obstructions_in_sector=len(sector_candidates),
            usable_height_count=usable_height_count,
            rejected_height_below_z_count=rejection_reason_counts.get("height_below_subject", 0),
            rejected_height_missing_count=unknown_height_count,
            rejected_excluded_manual_review_count=rejection_reason_counts.get(
                "excluded_or_manual_review",
                0,
            ),
            included_as_shielding_count=0,
            ns=0,
            indicative_ms=1.0,
            high_confidence_count=0,
            estimated_height_count=0,
            unknown_height_count=unknown_height_count,
            overall_confidence="unknown" if unknown_height_count else "low",
            notes=notes,
            rejection_reason_counts=rejection_reason_counts,
            rejected_obstructions=rejected[:10],
            warnings=_sector_confidence_warnings([], unknown_height_count),
        )

    heights = [shielding_height_m(obstruction) for obstruction in included]
    heights = [height for height in heights if height is not None]
    breadths = [
        footprint_breadth_normal_to_wind(
            obstruction.footprint_geometry,
            site.latitude,
            site.longitude,
            wind_direction_deg,
        )
        for obstruction in included
    ]
    average_hs = sum(heights) / ns
    average_bs = sum(breadths) / ns
    ls = subject_height_m * ((10.0 / ns) + 5.0)
    s = ls / math.sqrt(average_hs * average_bs) if average_hs > 0 and average_bs > 0 else None
    indicative_ms = ms_from_shielding_parameter(s, lookup) if s is not None else 1.0

    warnings = []
    estimated = [
        obstruction.obstruction_id
        for obstruction in included
        if obstruction.height_source == "DSM_DTM"
    ]
    low_confidence = [
        obstruction.obstruction_id
        for obstruction in included
        if obstruction.confidence in {"low", "unknown"} or obstruction.warnings
    ]
    review_required = [
        obstruction.obstruction_id for obstruction in included if obstruction.review_required
    ]
    vegetation = [
        obstruction.obstruction_id
        for obstruction in included
        if obstruction.classification == "vegetation"
    ]

    if s is None:
        notes.append("Indicative Ms defaults to 1.0 because average shielding breadth is zero.")
    else:
        notes.append(
            "Indicative Ms is linearly interpolated from shielding-parameter table thresholds "
            "0.7 at s<=1.5, 0.8 at s=3, 0.9 at s=6, and 1.0 at s>=12."
        )
    if estimated:
        warnings.append(
            "Sector uses DSM-DTM estimated obstruction heights for: " + ", ".join(estimated)
        )
    if estimated_height_count:
        warnings.append("Shielding assessment contains estimated obstruction heights.")
    if any(obstruction.height_source == "ESTIMATED" for obstruction in included) or estimated:
        warnings.append("Estimated or DSM-DTM heights are included for preliminary shielding only.")
    if low_confidence:
        warnings.append(
            "Sector includes low-confidence or warning-flagged obstructions: "
            + ", ".join(low_confidence)
        )
    if len(review_required) > 1:
        warnings.append("Multiple shielding structures require manual review.")
    if vegetation:
        warnings.append(
            "Vegetation appears as potential shielding and requires engineer review: "
            + ", ".join(vegetation)
        )
    if ground_gradient_unchecked:
        warnings.append(
            "Average upwind ground gradient could not be checked for shielding buildings: "
            + ", ".join(ground_gradient_unchecked)
        )
    if steep_gradient_exception_ids:
        warnings.append(
            "Steep-slope shielding candidates were retained because their overall height above "
            "the common datum exceeds the subject building under Clause 4.3.1 and Figure 4.2; "
            "competent engineering review is required: " + ", ".join(steep_gradient_exception_ids)
        )
    warnings.extend(_sector_confidence_warnings(included, unknown_height_count))
    overall_confidence = _overall_shielding_confidence(included, unknown_height_count)

    return ShieldingSectorResult(
        direction=direction,  # type: ignore[arg-type]
        wind_direction_deg=wind_direction_deg,
        sector_start_deg=_normalise_bearing(wind_direction_deg - half_width),
        sector_end_deg=_normalise_bearing(wind_direction_deg + half_width),
        sector_radius_m=sector_radius_m,
        subject_height_m=subject_height_m,
        subject_base_rl_m=resolved_subject_base_rl_m,
        subject_top_rl_m=subject_top_rl_m,
        subject_rl_source=subject_rl_source,
        total_obstructions_in_sector=len(sector_candidates),
        usable_height_count=usable_height_count,
        rejected_height_below_z_count=rejection_reason_counts.get("height_below_subject", 0),
        rejected_height_missing_count=unknown_height_count,
        rejected_excluded_manual_review_count=rejection_reason_counts.get(
            "excluded_or_manual_review",
            0,
        ),
        included_as_shielding_count=ns,
        ns=ns,
        average_hs_m=average_hs,
        average_bs_m=average_bs,
        ls_m=ls,
        s=s,
        indicative_ms=indicative_ms,
        high_confidence_count=high_confidence_count,
        estimated_height_count=estimated_height_count,
        unknown_height_count=unknown_height_count,
        overall_confidence=overall_confidence,
        included_obstruction_ids=[obstruction.obstruction_id for obstruction in included],
        rejection_reason_counts=rejection_reason_counts,
        rejected_obstructions=rejected[:10],
        notes=notes,
        warnings=warnings,
    )


def footprint_breadth_normal_to_wind(
    geometry: dict,
    site_latitude: float,
    site_longitude: float,
    wind_direction_deg: float,
) -> float:
    """Return building breadth normal to wind from footprint projection width."""

    coordinates = footprint_projection_coordinates(geometry)
    if len(coordinates) < 2:
        return 0.0
    theta = math.radians(wind_direction_deg)
    normal_east = math.cos(theta)
    normal_north = -math.sin(theta)
    projections = []
    for longitude, latitude in coordinates:
        east, north = _local_offsets_m(latitude, longitude, site_latitude, site_longitude)
        projections.append(east * normal_east + north * normal_north)
    return max(projections) - min(projections)


def footprint_projection_coordinates(geometry: dict) -> list[list[float]]:
    """Return exterior footprint coordinates used for breadth projection."""

    geometry_type = geometry.get("type")
    if geometry_type == "Polygon":
        return list(geometry.get("coordinates", [[]])[0])
    if geometry_type == "MultiPolygon":
        coordinates: list[list[float]] = []
        for polygon in geometry.get("coordinates", []):
            if polygon:
                coordinates.extend(polygon[0])
        return coordinates
    return []


def shielding_height_m(obstruction: ObstructionRecord) -> float | None:
    """Return the operational obstruction height used for preliminary shielding."""

    return (
        obstruction.selected_height_m
        if obstruction.selected_height_m is not None
        else obstruction.height_m
    )


def shielding_top_rl_m(
    obstruction: ObstructionRecord,
    shielding_height: float,
) -> float | None:
    """Return obstruction top RL on the best available common datum."""

    if (
        obstruction.height_source == "DSM_DTM"
        and obstruction.surface_rl_m is not None
        and math.isfinite(obstruction.surface_rl_m)
    ):
        return obstruction.surface_rl_m
    if obstruction.ground_rl_m is not None and math.isfinite(obstruction.ground_rl_m):
        return obstruction.ground_rl_m + shielding_height
    return None


def shielding_sector_polygon(
    site: SiteLocation,
    sector: ShieldingSectorResult,
    steps: int = 8,
) -> dict:
    """Return a GeoJSON polygon for a shielding sector."""

    start = sector.sector_start_deg
    end = sector.sector_end_deg
    sweep = (end - start) % 360
    if sweep == 0:
        sweep = SECTOR_WIDTH_DEG
    bearings = [start + (sweep * index / steps) for index in range(steps + 1)]
    arc = [
        list(
            reversed(
                destination_point(site.latitude, site.longitude, bearing, sector.sector_radius_m)
            )
        )
        for bearing in bearings
    ]
    site_point = [site.longitude, site.latitude]
    return {"type": "Polygon", "coordinates": [[site_point, *arc, site_point]]}


def _is_in_sector(
    obstruction: ObstructionRecord,
    wind_direction_deg: float,
    sector_radius_m: float,
    half_width_deg: float,
) -> bool:
    if obstruction.distance_m > sector_radius_m:
        return False
    return _angle_delta_deg(obstruction.bearing_deg, wind_direction_deg) <= half_width_deg


def _angle_delta_deg(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _normalise_bearing(value: float) -> float:
    return value % 360


def _overall_shielding_confidence(
    included: list[ObstructionRecord],
    unknown_height_count: int,
) -> str:
    if not included:
        return "unknown" if unknown_height_count else "low"
    if unknown_height_count or any(item.confidence in {"low", "unknown"} for item in included):
        return "low"
    if any(
        item.height_source in {"ESTIMATED", "DSM_DTM"} or item.review_required for item in included
    ):
        return "low"
    if all(item.confidence == "high" for item in included):
        return "high"
    return "medium"


def _record_rejection(
    rejected: list[dict[str, Any]],
    reason_counts: dict[str, int],
    obstruction: ObstructionRecord,
    reason: str,
    height_m: float | None = None,
) -> None:
    reason_counts[reason] = reason_counts.get(reason, 0) + 1
    if len(rejected) >= 10:
        return
    rejected.append(
        {
            "obstruction_id": obstruction.obstruction_id,
            "reason": reason,
            "distance_m": obstruction.distance_m,
            "bearing_deg": obstruction.bearing_deg,
            "height_m": height_m,
            "height_source": obstruction.height_source,
            "classification": obstruction.classification,
            "confidence": obstruction.confidence,
            "review_required": obstruction.review_required,
        }
    )


def _sector_confidence_warnings(
    included: list[ObstructionRecord],
    unknown_height_count: int,
) -> list[str]:
    warnings = []
    confidence = _overall_shielding_confidence(included, unknown_height_count)
    if unknown_height_count:
        warnings.append(f"{unknown_height_count} in-sector obstructions have unknown heights.")
    if confidence == "low":
        warnings.append("Shielding confidence is low.")
    return warnings


def _local_offsets_m(
    latitude: float,
    longitude: float,
    origin_latitude: float,
    origin_longitude: float,
) -> tuple[float, float]:
    lat_rad = math.radians(origin_latitude)
    east = math.radians(longitude - origin_longitude) * EARTH_RADIUS_M * math.cos(lat_rad)
    north = math.radians(latitude - origin_latitude) * EARTH_RADIUS_M
    return east, north
