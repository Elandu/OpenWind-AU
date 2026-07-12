"""Tests for reusable terrain profile generation."""

from __future__ import annotations

import pytest

from openwind_au.dem import DEMProvider
from openwind_au.terrain import (
    ALLOWED_ANALYSIS_RADII_M,
    PROFILE_DIRECTIONS,
    generate_standard_terrain_profiles,
    profile_distances,
    validate_analysis_radius,
)


class SlopingDEM(DEMProvider):
    """Synthetic DEM that rises with latitude and longitude."""

    def elevation(self, latitude: float, longitude: float) -> float:
        return 100 + latitude * 10 + longitude * 5


class BatchTrackingDEM(SlopingDEM):
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def elevations(self, points: list[tuple[float, float]]) -> list[float]:
        self.batch_sizes.append(len(points))
        return super().elevations(points)


class LegacySinglePointDEM:
    """Duck-typed provider implementing the original elevation contract only."""

    def elevation(self, latitude: float, longitude: float) -> float:
        return 50.0 + latitude - longitude


def test_profile_direction_contract() -> None:
    assert [direction.name for direction in PROFILE_DIRECTIONS] == [
        "N",
        "NE",
        "E",
        "SE",
        "S",
        "SW",
        "W",
        "NW",
    ]
    assert [direction.azimuth_deg for direction in PROFILE_DIRECTIONS] == [
        0.0,
        45.0,
        90.0,
        135.0,
        180.0,
        225.0,
        270.0,
        315.0,
    ]


@pytest.mark.parametrize("radius", ALLOWED_ANALYSIS_RADII_M)
def test_allowed_analysis_radii(radius: int) -> None:
    assert validate_analysis_radius(radius) == radius


def test_validate_analysis_radius_rejects_other_values() -> None:
    with pytest.raises(ValueError, match="radius_m must be one of"):
        validate_analysis_radius(1500)


def test_profile_distances_include_endpoint() -> None:
    distances = profile_distances(radius_m=500, sample_interval_m=120)

    assert distances[0] == pytest.approx(0)
    assert distances[-1] == pytest.approx(500)
    assert all(left < right for left, right in zip(distances, distances[1:], strict=False))


def test_standard_profiles_include_endpoint_coordinates() -> None:
    profiles = generate_standard_terrain_profiles(
        latitude=-33.86,
        longitude=151.21,
        dem_provider=SlopingDEM(),
        radius_m=500,
        sample_interval_m=100,
    )

    assert len(profiles) == 8
    assert all(profile.points[-1].distance_m == 500 for profile in profiles)
    assert all(profile.endpoint_latitude == profile.points[-1].latitude for profile in profiles)
    assert all(profile.endpoint_longitude == profile.points[-1].longitude for profile in profiles)


def test_standard_profiles_request_unique_elevations_in_one_batch() -> None:
    dem = BatchTrackingDEM()

    profiles = generate_standard_terrain_profiles(
        latitude=-33.86,
        longitude=151.21,
        dem_provider=dem,
        radius_m=500,
        sample_interval_m=100,
    )

    assert len(profiles) == 8
    assert dem.batch_sizes == [41]


def test_standard_profiles_support_legacy_single_point_provider() -> None:
    profiles = generate_standard_terrain_profiles(
        latitude=-33.86,
        longitude=151.21,
        dem_provider=LegacySinglePointDEM(),  # type: ignore[arg-type]
        radius_m=500,
        sample_interval_m=100,
    )

    assert len(profiles) == 8
    assert all(len(profile.points) == 6 for profile in profiles)
