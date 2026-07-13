"""Tests for conservative topographic feature screening."""

from __future__ import annotations

import pytest

from openwind_au.models import TerrainPoint, TerrainProfile
from openwind_au.topography import analyse_profile_topography, analyse_topography


def make_profile(
    elevations: list[float],
    direction: str = "N",
    *,
    spacing_m: float = 100.0,
) -> TerrainProfile:
    points = [
        TerrainPoint(
            distance_m=float(index * spacing_m),
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
    result = analyse_profile_topography(
        make_profile([100, 100, 100, 100, 100]),
        100,
        average_roof_height_m=20.0,
    )

    assert result.feature_type == "no significant feature"
    assert result.site_rl_m == 100
    assert result.h_m == 0
    assert result.lu_m == 0
    assert result.confidence == "none"
    assert "competent engineer" in " ".join(result.notes)


def test_simple_ridge_profile_returns_ridge_candidate() -> None:
    result = analyse_profile_topography(
        make_profile([100, 105, 125, 105, 100]),
        100,
        average_roof_height_m=20.0,
    )

    assert result.feature_type == "ridge"
    assert result.crest_rl_m == pytest.approx(125)
    assert result.base_rl_m == pytest.approx(100)
    assert result.h_m == pytest.approx(25)
    assert result.lu_m == pytest.approx(62.5)
    assert result.average_upwind_slope == pytest.approx(0.2)
    assert result.mt_geometry_resolved is True
    assert result.confidence == "medium"


def test_broad_low_gradient_ridge_screens_out_as_public_dem_undulation() -> None:
    elevations = [
        110,
        112,
        115,
        118,
        121,
        124,
        127,
        130,
        132,
        133,
        132,
        130,
        127,
        124,
        121,
        118,
        115,
        112,
        109,
        106,
        103,
        100,
        100,
    ]

    result = analyse_profile_topography(
        make_profile(elevations),
        110,
        average_roof_height_m=20.0,
    )

    assert result.feature_type == "no significant feature"
    assert result.h_m == 0


def test_large_relief_gentle_ridge_is_still_reported_for_review() -> None:
    elevations = [
        110,
        116,
        122,
        128,
        134,
        140,
        146,
        152,
        158,
        164,
        170,
        166,
        162,
        158,
        154,
        150,
        145,
        140,
        134,
        128,
        120,
        100,
        100,
    ]

    result = analyse_profile_topography(
        make_profile(elevations),
        110,
        average_roof_height_m=20.0,
    )

    assert result.feature_type == "ridge"
    assert result.h_m == pytest.approx(70)
    assert result.average_upwind_slope < 0.1


def test_simple_hill_profile_returns_hill_candidate() -> None:
    result = analyse_profile_topography(
        make_profile([100, 105, 112, 122, 135]),
        100,
        average_roof_height_m=20.0,
    )

    assert result.feature_type == "hill"
    assert result.crest_rl_m == pytest.approx(135)
    assert result.crest_x_m == pytest.approx(400)
    assert result.h_m == pytest.approx(35)
    assert result.lu_m == pytest.approx(400)


def test_escarpment_profile_returns_escarpment_candidate() -> None:
    result = analyse_profile_topography(
        make_profile([100, 100, 130, 132, 132]),
        100,
        average_roof_height_m=20.0,
    )

    assert result.feature_type == "escarpment"
    assert result.h_m == pytest.approx(30)
    assert result.lu_m == pytest.approx(100)
    assert result.average_upwind_slope == pytest.approx(0.3)
    assert result.mt_geometry_resolved is False
    assert result.confidence == "medium"


def test_windward_escarpment_resolves_clause_4_4_half_height_geometry() -> None:
    result = analyse_profile_topography(
        make_profile([132, 132, 130, 100, 100]),
        132,
        average_roof_height_m=20.0,
    )

    assert result.feature_type == "escarpment"
    assert result.h_m == pytest.approx(30)
    assert result.lu_m == pytest.approx(50)
    assert result.x_m == pytest.approx(200)
    assert result.average_upwind_slope == pytest.approx(0.3)
    assert result.mt_geometry_resolved is True


def test_valley_profile_returns_valley_candidate() -> None:
    result = analyse_profile_topography(
        make_profile([120, 110, 90, 110, 120]),
        100,
        average_roof_height_m=20.0,
    )

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

    results = analyse_topography(profiles, site_rl_m=100, average_roof_height_m=20.0)

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


def test_feature_screening_uses_dynamic_clause_height_threshold() -> None:
    profile = make_profile([100, 100, 104.5, 100, 100], spacing_m=10.0)

    low_building = analyse_profile_topography(
        profile,
        100,
        average_roof_height_m=10.0,
    )
    taller_building = analyse_profile_topography(
        profile,
        100,
        average_roof_height_m=20.0,
    )

    assert low_building.feature_type in {"ridge", "escarpment"}
    assert low_building.h_m == pytest.approx(4.5)
    assert taller_building.feature_type == "no significant feature"
