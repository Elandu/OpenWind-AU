"""Pydantic models and typed dataclasses for OpenWind-AU."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

DISCLAIMER = (
    "OpenWind-AU provides preliminary terrain and topographic analysis only. "
    "Outputs must be reviewed by a competent engineer and are not a certified "
    "AS/NZS 1170.2 design assessment."
)
SUPPORTED_LATITUDE_RANGE = (-44.5, -9.0)
SUPPORTED_LONGITUDE_RANGE = (112.0, 154.5)
MAX_MANUAL_OVERRIDES = 2_000
MAX_REVIEWED_FOOTPRINTS = 1_000
MAX_REVIEWED_GEOMETRY_RINGS = 32
MAX_REVIEWED_GEOMETRY_POSITIONS = 5_000
MAX_TOTAL_REVIEWED_GEOMETRY_POSITIONS = 20_000
MAX_MZCAT_REVIEWS = 8
MAX_CLASS_MULTIPLIER_OVERRIDES = 8
MAX_WORKFLOW_OVERRIDES = 64


class StrictRequestModel(BaseModel):
    """Public request model that rejects typos and implicit JSON coercion."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        str_max_length=5_000,
    )


class ApiErrorResponse(BaseModel):
    """Standard non-validation API error body."""

    detail: str


class ApiValidationErrorResponse(BaseModel):
    """Request-validation or completed-result integrity error body."""

    detail: str | list[dict[str, Any]]


class ReadinessResponse(BaseModel):
    """Readiness response returned with either HTTP 200 or 503."""

    status: Literal["ready", "not_ready"]
    checks: dict[str, dict[str, Any]]


class LivenessResponse(BaseModel):
    """Process liveness response."""

    status: Literal["ok"] = "ok"


class GeocodeQueryRequest(StrictRequestModel):
    """Bounded address-search input kept out of access-log query strings."""

    query: str = Field(min_length=3, max_length=300)
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("query must contain at least three non-space characters")
        return cleaned


class GeocodeResult(BaseModel):
    """Resolved Australian address candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    latitude: float = Field(ge=SUPPORTED_LATITUDE_RANGE[0], le=SUPPORTED_LATITUDE_RANGE[1])
    longitude: float = Field(ge=SUPPORTED_LONGITUDE_RANGE[0], le=SUPPORTED_LONGITUDE_RANGE[1])
    display_name: str | None = None
    source: str


class GeocodeSuggestionsResponse(BaseModel):
    """Bounded autocomplete result list."""

    suggestions: list[GeocodeResult]


class LocationRequest(StrictRequestModel):
    """Shared, unambiguous address-or-coordinate request fields."""

    model_config = ConfigDict(
        json_schema_extra={
            "oneOf": [
                {
                    "title": "Address location",
                    "required": ["address"],
                    "properties": {
                        "address": {"type": "string", "pattern": r".*\S.*"},
                        "site_label": {"type": "null"},
                        "latitude": {"type": "null"},
                        "longitude": {"type": "null"},
                    },
                },
                {
                    "title": "Coordinate location",
                    "required": ["latitude", "longitude"],
                    "properties": {
                        "latitude": {
                            "type": "number",
                            "minimum": SUPPORTED_LATITUDE_RANGE[0],
                            "maximum": SUPPORTED_LATITUDE_RANGE[1],
                        },
                        "longitude": {
                            "type": "number",
                            "minimum": SUPPORTED_LONGITUDE_RANGE[0],
                            "maximum": SUPPORTED_LONGITUDE_RANGE[1],
                        },
                        "address": {"type": "null"},
                    },
                },
            ]
        }
    )

    address: str | None = Field(
        default=None,
        max_length=300,
        description="Street address to geocode. Omit when coordinates are supplied.",
    )
    site_label: str | None = Field(
        default=None,
        max_length=300,
        description="Display label for supplied coordinates; this value is not geocoded.",
    )
    latitude: float | None = Field(
        default=None,
        ge=SUPPORTED_LATITUDE_RANGE[0],
        le=SUPPORTED_LATITUDE_RANGE[1],
    )
    longitude: float | None = Field(
        default=None,
        ge=SUPPORTED_LONGITUDE_RANGE[0],
        le=SUPPORTED_LONGITUDE_RANGE[1],
    )

    @field_validator("address", "site_label")
    @classmethod
    def normalize_location_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def validate_location(self) -> LocationRequest:
        """Require exactly one location mode and keep labels coordinate-only."""

        has_address = self.address is not None
        has_coords = self.latitude is not None and self.longitude is not None
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Provide both latitude and longitude when using coordinates.")
        if self.site_label is not None and not has_coords:
            raise ValueError("site_label may only be supplied with latitude and longitude.")
        if has_address and has_coords:
            raise ValueError(
                "Provide either address or latitude and longitude, not both. "
                "Use site_label to describe supplied coordinates."
            )
        if not has_address and not has_coords:
            raise ValueError("Provide either address or latitude and longitude.")
        return self


class SiteAnalysisRequest(LocationRequest):
    """Input payload for a preliminary site wind terrain analysis."""

    building_height_m: float = Field(
        gt=0,
        le=200,
        description="Building height in metres.",
    )
    radius_m: int = Field(default=2000, description="Analysis radius in metres.")
    sample_interval_m: float = Field(default=50, ge=5, le=500)
    mzcat_recommendation_mode: Literal["conservative", "best_estimate"] = "conservative"

    @model_validator(mode="after")
    def validate_analysis_radius(self) -> SiteAnalysisRequest:
        if self.radius_m not in {500, 1000, 2000, 4000}:
            raise ValueError("radius_m must be one of 500, 1000, 2000, or 4000.")
        return self

    @property
    def reference_height_m(self) -> float:
        """Return the common AS/NZS reference height z / average roof height h."""

        average_height = getattr(self, "average_roof_height_m", None)
        return float(average_height or self.building_height_m)


class SiteLocation(BaseModel):
    """Resolved site location."""

    model_config = ConfigDict(extra="forbid", strict=True)

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
    mt_geometry_resolved: bool = False
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


class MzCatDirectionAssessment(BaseModel):
    """Indicative directional Mz,cat evidence for engineering review."""

    direction: Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    azimuth_deg: float
    recommendation_mode: Literal["conservative", "best_estimate"] = "conservative"
    suggested_terrain_category_range: str
    lower_category_bound: Literal["TC1", "TC1.5", "TC2", "TC2.5", "TC3", "TC4"]
    upper_category_bound: Literal["TC1", "TC1.5", "TC2", "TC2.5", "TC3", "TC4"]
    assessment_height_m: float
    lower_indicative_mzcat: float
    upper_indicative_mzcat: float
    confidence: Literal["high", "medium", "low"]
    recommended_terrain_category: str = "review required"
    recommended_mzcat: float | None = None
    recommendation_confidence: Literal["high", "medium", "low"] = "low"
    recommendation_reasoning: list[str] = Field(default_factory=list)
    final_terrain_category: Literal["TC1", "TC1.5", "TC2", "TC2.5", "TC3", "TC4"] | None = None
    final_mzcat: float | None = None
    reviewed_by: str | None = None
    review_notes: str | None = None
    review_status: Literal["unreviewed", "accepted", "overridden"] = "unreviewed"
    directional_fetch_distance_m: float
    built_up_area_percentage: float
    vegetation_area_percentage: float
    obstruction_density_per_km2: float
    average_obstruction_height_m: float | None = None
    controlling_category_range: str
    reasoning: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MzCatReviewSelection(StrictRequestModel):
    """Engineer-selected final Mz,cat fields supplied for reviewed reports."""

    direction: Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    final_terrain_category: Literal["TC1", "TC1.5", "TC2", "TC2.5", "TC3", "TC4"] | None = None
    final_mzcat: float | None = Field(default=None, gt=0, le=10)
    reviewed_by: str | None = Field(default=None, max_length=200)
    review_notes: str | None = Field(default=None, max_length=5_000)
    review_status: Literal["unreviewed", "accepted", "overridden"] = "unreviewed"

    @model_validator(mode="after")
    def validate_review_selection(self) -> MzCatReviewSelection:
        if self.review_status in {"accepted", "overridden"} and (
            self.final_terrain_category is None or self.final_mzcat is None
        ):
            raise ValueError(
                "final_terrain_category and final_mzcat are required for reviewed Mz,cat values."
            )
        return self


class LookupProvenance(BaseModel):
    """Source identity for one immutable calculation lookup snapshot."""

    schema_version: int
    standard_reference: str
    review_status: str
    reviewed_by: str | None = None
    reviewed_on: str | None = None
    values_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    independent_review_recorded: bool
    source_reference: str


class MzCatAssessmentResult(BaseModel):
    """Indicative Mz,cat assessment result for all review directions."""

    input: SiteAnalysisRequest
    site: SiteLocation
    directions: list[MzCatDirectionAssessment]
    recommendation_mode: Literal["conservative", "best_estimate"] = "conservative"
    lookup_provenance: LookupProvenance
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Indicative Mz,cat evidence is provided for engineering review only. OpenWind-AU does "
        "not assign a final AS/NZS 1170.2 terrain category, does not claim compliance, and does "
        "not calculate final design wind speeds."
    )


class TerrainCategoryEvidenceResult(BaseModel):
    """Directional terrain category evidence for engineering review."""

    input: SiteAnalysisRequest
    site: SiteLocation
    directions: list[TerrainCategoryDirectionEvidence]
    mzcat_assessment: list[MzCatDirectionAssessment] = Field(default_factory=list)
    mzcat_lookup_provenance: LookupProvenance
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Terrain category evidence is provided for engineering review only. OpenWind-AU does "
        "not assign a final AS/NZS 1170.2 terrain category, does not claim compliance, and does "
        "not calculate final Mz,cat design values."
    )


class ObstructionManualOverride(StrictRequestModel):
    """Reviewed obstruction height data supplied by a user."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        str_max_length=5_000,
        json_schema_extra={
            "anyOf": [
                {
                    "required": ["height_m"],
                    "properties": {"height_m": {"type": "number", "minimum": 0, "maximum": 500}},
                },
                {
                    "required": ["building_levels"],
                    "properties": {
                        "building_levels": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 200,
                        }
                    },
                },
            ]
        },
    )

    obstruction_id: str = Field(min_length=1, max_length=300, pattern=r".*\S.*")
    height_m: float | None = Field(default=None, ge=0, le=500)
    building_levels: float | None = Field(default=None, ge=0, le=200)
    height_source: str = Field(default="manual_review", min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2_000)

    @field_validator("obstruction_id", mode="before")
    @classmethod
    def normalize_obstruction_id(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_reviewed_height(self) -> ObstructionManualOverride:
        if self.height_m is None and self.building_levels is None:
            raise ValueError("Provide height_m or building_levels for a manual override.")
        return self


def _finite_coordinate(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Reviewed footprint coordinates must be numbers.")
    try:
        parsed = float(value)
    except OverflowError as exc:
        raise ValueError("Reviewed footprint coordinates must be finite.") from exc
    if not math.isfinite(parsed):
        raise ValueError("Reviewed footprint coordinates must be finite.")
    return parsed


def _validate_reviewed_polygon_geometry(geometry: dict[str, Any]) -> int:
    """Validate one bounded WGS84 Polygon and return its position count."""

    unsupported_members = set(geometry) - {"type", "coordinates", "bbox"}
    if unsupported_members:
        raise ValueError("Reviewed footprint geometry contains unsupported members.")
    if geometry.get("type") != "Polygon":
        raise ValueError("Reviewed footprint geometry must be a GeoJSON Polygon.")
    rings = geometry.get("coordinates")
    if not isinstance(rings, list | tuple) or not rings:
        raise ValueError("Reviewed footprint Polygon coordinates must contain a ring.")
    if len(rings) > MAX_REVIEWED_GEOMETRY_RINGS:
        raise ValueError(
            f"Reviewed footprint geometry may contain at most {MAX_REVIEWED_GEOMETRY_RINGS} rings."
        )

    position_count = 0
    for ring in rings:
        if not isinstance(ring, list | tuple) or len(ring) < 4:
            raise ValueError("Each reviewed footprint Polygon ring needs at least four positions.")
        normalized_ring: list[tuple[float, float]] = []
        for position in ring:
            if not isinstance(position, list | tuple) or not 2 <= len(position) <= 3:
                raise ValueError("Each reviewed footprint position needs two or three coordinates.")
            longitude = _finite_coordinate(position[0])
            latitude = _finite_coordinate(position[1])
            if not SUPPORTED_LONGITUDE_RANGE[0] <= longitude <= SUPPORTED_LONGITUDE_RANGE[1]:
                raise ValueError("Reviewed footprint longitude is outside the supported range.")
            if not SUPPORTED_LATITUDE_RANGE[0] <= latitude <= SUPPORTED_LATITUDE_RANGE[1]:
                raise ValueError("Reviewed footprint latitude is outside the supported range.")
            if len(position) == 3:
                _finite_coordinate(position[2])
            normalized_ring.append((longitude, latitude))
            position_count += 1
            if position_count > MAX_REVIEWED_GEOMETRY_POSITIONS:
                raise ValueError(
                    f"Reviewed footprint geometry may contain at most "
                    f"{MAX_REVIEWED_GEOMETRY_POSITIONS} positions."
                )
        if normalized_ring[0] != normalized_ring[-1]:
            raise ValueError("Each reviewed footprint Polygon ring must be closed.")

    bbox = geometry.get("bbox")
    if bbox is not None:
        if not isinstance(bbox, list | tuple) or len(bbox) not in {4, 6}:
            raise ValueError("Reviewed footprint bbox must contain four or six coordinates.")
        for coordinate in bbox:
            _finite_coordinate(coordinate)
    return position_count


class ReviewedFootprint(StrictRequestModel):
    """Reviewed obstruction geometry supplied by a reviewed obstruction JSON file."""

    id: str = Field(min_length=1, max_length=300, pattern=r".*\S.*")
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
    height_m: float | None = Field(default=None, ge=0, le=500)
    building_levels: float | None = Field(default=None, ge=0, le=200)
    source: str = Field(default="reviewed obstruction JSON", min_length=1, max_length=200)
    obstruction_source_type: Literal["building", "vegetation", "other", "unknown"] = "unknown"
    source_dataset: str | None = Field(default=None, max_length=300)
    height_method: Literal[
        "manual",
        "dsm_dtm",
        "osm_height",
        "osm_levels",
        "assumption",
        "unknown",
    ] = "unknown"
    is_vegetation_candidate: bool = False
    notes: str | None = Field(default=None, max_length=2_000)

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("geometry")
    @classmethod
    def validate_geometry(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_reviewed_polygon_geometry(value)
        return value


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


class PublicObstructionDataQuality(BaseModel):
    """Consumer-safe obstruction diagnostics without raw geometry or local paths."""

    query_centre: dict[str, float] | None = None
    query_radius_m: int | None = None
    parsed_counts: dict[str, int] = Field(default_factory=dict)
    total_osm_building_footprints_found: int = 0
    total_microsoft_building_footprints_found: int = 0
    total_vegetation_polygons_found: int = 0
    microsoft_source_status: str = "unavailable"
    microsoft_cache_status: str = "miss"
    osm_fallback_used: bool = False
    total_usable_obstruction_polygons: int = 0
    number_excluded: int = 0
    excluded_reasons: dict[str, int] = Field(default_factory=dict)
    percentage_with_height_data: float = 0.0
    percentage_requiring_manual_review: float = 0.0
    source_summary: dict[str, int] = Field(default_factory=dict)
    duplicate_overlap_count: int = 0
    warnings: list[str] = Field(default_factory=list)


def _validate_obstruction_review_inputs(
    manual_overrides: list[ObstructionManualOverride],
    reviewed_footprints: list[ReviewedFootprint],
) -> None:
    override_ids = [item.obstruction_id for item in manual_overrides]
    if len(override_ids) != len(set(override_ids)):
        raise ValueError("manual_overrides contains duplicate obstruction_id entries.")
    footprint_ids = [item.id for item in reviewed_footprints]
    if len(footprint_ids) != len(set(footprint_ids)):
        raise ValueError("reviewed_footprints contains duplicate id entries.")
    position_count = sum(
        len(ring) for footprint in reviewed_footprints for ring in footprint.geometry["coordinates"]
    )
    if position_count > MAX_TOTAL_REVIEWED_GEOMETRY_POSITIONS:
        raise ValueError(
            f"reviewed_footprints may contain at most "
            f"{MAX_TOTAL_REVIEWED_GEOMETRY_POSITIONS} total positions."
        )


class ObstructionInventoryRequest(LocationRequest):
    """Input payload for building obstruction inventory."""

    radius_m: int = Field(default=500, ge=50, le=4000)
    building_height_m: float | None = Field(
        default=None,
        gt=0,
        le=200,
        description="Subject building height for preliminary shielding-sector analysis.",
    )
    subject_base_rl_m: float | None = Field(
        default=None,
        ge=-500,
        le=10_000,
        description="Reviewed subject-building base RL on the obstruction common datum.",
    )
    default_storey_height_m: float = Field(default=3.0, gt=0, le=6)
    residential_storey_height_m: float = Field(default=3.0, gt=0, le=6)
    residential_two_storey_height_m: float = Field(default=6.0, gt=0, le=12)
    commercial_storey_height_m: float = Field(default=4.0, gt=0, le=8)
    manual_overrides: list[ObstructionManualOverride] = Field(
        default_factory=list,
        max_length=MAX_MANUAL_OVERRIDES,
    )
    reviewed_footprints: list[ReviewedFootprint] = Field(
        default_factory=list,
        max_length=MAX_REVIEWED_FOOTPRINTS,
    )
    map_display_mode: Literal[
        "nearest_500",
        "shielding_candidates",
        "all_footprints",
        "centroids_only",
    ] = "nearest_500"
    map_max_display_obstructions: int = Field(default=500, ge=1, le=5000)

    @model_validator(mode="after")
    def validate_review_inputs(self) -> ObstructionInventoryRequest:
        _validate_obstruction_review_inputs(self.manual_overrides, self.reviewed_footprints)
        return self


class PublicObstructionInventoryInput(BaseModel):
    """Echoed inventory settings without repeating imported footprint geometry."""

    address: str | None = None
    site_label: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius_m: int
    building_height_m: float | None = None
    default_storey_height_m: float
    residential_storey_height_m: float
    residential_two_storey_height_m: float
    commercial_storey_height_m: float
    manual_overrides: list[ObstructionManualOverride] = Field(default_factory=list)
    map_display_mode: Literal[
        "nearest_500",
        "shielding_candidates",
        "all_footprints",
        "centroids_only",
    ]
    map_max_display_obstructions: int


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
    obstruction_source_type: Literal["building", "vegetation", "other", "unknown"] = "unknown"
    source_dataset: str | None = None
    height_method: Literal[
        "manual",
        "dsm_dtm",
        "osm_height",
        "osm_levels",
        "assumption",
        "unknown",
    ] = "unknown"
    is_vegetation_candidate: bool = False
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
    subject_base_rl_m: float | None = None
    subject_top_rl_m: float | None = None
    subject_rl_source: Literal["reviewed_base_rl", "site_ground_elevation"] = (
        "site_ground_elevation"
    )
    total_obstructions_in_sector: int = 0
    usable_height_count: int = 0
    rejected_height_below_z_count: int = 0
    rejected_height_missing_count: int = 0
    rejected_excluded_manual_review_count: int = 0
    included_as_shielding_count: int = 0
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
    rejection_reason_counts: dict[str, int] = Field(default_factory=dict)
    rejected_obstructions: list[dict[str, Any]] = Field(default_factory=list)
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
    ms_lookup_provenance: LookupProvenance | None = None
    data_source_status: Literal["ok", "unavailable"] = "ok"
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "OpenWind-AU provides preliminary obstruction and shielding-sector data for "
        "engineering review only. Indicative Ms values are not certified AS/NZS 1170.2 "
        "design outputs and require competent engineering verification."
    )


class PublicObstructionInventoryResult(BaseModel):
    """Stable public inventory contract with private diagnostics removed."""

    input: PublicObstructionInventoryInput
    site: SiteLocation
    obstructions: list[ObstructionRecord]
    missing_height_count: int
    reviewed_height_count: int
    height_source_summary: dict[str, int] = Field(default_factory=dict)
    data_quality: PublicObstructionDataQuality = Field(default_factory=PublicObstructionDataQuality)
    shielding_sectors: list[ShieldingSectorResult] = Field(default_factory=list)
    ms_lookup_provenance: LookupProvenance | None = None
    data_source_status: Literal["ok", "unavailable"] = "ok"
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str


class FullAnalysisResult(BaseModel):
    """Typed response for the combined legacy browser analysis workflow."""

    site_analysis: SiteAnalysisResult
    obstruction_inventory: PublicObstructionInventoryResult
    terrain_category_evidence: TerrainCategoryEvidenceResult
    profile_plot_html: str
    terrain_category_map_html: str
    combined_map_html: str


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
    manual_overrides: list[ObstructionManualOverride] = Field(
        default_factory=list,
        max_length=MAX_MANUAL_OVERRIDES,
    )
    reviewed_footprints: list[ReviewedFootprint] = Field(
        default_factory=list,
        max_length=MAX_REVIEWED_FOOTPRINTS,
    )
    map_display_mode: Literal[
        "nearest_500",
        "shielding_candidates",
        "all_footprints",
        "centroids_only",
    ] = "nearest_500"
    map_max_display_obstructions: int = Field(default=500, ge=1, le=5000)

    @model_validator(mode="after")
    def validate_review_inputs(self) -> CombinedMapRequest:
        _validate_obstruction_review_inputs(self.manual_overrides, self.reviewed_footprints)
        return self


class TerrainCategoryEvidenceRequest(CombinedMapRequest):
    """Request for terrain category evidence using terrain and obstruction data."""


class TerrainCategoryReportRequest(TerrainCategoryEvidenceRequest):
    """Request for terrain category reports with optional engineer Mz,cat reviews."""

    mzcat_reviews: list[MzCatReviewSelection] = Field(
        default_factory=list,
        max_length=MAX_MZCAT_REVIEWS,
    )

    @model_validator(mode="after")
    def validate_unique_mzcat_reviews(self) -> TerrainCategoryReportRequest:
        directions = [item.direction for item in self.mzcat_reviews]
        if len(directions) != len(set(directions)):
            raise ValueError("mzcat_reviews contains duplicate directions.")
        return self


WindDirection = Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
WindWorkflowVariable = Literal["VR", "Mc", "Md", "Mzcat", "Ms", "Mt", "Vsitb"]
WindWorkflowOverrideVariable = Literal["VR", "Md", "Mzcat", "Ms", "Mt", "Vsitb"]
WindDirectionMultiplierCase = Literal[
    "main_structure",
    "cladding_or_immediate_support",
    "circular_or_polygonal_chimney_tank_or_pole",
]
AssessmentStatus = Literal["draft", "reviewed"]
TerrainCategoryLabel = Literal["TC1", "TC1.5", "TC2", "TC2.5", "TC3", "TC4"]
ShieldingClassLabel = Literal["FS", "PS", "NS"]
TopographicClassLabel = Literal["T0", "T1", "T2", "T3", "T4", "T5"]
WindRegionLabel = Literal[
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
]
SpecificWindRegionLabel = Literal[
    "A0",
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "B1",
    "B2",
    "C",
    "D",
]
ExposureWindRegionLabel = Literal[
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
]
ClimateChangeWindRegionLabel = Literal[
    "A",
    "A0",
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "B1",
    "B2",
    "C",
    "D",
]


class PublicWindRegionAssessment(BaseModel):
    """Serializable wind-region evidence included in completed workflow results."""

    model_config = ConfigDict(extra="forbid", strict=True)

    latitude: float
    longitude: float
    wind_region: WindRegionLabel
    region_subclassification: str | None = None
    dataset_name: str | None = None
    polygon_count: int | None = None
    available_region_names: list[str] = Field(default_factory=list)
    source: str
    confidence: Literal["high", "medium", "low"]
    distance_to_boundary_m: float | None = None
    near_boundary: bool = False
    warnings: list[str] = Field(default_factory=list)


class WindRegionAssessment(PublicWindRegionAssessment):
    """Wind region assessment with server-only GIS geometry for map rendering."""

    region_polygon: dict[str, Any] | None = Field(
        default=None,
        exclude=True,
        description="Internal GIS geometry used by server-rendered map endpoints.",
    )


class WindRegionValidationResult(BaseModel):
    """One published wind-region dataset validation outcome."""

    site: str
    latitude: float
    longitude: float
    expected_region: WindRegionLabel
    warning: str | None = None
    actual_region: WindRegionLabel | None = None
    status: Literal["pass", "fail", "warning"]
    confidence: Literal["high", "medium", "low"]
    distance_to_boundary_m: float | None = None
    diagnosis: str


class RegionalWindSpeedAssessment(BaseModel):
    """VR lookup for the assessed wind region and selected annual probability."""

    model_config = ConfigDict(extra="forbid", strict=True)

    wind_region: WindRegionLabel
    importance_level: str | None = None
    ari_years: int
    annual_exceedance_probability: str
    vr_ult: float | None = None
    vr_serv: float | None = None
    selected_table: str
    lookup_values: list[str] = Field(default_factory=list)
    interpolation: str | None = None
    warnings: list[str] = Field(default_factory=list)


class DirectionMultiplierRow(BaseModel):
    """Directional Md value for one cardinal/intercardinal direction."""

    model_config = ConfigDict(extra="forbid", strict=True)

    direction: WindDirection
    md: float | None = None
    is_governing: bool = False


class DirectionMultiplierAssessment(BaseModel):
    """Direction multiplier table selected from the assessed wind region."""

    model_config = ConfigDict(extra="forbid", strict=True)

    wind_region: WindRegionLabel
    source_table: str
    directions: list[DirectionMultiplierRow]
    highest_md: float | None = None
    governing_directions: list[WindDirection]
    lookup_values: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WindVariableOverride(StrictRequestModel):
    """Optional override for a calculated wind workflow variable."""

    variable: WindWorkflowOverrideVariable
    direction: WindDirection | None = None
    override_value: float = Field(gt=0, le=500)
    reason: str = Field(min_length=1, max_length=2_000)
    label: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_direction_scope(self) -> WindVariableOverride:
        if self.variable == "VR" and self.direction is not None:
            raise ValueError("VR is non-directional; omit direction for a VR override.")
        if self.variable != "VR" and self.direction is None:
            raise ValueError(f"direction is required for a {self.variable} override.")
        maximum_by_variable = {
            "VR": 200.0,
            "Md": 2.0,
            "Mzcat": 10.0,
            "Ms": 1.0,
            "Mt": 10.0,
            "Vsitb": 500.0,
        }
        maximum = maximum_by_variable[self.variable]
        if self.override_value > maximum:
            raise ValueError(f"{self.variable} override_value must not exceed {maximum:g}.")
        return self


class WindClassMultiplierOverride(StrictRequestModel):
    """Optional reviewed class inputs for directional Mz,cat, Ms, and Mt values."""

    direction: WindDirection
    terrain_category: TerrainCategoryLabel | None = None
    shielding_class: ShieldingClassLabel | None = None
    topographic_class: TopographicClassLabel | None = None
    mzcat: float | None = Field(default=None, gt=0, le=10)
    ms: float | None = Field(default=None, gt=0, le=1)
    mt: float | None = Field(default=None, gt=0, le=10)
    reason: str = Field(min_length=1, max_length=2_000)
    source_reference: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_class_value_pairs(self) -> WindClassMultiplierOverride:
        if not any((self.terrain_category, self.shielding_class, self.topographic_class)):
            raise ValueError(
                "At least one reviewed terrain, shielding, or topographic class is required."
            )
        if self.mzcat is not None and self.terrain_category is None:
            raise ValueError("terrain_category is required when mzcat is supplied.")
        if self.ms is not None and self.shielding_class is None:
            raise ValueError("shielding_class is required when ms is supplied.")
        if self.mt is not None and self.topographic_class is None:
            raise ValueError("topographic_class is required when mt is supplied.")
        return self


class WindWorkflowRequest(TerrainCategoryEvidenceRequest):
    """AS/NZS 1170.2 site wind workflow request.

    The workflow uses bundled wind-region, VR, and Md lookup data for engineering
    review and does not calculate pressures.
    """

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        str_max_length=5_000,
    )

    project_number: str | None = Field(default=None, max_length=200)
    annual_exceedance_probability: str = Field(default="1/500", min_length=1, max_length=50)
    importance_level: str | None = Field(default=None, max_length=100)
    user_assumptions: str | None = Field(default=None, max_length=5_000)
    structure_class: Literal["building", "house", "monopole", "tower", "other"] | None = None
    structure_type: str | None = Field(default=None, max_length=300)
    wind_direction_multiplier_case: WindDirectionMultiplierCase = "main_structure"
    building_dimensions: str | None = Field(default=None, max_length=300)
    structure_orientation_deg: float | None = Field(default=None, ge=-90, le=90)
    roof_shape: Literal["gable", "hip", "monoslope"] | None = None
    building_width_m: float | None = Field(default=None, gt=0, le=5000)
    building_length_m: float | None = Field(default=None, gt=0, le=5000)
    roof_pitch_deg: float | None = Field(default=None, ge=0, le=90)
    average_roof_height_m: float | None = Field(
        default=None,
        gt=0,
        le=200,
        validation_alias=AliasChoices("average_roof_height_m", "average_height_m"),
        description=(
            "Average roof height h in metres for Mz,cat, shielding, and topographic calculations."
        ),
    )
    base_rl_m: float | None = Field(default=None, ge=-500, le=10_000)
    design_life_years: int | None = Field(default=None, gt=0, le=1000)
    assessment_status: AssessmentStatus = "draft"
    reviewed_by: str | None = Field(default=None, max_length=200)
    engineer_notes: str | None = Field(default=None, max_length=5000)
    class_multiplier_overrides: list[WindClassMultiplierOverride] = Field(
        default_factory=list,
        max_length=MAX_CLASS_MULTIPLIER_OVERRIDES,
    )
    workflow_overrides: list[WindVariableOverride] = Field(
        default_factory=list,
        max_length=MAX_WORKFLOW_OVERRIDES,
    )

    @field_validator("assessment_status", mode="before")
    @classmethod
    def reject_final_issue_status(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().lower() == "final":
            raise ValueError(
                "Final or certified issue is not supported. Use draft or reviewed; all "
                "OpenWind-AU workflow outputs remain preliminary."
            )
        return value

    @field_validator("reviewed_by", "engineer_notes", mode="before")
    @classmethod
    def normalize_review_text(cls, value: Any) -> Any:
        if value is None or not isinstance(value, str):
            return value
        return value.strip() or None

    @model_validator(mode="after")
    def validate_unique_overrides(self) -> WindWorkflowRequest:
        workflow_keys = [(item.variable, item.direction) for item in self.workflow_overrides]
        if len(workflow_keys) != len(set(workflow_keys)):
            raise ValueError("workflow_overrides contains duplicate variable/direction entries.")
        class_directions = [item.direction for item in self.class_multiplier_overrides]
        if len(class_directions) != len(set(class_directions)):
            raise ValueError("class_multiplier_overrides contains duplicate directions.")
        if self.assessment_status == "reviewed" and not self.reviewed_by:
            raise ValueError("reviewed_by is required for a reviewed preliminary assessment.")
        if self.assessment_status == "reviewed" and not self.engineer_notes:
            raise ValueError("engineer_notes are required for a reviewed preliminary assessment.")
        if (
            self.average_roof_height_m is not None
            and self.average_roof_height_m > self.building_height_m
        ):
            raise ValueError("Average roof height must not exceed the overall building height.")
        return self


class WindVariableAssessment(BaseModel):
    """Reviewable value for one AS/NZS site wind workflow variable."""

    model_config = ConfigDict(extra="forbid", strict=True)

    variable: WindWorkflowVariable
    label: str
    direction: WindDirection | None = None
    unit: str = ""
    recommended_value: float | None = None
    recommended_label: str | None = None
    confidence: Literal["high", "medium", "low"] = "low"
    calculated_value: float | None = None
    final_value: float | None = None
    final_label: str | None = None
    override_value: float | None = None
    override_reason: str | None = None
    is_overridden: bool = False
    warnings: list[str] = Field(default_factory=list)
    evidence_link: str
    source_reference: str = "Engineer review required."
    detail_label: str = "Show calculation"
    formula_basis: str
    calculation_inputs: list[str] = Field(default_factory=list)
    detail_items: list[str] = Field(default_factory=list)
    calculation_result: str


class SiteWindSpeedRow(BaseModel):
    """Directional Vsit,b row assembled from reviewed workflow variables."""

    model_config = ConfigDict(extra="forbid", strict=True)

    direction: WindDirection
    vr: float | None = None
    mc: float | None = None
    md: float | None = None
    mzcat: float | None = None
    ms: float | None = None
    mt: float | None = None
    recommended_vsitb: float | None = None
    final_vsitb: float | None = None
    status: Literal["blocked", "calculated"] = "blocked"
    is_governing: bool = False
    warnings: list[str] = Field(default_factory=list)


class WindWorkflowResult(BaseModel):
    """AS/NZS 1170.2 site wind workflow result through Vsit,b."""

    model_config = ConfigDict(extra="forbid", strict=True)

    input: WindWorkflowRequest
    site: SiteLocation
    wind_region_assessment: PublicWindRegionAssessment
    regional_wind_speed_assessment: RegionalWindSpeedAssessment
    direction_multiplier_assessment: DirectionMultiplierAssessment
    variables: list[WindVariableAssessment]
    directional_vsitb: list[SiteWindSpeedRow]
    governing_direction: WindDirection | None = None
    governing_vsitb: float | None = None
    integrity_token: str | None = Field(
        default=None,
        description="Server-issued integrity token required by completed-result report routes.",
    )
    evidence_references: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "OpenWind-AU organises preliminary site wind evidence through Vsit,b for "
        "engineering review. It does not calculate final pressures and does not certify "
        "AS/NZS 1170.2 compliance."
    )


@dataclass(frozen=True)
class ElevationSample:
    """Simple elevation sample for internal calculations."""

    distance_m: float
    latitude: float
    longitude: float
    elevation_m: float
