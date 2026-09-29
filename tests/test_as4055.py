"""AS 4055:2021 scope, classification and housing pressure regressions."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openwind_au.api import create_app
from openwind_au.as4055 import (
    HousingGeometry,
    HousingSurface,
    SiteConditions,
    calculate_housing_loads,
    calculate_racking_force,
    calculate_uplift,
    classify_site,
)
from openwind_au.calculations import list_calculations, run_calculation


def _geometry(**overrides) -> HousingGeometry:
    values = {
        "building_class": "1",
        "eaves_height_m": 3.0,
        "roof_height_m": 5.0,
        "width_m": 10.0,
        "length_m": 20.0,
        "roof_pitch_degrees": 20.0,
    }
    return HousingGeometry(**(values | overrides))


def _site(**overrides) -> SiteConditions:
    values = {
        "region": "A",
        "terrain_category": "TC3",
        "topographic_class": "T0",
        "shielding_class": "FS",
    }
    return SiteConditions(**(values | overrides))


def test_non_cyclonic_site_class_and_speed_lookup() -> None:
    result = classify_site(_geometry(), _site())

    assert result.site_wind_classification == "N1"
    assert result.roof_classification == "N1r"
    assert result.wall_classification == "N1w"
    assert result.serviceability_gust_speed_m_s == 26.0
    assert result.ultimate_gust_speed_m_s == 34.0
    assert len(result.lookup_digest) == 64
    assert result.status == "preliminary_independent_review_required"


@pytest.mark.parametrize(
    ("distance", "expected"),
    [(0.0, "C2"), (10.0, "C2"), (10.01, "C1"), (50.0, "C1")],
)
def test_region_c_distance_bands(distance: float, expected: str) -> None:
    result = classify_site(
        _geometry(),
        _site(
            region="C",
            shielding_class="PS",
            distance_km=distance,
            distance_basis="smoothed_coastline",
        ),
    )
    assert result.site_wind_classification == expected


def test_region_d_uses_boundary_distance_and_na_returns_referral() -> None:
    result = classify_site(
        _geometry(),
        _site(
            region="D", terrain_category="TC3", distance_km=0.0, distance_basis="smoothed_coastline"
        ),
    )
    assert result.site_wind_classification == "C2"
    assert result.referral is None

    unsupported = classify_site(
        _geometry(),
        _site(
            region="D",
            terrain_category="TC1",
            topographic_class="T4",
            shielding_class="NS",
            distance_km=0.0,
            distance_basis="smoothed_coastline",
        ),
    )
    assert unsupported.site_wind_classification == "NA"
    assert "refer to AS/NZS 1170.2" in (unsupported.referral or "")


@pytest.mark.parametrize(
    "overrides",
    [
        {"building_class": "2"},
        {"eaves_height_m": 6.01},
        {"roof_height_m": 8.51},
        {"width_m": 16.01},
        {"length_m": 50.01},
        {"roof_pitch_degrees": 35.01},
        {"width_m": 11.0, "length_m": 10.0},
    ],
)
def test_geometry_outside_scope_is_referred(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="AS 4055|refer to AS/NZS 1170.2"):
        classify_site(_geometry(**overrides), _site())


def test_region_c_requires_distance() -> None:
    with pytest.raises(ValueError, match="require a verified boundary/coast distance"):
        classify_site(_geometry(), _site(region="C"))


def test_non_cyclonic_pressure_and_force_calculation() -> None:
    classification = classify_site(_geometry(), _site())
    loads = calculate_housing_loads(
        classification,
        (HousingSurface(component="roof_cladding", zone="G", area_m2=10.0),),
        limit_state="ultimate",
        roof_pitch_degrees=20.0,
    )

    net_suction = next(
        load for load in loads if load.pressure_basis == "net" and load.load_case == "suction"
    )
    assert net_suction.pressure_coefficient == -1.0
    assert net_suction.pressure_kpa == pytest.approx(-0.6936)
    assert net_suction.force_kn == pytest.approx(-6.936)
    assert net_suction.limit_state == "ultimate"
    assert net_suction.design_gust_speed_m_s == 34.0
    assert net_suction.dynamic_gust_pressure_kpa == pytest.approx(0.6936)
    assert calculate_uplift(loads, "roof_cladding") == pytest.approx(6.936)


def test_cyclonic_ultimate_uses_cyclonic_corner_coefficient() -> None:
    classification = classify_site(
        _geometry(),
        _site(region="C", distance_km=0.0, distance_basis="smoothed_coastline"),
    )
    loads = calculate_housing_loads(
        classification,
        (HousingSurface(component="roof_cladding", zone="RC", area_m2=1.0),),
        limit_state="ultimate",
        roof_pitch_degrees=9.9,
    )
    net_suction = next(
        load for load in loads if load.pressure_basis == "net" and load.load_case == "suction"
    )
    assert net_suction.pressure_coefficient == -3.06
    assert net_suction.pressure_kpa == pytest.approx(-4.59)


def test_cyclonic_serviceability_uses_serviceability_corner_coefficient() -> None:
    classification = classify_site(
        _geometry(),
        _site(
            region="C",
            shielding_class="PS",
            distance_km=0.0,
            distance_basis="smoothed_coastline",
        ),
    )
    loads = calculate_housing_loads(
        classification,
        (HousingSurface(component="roof_cladding", zone="RC", area_m2=1.0),),
        limit_state="serviceability",
        roof_pitch_degrees=9.9,
    )
    net_suction = next(
        load for load in loads if load.pressure_basis == "net" and load.load_case == "suction"
    )

    assert classification.site_wind_classification == "C2"
    assert net_suction.pressure_coefficient == -2.61
    assert net_suction.dynamic_gust_pressure_kpa == pytest.approx(0.9126)
    assert net_suction.pressure_kpa == pytest.approx(-2.381886)


def test_roof_corner_rule_and_racking_force() -> None:
    classification = classify_site(_geometry(), _site())
    with pytest.raises(ValueError, match="below 10 degrees"):
        calculate_housing_loads(
            classification,
            (HousingSurface(component="roof_cladding", zone="RC", area_m2=1.0),),
            roof_pitch_degrees=10.0,
        )
    assert calculate_racking_force(42.0, 0.8) == pytest.approx(33.6)


def test_load_calculation_refuses_na_classification() -> None:
    classification = classify_site(
        _geometry(),
        _site(
            region="D",
            terrain_category="TC1",
            topographic_class="T4",
            shielding_class="NS",
            distance_km=0.0,
            distance_basis="smoothed_coastline",
        ),
    )
    with pytest.raises(ValueError, match="marks this site condition/distance NA"):
        calculate_housing_loads(
            classification,
            (HousingSurface(component="wall_cladding", zone="G", area_m2=1.0),),
        )


def test_as4055_api_classifies_and_calculates_in_a_separate_path() -> None:
    client = TestClient(create_app())
    classification_response = client.post(
        "/api/as4055/classification",
        json={
            "geometry": {
                "building_class": "1",
                "eaves_height_m": 3,
                "roof_height_m": 5,
                "width_m": 10,
                "length_m": 20,
                "roof_pitch_degrees": 20,
            },
            "site_conditions": {
                "region": "A",
                "terrain_category": "TC3",
                "topographic_class": "T0",
                "shielding_class": "FS",
            },
        },
    )

    assert classification_response.status_code == 200
    classification = classification_response.json()
    assert classification["site_wind_classification"] == "N1"
    loads_response = client.post(
        "/api/as4055/housing-loads",
        json={
            "classification": classification,
            "surfaces": [{"component": "roof_cladding", "zone": "G", "area_m2": 10}],
            "limit_state": "ultimate",
            "roof_pitch_degrees": 20,
        },
    )

    assert loads_response.status_code == 200
    assert loads_response.json()["uplift_force_kn"]["roof_cladding_load_path"] == pytest.approx(
        6.936
    )
    assert loads_response.json()["lookup_digest"] == classification["lookup_digest"]
    assert loads_response.json()["status"] == "preliminary_independent_review_required"


def test_opencalcs_registry_exposes_as4055_as_a_separate_standard_path() -> None:
    ids = {item["id"] for item in list_calculations()}
    assert {
        "au.wind.as4055.classify_housing_site",
        "au.wind.as4055.housing_surface_loads",
        "au.wind.as4055.racking_force",
    } <= ids

    classified = run_calculation(
        "au.wind.as4055.classify_housing_site",
        {
            "geometry": {
                "building_class": "1",
                "eaves_height_m": 3.0,
                "roof_height_m": 5.0,
                "width_m": 10.0,
                "length_m": 20.0,
                "roof_pitch_degrees": 20.0,
            },
            "site_conditions": {
                "region": "A",
                "terrain_category": "TC3",
                "topographic_class": "T0",
                "shielding_class": "FS",
            },
        },
    )
    assert classified["classification"]["site_wind_classification"] == "N1"
    loads = run_calculation(
        "au.wind.as4055.housing_surface_loads",
        {
            "classification": classified["classification"],
            "surfaces": [{"component": "roof_cladding", "zone": "G", "area_m2": 10.0}],
            "limit_state": "ultimate",
            "roof_pitch_degrees": 20.0,
        },
    )
    assert loads["status"] == "preliminary_independent_review_required"
    assert loads["uplift_force_kn"]["roof_cladding_load_path"] == pytest.approx(6.936)
    assert loads["site_wind_classification"] == "N1"
    assert len(loads["lookup_digest"]) == 64
