"""Pressure equation, sign mapping and frame-load conservation regressions."""

from copy import deepcopy

import pytest

from openwind_au.calculations import get_calculation, run_calculation


def test_linkable_speed_schema_declares_units():
    schema = get_calculation("au.wind.frame_loads").input_schema
    fields = schema["properties"]["pressure_cases"]["items"]["properties"]
    assert fields["vdes_external_mps"]["unit"] == "m/s"
    assert fields["vdes_internal_mps"]["unit"] == "m/s"


def payload():
    return {
        "pressure_cases": [
            {
                "case_id": "WU-N",
                "source_run_id": "saved-wind-run-1",
                "limit_state": "ultimate",
                "wind_direction": "N",
                "vdes_external_mps": 40.0,
                "vdes_internal_mps": 30.0,
                "dynamic_wind_sensitive": False,
            }
        ],
        "panels": [
            {
                "panel_id": "wall",
                "case_id": "WU-N",
                "area_m2": 12.0,
                "cshp_external": 0.8,
                "cshp_internal": 0.2,
                "external_coefficient_reference": "Reviewed external Cshp",
                "internal_coefficient_reference": "Reviewed internal Cshp",
                "area_review_reference": "Wall elevation A",
                "coefficient_reviewer": "QA",
                "coefficient_review_date": "2026-09-28",
                "coefficient_review_note": "Analytical fixture",
            }
        ],
        "tributary_members": [
            {
                "panel_id": "wall",
                "member_id": "M1",
                "member_length_m": 6.0,
                "x_start_m": 0.0,
                "x_end_m": 6.0,
                "tributary_width_m": 2.0,
                "direction": "Fy",
                "axis_reference": "Local y normal to wall",
                "positive_direction_toward_inside": True,
            }
        ],
    }


def run(values):
    return run_calculation("au.wind.frame_loads", values)


def test_separate_speed_bases_and_contract_force_conservation():
    result = run(payload())
    pressure = result["panel_pressures"][0]
    assert pressure["q_external_kpa"] == pytest.approx(0.96)
    assert pressure["q_internal_kpa"] == pytest.approx(0.54)
    assert pressure["net_pressure_toward_inside_kpa"] == pytest.approx(0.660)
    load = result["member_distributed_loads"][0]
    assert load == {
        "member_id": "M1",
        "load_case": "WU-N",
        "direction": "Fy",
        "start_kn_m": pytest.approx(1.32),
        "end_kn_m": pytest.approx(1.32),
        "start_m": 0,
        "end_m": 6,
    }
    assert load["start_kn_m"] * 6 == pytest.approx(0.660 * 12)
    assert result["member_loads"][0]["source_run_id"] == "saved-wind-run-1"


def test_suction_and_axis_sign_are_independent():
    values = payload()
    values["panels"][0]["cshp_external"] = -0.9
    values["tributary_members"][0]["positive_direction_toward_inside"] = False
    result = run(values)
    assert result["member_distributed_loads"][0]["start_kn_m"] == pytest.approx(1.944)


def test_serviceability_speed_is_not_clamped_to_uls():
    values = payload()
    values["pressure_cases"][0].update(
        limit_state="serviceability", vdes_external_mps=20.0, vdes_internal_mps=20.0
    )
    assert run(values)["panel_pressures"][0]["q_external_kpa"] == pytest.approx(0.24)


@pytest.mark.parametrize(
    "scope,value",
    [
        ("vdes_external_mps", 29.9),
        ("dynamic_wind_sensitive", True),
        ("vdes_internal_mps", float("nan")),
    ],
)
def test_invalid_pressure_scope_fails(scope, value):
    values = payload()
    values["pressure_cases"][0][scope] = value
    with pytest.raises(ValueError):
        run(values)


def test_missing_area_overlap_unknown_case_and_excess_length_fail():
    for update in ("area", "overlap", "unknown", "length"):
        values = payload()
        if update == "area":
            values["panels"][0]["area_m2"] = 13
        elif update == "overlap":
            values["panels"][0]["area_m2"] = 24
            values["tributary_members"].append(deepcopy(values["tributary_members"][0]))
        elif update == "unknown":
            values["panels"][0]["case_id"] = "missing"
        else:
            values["tributary_members"][0]["x_end_m"] = 7
        with pytest.raises(ValueError):
            run(values)
