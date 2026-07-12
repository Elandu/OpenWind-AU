"""Model Context Protocol tools for traceable AS/NZS 1170.2 calculations."""

from __future__ import annotations

import argparse
import math
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from openwind_au.mzcat import indicative_mzcat
from openwind_au.standard_calculations import (
    DIRECTIONS,
    direction_multiplier_values,
    ms_from_shielding_parameter,
    regional_wind_speed,
)
from openwind_au.topographic_multiplier import (
    calculate_topographic_multiplier as calculate_mt,
)

STANDARD = "AS/NZS 1170.2:2021 incorporating Amendments 1 and 2"

mcp = FastMCP(
    "OpenWind-AU",
    instructions=(
        "Traceable Australian site-wind calculations through Vsit,b. Inputs that depend on "
        "site classification or survey evidence must be reviewed by a competent engineer."
    ),
    stateless_http=True,
    json_response=True,
)


def _result(
    *,
    clause: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "standard": STANDARD,
        "clause": clause,
        "inputs": inputs,
        "outputs": outputs,
        "warnings": warnings or [],
        "engineering_review_required": True,
    }


def _finite_value(
    name: str,
    value: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    minimum_inclusive: bool = True,
) -> float:
    """Validate a bounded finite numeric MCP input."""

    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite.")
    if minimum is not None:
        invalid_minimum = number < minimum if minimum_inclusive else number <= minimum
        if invalid_minimum:
            operator = "at least" if minimum_inclusive else "greater than"
            raise ValueError(f"{name} must be {operator} {minimum}.")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must not exceed {maximum}.")
    return number


@mcp.tool()
def calculate_regional_wind_speed(wind_region: str, ari_years: int) -> dict[str, Any]:
    """Calculate Australian regional wind speed VR for a reviewed region and ARI."""

    vr = regional_wind_speed(wind_region, ari_years)
    return _result(
        clause="Table 3.1(A)",
        inputs={"wind_region": wind_region, "ari_years": ari_years},
        outputs={"vr_mps": vr},
        warnings=["Confirm the wind-region boundary and applicable NCC jurisdictional variations."],
    )


@mcp.tool()
def get_direction_multipliers(wind_region: str) -> dict[str, Any]:
    """Return the eight Australian wind direction multipliers Md for a reviewed region."""

    multipliers = direction_multiplier_values(wind_region)
    return _result(
        clause="Table 3.2(A)",
        inputs={"wind_region": wind_region},
        outputs={"md": multipliers, "any_direction_md": 1.0},
    )


@mcp.tool()
def calculate_terrain_height_multiplier(
    terrain_category: str,
    height_m: float,
    wind_region: str,
) -> dict[str, Any]:
    """Calculate Mz,cat from a reviewed terrain category, height, and wind region."""

    height_m = _finite_value("Height", height_m, minimum=0, maximum=500, minimum_inclusive=False)
    mzcat = indicative_mzcat(terrain_category, height_m, wind_region=wind_region)
    return _result(
        clause="Clauses 4.2.2 and 4.2.3; Table 4.1",
        inputs={
            "terrain_category": terrain_category,
            "height_m": height_m,
            "wind_region": wind_region,
        },
        outputs={"mzcat": round(mzcat, 6)},
        warnings=[
            "The terrain category and any mixed-fetch weighted averaging must be "
            "reviewed separately."
        ],
    )


@mcp.tool()
def calculate_shielding_multiplier(
    shielding_parameter: float,
    building_height_m: float,
) -> dict[str, Any]:
    """Calculate Ms from a reviewed shielding parameter and building height."""

    shielding_parameter = _finite_value(
        "Shielding parameter s",
        shielding_parameter,
        minimum=0,
        maximum=1_000_000,
    )
    building_height_m = _finite_value(
        "Building height",
        building_height_m,
        minimum=0,
        maximum=500,
        minimum_inclusive=False,
    )
    warnings: list[str] = []
    if building_height_m > 25.0:
        ms = 1.0
        warnings.append("Clause 4.3.1 requires Ms = 1.0 when h > 25 m.")
    else:
        ms = ms_from_shielding_parameter(shielding_parameter)
    return _result(
        clause="Clause 4.3; Table 4.2",
        inputs={
            "shielding_parameter": shielding_parameter,
            "building_height_m": building_height_m,
        },
        outputs={"ms": round(ms, 6)},
        warnings=warnings,
    )


@mcp.tool()
def calculate_topographic_wind_multiplier(
    feature_type: str,
    h_m: float,
    lu_m: float,
    x_m: float,
    z_m: float,
    wind_region: str,
    site_elevation_m: float,
    site_is_downwind: bool = True,
) -> dict[str, Any]:
    """Calculate Mt from reviewed Clause 4.4 hill, ridge, or escarpment geometry."""

    calculation = calculate_mt(
        feature_type=feature_type,
        h_m=h_m,
        lu_m=lu_m,
        x_m=x_m,
        z_m=z_m,
        wind_region=wind_region,
        site_elevation_m=site_elevation_m,
        site_is_downwind=site_is_downwind,
    )
    return _result(
        clause="Clause 4.4",
        inputs={
            "feature_type": feature_type,
            "h_m": h_m,
            "lu_m": lu_m,
            "x_m": x_m,
            "z_m": z_m,
            "wind_region": wind_region,
            "site_elevation_m": site_elevation_m,
            "site_is_downwind": site_is_downwind,
        },
        outputs={
            "mt": round(calculation.mt, 6),
            "mh": round(calculation.mh, 6),
            "mlee": round(calculation.mlee, 6),
            "elevation_factor": round(calculation.elevation_factor, 6),
            "slope_parameter": round(calculation.slope_parameter, 6),
            "l1_m": calculation.l1_m,
            "l2_m": calculation.l2_m,
            "equation": calculation.equation,
        },
        warnings=list(calculation.warnings),
    )


@mcp.tool()
def calculate_site_wind_speed(
    vr_mps: float,
    md: float,
    mzcat: float,
    ms: float,
    mt: float,
) -> dict[str, Any]:
    """Calculate site wind speed Vsit,b from reviewed multiplier inputs."""

    values = {
        "vr_mps": _finite_value(
            "VR",
            vr_mps,
            minimum=0,
            maximum=200,
            minimum_inclusive=False,
        ),
        "md": _finite_value("Md", md, minimum=0, maximum=10, minimum_inclusive=False),
        "mzcat": _finite_value(
            "Mz,cat",
            mzcat,
            minimum=0,
            maximum=10,
            minimum_inclusive=False,
        ),
        "ms": _finite_value("Ms", ms, minimum=0, maximum=10, minimum_inclusive=False),
        "mt": _finite_value("Mt", mt, minimum=0, maximum=10, minimum_inclusive=False),
    }
    vsitb = vr_mps * md * mzcat * ms * mt
    return _result(
        clause="Clause 2.3",
        inputs=values,
        outputs={"vsitb_mps": round(vsitb, 6)},
    )


@mcp.tool()
def calculate_all_wind_variables(
    wind_region: str,
    ari_years: int,
    direction: str,
    terrain_category: str,
    height_m: float,
    shielding_parameter: float,
    building_height_m: float,
    feature_type: str,
    h_m: float,
    lu_m: float,
    x_m: float,
    site_elevation_m: float,
    site_is_downwind: bool = True,
) -> dict[str, Any]:
    """Calculate VR, Md, Mz,cat, Ms, Mt, and Vsit,b from reviewed inputs."""

    direction = direction.upper()
    if direction not in DIRECTIONS:
        raise ValueError(f"Direction must be one of: {', '.join(DIRECTIONS)}")
    height_m = _finite_value("Height", height_m, minimum=0, maximum=500, minimum_inclusive=False)
    building_height_m = _finite_value(
        "Building height",
        building_height_m,
        minimum=0,
        maximum=500,
        minimum_inclusive=False,
    )
    shielding_parameter = _finite_value(
        "Shielding parameter s",
        shielding_parameter,
        minimum=0,
        maximum=1_000_000,
    )
    h_m = _finite_value("Topographic H", h_m, minimum=0, maximum=100_000)
    lu_m = _finite_value("Topographic Lu", lu_m, minimum=0, maximum=1_000_000)
    x_m = _finite_value("Topographic x", x_m, minimum=0, maximum=1_000_000)
    site_elevation_m = _finite_value(
        "Site elevation",
        site_elevation_m,
        minimum=-500,
        maximum=10_000,
    )

    vr = regional_wind_speed(wind_region, ari_years)
    md = direction_multiplier_values(wind_region)[direction]
    mzcat = indicative_mzcat(terrain_category, height_m, wind_region=wind_region)
    ms = 1.0 if building_height_m > 25.0 else ms_from_shielding_parameter(shielding_parameter)
    mt_calculation = calculate_mt(
        feature_type=feature_type,
        h_m=h_m,
        lu_m=lu_m,
        x_m=x_m,
        z_m=height_m,
        wind_region=wind_region,
        site_elevation_m=site_elevation_m,
        site_is_downwind=site_is_downwind,
    )
    vsitb = vr * md * mzcat * ms * mt_calculation.mt
    warnings = list(mt_calculation.warnings)
    if building_height_m > 25.0:
        warnings.append("Clause 4.3.1 requires Ms = 1.0 when h > 25 m.")
    warnings.append(
        "Terrain, shielding, topographic geometry, wind region, and jurisdictional variations "
        "must be independently reviewed."
    )
    return _result(
        clause="Clauses 2.3, 3.2, 3.3, 4.2, 4.3 and 4.4",
        inputs={
            "wind_region": wind_region,
            "ari_years": ari_years,
            "direction": direction,
            "terrain_category": terrain_category,
            "height_m": height_m,
            "shielding_parameter": shielding_parameter,
            "building_height_m": building_height_m,
            "feature_type": feature_type,
            "h_m": h_m,
            "lu_m": lu_m,
            "x_m": x_m,
            "site_elevation_m": site_elevation_m,
            "site_is_downwind": site_is_downwind,
        },
        outputs={
            "vr_mps": vr,
            "md": md,
            "mzcat": round(mzcat, 6),
            "ms": round(ms, 6),
            "mt": round(mt_calculation.mt, 6),
            "vsitb_mps": round(vsitb, 6),
        },
        warnings=warnings,
    )


def main() -> None:
    """Run the MCP server over stdio or Streamable HTTP."""

    parser = argparse.ArgumentParser(description="Run the OpenWind-AU MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.environ.get("OPENWIND_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.environ.get("OPENWIND_MCP_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OPENWIND_MCP_PORT", "8001")),
    )
    args = parser.parse_args()
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
