"""Tests for the OpenWind-AU Model Context Protocol server."""

from __future__ import annotations

import argparse
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from openwind_au import __version__
from openwind_au.mcp_server import (
    _allowed_host,
    _transport_security_settings,
    calculate_all_wind_variables,
    calculate_climate_change_multiplier,
    calculate_regional_wind_speed,
    calculate_shielding_multiplier,
    calculate_site_wind_speed,
    calculate_terrain_height_multiplier,
    calculate_topographic_wind_multiplier,
    get_direction_multipliers,
    main,
    mcp,
)
from openwind_au.models import WindRegionAssessment
from openwind_au.standard_lookup_tables import VR_DATA_FILE, load_packaged_lookup_data
from openwind_au.wind_inputs import regional_wind_speed_assessment


def test_mcp_registers_traceable_wind_calculation_tools() -> None:
    tools = asyncio.run(mcp.list_tools())

    assert {tool.name for tool in tools} == {
        "calculate_regional_wind_speed",
        "calculate_climate_change_multiplier",
        "get_direction_multipliers",
        "calculate_terrain_height_multiplier",
        "calculate_shielding_multiplier",
        "calculate_topographic_wind_multiplier",
        "calculate_site_wind_speed",
        "calculate_all_wind_variables",
    }


def test_mcp_initialize_reports_application_version() -> None:
    initialization = mcp._mcp_server.create_initialization_options()

    assert initialization.server_name == "OpenWind-AU"
    assert initialization.server_version == __version__ == "0.8.0"


def test_mcp_tool_schemas_publish_supported_values_and_result_envelope() -> None:
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    regional_schema = tools["calculate_regional_wind_speed"].inputSchema
    climate_schema = tools["calculate_climate_change_multiplier"].inputSchema
    combined_schema = tools["calculate_all_wind_variables"].inputSchema
    direction_schema = tools["get_direction_multipliers"].inputSchema
    terrain_schema = tools["calculate_terrain_height_multiplier"].inputSchema
    topographic_schema = tools["calculate_topographic_wind_multiplier"].inputSchema
    site_speed_schema = tools["calculate_site_wind_speed"].inputSchema
    output_schema = tools["calculate_regional_wind_speed"].outputSchema

    assert regional_schema["properties"]["wind_region"]["enum"] == [
        "A",
        "A0",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "B",
        "B1",
        "B2",
        "C",
        "D",
    ]
    assert regional_schema["properties"]["ari_years"]["minimum"] == 1
    assert climate_schema["properties"]["wind_region"]["enum"] == [
        "A",
        "A0",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "B1",
        "B2",
        "C",
        "D",
    ]
    specific_regions = ["A0", "A1", "A2", "A3", "A4", "A5", "B1", "B2", "C", "D"]
    exposure_regions = [
        "A0",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "B",
        "B1",
        "B2",
        "C",
        "D",
    ]
    assert direction_schema["properties"]["wind_region"]["enum"] == specific_regions
    assert combined_schema["properties"]["wind_region"]["enum"] == specific_regions
    assert terrain_schema["properties"]["wind_region"]["enum"] == exposure_regions
    assert topographic_schema["properties"]["wind_region"]["enum"] == exposure_regions
    assert combined_schema["properties"]["direction"]["enum"] == [
        "N",
        "NE",
        "E",
        "SE",
        "S",
        "SW",
        "W",
        "NW",
    ]
    assert combined_schema["properties"]["terrain_category"]["enum"] == [
        "TC1",
        "TC1.5",
        "TC2",
        "TC2.5",
        "TC3",
        "TC4",
    ]
    assert combined_schema["properties"]["wind_direction_multiplier_case"]["enum"] == [
        "main_structure",
        "cladding_or_immediate_support",
        "circular_or_polygonal_chimney_tank_or_pole",
    ]
    assert "average_roof_height_m" in combined_schema["required"]
    assert "height_m" not in combined_schema["properties"]
    assert "mc" in site_speed_schema["required"]
    assert output_schema is not None
    assert set(output_schema["required"]) == {
        "standard",
        "clause",
        "inputs",
        "outputs",
        "warnings",
        "engineering_review_required",
    }


@pytest.mark.parametrize(
    ("tool_name", "arguments", "field_name"),
    [
        (
            "calculate_regional_wind_speed",
            {"wind_region": "A2", "ari_years": True},
            "ari_years",
        ),
        (
            "calculate_regional_wind_speed",
            {"wind_region": "A2", "ari_years": "500"},
            "ari_years",
        ),
        (
            "calculate_site_wind_speed",
            {"vr_mps": 45, "mc": 1, "md": True, "mzcat": 1, "ms": 1, "mt": 1},
            "md",
        ),
        (
            "calculate_topographic_wind_multiplier",
            {
                "feature_type": "hill",
                "h_m": 10,
                "lu_m": 100,
                "x_m": 10,
                "z_m": 10,
                "average_roof_height_m": 10,
                "wind_region": "A2",
                "site_elevation_m": 100,
                "site_is_downwind": "false",
            },
            "site_is_downwind",
        ),
    ],
)
def test_mcp_call_boundary_rejects_coercible_engineering_inputs(
    tool_name: str,
    arguments: dict,
    field_name: str,
) -> None:
    with pytest.raises(ToolError, match=field_name):
        asyncio.run(mcp.call_tool(tool_name, arguments))


def test_mcp_individual_tools_return_structured_traceability() -> None:
    vr = calculate_regional_wind_speed("A2", 500)
    mc = calculate_climate_change_multiplier("A2")
    md = get_direction_multipliers("A2")
    mzcat = calculate_terrain_height_multiplier("TC3", 10.0, "A2")
    ms = calculate_shielding_multiplier(4.5, 10.0)
    vsitb = calculate_site_wind_speed(45.0, 1.0, 0.85, 0.83, 0.85, 1.0)

    assert vr["outputs"]["vr_mps"] == 45.0
    assert "regional equation" in vr["outputs"]["source_reference"]
    assert mc["outputs"]["mc"] == 1.0
    assert md["outputs"]["md"]["N"] == 0.85
    assert mzcat["outputs"]["mzcat"] == 0.83
    assert ms["outputs"]["ms"] == 0.85
    assert vsitb["outputs"]["vsitb_mps"] == pytest.approx(26.985375)
    assert all(result["engineering_review_required"] for result in (vr, mc, md, mzcat, ms, vsitb))


def test_mcp_regional_speed_matches_api_configured_table(monkeypatch, tmp_path) -> None:
    table = load_packaged_lookup_data(VR_DATA_FILE)
    table["tables"]["A"]["ultimate"]["500"] = 52.0
    table_path = tmp_path / "regional-wind-speeds.json"
    table_path.write_text(json.dumps(table), encoding="utf-8")
    monkeypatch.setenv("OPENWIND_VR_TABLE_PATH", str(table_path))
    region = WindRegionAssessment(
        latitude=-33.8688,
        longitude=151.2093,
        wind_region="A2",
        source="deterministic MCP parity fixture",
        confidence="high",
    )

    api_result = regional_wind_speed_assessment(
        region,
        importance_level="IL2",
        annual_exceedance_probability="1/500",
    )
    mcp_result = calculate_regional_wind_speed("A2", 500)
    combined_result = calculate_all_wind_variables(
        wind_region="A2",
        ari_years=500,
        direction="N",
        wind_direction_multiplier_case="main_structure",
        terrain_category="TC3",
        average_roof_height_m=10.0,
        shielding_parameter=4.5,
        building_height_m=10.0,
        feature_type="no significant feature",
        h_m=0.0,
        lu_m=0.0,
        x_m=0.0,
        site_elevation_m=100.0,
    )

    assert api_result.vr_ult == 52.0
    assert mcp_result["outputs"]["vr_mps"] == api_result.vr_ult
    assert mcp_result["outputs"]["source_reference"] == api_result.selected_table
    assert combined_result["outputs"]["vr_mps"] == api_result.vr_ult
    assert combined_result["outputs"]["vr_source_reference"] == api_result.selected_table
    assert any("exact 500-year ARI row" in warning for warning in mcp_result["warnings"])
    assert combined_result["outputs"]["vsitb_mps"] == pytest.approx(31.1831)


def test_mcp_identical_configured_table_attributes_equation_fallback(monkeypatch, tmp_path) -> None:
    table = load_packaged_lookup_data(VR_DATA_FILE)
    table_path = tmp_path / "regional-wind-speeds.json"
    table_path.write_text(json.dumps(table), encoding="utf-8")
    monkeypatch.setenv("OPENWIND_VR_TABLE_PATH", str(table_path))

    result = calculate_regional_wind_speed("A2", 30)

    assert result["outputs"]["vr_mps"] == 38.0
    assert result["outputs"]["source_reference"] == (
        "AS/NZS 1170.2:2021 incorporating Amendments 1 and 2 Table 3.1(A) regional equation"
    )
    assert any("regional equation" in warning for warning in result["warnings"])


def test_mcp_configured_vr_table_missing_value_fails_closed(monkeypatch, tmp_path) -> None:
    table = load_packaged_lookup_data(VR_DATA_FILE)
    table["tables"]["A"]["ultimate"] = {"25": 37.0}
    table_path = tmp_path / "regional-wind-speeds.json"
    table_path.write_text(json.dumps(table), encoding="utf-8")
    monkeypatch.setenv("OPENWIND_VR_TABLE_PATH", str(table_path))

    with pytest.raises(ValueError, match="manual input is required"):
        calculate_regional_wind_speed("A2", 500)


def test_mcp_all_variables_matches_component_product() -> None:
    result = calculate_all_wind_variables(
        wind_region="A2",
        ari_years=500,
        direction="N",
        wind_direction_multiplier_case="main_structure",
        terrain_category="TC3",
        average_roof_height_m=10.0,
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
        "vr_source_reference": (
            "AS/NZS 1170.2:2021 incorporating Amendments 1 and 2 Table 3.1(A) regional equation"
        ),
        "mc": 1.0,
        "md": 0.85,
        "md_source_reference": ("AS/NZS 1170.2:2021 incorporating Amendments 1 and 2 Table 3.2(A)"),
        "mzcat": 0.83,
        "ms": 0.85,
        "mt": 1.0,
        "vsitb_mps": pytest.approx(26.985375),
    }


def test_mcp_all_variables_uses_full_precision_mt_before_rounding_vsitb() -> None:
    result = calculate_all_wind_variables(
        wind_region="A2",
        ari_years=500,
        direction="N",
        wind_direction_multiplier_case="main_structure",
        terrain_category="TC3",
        average_roof_height_m=10.0,
        shielding_parameter=4.5,
        building_height_m=10.0,
        feature_type="ridge",
        h_m=30.0,
        lu_m=75.0,
        x_m=20.0,
        site_elevation_m=0.0,
    )

    assert result["outputs"]["mt"] == pytest.approx(1.18876)
    assert result["outputs"]["vsitb_mps"] == pytest.approx(32.079139)


def test_mcp_b2_climate_change_multiplier_uplifts_site_wind_speed() -> None:
    mc = calculate_climate_change_multiplier("B2")
    result = calculate_all_wind_variables(
        wind_region="B2",
        ari_years=500,
        direction="N",
        wind_direction_multiplier_case="main_structure",
        terrain_category="TC3",
        average_roof_height_m=10.0,
        shielding_parameter=4.5,
        building_height_m=10.0,
        feature_type="no significant feature",
        h_m=0.0,
        lu_m=0.0,
        x_m=0.0,
        site_elevation_m=100.0,
    )

    assert mc["outputs"]["mc"] == 1.05
    assert result["outputs"]["mc"] == 1.05
    assert result["outputs"]["vsitb_mps"] == pytest.approx(
        result["outputs"]["vr_mps"]
        * 1.05
        * result["outputs"]["md"]
        * result["outputs"]["mzcat"]
        * result["outputs"]["ms"]
        * result["outputs"]["mt"]
    )


def test_mcp_clause_3_3_cladding_case_forces_md_one_in_b2() -> None:
    result = calculate_all_wind_variables(
        wind_region="B2",
        ari_years=500,
        direction="N",
        wind_direction_multiplier_case="cladding_or_immediate_support",
        terrain_category="TC3",
        average_roof_height_m=10.0,
        shielding_parameter=4.5,
        building_height_m=10.0,
        feature_type="no significant feature",
        h_m=0.0,
        lu_m=0.0,
        x_m=0.0,
        site_elevation_m=100.0,
    )

    assert result["outputs"]["mc"] == 1.05
    assert result["outputs"]["md"] == 1.0
    assert "Clause 3.3" in result["outputs"]["md_source_reference"]
    assert any("Md = 1.0" in warning for warning in result["warnings"])


@pytest.mark.parametrize("wind_region", ["A2", "B1", "C", "D"])
def test_mcp_clause_3_3_circular_case_forces_md_one_in_every_region(wind_region: str) -> None:
    result = calculate_all_wind_variables(
        wind_region=wind_region,
        ari_years=500,
        direction="N",
        wind_direction_multiplier_case="circular_or_polygonal_chimney_tank_or_pole",
        terrain_category="TC3",
        average_roof_height_m=10.0,
        shielding_parameter=4.5,
        building_height_m=10.0,
        feature_type="no significant feature",
        h_m=0.0,
        lu_m=0.0,
        x_m=0.0,
        site_elevation_m=100.0,
    )

    assert result["outputs"]["md"] == 1.0
    assert "Clause 3.3" in result["outputs"]["md_source_reference"]


@pytest.mark.parametrize("wind_region", ["A2", "B1"])
def test_mcp_cladding_case_retains_table_3_2_outside_b2_c_d(wind_region: str) -> None:
    result = calculate_all_wind_variables(
        wind_region=wind_region,
        ari_years=500,
        direction="N",
        wind_direction_multiplier_case="cladding_or_immediate_support",
        terrain_category="TC3",
        average_roof_height_m=10.0,
        shielding_parameter=4.5,
        building_height_m=10.0,
        feature_type="no significant feature",
        h_m=0.0,
        lu_m=0.0,
        x_m=0.0,
        site_elevation_m=100.0,
    )

    expected = get_direction_multipliers(wind_region)["outputs"]["md"]["N"]
    assert result["outputs"]["md"] == expected
    assert "Table 3.2(A)" in result["outputs"]["md_source_reference"]


def test_mcp_rejects_ambiguous_generic_b_climate_mapping() -> None:
    with pytest.raises(ValueError, match="B1 or B2"):
        calculate_climate_change_multiplier("B")
    with pytest.raises(ValueError, match="B1 or B2"):
        calculate_all_wind_variables(
            wind_region="B",
            ari_years=500,
            direction="N",
            wind_direction_multiplier_case="main_structure",
            terrain_category="TC3",
            average_roof_height_m=10.0,
            shielding_parameter=4.5,
            building_height_m=10.0,
            feature_type="no significant feature",
            h_m=0.0,
            lu_m=0.0,
            x_m=0.0,
            site_elevation_m=100.0,
        )


def test_mcp_rejects_generic_region_a_for_exposure_calculations() -> None:
    calls = [
        lambda: get_direction_multipliers("A"),
        lambda: calculate_terrain_height_multiplier("TC3", 10.0, "A"),
        lambda: calculate_topographic_wind_multiplier(
            "no significant feature", 0, 0, 0, 10, 10, "A", 100
        ),
        lambda: calculate_all_wind_variables(
            wind_region="A",
            ari_years=500,
            direction="N",
            wind_direction_multiplier_case="circular_or_polygonal_chimney_tank_or_pole",
            terrain_category="TC3",
            average_roof_height_m=10.0,
            shielding_parameter=4.5,
            building_height_m=10.0,
            feature_type="no significant feature",
            h_m=0.0,
            lu_m=0.0,
            x_m=0.0,
            site_elevation_m=100.0,
        ),
    ]

    for call in calls:
        with pytest.raises(ValueError, match="A0, A1, A2, A3, A4, or A5"):
            call()


def test_mcp_combined_uses_average_roof_height_for_shielding_rule() -> None:
    result = calculate_all_wind_variables(
        wind_region="A2",
        ari_years=500,
        direction="N",
        wind_direction_multiplier_case="main_structure",
        terrain_category="TC3",
        average_roof_height_m=20.0,
        shielding_parameter=1.0,
        building_height_m=30.0,
        feature_type="no significant feature",
        h_m=0.0,
        lu_m=0.0,
        x_m=0.0,
        site_elevation_m=100.0,
    )

    assert result["outputs"]["ms"] == pytest.approx(0.7)


def test_mcp_shielding_for_structure_over_25_m_is_one() -> None:
    result = calculate_shielding_multiplier(1.0, 25.1)

    assert result["outputs"]["ms"] == 1.0
    assert any("h > 25 m" in warning for warning in result["warnings"])


@pytest.mark.parametrize(
    ("call", "error"),
    [
        (lambda: calculate_site_wind_speed(float("nan"), 1, 1, 1, 1, 1), "finite"),
        (lambda: calculate_site_wind_speed(45, float("inf"), 1, 1, 1, 1), "finite"),
        (lambda: calculate_terrain_height_multiplier("TC3", float("nan"), "A2"), "finite"),
        (lambda: calculate_shielding_multiplier(float("nan"), 10), "finite"),
        (
            lambda: calculate_topographic_wind_multiplier(
                "hill",
                20,
                50,
                0,
                float("inf"),
                10,
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


@pytest.mark.parametrize(
    "call",
    [
        lambda: calculate_regional_wind_speed("Aardvark", 500),
        lambda: calculate_regional_wind_speed("BLAH", 500),
        lambda: get_direction_multipliers("Aardvark"),
        lambda: get_direction_multipliers("BLAH"),
        lambda: calculate_terrain_height_multiplier("TC3", 10.0, "ZZ"),
        lambda: calculate_topographic_wind_multiplier(
            "hill",
            20,
            50,
            0,
            10,
            10,
            "ZZ",
            100,
        ),
    ],
)
def test_mcp_multiplier_tools_reject_unknown_wind_region(call) -> None:
    with pytest.raises(ValueError, match="Unsupported Australian wind region"):
        call()


def test_mcp_topographic_tool_rejects_unknown_feature_type() -> None:
    with pytest.raises(ValueError, match="Unsupported topographic feature type"):
        calculate_topographic_wind_multiplier("unknown", 20, 50, 0, 10, 10, "A2", 100)


def test_mcp_topographic_tool_rejects_reference_height_above_standard_scope() -> None:
    with pytest.raises(ValueError, match="at most 200 m"):
        calculate_topographic_wind_multiplier(
            "no significant feature",
            0,
            0,
            0,
            200.1,
            10,
            "A2",
            100,
        )


def test_mcp_topographic_tools_block_unresolved_qualifying_geometry() -> None:
    with pytest.raises(ValueError, match="Lu is required"):
        calculate_topographic_wind_multiplier("hill", 20, 0, 0, 10, 10, "A2", 100)

    with pytest.raises(ValueError, match="Lu is required"):
        calculate_all_wind_variables(
            wind_region="A2",
            ari_years=500,
            direction="N",
            wind_direction_multiplier_case="main_structure",
            terrain_category="TC3",
            average_roof_height_m=10.0,
            shielding_parameter=4.5,
            building_height_m=10.0,
            feature_type="hill",
            h_m=20.0,
            lu_m=0.0,
            x_m=0.0,
            site_elevation_m=100.0,
        )


def test_mcp_combined_tool_rejects_average_roof_height_above_building_height() -> None:
    with pytest.raises(ValueError, match="Average roof height.*building height"):
        calculate_all_wind_variables(
            wind_region="A2",
            ari_years=500,
            direction="N",
            wind_direction_multiplier_case="main_structure",
            terrain_category="TC3",
            average_roof_height_m=11.0,
            shielding_parameter=4.5,
            building_height_m=10.0,
            feature_type="no significant feature",
            h_m=0.0,
            lu_m=0.0,
            x_m=0.0,
            site_elevation_m=100.0,
        )


def test_mcp_shielding_uses_table_at_exact_25_m_limit() -> None:
    result = calculate_shielding_multiplier(1.0, 25.0)

    assert result["outputs"]["ms"] == pytest.approx(0.7)


def test_mcp_cli_uses_validated_environment_defaults(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("OPENWIND_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("OPENWIND_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("OPENWIND_MCP_PORT", "9001")
    monkeypatch.setenv("OPENWIND_MCP_ALLOWED_HOSTS", "wind.example,192.168.1.50")
    monkeypatch.setattr(mcp, "run", lambda *, transport: calls.append(transport))
    monkeypatch.setattr(mcp.settings, "host", mcp.settings.host)
    monkeypatch.setattr(mcp.settings, "port", mcp.settings.port)
    monkeypatch.setattr(mcp.settings, "transport_security", mcp.settings.transport_security)

    assert main([]) == 0

    assert calls == ["streamable-http"]
    assert mcp.settings.host == "0.0.0.0"
    assert mcp.settings.port == 9001
    assert "wind.example:*" in mcp.settings.transport_security.allowed_hosts
    assert "192.168.1.50:*" in mcp.settings.transport_security.allowed_hosts


@pytest.mark.parametrize(
    ("name", "value", "error"),
    [
        ("OPENWIND_MCP_TRANSPORT", "sse", "transport must be one of"),
        ("OPENWIND_MCP_HOST", " ", "host must not be empty"),
        ("OPENWIND_MCP_PORT", "not-a-port", "port must be an integer"),
        ("OPENWIND_MCP_PORT", "0", "port must be between 1 and 65535"),
        ("OPENWIND_MCP_PORT", "65536", "port must be between 1 and 65535"),
        ("OPENWIND_MCP_ALLOWED_HOSTS", "bad/path", "allowed host must be"),
        ("OPENWIND_MCP_ALLOWED_ORIGINS", "wind.example", "allowed origin must be"),
        ("OPENWIND_MCP_ALLOWED_ORIGINS", "http://[bad", "invalid host"),
    ],
)
def test_mcp_cli_rejects_invalid_environment_defaults(
    monkeypatch,
    capsys,
    name: str,
    value: str,
    error: str,
) -> None:
    for variable in (
        "OPENWIND_MCP_TRANSPORT",
        "OPENWIND_MCP_HOST",
        "OPENWIND_MCP_PORT",
        "OPENWIND_MCP_ALLOWED_HOSTS",
        "OPENWIND_MCP_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit) as exc_info:
        main([])

    assert exc_info.value.code == 2
    diagnostic = capsys.readouterr().err
    assert name in diagnostic
    assert error in diagnostic


def test_mcp_cli_arguments_override_invalid_environment(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("OPENWIND_MCP_TRANSPORT", "invalid")
    monkeypatch.setenv("OPENWIND_MCP_HOST", " ")
    monkeypatch.setenv("OPENWIND_MCP_PORT", "invalid")
    monkeypatch.setattr(mcp, "run", lambda *, transport: calls.append(transport))
    monkeypatch.setattr(mcp.settings, "host", mcp.settings.host)
    monkeypatch.setattr(mcp.settings, "port", mcp.settings.port)
    monkeypatch.setattr(mcp.settings, "transport_security", mcp.settings.transport_security)

    assert main(["--transport", "streamable-http", "--host", "127.0.0.1", "--port", "8001"]) == 0

    assert calls == ["streamable-http"]
    assert mcp.settings.host == "127.0.0.1"
    assert mcp.settings.port == 8001


@pytest.mark.parametrize("bind_host", ["0.0.0.0", "::", "0::", "0:0:0:0:0:0:0:0"])
def test_mcp_http_wildcard_bind_requires_an_explicit_host_allowlist(
    monkeypatch,
    capsys,
    bind_host: str,
) -> None:
    for variable in (
        "OPENWIND_MCP_ALLOWED_HOSTS",
        "OPENWIND_MCP_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(mcp, "run", lambda *, transport: None)

    with pytest.raises(SystemExit) as exc_info:
        main(["--transport", "streamable-http", "--host", bind_host])

    assert exc_info.value.code == 2
    assert "--allowed-host" in capsys.readouterr().err


def test_mcp_http_normalizes_bare_ipv6_allowed_host() -> None:
    assert _allowed_host("2001:db8::1") == "[2001:db8::1]"


def test_mcp_http_non_loopback_host_passes_protected_initialize_request() -> None:
    settings = _transport_security_settings(
        argparse.ArgumentParser(),
        bind_host="0.0.0.0",
        allowed_hosts=["192.168.1.50"],
        allowed_origins=[],
    )
    server = FastMCP(
        "OpenWind-AU security test",
        stateless_http=True,
        json_response=True,
        transport_security=settings,
    )
    request_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    headers = {
        "host": "192.168.1.50:8001",
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }

    with TestClient(server.streamable_http_app(), raise_server_exceptions=False) as test_client:
        accepted = test_client.post("/mcp", headers=headers, json=request_body)
        rejected = test_client.post(
            "/mcp",
            headers={**headers, "host": "untrusted.example:8001"},
            json=request_body,
        )

    assert accepted.status_code == 200
    assert rejected.status_code == 421
