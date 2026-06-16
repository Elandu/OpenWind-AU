"""Tests for conservative topographic feature screening."""

from __future__ import annotations

import pytest

from openwind_au.models import TerrainPoint, TerrainProfile
from openwind_au.topography import analyse_profile_topography, analyse_topography


def make_profile(elevations: list[float], direction: str = "N") -> TerrainProfile:
    points = [
        TerrainPoint(
            distance_m=float(index * 100),
            latitude=-33.86,
            longitude=151.21,
            elevation_m=elevation,
        )
        for index, elevation in enumerate(elevations)
    ]
    return TerrainProfile(
        direction=direction,
        azimuth_deg=0.0,
        radius_m=int(points[-1].distance_m),
        endpoint_latitude=points[-1].latitude,
        endpoint_longitude=points[-1].longitude,
        points=points,
        min_elevation_m=min(elevations),
        max_elevation_m=max(elevations),
        average_slope=(elevations[-1] - elevations[0]) / max(points[-1].distance_m, 1),
    )


def test_flat_profile_returns_no_significant_feature() -> None:
    result = analyse_profile_topography(make_profile([100, 100, 100, 100, 100]), 100)

    assert result.feature_type == "no significant feature"
    assert result.site_rl_m == 100
    assert result.h_m == 0
    assert result.lu_m == 0
    assert result.confidence == "none"
    assert "competent engineer" in " ".join(result.notes)


def test_simple_ridge_profile_returns_ridge_candidate() -> None:
    result = analyse_profile_topography(make_profile([100, 105, 125, 105, 100]), 100)

    assert result.feature_type == "ridge"
    assert result.crest_rl_m == pytest.approx(125)
    assert result.base_rl_m == pytest.approx(100)
    assert result.h_m == pytest.approx(25)
    assert result.lu_m == pytest.approx(200)
    assert result.average_upwind_slope == pytest.approx(0.125)
    assert result.confidence == "low"


def test_simple_hill_profile_returns_hill_candidate() -> None:
    result = analyse_profile_topography(make_profile([100, 105, 112, 122, 135]), 100)

    assert result.feature_type == "hill"
    assert result.crest_rl_m == pytest.approx(135)
    assert result.crest_x_m == pytest.approx(400)
    assert result.h_m == pytest.approx(35)
    assert result.lu_m == pytest.approx(400)


def test_escarpment_profile_returns_escarpment_candidate() -> None:
    result = analyse_profile_topography(make_profile([100, 100, 130, 132, 132]), 100)

    assert result.feature_type == "escarpment"
    assert result.h_m == pytest.approx(30)
    assert result.lu_m == pytest.approx(100)
    assert result.average_upwind_slope == pytest.approx(0.3)
    assert result.confidence == "medium"


def test_valley_profile_returns_valley_candidate() -> None:
    result = analyse_profile_topography(make_profile([120, 110, 90, 110, 120]), 100)

    assert result.feature_type == "valley"
    assert result.base_rl_m == pytest.approx(90)
    assert result.crest_rl_m == pytest.approx(120)
    assert result.h_m == pytest.approx(30)
    assert result.x_m == pytest.approx(200)


def test_analyse_topography_returns_one_result_per_profile() -> None:
    profiles = [
        make_profile([100, 100, 100, 100, 100], direction)
        for direction in ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    ]

    results = analyse_topography(profiles, site_rl_m=100)

    assert len(results) == 8
    assert [result.direction for result in results] == [
        "N",
        "NE",
        "E",
        "SE",
        "S",
        "SW",
        "W",
        "NW",
    ]
    assert all(result.feature_type == "no significant feature" for result in results)
