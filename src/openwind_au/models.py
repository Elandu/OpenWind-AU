"""Pydantic models and typed dataclasses for OpenWind-AU."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

DISCLAIMER = (
    "OpenWind-AU provides preliminary terrain and topographic analysis only. "
    "Outputs must be reviewed by a competent engineer and are not a certified "
    "AS/NZS 1170.2 design assessment."
)


class SiteAnalysisRequest(BaseModel):
    """Input payload for a preliminary site wind terrain analysis."""

    address: str | None = Field(default=None, description="Street address to geocode.")
    latitude: float | None = Field(default=None, ge=-44.5, le=-9.0)
    longitude: float | None = Field(default=None, ge=112.0, le=154.5)
    building_height_m: float = Field(gt=0, description="Building height in metres.")
    radius_m: int = Field(default=2000, description="Analysis radius in metres.")
    sample_interval_m: float = Field(default=50, ge=5, le=500)

    @model_validator(mode="after")
    def validate_location(self) -> SiteAnalysisRequest:
        """Require either an address or a complete coordinate pair."""

        has_address = bool(self.address and self.address.strip())
        has_coords = self.latitude is not None and self.longitude is not None
        if not has_address and not has_coords:
            raise ValueError("Provide either address or latitude and longitude.")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Provide both latitude and longitude when using coordinates.")
        if self.radius_m not in {500, 1000, 2000, 4000}:
            raise ValueError("radius_m must be one of 500, 1000, 2000, or 4000.")
        return self


class SiteLocation(BaseModel):
    """Resolved site location."""

    latitude: float
    longitude: float
    ground_elevation_m: float
    source: str
    display_name: str | None = None


class TerrainPoint(BaseModel):
    """A sampled point along a radial terrain profile."""

    distance_m: float
    latitude: float
    longitude: float
    elevation_m: float


class TerrainProfile(BaseModel):
    """Terrain profile for one azimuth around the site."""

    direction: Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    azimuth_deg: float
    radius_m: int
    endpoint_latitude: float
    endpoint_longitude: float
    points: list[TerrainPoint]
    min_elevation_m: float
    max_elevation_m: float
    average_slope: float


class TopographicFeature(BaseModel):
    """Detected topographic feature relevant to preliminary wind review."""

    direction: Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    azimuth_deg: float
    feature_type: Literal["ridge", "hill", "escarpment", "valley", "no significant feature"]
    site_rl_m: float
    crest_rl_m: float
    base_rl_m: float
    h_m: float
    lu_m: float
    x_m: float
    base_x_m: float
    crest_x_m: float
    average_upwind_slope: float
    confidence: Literal["none", "low", "medium", "high"]
    notes: list[str]


class SiteAnalysisResult(BaseModel):
    """Complete preliminary analysis result."""

    input: SiteAnalysisRequest
    site: SiteLocation
    profiles: list[TerrainProfile]
    features: list[TopographicFeature]
    assumptions: list[str]
    limitations: list[str]
    disclaimer: str = DISCLAIMER


class TerrainCategoryScoreComponents(BaseModel):
    """Separate directional evidence scores for terrain category review."""

    open_exposure_score: float
    vegetation_score: float
    urban_density_score: float
    obstruction_height_score: float


class TerrainCategoryDirectionEvidence(BaseModel):
    """Evidence summary for one directional terrain category review sector."""

    direction: Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    azimuth_deg: float
    sector_start_deg: float
    sector_end_deg: float
    directional_fetch_distance_m: float
    assessment_radius_m: float
    built_up_area_percentage: float
    vegetation_area_percentage: float
    open_terrain_percentage: float
    average_obstruction_height_m: float | None = None
    median_obstruction_height_m: float | None = None
    maximum_obstruction_height_m: float | None = None
    obstruction_density_per_km2: float
    average_obstruction_spacing_m: float | None = None
    vegetation_density_per_km2: float
    obstruction_count: int
    vegetation_count: int
    height_coverage_percentage: float
    shielding_confidence: Literal["high", "medium", "low", "unknown"]
    evidence_scores: TerrainCategoryScoreComponents
    suggested_category_range: str
    confidence: Literal["high", "medium", "low"]
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class TerrainCategoryEvidenceResult(BaseModel):
    """Directional terrain category evidence for engineering review."""

    input: SiteAnalysisRequest
    site: SiteLocation
    directions: list[TerrainCategoryDirectionEvidence]
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Terrain category evidence is provided for engineering review only. OpenWind-AU does "
        "not assign a final AS/NZS 1170.2 terrain category, does not claim compliance, and does "
        "not calculate Mz,cat values."
    )


class ObstructionManualOverride(BaseModel):
    """Reviewed obstruction height data supplied by a user."""

    obstruction_id: str
    height_m: float | None = Field(default=None, ge=0)
    building_levels: float | None = Field(default=None, ge=0)
    height_source: str = "manual_review"
    notes: str | None = None


class ReviewedFootprint(BaseModel):
    """Reviewed obstruction geometry supplied by a reviewed obstruction JSON file."""

    id: str
    geometry: dict[str, Any]
    classification: Literal[
        "residential",
        "commercial",
        "industrial",
        "apartment",
        "vegetation",
        "mixed",
        "unknown",
    ] = "unknown"
    height_m: float | None = Field(default=None, ge=0)
    building_levels: float | None = Field(default=None, ge=0)
    source: str = "reviewed obstruction JSON"
    notes: str | None = None


class ExcludedObstructionObject(BaseModel):
    """Footprint object excluded from usable obstruction records."""

    object_id: str
    source: str
    reason: str
    footprint_geometry: dict[str, Any] | None = None


class ObstructionDataQuality(BaseModel):
    """Obstruction source and coverage diagnostics."""

    query_centre: dict[str, float] | None = None
    query_radius_m: int | None = None
    overpass_query: str | None = None
    raw_overpass_counts: dict[str, int] = Field(default_factory=dict)
    parsed_counts: dict[str, int] = Field(default_factory=dict)
    total_osm_building_footprints_found: int = 0
    total_microsoft_building_footprints_found: int = 0
    total_vegetation_polygons_found: int = 0
    microsoft_source_status: str = "unavailable"
    microsoft_cache_status: str = "miss"
    microsoft_cache_path: str | None = None
    microsoft_cache_files: list[str] = Field(default_factory=list)
    osm_fallback_used: bool = False
    total_usable_obstruction_polygons: int = 0
    number_excluded: int = 0
    excluded_reasons: dict[str, int] = Field(default_factory=dict)
    percentage_with_height_data: float = 0.0
    percentage_requiring_manual_review: float = 0.0
    source_summary: dict[str, int] = Field(default_factory=dict)
    duplicate_overlap_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    excluded_objects: list[ExcludedObstructionObject] = Field(default_factory=list)
    raw_osm_building_footprints: list[dict[str, Any]] = Field(default_factory=list)
    sample_building_ids: list[str] = Field(default_factory=list)
    returned_geometry_bbox: list[float] | None = None
    pipeline_log: list[str] = Field(default_factory=list)


class ObstructionInventoryRequest(BaseModel):
    """Input payload for building obstruction inventory."""

    address: str | None = Field(default=None, description="Street address to geocode.")
    latitude: float | None = Field(default=None, ge=-44.5, le=-9.0)
    longitude: float | None = Field(default=None, ge=112.0, le=154.5)
    radius_m: int = Field(default=500, ge=50, le=4000)
    building_height_m: float | None = Field(
        default=None,
        gt=0,
        description="Subject building height for preliminary shielding-sector analysis.",
    )
    default_storey_height_m: float = Field(default=3.0, gt=0, le=6)
    residential_storey_height_m: float = Field(default=3.0, gt=0, le=6)
    residential_two_storey_height_m: float = Field(default=6.0, gt=0, le=12)
    commercial_storey_height_m: float = Field(default=4.0, gt=0, le=8)
    manual_overrides: list[ObstructionManualOverride] = Field(default_factory=list)
    reviewed_footprints: list[ReviewedFootprint] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_location(self) -> ObstructionInventoryRequest:
        """Require either an address or a complete coordinate pair."""

        has_address = bool(self.address and self.address.strip())
        has_coords = self.latitude is not None and self.longitude is not None
        if not has_address and not has_coords:
            raise ValueError("Provide either address or latitude and longitude.")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Provide both latitude and longitude when using coordinates.")
        return self


class ObstructionRecord(BaseModel):
    """Building obstruction record for shielding input review."""

    obstruction_id: str
    source_id: str | None = None
    classification: Literal[
        "residential",
        "commercial",
        "industrial",
        "apartment",
        "vegetation",
        "mixed",
        "unknown",
    ] = "unknown"
    footprint_geometry: dict[str, Any]
    centroid_latitude: float
    centroid_longitude: float
    distance_m: float
    bearing_deg: float
    height_m: float | None
    selected_height_m: float | None = None
    raw_source_height_m: float | None = None
    raw_source_height_source: str | None = None
    estimated_height_m: float | None = None
    ground_rl_m: float | None = None
    surface_rl_m: float | None = None
    obstruction_height_m: float | None = None
    building_levels: float | None
    height_source: Literal[
        "manual_verified",
        "IMPORTED",
        "OSM_HEIGHT",
        "OSM_LEVELS",
        "DSM_DTM",
        "ESTIMATED",
        "missing",
    ]
    confidence: Literal["high", "medium", "low", "unknown"]
    enrichment_method: str | None = None
    manual_review_required: bool
    review_required: bool
    footprint_source: Literal[
        "OSM",
        "microsoft_building_footprints",
        "manual_reviewed",
        "DSM_DERIVED",
    ] = "OSM"
    source_provenance: list[str] = Field(default_factory=list)
    duplicate_source_ids: list[str] = Field(default_factory=list)
    tags: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ShieldingSectorResult(BaseModel):
    """Preliminary shielding sector result for one wind direction."""

    direction: Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    wind_direction_deg: float
    sector_start_deg: float
    sector_end_deg: float
    sector_radius_m: float
    subject_height_m: float
    ns: int
    average_hs_m: float | None = None
    average_bs_m: float | None = None
    ls_m: float | None = None
    s: float | None = None
    indicative_ms: float
    high_confidence_count: int = 0
    estimated_height_count: int = 0
    unknown_height_count: int = 0
    overall_confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    included_obstruction_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ObstructionInventoryResult(BaseModel):
    """Complete obstruction inventory result."""

    input: ObstructionInventoryRequest
    site: SiteLocation
    obstructions: list[ObstructionRecord]
    missing_height_count: int
    reviewed_height_count: int
    height_source_summary: dict[str, int] = Field(default_factory=dict)
    data_quality: ObstructionDataQuality = Field(default_factory=ObstructionDataQuality)
    shielding_sectors: list[ShieldingSectorResult] = Field(default_factory=list)
    data_source_status: Literal["ok", "unavailable"] = "ok"
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "OpenWind-AU provides preliminary obstruction and shielding-sector data for "
        "engineering review only. Indicative Ms values are not certified AS/NZS 1170.2 "
        "design outputs and require competent engineering verification."
    )


class CombinedMapRequest(SiteAnalysisRequest):
    """Request for the unified site + obstruction map with toggleable layers.

    Extends :class:`SiteAnalysisRequest` with the obstruction inventory fields so
    a single map can be rendered that combines the terrain analysis radius, the
    8-direction profile lines, candidate topographic features, and the nearby
    obstruction footprints.
    """

    obstruction_radius_m: int = Field(default=500, ge=50, le=4000)
    default_storey_height_m: float = Field(default=3.0, gt=0, le=6)
    residential_storey_height_m: float = Field(default=3.0, gt=0, le=6)
    residential_two_storey_height_m: float = Field(default=6.0, gt=0, le=12)
    commercial_storey_height_m: float = Field(default=4.0, gt=0, le=8)
    manual_overrides: list[ObstructionManualOverride] = Field(default_factory=list)
    reviewed_footprints: list[ReviewedFootprint] = Field(default_factory=list)


class TerrainCategoryEvidenceRequest(CombinedMapRequest):
    """Request for terrain category evidence using terrain and obstruction data."""


@dataclass(frozen=True)
class ElevationSample:
    """Simple elevation sample for internal calculations."""

    distance_m: float
    latitude: float
    longitude: float
    elevation_m: float
