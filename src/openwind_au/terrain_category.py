"""Directional terrain category evidence calculations for engineering review."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Literal

import geopandas as gpd
import numpy as np
import pyproj
import rasterio
from shapely.geometry import Point, Polygon
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union

from openwind_au.data.landcover import DEFAULT_LANDCOVER_CLASS_MAP, LandcoverClassSpec
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
from openwind_au.mzcat import run_mzcat_assessment
from openwind_au.shielding import DIRECTION_AZIMUTHS, SECTOR_WIDTH_DEG

HIGH_COVERAGE_THRESHOLD = 0.8
MEDIUM_COVERAGE_THRESHOLD = 0.5
TerrainCategoryClass = Literal["TC1", "TC2", "TC2.5", "TC3", "TC4"]
SourceCoverage = Literal["osm+raster", "osm_only", "raster_only", "none"]
COMPASS_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@dataclass(frozen=True)
class TerrainCategoryResult:
    """Result from direct OSM/raster terrain category classification."""

    terrain_class: TerrainCategoryClass
    per_direction: dict[str, str]
    obstruction_density_per_ha: float
    average_obstruction_height_m: float
    forest_fraction: float
    water_fraction: float
    built_fraction: float
    source_coverage: SourceCoverage
    reasoning: str

    @property
    def class_(self) -> TerrainCategoryClass:
        """Alias for callers that want a field-like class name."""

        return self.terrain_class

    def __getitem__(self, key: str):
        if key == "class":
            return self.terrain_class
        return getattr(self, key)

    def to_dict(self) -> dict:
        return {
            "class": self.terrain_class,
            "per_direction": self.per_direction,
            "obstruction_density_per_ha": self.obstruction_density_per_ha,
            "average_obstruction_height_m": self.average_obstruction_height_m,
            "forest_fraction": self.forest_fraction,
            "water_fraction": self.water_fraction,
            "built_fraction": self.built_fraction,
            "source_coverage": self.source_coverage,
            "reasoning": self.reasoning,
        }


@dataclass
class _SectorStats:
    area_m2: float
    built_area_m2: float = 0.0
    forest_area_m2: float = 0.0
    water_area_m2: float = 0.0
    raster_obstruction_count: float = 0.0
    osm_obstruction_count: float = 0.0
    height_area_sum: float = 0.0
    height_area_m2: float = 0.0


def classify_terrain_category(
    site_point: Point,
    osm_obstructions: gpd.GeoDataFrame,
    landcover_raster: np.ndarray | None,
    landcover_transform: rasterio.Affine | None,
    landcover_crs: pyproj.CRS | None,
    landcover_class_map: dict[int, LandcoverClassSpec],
    radius_m: float = 500.0,
    direction_count: int = 8,
) -> TerrainCategoryResult:
    """Classify terrain category from supplied OSM obstructions and landcover raster.

    Threshold comments cite AS/NZS 1170.2:2021 Clause 4.2.2/Table 4.1 and AS 4055 terrain
    category descriptions as review-screening sources. This implementation paraphrases
    terrain roughness classes; it does not replace the licensed standards.
    """

    if direction_count != 8:
        raise ValueError("direction_count must be 8 for compass-sector terrain classification.")
    if landcover_raster is not None and (landcover_transform is None or landcover_crs is None):
        raise ValueError(
            "landcover_transform and landcover_crs are required with landcover_raster."
        )

    class_map = landcover_class_map or DEFAULT_LANDCOVER_CLASS_MAP
    local_crs, to_local, _from_local = _to_local_utm(site_point)
    site_local = shapely_transform(to_local.transform, site_point)
    buffer = site_local.buffer(radius_m)
    sector_area_m2 = math.pi * radius_m * radius_m / direction_count
    sectors = {direction: _SectorStats(area_m2=sector_area_m2) for direction in COMPASS_DIRECTIONS}

    osm_local = _project_osm_obstructions(osm_obstructions, local_crs)
    osm_clipped = _clip_osm_to_buffer(osm_local, buffer)
    osm_union = unary_union(list(osm_clipped.geometry)) if len(osm_clipped) else None
    raster_used = landcover_raster is not None
    osm_used = len(osm_clipped) > 0
    raster_cells = 0
    raster_obstructions = 0.0
    osm_obstructions_count = 0.0

    if (
        landcover_raster is not None
        and landcover_transform is not None
        and landcover_crs is not None
    ):
        raster_cells, raster_obstructions = _accumulate_landcover_raster(
            sectors=sectors,
            site_local=site_local,
            buffer=buffer,
            osm_union=osm_union,
            raster=landcover_raster,
            raster_transform=landcover_transform,
            raster_crs=pyproj.CRS.from_user_input(landcover_crs),
            local_crs=local_crs,
            class_map=class_map,
        )

    if len(osm_clipped):
        osm_obstructions_count = _accumulate_osm_obstructions(
            sectors=sectors,
            osm_local=osm_clipped,
            site_local=site_local,
            site_point=site_point,
            landcover_raster=landcover_raster,
            landcover_transform=landcover_transform,
            landcover_crs=landcover_crs,
            class_map=class_map,
        )

    if not raster_used and not osm_used:
        return TerrainCategoryResult(
            terrain_class="TC1",
            per_direction={direction: "TC1" for direction in COMPASS_DIRECTIONS},
            obstruction_density_per_ha=0.0,
            average_obstruction_height_m=0.0,
            forest_fraction=0.0,
            water_fraction=0.0,
            built_fraction=0.0,
            source_coverage="none",
            reasoning=(
                f"radius={radius_m:.1f} m; projection={local_crs.to_string()}; no OSM or "
                "raster source coverage; defaulted all sectors to TC1."
            ),
        )

    per_direction: dict[str, str] = {}
    reasoning_parts = [
        f"radius={radius_m:.1f} m",
        f"projection={local_crs.to_string()}",
        f"OSM obstruction count={osm_obstructions_count:.1f}",
        f"raster obstruction count={raster_obstructions:.1f}",
        f"raster cells used={raster_cells}",
    ]
    max_density = 0.0
    total_area = sum(sector.area_m2 for sector in sectors.values())
    total_built = sum(sector.built_area_m2 for sector in sectors.values())
    total_forest = sum(sector.forest_area_m2 for sector in sectors.values())
    total_water = sum(sector.water_area_m2 for sector in sectors.values())
    total_height_sum = sum(sector.height_area_sum for sector in sectors.values())
    total_height_area = sum(sector.height_area_m2 for sector in sectors.values())
    for direction, sector in sectors.items():
        density = _sector_density_per_ha(sector)
        avg_height = _sector_average_height(sector)
        forest_fraction = _fraction(sector.forest_area_m2, sector.area_m2)
        built_fraction = _fraction(sector.built_area_m2, sector.area_m2)
        category = _classify_sector(density, avg_height, forest_fraction, built_fraction)
        per_direction[direction] = category
        max_density = max(max_density, density)
        reasoning_parts.append(
            f"{direction}: density={density:.2f}/ha, height={avg_height:.2f} m, "
            f"forest={forest_fraction:.2f}, built={built_fraction:.2f}, class={category}"
        )

    final_class = _worst_category(per_direction.values())
    reasoning_parts.append(f"worst={final_class}")
    return TerrainCategoryResult(
        terrain_class=final_class,
        per_direction=per_direction,
        obstruction_density_per_ha=max_density,
        average_obstruction_height_m=(
            total_height_sum / total_height_area if total_height_area else 0.0
        ),
        forest_fraction=_fraction(total_forest, total_area),
        water_fraction=_fraction(total_water, total_area),
        built_fraction=_fraction(total_built, total_area),
        source_coverage=_source_coverage(osm_used, raster_used),
        reasoning="; ".join(reasoning_parts),
    )


def _to_local_utm(point: Point) -> tuple[pyproj.CRS, pyproj.Transformer, pyproj.Transformer]:
    lon = point.x
    lat = point.y
    zone = int((lon + 180) // 6) + 1
    epsg = (32600 if lat >= 0 else 32700) + zone
    local_crs = pyproj.CRS.from_epsg(epsg)
    wgs84 = pyproj.CRS.from_epsg(4326)
    return (
        local_crs,
        pyproj.Transformer.from_crs(wgs84, local_crs, always_xy=True),
        pyproj.Transformer.from_crs(local_crs, wgs84, always_xy=True),
    )


def _project_osm_obstructions(
    osm_obstructions: gpd.GeoDataFrame,
    local_crs: pyproj.CRS,
) -> gpd.GeoDataFrame:
    if osm_obstructions.empty:
        return gpd.GeoDataFrame(columns=["geometry", "category", "height_m"], crs=local_crs)
    gdf = osm_obstructions.copy()
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    return gdf.to_crs(local_crs)


def _clip_osm_to_buffer(osm_local: gpd.GeoDataFrame, buffer) -> gpd.GeoDataFrame:
    if osm_local.empty:
        return osm_local
    mask = osm_local.geometry.notna() & osm_local.geometry.intersects(buffer)
    clipped = osm_local.loc[mask].copy()
    clipped.geometry = clipped.geometry.intersection(buffer)
    clipped = clipped[~clipped.geometry.is_empty]
    return clipped


def _accumulate_landcover_raster(
    *,
    sectors: dict[str, _SectorStats],
    site_local: Point,
    buffer,
    osm_union,
    raster: np.ndarray,
    raster_transform: rasterio.Affine,
    raster_crs: pyproj.CRS,
    local_crs: pyproj.CRS,
    class_map: dict[int, LandcoverClassSpec],
) -> tuple[int, float]:
    raster_to_local = pyproj.Transformer.from_crs(raster_crs, local_crs, always_xy=True)
    cell_count = 0
    obstruction_count = 0.0
    for row in range(raster.shape[0]):
        for col in range(raster.shape[1]):
            cell = _cell_polygon_local(row, col, raster_transform, raster_to_local)
            center = cell.centroid
            if not buffer.contains(center):
                continue
            if osm_union is not None and cell.intersects(osm_union):
                continue
            code = int(raster[row, col])
            spec = class_map.get(code)
            if spec is None:
                continue
            direction = _direction_for_point(center, site_local)
            sector = sectors[direction]
            cell_area = cell.area
            _accumulate_landcover_area(
                sector=sector,
                code=code,
                spec=spec,
                area_m2=cell_area,
                default_height_m=spec.default_height_m,
                site_inside_forest=_cell_contains_site_forest(cell, site_local, code),
            )
            cell_count += 1
            if spec.is_obstruction:
                obstruction_count += spec.weight
    return cell_count, obstruction_count


def _accumulate_osm_obstructions(
    *,
    sectors: dict[str, _SectorStats],
    osm_local: gpd.GeoDataFrame,
    site_local: Point,
    site_point: Point,
    landcover_raster: np.ndarray | None,
    landcover_transform: rasterio.Affine | None,
    landcover_crs: pyproj.CRS | None,
    class_map: dict[int, LandcoverClassSpec],
) -> float:
    count = 0.0
    for row in osm_local.itertuples():
        geometry = row.geometry
        if geometry.is_empty:
            continue
        category = str(getattr(row, "category", "open") or "open").lower()
        direction = _direction_for_point(geometry.representative_point(), site_local)
        sector = sectors[direction]
        area_m2 = geometry.area
        height = _osm_height(row)
        if height <= 0:
            height = _default_height_for_osm_geometry(
                geometry=geometry,
                category=category,
                site_point=site_point,
                landcover_raster=landcover_raster,
                landcover_transform=landcover_transform,
                landcover_crs=landcover_crs,
                class_map=class_map,
            )
        if _osm_category_is_built(category):
            sector.built_area_m2 += area_m2
        elif category == "forest":
            if not geometry.contains(site_local):
                sector.forest_area_m2 += area_m2
        elif category == "water":
            sector.water_area_m2 += area_m2
        if _osm_category_is_obstruction(category):
            count += 1.0
            sector.osm_obstruction_count += 1.0
            if height > 0 and area_m2 > 0:
                sector.height_area_sum += height * area_m2
                sector.height_area_m2 += area_m2
    return count


def _cell_polygon_local(
    row: int,
    col: int,
    transform: rasterio.Affine,
    transformer: pyproj.Transformer,
):
    corners = [
        transform * (col, row),
        transform * (col + 1, row),
        transform * (col + 1, row + 1),
        transform * (col, row + 1),
    ]
    local_corners = [transformer.transform(x, y) for x, y in corners]
    return Polygon(local_corners)


def _accumulate_landcover_area(
    *,
    sector: _SectorStats,
    code: int,
    spec: LandcoverClassSpec,
    area_m2: float,
    default_height_m: float,
    site_inside_forest: bool,
) -> None:
    if code == 50:
        sector.built_area_m2 += area_m2
    elif code in {10, 20, 95} and not site_inside_forest:
        sector.forest_area_m2 += area_m2
    elif code == 80:
        sector.water_area_m2 += area_m2
    if spec.is_obstruction:
        sector.raster_obstruction_count += spec.weight
        if default_height_m > 0 and spec.weight > 0:
            weighted_area = area_m2 * spec.weight
            sector.height_area_sum += default_height_m * weighted_area
            sector.height_area_m2 += weighted_area


def _cell_contains_site_forest(cell, site_local: Point, code: int) -> bool:
    return code in {10, 20, 95} and cell.contains(site_local)


def _default_height_for_osm_geometry(
    *,
    geometry,
    category: str,
    site_point: Point,
    landcover_raster: np.ndarray | None,
    landcover_transform: rasterio.Affine | None,
    landcover_crs: pyproj.CRS | None,
    class_map: dict[int, LandcoverClassSpec],
) -> float:
    if (
        landcover_raster is not None
        and landcover_transform is not None
        and landcover_crs is not None
    ):
        point = geometry.representative_point()
        local_crs, _to_local, _from_local = _to_local_utm(site_point)
        raster_crs = pyproj.CRS.from_user_input(landcover_crs)
        local_to_raster = pyproj.Transformer.from_crs(local_crs, raster_crs, always_xy=True)
        x, y = local_to_raster.transform(point.x, point.y)
        try:
            raster_row, raster_col = rasterio.transform.rowcol(landcover_transform, x, y)
        except ValueError:
            raster_row, raster_col = -1, -1
        if (
            0 <= raster_row < landcover_raster.shape[0]
            and 0 <= raster_col < landcover_raster.shape[1]
        ):
            spec = class_map.get(int(landcover_raster[raster_row, raster_col]))
            if spec is not None and spec.default_height_m > 0:
                return spec.default_height_m
    if category in {"building", "industrial"}:
        return class_map.get(50, DEFAULT_LANDCOVER_CLASS_MAP[50]).default_height_m
    if category == "forest":
        return class_map.get(10, DEFAULT_LANDCOVER_CLASS_MAP[10]).default_height_m
    return 0.0


def _osm_height(row) -> float:
    value = getattr(row, "height_m", 0.0)
    try:
        if value is None or math.isnan(float(value)):
            return 0.0
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _osm_category_is_built(category: str) -> bool:
    return category in {"building", "industrial"}


def _osm_category_is_obstruction(category: str) -> bool:
    return category in {"building", "forest", "industrial"}


def _direction_for_point(point: Point, site_local: Point) -> str:
    dx = point.x - site_local.x
    dy = point.y - site_local.y
    if dx == 0 and dy == 0:
        return "N"
    bearing = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    sector = int((bearing + 22.5) // 45) % 8
    return COMPASS_DIRECTIONS[sector]


def _sector_density_per_ha(sector: _SectorStats) -> float:
    area_ha = sector.area_m2 / 10_000
    if not area_ha:
        return 0.0
    return max(sector.raster_obstruction_count, sector.osm_obstruction_count) / area_ha


def _sector_average_height(sector: _SectorStats) -> float:
    if not sector.height_area_m2:
        return 0.0
    return sector.height_area_sum / sector.height_area_m2


def _classify_sector(
    density_per_ha: float,
    avg_height_m: float,
    forest_fraction: float,
    built_fraction: float,
) -> TerrainCategoryClass:
    # AS/NZS 1170.2:2021 Cl 4.2.2/Table 4.1 and AS 4055 terrain category
    # descriptions distinguish exposed/open, scattered low obstructions, suburban/tree cover,
    # and dense high obstruction environments. Numeric cut-offs are conservative review
    # thresholds derived from those descriptions and must be engineer-reviewed.
    if density_per_ha < 0.5 and avg_height_m < 1.5:
        return "TC1"
    if density_per_ha < 3 and avg_height_m < 5:
        return "TC2"
    if density_per_ha < 8 and forest_fraction > 0.3:
        return "TC2.5"
    if density_per_ha >= 8 and 3 <= avg_height_m <= 10:
        return "TC3"
    if density_per_ha >= 8 and avg_height_m > 10:
        return "TC4"
    return _nearest_category(density_per_ha, avg_height_m, forest_fraction, built_fraction)


def _nearest_category(
    density_per_ha: float,
    avg_height_m: float,
    forest_fraction: float,
    built_fraction: float,
) -> TerrainCategoryClass:
    if density_per_ha >= 8:
        return "TC3" if avg_height_m <= 10 else "TC4"
    if density_per_ha >= 3 and avg_height_m >= 5:
        return "TC3"
    if density_per_ha >= 3 or forest_fraction > 0.15 or built_fraction > 0.02:
        return "TC2.5"
    if avg_height_m >= 1.5 or density_per_ha >= 0.5:
        return "TC2"
    return "TC1"


def _worst_category(categories) -> TerrainCategoryClass:
    order = {"TC1": 1.0, "TC2": 2.0, "TC2.5": 2.5, "TC3": 3.0, "TC4": 4.0}
    return max(categories, key=lambda item: order[item])


def _source_coverage(osm_used: bool, raster_used: bool) -> SourceCoverage:
    if osm_used and raster_used:
        return "osm+raster"
    if osm_used:
        return "osm_only"
    if raster_used:
        return "raster_only"
    return "none"


def _fraction(value: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, value / total))


def run_terrain_category_evidence(
    site_result: SiteAnalysisResult,
    obstruction_result: ObstructionInventoryResult,
    *,
    mzcat_lookup_data: dict[str, Any] | None = None,
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
    mzcat_assessment = run_mzcat_assessment(
        request=site_result.input,
        site=site_result.site,
        directions=directions,
        recommendation_mode=getattr(site_result.input, "mzcat_recommendation_mode", "conservative"),
        lookup_data=mzcat_lookup_data,
    )
    return TerrainCategoryEvidenceResult(
        input=site_result.input,
        site=site_result.site,
        directions=directions,
        mzcat_assessment=mzcat_assessment.directions,
        mzcat_lookup_provenance=mzcat_assessment.lookup_provenance,
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
    if built_up_area_percentage < 3 and scores.open_exposure_score >= 90:
        return "TC1.5-TC2"
    if built_up_area_percentage < 8 and scores.open_exposure_score >= 70:
        return "TC2-TC2.5"
    if roughness_score < 25:
        return "TC2-TC2.5"
    if roughness_score < 45:
        return "TC2.5-TC3"
    if roughness_score < 65 or obstruction_density_per_km2 < 1200:
        return "TC3-TC4"
    return "TC3-TC4"


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
