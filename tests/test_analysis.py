"""Tests for terrain profile and topographic feature analysis."""

from __future__ import annotations

import math

import pytest

from openwind_au.analysis import (
    detect_topographic_features,
    generate_terrain_profiles,
    run_site_analysis,
)
from openwind_au.dem import DEMProvider
from openwind_au.models import SiteAnalysisRequest


class DirectionalRidgeDEM(DEMProvider):
    """Synthetic DEM with a ridge to the east of the site."""

    def __init__(self, origin_latitude: float, origin_longitude: float) -> None:
        self.origin_latitude = origin_latitude
        self.origin_longitude = origin_longitude

    def elevation(self, latitude: float, longitude: float) -> float:
        east_m = (
            (longitude - self.origin_longitude)
            * 111_320
            * math.cos(math.radians(self.origin_latitude))
        )
        north_m = (latitude - self.origin_latitude) * 110_540
        ridge = 42 * math.exp(-((east_m - 800) ** 2) / (2 * 180**2))
        valley = -18 * math.exp(-((north_m + 600) ** 2) / (2 * 160**2))
        return 100 + 0.01 * east_m + ridge + valley


def test_generate_terrain_profiles_creates_full_circle() -> None:
    dem = DirectionalRidgeDEM(-33.86, 151.21)

    profiles = generate_terrain_profiles(
        latitude=-33.86,
        longitude=151.21,
        dem_provider=dem,
        radius_m=1000,
        radial_count=8,
        sample_interval_m=100,
    )

    assert len(profiles) == 8
    assert profiles[0].azimuth_deg == pytest.approx(0)
    assert profiles[-1].azimuth_deg == pytest.approx(315)
    assert all(profile.points[0].distance_m == 0 for profile in profiles)
    assert all(profile.points[-1].distance_m == 1000 for profile in profiles)


def test_detect_topographic_features_finds_ridge_or_escarpment() -> None:
    dem = DirectionalRidgeDEM(-33.86, 151.21)
    profiles = generate_terrain_profiles(
        latitude=-33.86,
        longitude=151.21,
        dem_provider=dem,
        radius_m=1400,
        radial_count=16,
        sample_interval_m=50,
    )

    features = detect_topographic_features(profiles, site_elevation_m=100)

    assert features
    assert any(feature.feature_type in {"ridge", "hill", "escarpment"} for feature in features)
    assert all(feature.h_m > 0 for feature in features)
    assert all(feature.lu_m > 0 for feature in features)


def test_run_site_analysis_returns_required_metrics() -> None:
    dem = DirectionalRidgeDEM(-33.86, 151.21)
    request = SiteAnalysisRequest(
        latitude=-33.86,
        longitude=151.21,
        building_height_m=10,
        radius_m=1200,
        radial_count=12,
        sample_interval_m=100,
    )

    result = run_site_analysis(request, dem)

    assert result.site.ground_elevation_m == pytest.approx(100, abs=1)
    assert result.profiles
    assert result.disclaimer
    if result.features:
        feature = result.features[0]
        assert feature.crest_rl_m >= feature.base_rl_m
        assert feature.h_m == pytest.approx(feature.crest_rl_m - feature.base_rl_m)
        assert feature.average_upwind_slope > 0
