"""Tests for the OpenWind-AU Model Context Protocol server."""

from __future__ import annotations

import asyncio

import pytest

from openwind_au.mcp_server import (
    calculate_all_wind_variables,
    calculate_regional_wind_speed,
    calculate_shielding_multiplier,
    calculate_site_wind_speed,
    calculate_terrain_height_multiplier,
    calculate_topographic_wind_multiplier,
    get_direction_multipliers,
    mcp,
)


def test_mcp_registers_traceable_wind_calculation_tools() -> None:
    tools = asyncio.run(mcp.list_tools())

    assert {tool.name for tool in tools} == {
        "calculate_regional_wind_speed",
        "get_direction_multipliers",
        "calculate_terrain_height_multiplier",
        "calculate_shielding_multiplier",
        "calculate_topographic_wind_multiplier",
        "calculate_site_wind_speed",
        "calculate_all_wind_variables",
    }


def test_mcp_individual_tools_return_structured_traceability() -> None:
    vr = calculate_regional_wind_speed("A2", 500)
    md = get_direction_multipliers("A2")
    mzcat = calculate_terrain_height_multiplier("TC3", 10.0, "A2")
    ms = calculate_shielding_multiplier(4.5, 10.0)
    vsitb = calculate_site_wind_speed(45.0, 0.85, 0.83, 0.85, 1.0)

    assert vr["outputs"]["vr_mps"] == 45.0
    assert md["outputs"]["md"]["N"] == 0.85
    assert mzcat["outputs"]["mzcat"] == 0.83
    assert ms["outputs"]["ms"] == 0.85
    assert vsitb["outputs"]["vsitb_mps"] == pytest.approx(26.985375)
    assert all(result["engineering_review_required"] for result in (vr, md, mzcat, ms, vsitb))


def test_mcp_all_variables_matches_component_product() -> None:
    result = calculate_all_wind_variables(
        wind_region="A2",
        ari_years=500,
        direction="N",
        terrain_category="TC3",
        height_m=10.0,
        shielding_parameter=4.5,
        building_height_m=10.0,
        feature_type="no significant feature",
        h_m=0.0,
        lu_m=0.0,
        x_m=0.0,
        site_elevation_m=100.0,
    )

    assert result["outputs"] == {
        "vr_mps": 45.0,
        "md": 0.85,
        "mzcat": 0.83,
        "ms": 0.85,
        "mt": 1.0,
        "vsitb_mps": pytest.approx(26.985375),
    }


def test_mcp_shielding_for_structure_over_25_m_is_one() -> None:
    result = calculate_shielding_multiplier(1.0, 25.1)

    assert result["outputs"]["ms"] == 1.0
    assert any("h > 25 m" in warning for warning in result["warnings"])


@pytest.mark.parametrize(
    ("call", "error"),
    [
        (lambda: calculate_site_wind_speed(float("nan"), 1, 1, 1, 1), "finite"),
        (lambda: calculate_site_wind_speed(45, float("inf"), 1, 1, 1), "finite"),
        (lambda: calculate_terrain_height_multiplier("TC3", float("nan"), "A2"), "finite"),
        (lambda: calculate_shielding_multiplier(float("nan"), 10), "finite"),
        (
            lambda: calculate_topographic_wind_multiplier(
                "hill",
                20,
                50,
                0,
                float("inf"),
                "A2",
                100,
            ),
            "finite",
        ),
    ],
)
def test_mcp_tools_reject_nonfinite_inputs(call, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        call()
