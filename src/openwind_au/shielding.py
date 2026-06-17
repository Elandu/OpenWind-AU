"""Preliminary shielding-sector calculations from reviewed obstruction records."""

from __future__ import annotations

import math

from openwind_au.geo import EARTH_RADIUS_M, destination_point
from openwind_au.models import ObstructionRecord, ShieldingSectorResult, SiteLocation

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
) -> list[ShieldingSectorResult]:
    """Calculate preliminary 45-degree upwind shielding sectors."""

    sector_radius_m = 20.0 * subject_height_m
    return [
        shielding_sector_result(
            direction=direction,
            wind_direction_deg=azimuth,
            site=site,
            obstructions=obstructions,
            subject_height_m=subject_height_m,
            sector_radius_m=sector_radius_m,
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
) -> ShieldingSectorResult:
    """Calculate shielding quantities for one wind direction."""

    half_width = SECTOR_WIDTH_DEG / 2
    sector_candidates = [
        obstruction
        for obstruction in obstructions
        if _is_in_sector(obstruction, wind_direction_deg, sector_radius_m, half_width)
    ]
    included = [
        obstruction
        for obstruction in sector_candidates
        if obstruction.height_m is not None and obstruction.height_m >= subject_height_m
    ]
    ns = len(included)
    unknown_height_count = sum(
        obstruction.height_m is None or obstruction.height_source == "missing"
        for obstruction in sector_candidates
    )
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
            ns=0,
            indicative_ms=1.0,
            high_confidence_count=0,
            estimated_height_count=0,
            unknown_height_count=unknown_height_count,
            overall_confidence="unknown" if unknown_height_count else "low",
            notes=notes,
            warnings=_sector_confidence_warnings([], unknown_height_count),
        )

    heights = [obstruction.height_m for obstruction in included if obstruction.height_m is not None]
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
    indicative_ms = ms_from_shielding_parameter(s) if s is not None else 1.0

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
    if low_confidence:
        warnings.append(
            "Sector includes low-confidence or warning-flagged obstructions: "
            + ", ".join(low_confidence)
        )
    if len(review_required) > 1:
        warnings.append("Multiple shielding structures require manual review.")
    warnings.extend(_sector_confidence_warnings(included, unknown_height_count))
    overall_confidence = _overall_shielding_confidence(included, unknown_height_count)

    return ShieldingSectorResult(
        direction=direction,  # type: ignore[arg-type]
        wind_direction_deg=wind_direction_deg,
        sector_start_deg=_normalise_bearing(wind_direction_deg - half_width),
        sector_end_deg=_normalise_bearing(wind_direction_deg + half_width),
        sector_radius_m=sector_radius_m,
        subject_height_m=subject_height_m,
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
        notes=notes,
        warnings=warnings,
    )


def ms_from_shielding_parameter(s: float) -> float:
    """Return indicative Ms by linear interpolation from public table thresholds."""

    if s <= 1.5:
        return 0.7
    if s >= 12.0:
        return 1.0
    points = [(1.5, 0.7), (3.0, 0.8), (6.0, 0.9), (12.0, 1.0)]
    for (s0, ms0), (s1, ms1) in zip(points, points[1:], strict=True):
        if s <= s1:
            ratio = (s - s0) / (s1 - s0)
            return ms0 + ratio * (ms1 - ms0)
    return 1.0


def footprint_breadth_normal_to_wind(
    geometry: dict,
    site_latitude: float,
    site_longitude: float,
    wind_direction_deg: float,
) -> float:
    """Return building breadth normal to wind from footprint projection width."""

    coordinates = geometry.get("coordinates", [[]])[0]
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
    if any(item.height_source == "ESTIMATED" or item.review_required for item in included):
        return "low"
    if all(item.confidence == "high" for item in included):
        return "high"
    return "medium"


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
