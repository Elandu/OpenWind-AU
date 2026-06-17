"""Directional terrain category evidence calculations for engineering review."""

from __future__ import annotations

import math
import statistics

from openwind_au.geo import EARTH_RADIUS_M
from openwind_au.models import (
    ObstructionInventoryResult,
    ObstructionRecord,
    ShieldingSectorResult,
    SiteAnalysisResult,
    TerrainCategoryDirectionEvidence,
    TerrainCategoryEvidenceResult,
    TerrainCategoryScoreComponents,
    TerrainProfile,
)
from openwind_au.shielding import DIRECTION_AZIMUTHS, SECTOR_WIDTH_DEG

HIGH_COVERAGE_THRESHOLD = 0.8
MEDIUM_COVERAGE_THRESHOLD = 0.5


def run_terrain_category_evidence(
    site_result: SiteAnalysisResult,
    obstruction_result: ObstructionInventoryResult,
) -> TerrainCategoryEvidenceResult:
    """Generate directional terrain category evidence without assigning a final category."""

    profiles_by_direction = {profile.direction: profile for profile in site_result.profiles}
    shielding_by_direction = {
        sector.direction: sector for sector in obstruction_result.shielding_sectors
    }
    directions = [
        direction_evidence(
            direction=direction,
            azimuth_deg=azimuth,
            site_result=site_result,
            obstruction_result=obstruction_result,
            profile=profiles_by_direction.get(direction),
            shielding_sector=shielding_by_direction.get(direction),
        )
        for direction, azimuth in DIRECTION_AZIMUTHS
    ]
    warnings = [
        "Terrain category requires engineer confirmation.",
        "Suggested ranges are evidence summaries, not final AS/NZS 1170.2 terrain categories.",
    ]
    if obstruction_result.data_source_status == "unavailable":
        warnings.append("Insufficient obstruction data: public footprint source was unavailable.")
    return TerrainCategoryEvidenceResult(
        input=site_result.input,
        site=site_result.site,
        directions=directions,
        warnings=warnings,
    )


def direction_evidence(
    *,
    direction: str,
    azimuth_deg: float,
    site_result: SiteAnalysisResult,
    obstruction_result: ObstructionInventoryResult,
    profile: TerrainProfile | None,
    shielding_sector: ShieldingSectorResult | None,
) -> TerrainCategoryDirectionEvidence:
    """Calculate terrain category evidence metrics for one 45-degree direction sector."""

    directional_fetch_distance_m = _directional_fetch_distance(profile, site_result.input.radius_m)
    assessment_radius_m = min(directional_fetch_distance_m, obstruction_result.input.radius_m)
    half_width = SECTOR_WIDTH_DEG / 2
    sector_records = [
        record
        for record in obstruction_result.obstructions
        if record.distance_m <= assessment_radius_m
        and _angle_delta_deg(record.bearing_deg, azimuth_deg) <= half_width
    ]
    sector_area_m2 = _sector_area_m2(assessment_radius_m)
    coverage = _coverage_percentages(
        sector_records=sector_records,
        sector_area_m2=sector_area_m2,
        origin_latitude=site_result.site.latitude,
        origin_longitude=site_result.site.longitude,
    )
    heights = [record.height_m for record in sector_records if record.height_m is not None]
    obstruction_count = len(sector_records)
    vegetation_records = [record for record in sector_records if _is_vegetation(record)]
    obstruction_density = _density_per_km2(obstruction_count, sector_area_m2)
    vegetation_density = _density_per_km2(len(vegetation_records), sector_area_m2)
    average_spacing = (
        math.sqrt(sector_area_m2 / obstruction_count)
        if obstruction_count and sector_area_m2
        else None
    )
    height_coverage = (len(heights) / obstruction_count * 100) if obstruction_count else 0.0
    scores = terrain_category_scores(
        built_up_area_percentage=coverage["built_up"],
        vegetation_area_percentage=coverage["vegetation"],
        open_terrain_percentage=coverage["open"],
        obstruction_density_per_km2=obstruction_density,
        average_obstruction_height_m=statistics.fmean(heights) if heights else None,
    )
    suggested_range = suggested_category_range(scores, coverage["built_up"], obstruction_density)
    confidence = confidence_from_evidence(
        obstruction_count=obstruction_count,
        height_coverage_percentage=height_coverage,
        obstruction_result_status=obstruction_result.data_source_status,
        sources={record.height_source for record in sector_records},
    )
    warnings = evidence_warnings(
        obstruction_count=obstruction_count,
        vegetation_count=len(vegetation_records),
        height_coverage_percentage=height_coverage,
        confidence=confidence,
        sources={record.height_source for record in sector_records},
    )
    return TerrainCategoryDirectionEvidence(
        direction=direction,  # type: ignore[arg-type]
        azimuth_deg=azimuth_deg,
        sector_start_deg=_normalise_bearing(azimuth_deg - half_width),
        sector_end_deg=_normalise_bearing(azimuth_deg + half_width),
        directional_fetch_distance_m=directional_fetch_distance_m,
        assessment_radius_m=assessment_radius_m,
        built_up_area_percentage=coverage["built_up"],
        vegetation_area_percentage=coverage["vegetation"],
        open_terrain_percentage=coverage["open"],
        average_obstruction_height_m=statistics.fmean(heights) if heights else None,
        median_obstruction_height_m=statistics.median(heights) if heights else None,
        maximum_obstruction_height_m=max(heights) if heights else None,
        obstruction_density_per_km2=obstruction_density,
        average_obstruction_spacing_m=average_spacing,
        vegetation_density_per_km2=vegetation_density,
        obstruction_count=obstruction_count,
        vegetation_count=len(vegetation_records),
        height_coverage_percentage=height_coverage,
        shielding_confidence=(
            shielding_sector.overall_confidence if shielding_sector is not None else "unknown"
        ),
        evidence_scores=scores,
        suggested_category_range=suggested_range,
        confidence=confidence,
        warnings=warnings,
        notes=[
            "Directional evidence uses obstruction footprint centroids within a 45-degree sector.",
            "Footprint coverage is area-based within the obstruction assessment radius.",
        ],
    )


def terrain_category_scores(
    *,
    built_up_area_percentage: float,
    vegetation_area_percentage: float,
    open_terrain_percentage: float,
    obstruction_density_per_km2: float,
    average_obstruction_height_m: float | None,
) -> TerrainCategoryScoreComponents:
    """Return separate scoring components scaled from 0 to 100."""

    height = average_obstruction_height_m or 0.0
    return TerrainCategoryScoreComponents(
        open_exposure_score=_clamp(open_terrain_percentage),
        vegetation_score=_clamp(vegetation_area_percentage * 1.5),
        urban_density_score=_clamp(
            (built_up_area_percentage * 1.4) + obstruction_density_per_km2 / 30
        ),
        obstruction_height_score=_clamp((height / 15) * 100),
    )


def suggested_category_range(
    scores: TerrainCategoryScoreComponents,
    built_up_area_percentage: float,
    obstruction_density_per_km2: float,
) -> str:
    """Return a qualified likely terrain category range for review."""

    roughness_score = (
        scores.urban_density_score * 0.42
        + scores.obstruction_height_score * 0.28
        + scores.vegetation_score * 0.18
        - scores.open_exposure_score * 0.12
    )
    if built_up_area_percentage < 8 and scores.open_exposure_score >= 70:
        return "TC2-TC2.5"
    if roughness_score < 25:
        return "TC2-TC2.5"
    if roughness_score < 45:
        return "TC2.5-TC3"
    if roughness_score < 65 or obstruction_density_per_km2 < 1200:
        return "TC3-TC3.5"
    return "TC3.5-TC4"


def confidence_from_evidence(
    *,
    obstruction_count: int,
    height_coverage_percentage: float,
    obstruction_result_status: str,
    sources: set[str],
) -> str:
    """Assign evidence confidence from coverage and source mix."""

    if obstruction_result_status == "unavailable" or obstruction_count < 3:
        return "low"
    if height_coverage_percentage < MEDIUM_COVERAGE_THRESHOLD * 100:
        return "low"
    if height_coverage_percentage >= HIGH_COVERAGE_THRESHOLD * 100 and sources <= {
        "manual_verified",
        "DSM_DTM",
        "OSM_HEIGHT",
        "OSM_LEVELS",
    }:
        return "high"
    return "medium"


def evidence_warnings(
    *,
    obstruction_count: int,
    vegetation_count: int,
    height_coverage_percentage: float,
    confidence: str,
    sources: set[str],
) -> list[str]:
    """Return terrain-category evidence warnings for one direction."""

    warnings = ["Terrain category requires engineer confirmation."]
    if obstruction_count < 3:
        warnings.append("Insufficient obstruction data.")
    if vegetation_count == 0:
        warnings.append("Limited vegetation coverage data.")
    if height_coverage_percentage < 80:
        warnings.append("Missing obstruction heights reduce evidence confidence.")
    if "ESTIMATED" in sources:
        warnings.append("Significant manual assumptions or estimated heights are present.")
    if confidence == "low":
        warnings.append("Terrain category evidence confidence is low.")
    return warnings


def _coverage_percentages(
    *,
    sector_records: list[ObstructionRecord],
    sector_area_m2: float,
    origin_latitude: float,
    origin_longitude: float,
) -> dict[str, float]:
    built_up_area = 0.0
    vegetation_area = 0.0
    for record in sector_records:
        area = polygon_area_m2(record.footprint_geometry, origin_latitude, origin_longitude)
        if record.classification == "mixed":
            built_up_area += area * 0.5
            vegetation_area += area * 0.5
        elif _is_vegetation(record):
            vegetation_area += area
        else:
            built_up_area += area
    built_up_pct = _percentage(built_up_area, sector_area_m2)
    vegetation_pct = _percentage(vegetation_area, sector_area_m2)
    occupied_pct = min(100.0, built_up_pct + vegetation_pct)
    return {
        "built_up": built_up_pct,
        "vegetation": vegetation_pct,
        "open": max(0.0, 100.0 - occupied_pct),
    }


def polygon_area_m2(
    geometry: dict,
    origin_latitude: float,
    origin_longitude: float,
) -> float:
    """Approximate a WGS84 polygon area with a local tangent-plane shoelace calculation."""

    ring = geometry.get("coordinates", [[]])[0]
    if len(ring) < 3:
        return 0.0
    points = [
        _local_offsets_m(latitude, longitude, origin_latitude, origin_longitude)
        for longitude, latitude in ring
    ]
    area = 0.0
    for (east_a, north_a), (east_b, north_b) in zip(points, points[1:], strict=False):
        area += east_a * north_b - east_b * north_a
    return abs(area) / 2


def _directional_fetch_distance(profile: TerrainProfile | None, fallback_radius_m: float) -> float:
    if profile is None:
        return fallback_radius_m
    return max((point.distance_m for point in profile.points), default=profile.radius_m)


def _sector_area_m2(radius_m: float) -> float:
    return math.pi * radius_m * radius_m * (SECTOR_WIDTH_DEG / 360)


def _density_per_km2(count: int, area_m2: float) -> float:
    if not area_m2:
        return 0.0
    return count / (area_m2 / 1_000_000)


def _percentage(value: float, total: float) -> float:
    if not total:
        return 0.0
    return min(100.0, max(0.0, value / total * 100))


def _is_vegetation(record: ObstructionRecord) -> bool:
    return record.classification == "vegetation"


def _angle_delta_deg(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _normalise_bearing(value: float) -> float:
    return value % 360


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


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))
