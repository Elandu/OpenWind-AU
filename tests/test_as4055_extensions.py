"""Source anchors, interpolation, conservation, trust boundaries and API wiring."""

import json
import math
from dataclasses import asdict, replace
from functools import cache

import pytest
from fastapi.testclient import TestClient

from openwind_au.api import create_app
from openwind_au.as4055 import (
    HousingGeometry,
    HousingSurface,
    SiteConditions,
    calculate_housing_loads,
    calculate_pressure_zone_areas,
    calculate_racking_pressure,
    calculate_roof_anchoring,
    classify_site,
)
from openwind_au.as4055_racking_data import RACKING_TABLES
from openwind_au.calculations import run_calculation


@cache
def site_for_class(label):
    geometry = HousingGeometry("1", 2.4, 4.4, 10.0, 20.0, 20.0)
    for region in "ABCD":
        for terrain in ("TC1", "TC2", "TC2.5", "TC3"):
            for topo, shielding in (
                ("T0", "FS"),
                ("T0", "NS"),
                ("T2", "NS"),
                ("T3", "NS"),
                ("T4", "NS"),
                ("T5", "NS"),
            ):
                result = classify_site(
                    geometry,
                    SiteConditions(region, terrain, topo, shielding, 0.0, "smoothed_coastline"),
                )
                if result.site_wind_classification == label:
                    return result.site_conditions
    raise AssertionError(label)


def classified(label="N1", width=10.0, pitch=20.0):
    geometry = HousingGeometry(
        "1", 2.4, 2.4 + width / 2 * math.tan(math.radians(pitch)), width, 20.0, pitch
    )
    return classify_site(geometry, site_for_class(label))


def rack(classification=None, **updates):
    values = dict(
        classification=classification or classified(),
        elevation_type="hip_roof",
        storey="single_or_upper",
        wind_on="side",
        width_m=10.0,
        roof_pitch_degrees=20.0,
        storey_height_m=2.4,
        floor_depth_m=0.3,
        elevation_area_m2=42.0,
    )
    return calculate_racking_pressure(**(values | updates))


@pytest.mark.parametrize(
    "label,expected",
    [
        ("N1", (0, 0.04, 0, 0.33)),
        ("N2", (0, 0.04, 0.14, 0.59)),
        ("N3", (0, 0.25, 0.68, 1.13)),
        ("N4", (0, 0.54, 1.40, 1.85)),
        ("N5", (0.42, 0.95, 2.44, 2.89)),
        ("N6", (0.90, 1.44, 3.58, 4.03)),
        ("C1", (0, 0.25, 1.35, 1.80)),
        ("C2", (0, 0.54, 2.40, 2.85)),
        ("C3", (0.41, 0.95, 3.92, 4.37)),
        ("C4", (0.90, 1.44, 5.58, 6.03)),
    ],
)
def test_table4_all_source_cells(label, expected):
    for i, (state, roof) in enumerate(
        (s, r) for s in ("serviceability", "ultimate") for r in ("tile", "sheet")
    ):
        result = calculate_roof_anchoring(
            classified(label), roof, 200.0, state, all_cladding_resists_design_wind=True
        )
        assert result.net_upward_pressure_kpa == expected[i]
        assert result.anchoring_force_kn == pytest.approx(expected[i] * 200)


def test_anchoring_requires_noncyclonic_envelope_assumption():
    with pytest.raises(ValueError, match="all cladding"):
        calculate_roof_anchoring(
            classified(), "sheet", 200, "ultimate", all_cladding_resists_design_wind=False
        )


@pytest.mark.parametrize("pitch", [0.0, 9.99, 10.0, 20.0, 35.0])
def test_zone_partition_conserves_actual_surface_areas(pitch):
    classification = classified(pitch=pitch)
    zones = calculate_pressure_zone_areas(classification.geometry, "gable" if pitch else "flat")
    roof = sum(s.area_m2 for s in zones if s.component == "roof_cladding")
    wall = sum(s.area_m2 for s in zones if s.component == "wall_cladding")
    assert roof == pytest.approx(200 / math.cos(math.radians(pitch)))
    assert roof == pytest.approx(next(s.area_m2 for s in zones if s.component == "roof_structure"))
    assert wall == pytest.approx(next(s.area_m2 for s in zones if s.component == "wall_structure"))
    assert all(s.area_m2 > 0 for s in zones)
    assert any(s.zone == "RC" for s in zones) == (pitch < 10)
    calculate_housing_loads(classification, zones, roof_pitch_degrees=pitch)


def test_zone_geometry_guard_and_known_flat_areas():
    geometry = classified(pitch=0).geometry
    areas = {
        (s.component, s.zone): s.area_m2 for s in calculate_pressure_zone_areas(geometry, "flat")
    }
    assert areas["roof_cladding", "RC"] == pytest.approx(5.76)
    assert areas["roof_cladding", "G"] == pytest.approx(17.6 * 7.6)
    assert areas["wall_cladding", "SC"] == pytest.approx(8 * 1.2 * 2.4)
    with pytest.raises(ValueError, match="height must match"):
        calculate_pressure_zone_areas(replace(geometry, roof_pitch_degrees=20), "gable")


@pytest.mark.parametrize(
    "label,table,upper,lower",
    [
        ("N1", "B", 0.49, 0.50),
        ("N2", "D", 0.68, 0.69),
        ("N3", "F", 1.06, 1.08),
        ("C1", "F", 1.06, 1.08),
        ("N4", "H", 1.57, 1.61),
        ("C2", "H", 1.57, 1.61),
        ("N5", "J", 2.32, 2.37),
        ("C3", "J", 2.32, 2.37),
        ("N6", "L", 3.13, 3.20),
        ("C4", "L", 3.13, 3.20),
    ],
)
def test_racking_class_and_storey_source_anchors(label, table, upper, lower):
    result = rack(classified(label))
    assert result["source_table"] == f"Table 5.2({table})"
    assert result["lateral_pressure_kpa"] == upper
    assert rack(classified(label), storey="lower")["lateral_pressure_kpa"] == lower


def test_racking_bilinear_interpolation_and_endpoints():
    result = rack(classified(width=10.5, pitch=22.5), width_m=10.5, roof_pitch_degrees=22.5)
    assert result["lateral_pressure_kpa"] == pytest.approx((0.49 + 0.53 + 0.48 + 0.53) / 4)
    assert result["racking_force_kn"] == pytest.approx(0.5075 * 42)
    assert (
        rack(classified(width=16, pitch=35), width_m=16, roof_pitch_degrees=35)[
            "lateral_pressure_kpa"
        ]
        == 0.55
    )
    assert (
        rack(classified(width=4, pitch=0), width_m=4, roof_pitch_degrees=0, wind_on="end")[
            "lateral_pressure_kpa"
        ]
        == 0.63
    )


def test_all_lookup_nodes_are_returned_without_scaling():
    # Verifies addressing of every source cell; source-anchor tests above are separate.
    for group, label in enumerate(("N1", "N2", "N3", "N4", "N5", "N6")):
        for lower in (False, True):
            table = RACKING_TABLES[chr(ord("B") + group * 2 + lower)]
            for direction in ("side", "end"):
                for i, width in enumerate(range(4, 17)):
                    for j, pitch in enumerate(range(0, 36, 5)):
                        result = rack(
                            classified(label, width, pitch),
                            width_m=width,
                            roof_pitch_degrees=pitch,
                            wind_on=direction,
                            storey="lower" if lower else "single_or_upper",
                        )
                        assert result["lateral_pressure_kpa"] == table[direction][i][j]


@pytest.mark.parametrize(
    "updates",
    [
        {"storey_height_m": 3.0},
        {"floor_depth_m": 0.2},
        {"width_m": 16.1},
        {"width_m": 9},
        {"roof_pitch_degrees": 35.1},
        {"roof_pitch_degrees": 25},
        {"elevation_type": "gable_side", "wind_on": "end"},
        {"elevation_area_m2": float("nan")},
    ],
)
def test_racking_rejects_unsupported_inputs(updates):
    with pytest.raises(ValueError):
        rack(**updates)


def test_flat_racking_and_tampered_classification():
    assert (
        rack(elevation_type="flat_vertical", wind_on=None, width_m=None, roof_pitch_degrees=None)[
            "lateral_pressure_kpa"
        ]
        == 0.66
    )
    tampered = replace(classified(), ultimate_gust_speed_m_s=1)
    with pytest.raises(ValueError, match="inconsistent"):
        rack(tampered)
    with pytest.raises(ValueError, match="inconsistent"):
        calculate_housing_loads(tampered, (HousingSurface("roof_cladding", "G", 10),))


def test_extensions_registry_and_api():
    client = TestClient(create_app())
    cls = classified(pitch=0)
    payloads = [
        ("housing_assessment", "housing-assessment", housing_inputs()),
        (
            "pressure_zone_areas",
            "pressure-zones",
            {"geometry": asdict(cls.geometry), "roof_form": "flat"},
        ),
        (
            "roof_anchoring",
            "roof-anchoring",
            {
                "classification": asdict(cls),
                "roof_type": "sheet",
                "roof_surface_area_m2": 200.0,
                "limit_state": "ultimate",
                "all_cladding_resists_design_wind": True,
            },
        ),
        (
            "racking_pressure",
            "racking-pressure",
            {
                "classification": asdict(cls),
                "elevation_type": "flat_vertical",
                "storey_height_m": 2.4,
                "floor_depth_m": 0.3,
                "elevation_area_m2": 42.0,
            },
        ),
    ]
    for name, route, payload in payloads:
        expected = run_calculation(f"au.wind.as4055.{name}", payload)
        response = client.post(f"/api/as4055/{route}", json=payload)
        assert response.status_code == 200, response.text
        # HTTP JSON represents tuple-valued standard references as arrays.
        assert response.json() == json.loads(json.dumps(expected))
        assert expected["status"] == "preliminary_independent_review_required"


def test_malformed_saved_geometry_returns_client_error():
    saved = asdict(classified())
    saved["geometry"] = None
    response = TestClient(create_app()).post(
        "/api/as4055/roof-anchoring",
        json={
            "classification": saved,
            "roof_type": "sheet",
            "roof_surface_area_m2": 200.0,
            "limit_state": "ultimate",
            "all_cladding_resists_design_wind": True,
        },
    )
    assert response.status_code == 400


def housing_inputs():
    cls = classified()
    return {
        "geometry": asdict(cls.geometry),
        "site_conditions": asdict(cls.site_conditions),
        "roof_form": "gable",
        "roof_type": "sheet",
        "storeys": 1,
        "all_cladding_resists_design_wind": True,
        "site_review_reference": "Reviewed site survey",
        "racking_elevations": [
            {
                "wind_on": direction,
                "storey": "single_or_upper",
                "elevation_area_m2": area,
                "storey_height_m": 2.4,
                "floor_depth_m": 0.3,
                "area_review_reference": f"Reviewed {direction} elevation",
            }
            for direction, area in (("side", 42.0), ("end", 25.0))
        ],
    }


def test_combined_housing_assessment_preserves_distinct_load_paths():
    result = run_calculation("au.wind.as4055.housing_assessment", housing_inputs())
    assert result["site_wind_classification"] == "N1"
    assert result["serviceability_anchoring_force_kn"] == pytest.approx(
        0.04 * 200 / math.cos(math.radians(20))
    )
    assert result["ultimate_anchoring_force_kn"] == pytest.approx(
        0.33 * 200 / math.cos(math.radians(20))
    )
    assert [r["source_table"] for r in result["racking"]] == ["Table 5.2(B)", "Table 5.2(A)"]
    assert [r["racking_force_kn"] for r in result["racking"]] == pytest.approx(
        [0.49 * 42, 0.66 * 25]
    )
    assert set(result["loads"]) == {"serviceability", "ultimate"}
    assert result["status"] == "preliminary_independent_review_required"


@pytest.mark.parametrize("mistake", ["duplicate", "missing_storey", "wrong_height", "envelope"])
def test_combined_housing_assessment_rejects_incomplete_or_inconsistent_inputs(mistake):
    inputs = housing_inputs()
    if mistake == "duplicate":
        inputs["racking_elevations"][1]["wind_on"] = "side"
    elif mistake == "missing_storey":
        inputs["storeys"] = 2
    elif mistake == "wrong_height":
        inputs["geometry"]["eaves_height_m"] += 0.2
        inputs["geometry"]["roof_height_m"] += 0.2
    else:
        inputs["all_cladding_resists_design_wind"] = False
    with pytest.raises(ValueError):
        run_calculation("au.wind.as4055.housing_assessment", inputs)
    response = TestClient(create_app()).post("/api/as4055/housing-assessment", json=inputs)
    assert response.status_code == 400
