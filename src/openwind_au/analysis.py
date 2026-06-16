"""Terrain profile and topographic feature analysis."""

from __future__ import annotations

import numpy as np
from scipy.signal import find_peaks

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
    features = detect_topographic_features(profiles, location.ground_elevation_m)
    return SiteAnalysisResult(
        input=request,
        site=location,
        profiles=profiles,
        features=features,
        assumptions=[
            "Terrain profiles are sampled in the eight cardinal and intercardinal directions.",
            "DEM elevations are public terrain data and may not reflect local survey levels.",
            "Feature metrics are geometric indicators for preliminary engineering review.",
            "Building height is recorded for context and future wind workflow integration.",
        ],
        limitations=[
            "This MVP does not calculate terrain category, shielding, "
            "topographic multipliers, or design wind pressures.",
            "Detected ridges, hills, escarpments, and valleys require review "
            "against project-specific context.",
            "DEM resolution and vertical accuracy may be insufficient for final design decisions.",
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
    """Detect ridges, hills, escarpments, and valleys from terrain profiles."""

    features: list[TopographicFeature] = []
    for profile in profiles:
        distances = np.array([point.distance_m for point in profile.points])
        elevations = np.array([point.elevation_m for point in profile.points])
        if len(distances) < 5:
            continue

        smoothed = _smooth(elevations)
        prominence_threshold = max(5.0, float(np.ptp(smoothed)) * 0.25)
        peaks, peak_props = find_peaks(smoothed, prominence=prominence_threshold)
        valleys, valley_props = find_peaks(-smoothed, prominence=prominence_threshold)

        for peak_index, prominence in zip(peaks, peak_props.get("prominences", []), strict=False):
            feature = _feature_from_peak(
                profile,
                distances,
                smoothed,
                int(peak_index),
                float(prominence),
            )
            if feature:
                features.append(feature)

        for valley_index, prominence in zip(
            valleys, valley_props.get("prominences", []), strict=False
        ):
            feature = _feature_from_valley(
                profile,
                distances,
                smoothed,
                int(valley_index),
                float(prominence),
            )
            if feature:
                features.append(feature)

        slope_feature = _feature_from_steep_slope(profile, distances, smoothed, site_elevation_m)
        if slope_feature:
            features.append(slope_feature)
        endpoint_feature = _feature_from_endpoint_relief(profile, distances, smoothed)
        if endpoint_feature:
            features.append(endpoint_feature)

    features.sort(key=lambda item: (item.azimuth_deg, -item.h_m, item.x_m))
    return features


def _smooth(values: np.ndarray) -> np.ndarray:
    if len(values) < 5:
        return values
    kernel_size = 5
    kernel = np.ones(kernel_size) / kernel_size
    padded = np.pad(values, (kernel_size // 2, kernel_size // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _feature_from_peak(
    profile: TerrainProfile,
    distances: np.ndarray,
    elevations: np.ndarray,
    peak_index: int,
    prominence: float,
) -> TopographicFeature | None:
    crest_rl = float(elevations[peak_index])
    left_min_index = int(np.argmin(elevations[: peak_index + 1]))
    right_min_index = peak_index + int(np.argmin(elevations[peak_index:]))
    base_index = (
        left_min_index
        if elevations[left_min_index] <= elevations[right_min_index]
        else right_min_index
    )
    base_rl = float(elevations[base_index])
    h = crest_rl - base_rl
    if h < 5:
        return None
    lu = abs(float(distances[peak_index] - distances[base_index]))
    if lu <= 0:
        return None
    slope = h / lu
    feature_type = "ridge" if peak_index not in (0, len(distances) - 1) else "hill"
    if slope > 0.2 and lu < 500:
        feature_type = "escarpment"
    return TopographicFeature(
        feature_type=feature_type,
        direction=profile.direction,
        azimuth_deg=profile.azimuth_deg,
        crest_rl_m=crest_rl,
        base_rl_m=base_rl,
        h_m=h,
        lu_m=lu,
        x_m=float(distances[peak_index]),
        average_upwind_slope=slope,
        confidence=_confidence(prominence, slope),
        notes=[
            "Detected from radial DEM profile using peak prominence and slope heuristics.",
            "Review against survey, aerial imagery, and engineering judgement before use.",
        ],
    )


def _feature_from_valley(
    profile: TerrainProfile,
    distances: np.ndarray,
    elevations: np.ndarray,
    valley_index: int,
    prominence: float,
) -> TopographicFeature | None:
    base_rl = float(elevations[valley_index])
    left_max_index = int(np.argmax(elevations[: valley_index + 1]))
    right_max_index = valley_index + int(np.argmax(elevations[valley_index:]))
    crest_index = (
        left_max_index
        if elevations[left_max_index] >= elevations[right_max_index]
        else right_max_index
    )
    crest_rl = float(elevations[crest_index])
    h = crest_rl - base_rl
    if h < 5:
        return None
    lu = abs(float(distances[crest_index] - distances[valley_index]))
    if lu <= 0:
        return None
    slope = h / lu
    return TopographicFeature(
        feature_type="valley",
        direction=profile.direction,
        azimuth_deg=profile.azimuth_deg,
        crest_rl_m=crest_rl,
        base_rl_m=base_rl,
        h_m=h,
        lu_m=lu,
        x_m=float(distances[valley_index]),
        average_upwind_slope=slope,
        confidence=_confidence(prominence, slope),
        notes=[
            "Detected from radial DEM profile as a local low point with "
            "surrounding higher terrain.",
            "Review valley orientation and local exposure manually.",
        ],
    )


def _feature_from_steep_slope(
    profile: TerrainProfile,
    distances: np.ndarray,
    elevations: np.ndarray,
    site_elevation_m: float,
) -> TopographicFeature | None:
    gradients = np.gradient(elevations, distances)
    steep_index = int(np.argmax(np.abs(gradients)))
    slope = abs(float(gradients[steep_index]))
    if slope < 0.15:
        return None
    window = max(2, min(6, len(distances) // 5))
    start = max(0, steep_index - window)
    end = min(len(distances) - 1, steep_index + window)
    local = elevations[start : end + 1]
    crest_rl = float(np.max(local))
    base_rl = float(np.min(local))
    h = crest_rl - base_rl
    if h < 5:
        return None
    lu = float(distances[end] - distances[start])
    return TopographicFeature(
        feature_type="escarpment",
        direction=profile.direction,
        azimuth_deg=profile.azimuth_deg,
        crest_rl_m=crest_rl,
        base_rl_m=base_rl,
        h_m=h,
        lu_m=max(lu, 1.0),
        x_m=float(distances[steep_index]),
        average_upwind_slope=slope,
        confidence=_confidence(h, slope),
        notes=[
            f"Steep local slope detected relative to site RL {site_elevation_m:.1f} m.",
            "Treat as a preliminary escarpment indicator requiring manual review.",
        ],
    )


def _feature_from_endpoint_relief(
    profile: TerrainProfile,
    distances: np.ndarray,
    elevations: np.ndarray,
) -> TopographicFeature | None:
    """Detect a hill/rising feature where the crest is at the profile endpoint."""

    endpoint_index = len(elevations) - 1
    crest_rl = float(elevations[endpoint_index])
    base_index = int(np.argmin(elevations))
    base_rl = float(elevations[base_index])
    h = crest_rl - base_rl
    lu = abs(float(distances[endpoint_index] - distances[base_index]))
    if h < 5 or lu <= 0:
        return None
    slope = h / lu
    if slope < 0.03:
        return None
    return TopographicFeature(
        feature_type="hill",
        direction=profile.direction,
        azimuth_deg=profile.azimuth_deg,
        crest_rl_m=crest_rl,
        base_rl_m=base_rl,
        h_m=h,
        lu_m=lu,
        x_m=float(distances[endpoint_index]),
        average_upwind_slope=slope,
        confidence=_confidence(h, slope),
        notes=[
            "Rising terrain reaches a local maximum at the analysis radius endpoint.",
            "Extend the radius or review wider terrain before treating this as a bounded hill.",
        ],
    )


def _confidence(prominence: float, slope: float) -> str:
    if prominence >= 20 and slope >= 0.15:
        return "high"
    if prominence >= 10 and slope >= 0.08:
        return "medium"
    return "low"
