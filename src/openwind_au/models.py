"""Pydantic models and typed dataclasses for OpenWind-AU."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
    radius_m: float = Field(default=2000, gt=100, le=10000)
    radial_count: int = Field(default=36, ge=8, le=144)
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

    azimuth_deg: float
    points: list[TerrainPoint]
    min_elevation_m: float
    max_elevation_m: float
    average_slope: float


class TopographicFeature(BaseModel):
    """Detected topographic feature relevant to preliminary wind review."""

    feature_type: Literal["ridge", "hill", "escarpment", "valley"]
    azimuth_deg: float
    crest_rl_m: float
    base_rl_m: float
    h_m: float
    lu_m: float
    x_m: float
    average_upwind_slope: float
    confidence: Literal["low", "medium", "high"]
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


@dataclass(frozen=True)
class ElevationSample:
    """Simple elevation sample for internal calculations."""

    distance_m: float
    latitude: float
    longitude: float
    elevation_m: float
