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


class ObstructionManualOverride(BaseModel):
    """Reviewed obstruction height data supplied by a user."""

    obstruction_id: str
    height_m: float | None = Field(default=None, ge=0)
    building_levels: float | None = Field(default=None, ge=0)
    height_source: str = "manual_review"
    notes: str | None = None


class ObstructionInventoryRequest(BaseModel):
    """Input payload for building obstruction inventory."""

    address: str | None = Field(default=None, description="Street address to geocode.")
    latitude: float | None = Field(default=None, ge=-44.5, le=-9.0)
    longitude: float | None = Field(default=None, ge=112.0, le=154.5)
    radius_m: int = Field(default=500, ge=50, le=4000)
    default_storey_height_m: float = Field(default=3.0, gt=0, le=6)
    manual_overrides: list[ObstructionManualOverride] = Field(default_factory=list)

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
    footprint_geometry: dict[str, Any]
    centroid_latitude: float
    centroid_longitude: float
    distance_m: float
    bearing_deg: float
    height_m: float | None
    building_levels: float | None
    height_source: Literal["explicit_height", "building_levels", "manual_override", "missing"]
    confidence: Literal["verified", "high", "medium", "unknown"]
    manual_review_required: bool
    tags: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ObstructionInventoryResult(BaseModel):
    """Complete obstruction inventory result."""

    input: ObstructionInventoryRequest
    site: SiteLocation
    obstructions: list[ObstructionRecord]
    missing_height_count: int
    reviewed_height_count: int
    data_source_status: Literal["ok", "unavailable"] = "ok"
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "OpenWind-AU provides obstruction inventory data for shielding review only. "
        "Ms cannot be assessed without reliable obstruction heights and competent "
        "engineering review."
    )


class CombinedMapRequest(SiteAnalysisRequest):
    """Request for the unified site + obstruction map with toggleable layers.

    Extends :class:`SiteAnalysisRequest` with the obstruction inventory fields so
    a single map can be rendered that combines the terrain analysis radius, the
    8-direction profile lines, candidate topographic features, and the nearby
    building obstruction footprints.
    """

    obstruction_radius_m: int = Field(default=500, ge=50, le=4000)
    default_storey_height_m: float = Field(default=3.0, gt=0, le=6)
    manual_overrides: list[ObstructionManualOverride] = Field(default_factory=list)


@dataclass(frozen=True)
class ElevationSample:
    """Simple elevation sample for internal calculations."""

    distance_m: float
    latitude: float
    longitude: float
    elevation_m: float
