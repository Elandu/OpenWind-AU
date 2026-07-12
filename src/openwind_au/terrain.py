"""Reusable terrain profile generation for OpenWind-AU."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from openwind_au.dem import DEMProvider
from openwind_au.geo import destination_point
from openwind_au.models import ElevationSample, TerrainPoint, TerrainProfile

ALLOWED_ANALYSIS_RADII_M = (500, 1000, 2000, 4000)


@dataclass(frozen=True)
class ProfileDirection:
    """Named terrain profile direction."""

    name: str
    azimuth_deg: float


PROFILE_DIRECTIONS = (
    ProfileDirection("N", 0.0),
    ProfileDirection("NE", 45.0),
    ProfileDirection("E", 90.0),
    ProfileDirection("SE", 135.0),
    ProfileDirection("S", 180.0),
    ProfileDirection("SW", 225.0),
    ProfileDirection("W", 270.0),
    ProfileDirection("NW", 315.0),
)


def generate_standard_terrain_profiles(
    latitude: float,
    longitude: float,
    dem_provider: DEMProvider,
    radius_m: int = 2000,
    sample_interval_m: float = 50,
) -> list[TerrainProfile]:
    """Generate the standard 8-direction OpenWind-AU terrain profile set."""

    validate_analysis_radius(radius_m)
    return generate_terrain_profiles(
        latitude=latitude,
        longitude=longitude,
        dem_provider=dem_provider,
        directions=PROFILE_DIRECTIONS,
        radius_m=radius_m,
        sample_interval_m=sample_interval_m,
    )


def generate_terrain_profiles(
    latitude: float,
    longitude: float,
    dem_provider: DEMProvider,
    directions: tuple[ProfileDirection, ...] = PROFILE_DIRECTIONS,
    radius_m: int = 2000,
    sample_interval_m: float = 50,
) -> list[TerrainProfile]:
    """Generate named radial terrain profiles around a site."""

    validate_analysis_radius(radius_m)
    if sample_interval_m <= 0:
        raise ValueError("sample_interval_m must be greater than zero.")
    if sample_interval_m > radius_m:
        raise ValueError("sample_interval_m must be less than or equal to radius_m.")

    distances = profile_distances(radius_m=radius_m, sample_interval_m=sample_interval_m)
    profile_locations: list[list[tuple[float, float, float]]] = []
    for direction in directions:
        profile_locations.append(
            [
                (
                    float(distance),
                    *destination_point(latitude, longitude, direction.azimuth_deg, float(distance)),
                )
                for distance in distances
            ]
        )
    unique_locations = list(
        dict.fromkeys(
            (point_latitude, point_longitude)
            for locations in profile_locations
            for _distance, point_latitude, point_longitude in locations
        )
    )
    batch_elevations = getattr(dem_provider, "elevations", None)
    if callable(batch_elevations):
        elevations = batch_elevations(unique_locations)
    else:
        # Keep duck-typed/custom providers written against the original
        # single-point interface working while built-in providers batch.
        elevations = [
            dem_provider.elevation(point_latitude, point_longitude)
            for point_latitude, point_longitude in unique_locations
        ]
    if len(elevations) != len(unique_locations):
        raise RuntimeError("DEM provider returned a different number of elevations than requested.")
    elevation_by_location = dict(zip(unique_locations, elevations, strict=True))

    profiles: list[TerrainProfile] = []
    for direction, locations in zip(directions, profile_locations, strict=True):
        samples = [
            ElevationSample(
                distance_m=distance,
                latitude=point_latitude,
                longitude=point_longitude,
                elevation_m=elevation_by_location[(point_latitude, point_longitude)],
            )
            for distance, point_latitude, point_longitude in locations
        ]
        elevations = np.array([sample.elevation_m for sample in samples])
        total_rise = elevations[-1] - elevations[0]
        average_slope = float(total_rise / max(distances[-1], 1))
        endpoint = samples[-1]
        profiles.append(
            TerrainProfile(
                direction=direction.name,
                azimuth_deg=direction.azimuth_deg,
                radius_m=radius_m,
                endpoint_latitude=endpoint.latitude,
                endpoint_longitude=endpoint.longitude,
                points=[
                    TerrainPoint(
                        distance_m=sample.distance_m,
                        latitude=sample.latitude,
                        longitude=sample.longitude,
                        elevation_m=sample.elevation_m,
                    )
                    for sample in samples
                ],
                min_elevation_m=float(np.min(elevations)),
                max_elevation_m=float(np.max(elevations)),
                average_slope=average_slope,
            )
        )

    return profiles


def profile_distances(radius_m: int, sample_interval_m: float) -> np.ndarray:
    """Return monotonically increasing profile sample distances including radius."""

    distances = np.arange(0, radius_m + sample_interval_m, sample_interval_m)
    distances = distances[distances <= radius_m]
    if distances[-1] < radius_m:
        distances = np.append(distances, radius_m)
    return distances


def sample_elevation(
    latitude: float,
    longitude: float,
    azimuth_deg: float,
    distance_m: float,
    dem_provider: DEMProvider,
) -> ElevationSample:
    """Sample DEM elevation at a radial distance from the site."""

    point_lat, point_lon = destination_point(latitude, longitude, azimuth_deg, distance_m)
    elevation = dem_provider.elevation(point_lat, point_lon)
    return ElevationSample(
        distance_m=distance_m,
        latitude=point_lat,
        longitude=point_lon,
        elevation_m=elevation,
    )


def validate_analysis_radius(radius_m: int | float) -> int:
    """Validate and return a supported analysis radius."""

    if int(radius_m) != float(radius_m):
        raise ValueError("radius_m must be one of 500, 1000, 2000, or 4000.")
    radius = int(radius_m)
    if radius not in ALLOWED_ANALYSIS_RADII_M:
        raise ValueError("radius_m must be one of 500, 1000, 2000, or 4000.")
    return radius
