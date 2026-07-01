"""Terrain profile and preliminary site analysis orchestration."""

from __future__ import annotations

from openwind_au.dem import DEMProvider
from openwind_au.geo import geocode_address
from openwind_au.models import (
    SiteAnalysisRequest,
    SiteAnalysisResult,
    SiteLocation,
    TerrainProfile,
    TopographicFeature,
)
from openwind_au.terrain import generate_standard_terrain_profiles
from openwind_au.topography import analyse_topography


def run_site_analysis(
    request: SiteAnalysisRequest,
    dem_provider: DEMProvider,
) -> SiteAnalysisResult:
    """Run preliminary terrain and topographic site analysis."""

    location = resolve_site_location(request, dem_provider)
    profiles = generate_standard_terrain_profiles(
        latitude=location.latitude,
        longitude=location.longitude,
        dem_provider=dem_provider,
        radius_m=request.radius_m,
        sample_interval_m=request.sample_interval_m,
    )
    features = analyse_topography(profiles, location.ground_elevation_m)
    return SiteAnalysisResult(
        input=request,
        site=location,
        profiles=profiles,
        features=features,
        assumptions=[
            "Terrain profiles are sampled in the eight cardinal and intercardinal directions.",
            "DEM elevations are public SRTM terrain data and may not reflect local survey levels.",
            "Topographic screening is rule-based and conservative.",
            "Feature metrics are geometric indicators for preliminary engineering review only.",
            "Building height is recorded for context and future wind workflow integration.",
        ],
        limitations=[
            "This terrain endpoint does not calculate final terrain category, certified shielding "
            "multipliers, topographic multipliers, or design wind pressures.",
            "Candidate ridges, hills, escarpments, and valleys require review "
            "by a competent engineer against project-specific context.",
            "SRTM DEM resolution and vertical accuracy may be insufficient for final design "
            "decisions.",
        ],
    )


def resolve_site_location(request: SiteAnalysisRequest, dem_provider: DEMProvider) -> SiteLocation:
    """Resolve request address/coordinates and sample ground elevation."""

    if request.latitude is not None and request.longitude is not None:
        latitude = request.latitude
        longitude = request.longitude
        display_name = request.address
        source = "User supplied coordinates"
    else:
        assert request.address is not None
        geocoded = geocode_address(request.address)
        latitude = geocoded["latitude"]
        longitude = geocoded["longitude"]
        display_name = geocoded.get("display_name")
        source = geocoded.get("source", "OpenStreetMap Nominatim")

    ground_elevation = dem_provider.elevation(latitude, longitude)
    return SiteLocation(
        latitude=latitude,
        longitude=longitude,
        ground_elevation_m=ground_elevation,
        source=source,
        display_name=display_name,
    )


def detect_topographic_features(
    profiles: list[TerrainProfile],
    site_elevation_m: float,
) -> list[TopographicFeature]:
    """Backward-compatible wrapper for rule-based topographic screening."""

    return analyse_topography(profiles, site_elevation_m)
