"""Model Context Protocol tools for traceable AS/NZS 1170.2 calculations."""

from __future__ import annotations

import argparse
import ipaddress
import math
import os
from collections.abc import Sequence
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from typing_extensions import TypedDict

from openwind_au import __version__
from openwind_au.models import TerrainCategoryLabel, WindDirection, WindRegionLabel
from openwind_au.mzcat import indicative_mzcat, mzcat_lookup_warnings
from openwind_au.standard_calculations import (
    DIRECTIONS,
    direction_multiplier_values,
    ms_from_shielding_parameter,
    shielding_lookup_warnings,
    shielding_reduction_height_limit_m,
    site_wind_speed,
)
from openwind_au.standard_lookup_tables import lookup_metadata_warnings, source_reference
from openwind_au.topographic_multiplier import (
    calculate_topographic_multiplier as calculate_mt,
)
from openwind_au.wind_inputs import (
    VR_METADATA_WARNING,
    VR_TABLE_ENV,
    configured_regional_wind_speed,
    load_vr_tables,
)

STANDARD = "AS/NZS 1170.2:2021 incorporating Amendments 1 and 2"
MCP_TRANSPORTS = ("stdio", "streamable-http")
LOOPBACK_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
LOOPBACK_ALLOWED_ORIGINS = [
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
]

FeatureType = Literal["hill", "ridge", "escarpment", "valley", "no significant feature"]
AriYears = Annotated[
    int,
    Field(
        strict=True,
        ge=1,
        description="Annual recurrence interval in years; use 1 or at least 5 without an override.",
    ),
]
ReferenceHeight = Annotated[float, Field(strict=True, ge=0, le=200, allow_inf_nan=False)]
PositiveHeight = Annotated[float, Field(strict=True, gt=0, le=200, allow_inf_nan=False)]
TopographicHeight = Annotated[float, Field(strict=True, ge=0, le=100_000, allow_inf_nan=False)]
TopographicDistance = Annotated[float, Field(strict=True, ge=0, le=1_000_000, allow_inf_nan=False)]
SiteElevation = Annotated[float, Field(strict=True, ge=-500, le=10_000, allow_inf_nan=False)]
ShieldingParameter = Annotated[float, Field(strict=True, ge=0, le=1_000_000, allow_inf_nan=False)]
PositiveWindValue = Annotated[float, Field(strict=True, gt=0, le=200, allow_inf_nan=False)]
PositiveMultiplier = Annotated[float, Field(strict=True, gt=0, le=10, allow_inf_nan=False)]
StrictBoolean = Annotated[bool, Field(strict=True)]


class CalculationResult(TypedDict):
    """Stable envelope returned by every OpenWind-AU MCP calculation tool."""

    standard: str
    clause: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    warnings: list[str]
    engineering_review_required: bool


mcp = FastMCP(
    "OpenWind-AU",
    instructions=(
        "Traceable Australian site-wind calculations through Vsit,b. Inputs that depend on "
        "site classification or survey evidence must be reviewed by a competent engineer."
    ),
    stateless_http=True,
    json_response=True,
)
# FastMCP v1 does not expose the low-level server version in its constructor. Setting the
# supported Server attribute ensures initialize reports the application release, not the SDK.
mcp._mcp_server.version = __version__


def _result(
    *,
    clause: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    warnings: list[str] | None = None,
) -> CalculationResult:
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


def _regional_wind_speed(wind_region: str, ari_years: int) -> tuple[float, list[str], str]:
    """Resolve ultimate VR through the API's equation-or-configured-table path."""

    data = load_vr_tables()
    vr, note = configured_regional_wind_speed(
        wind_region,
        ari_years,
        lookup_data=data,
    )
    if vr is None:
        raise ValueError(
            "Configured regional wind speed table has no ultimate value for "
            f"{wind_region} at ARI {ari_years} years; manual input is required."
        )
    warnings = lookup_metadata_warnings(data, VR_METADATA_WARNING)
    if note:
        warnings.append(note)
    configured_table = bool(os.environ.get(VR_TABLE_ENV))
    if configured_table and note is None:
        warnings.append(
            f"Selected the exact {ari_years}-year ARI row from the configured VR table."
        )
    selected_source = (
        source_reference(data) if configured_table else f"{STANDARD} Table 3.1(A) regional equation"
    )
    return vr, warnings, selected_source


@mcp.tool()
def calculate_regional_wind_speed(
    wind_region: WindRegionLabel,
    ari_years: AriYears,
) -> CalculationResult:
    """Calculate Australian regional wind speed VR for a reviewed region and ARI."""

    vr, lookup_warnings, selected_source = _regional_wind_speed(wind_region, ari_years)
    return _result(
        clause="Table 3.1(A)",
        inputs={"wind_region": wind_region, "ari_years": ari_years},
        outputs={"vr_mps": vr, "source_reference": selected_source},
        warnings=[
            "Confirm the wind-region boundary and applicable NCC jurisdictional variations.",
            *lookup_warnings,
        ],
    )


@mcp.tool()
def get_direction_multipliers(wind_region: WindRegionLabel) -> CalculationResult:
    """Return the eight Australian wind direction multipliers Md for a reviewed region."""

    multipliers = direction_multiplier_values(wind_region)
    return _result(
        clause="Table 3.2(A)",
        inputs={"wind_region": wind_region},
        outputs={"md": multipliers, "any_direction_md": 1.0},
    )


@mcp.tool()
def calculate_terrain_height_multiplier(
    terrain_category: TerrainCategoryLabel,
    height_m: PositiveHeight,
    wind_region: WindRegionLabel,
) -> CalculationResult:
    """Calculate Mz,cat from a reviewed terrain category, height, and wind region."""

    height_m = _finite_value("Height", height_m, minimum=0, maximum=200, minimum_inclusive=False)
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
            "reviewed separately.",
            *mzcat_lookup_warnings(),
        ],
    )


@mcp.tool()
def calculate_shielding_multiplier(
    shielding_parameter: ShieldingParameter,
    building_height_m: PositiveHeight,
) -> CalculationResult:
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
        maximum=200,
        minimum_inclusive=False,
    )
    warnings = shielding_lookup_warnings()
    height_limit_m = shielding_reduction_height_limit_m()
    if building_height_m > height_limit_m:
        ms = 1.0
        warnings.append(f"Clause 4.3.1 requires Ms = 1.0 when h > {height_limit_m:g} m.")
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
    feature_type: FeatureType,
    h_m: TopographicHeight,
    lu_m: TopographicDistance,
    x_m: TopographicDistance,
    z_m: ReferenceHeight,
    average_roof_height_m: PositiveHeight,
    wind_region: WindRegionLabel,
    site_elevation_m: SiteElevation,
    site_is_downwind: StrictBoolean = True,
) -> CalculationResult:
    """Calculate Mt from reviewed Clause 4.4 hill, ridge, or escarpment geometry."""

    calculation = calculate_mt(
        feature_type=feature_type,
        h_m=h_m,
        lu_m=lu_m,
        x_m=x_m,
        z_m=z_m,
        average_roof_height_m=average_roof_height_m,
        wind_region=wind_region,
        site_elevation_m=site_elevation_m,
        site_is_downwind=site_is_downwind,
    )
    if not calculation.geometry_resolved:
        raise ValueError(
            "Topographic Lu is required for a qualifying hill, ridge, or escarpment; "
            "Mt and Vsit,b are blocked until geometry is resolved."
        )
    return _result(
        clause="Clause 4.4",
        inputs={
            "feature_type": feature_type,
            "h_m": h_m,
            "lu_m": lu_m,
            "x_m": x_m,
            "z_m": z_m,
            "average_roof_height_m": average_roof_height_m,
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
            "minimum_feature_height_m": calculation.minimum_feature_height_m,
            "geometry_resolved": calculation.geometry_resolved,
            "l1_m": calculation.l1_m,
            "l2_m": calculation.l2_m,
            "equation": calculation.equation,
        },
        warnings=list(calculation.warnings),
    )


@mcp.tool()
def calculate_site_wind_speed(
    vr_mps: PositiveWindValue,
    md: PositiveMultiplier,
    mzcat: PositiveMultiplier,
    ms: PositiveMultiplier,
    mt: PositiveMultiplier,
) -> CalculationResult:
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
    vsitb = site_wind_speed(
        values["vr_mps"],
        values["md"],
        values["mzcat"],
        values["ms"],
        values["mt"],
    )
    return _result(
        clause="Clause 2.3",
        inputs=values,
        outputs={"vsitb_mps": round(vsitb, 6)},
    )


@mcp.tool()
def calculate_all_wind_variables(
    wind_region: WindRegionLabel,
    ari_years: AriYears,
    direction: WindDirection,
    terrain_category: TerrainCategoryLabel,
    height_m: PositiveHeight,
    shielding_parameter: ShieldingParameter,
    building_height_m: PositiveHeight,
    feature_type: FeatureType,
    h_m: TopographicHeight,
    lu_m: TopographicDistance,
    x_m: TopographicDistance,
    site_elevation_m: SiteElevation,
    site_is_downwind: StrictBoolean = True,
) -> CalculationResult:
    """Calculate VR, Md, Mz,cat, Ms, Mt, and Vsit,b from reviewed inputs."""

    direction = direction.upper()
    if direction not in DIRECTIONS:
        raise ValueError(f"Direction must be one of: {', '.join(DIRECTIONS)}")
    height_m = _finite_value(
        "Reference height",
        height_m,
        minimum=0,
        maximum=200,
        minimum_inclusive=False,
    )
    building_height_m = _finite_value(
        "Building height",
        building_height_m,
        minimum=0,
        maximum=200,
        minimum_inclusive=False,
    )
    if height_m > building_height_m:
        raise ValueError("Reference height must not exceed the overall building height.")
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

    vr, vr_warnings, vr_source = _regional_wind_speed(wind_region, ari_years)
    md = direction_multiplier_values(wind_region)[direction]
    mzcat = indicative_mzcat(terrain_category, height_m, wind_region=wind_region)
    height_limit_m = shielding_reduction_height_limit_m()
    ms = (
        1.0
        if building_height_m > height_limit_m
        else ms_from_shielding_parameter(shielding_parameter)
    )
    mt_calculation = calculate_mt(
        feature_type=feature_type,
        h_m=h_m,
        lu_m=lu_m,
        x_m=x_m,
        z_m=height_m,
        average_roof_height_m=building_height_m,
        wind_region=wind_region,
        site_elevation_m=site_elevation_m,
        site_is_downwind=site_is_downwind,
    )
    if not mt_calculation.geometry_resolved:
        raise ValueError(
            "Topographic Lu is required for a qualifying hill, ridge, or escarpment; "
            "Mt and Vsit,b are blocked until geometry is resolved."
        )
    vsitb = site_wind_speed(vr, md, mzcat, ms, mt_calculation.mt)
    warnings = [
        *vr_warnings,
        *mzcat_lookup_warnings(),
        *shielding_lookup_warnings(),
        *mt_calculation.warnings,
    ]
    if building_height_m > height_limit_m:
        warnings.append(f"Clause 4.3.1 requires Ms = 1.0 when h > {height_limit_m:g} m.")
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
            "vr_source_reference": vr_source,
            "md": md,
            "mzcat": round(mzcat, 6),
            "ms": round(ms, 6),
            "mt": round(mt_calculation.mt, 6),
            "vsitb_mps": round(vsitb, 6),
        },
        warnings=warnings,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the MCP server over stdio or Streamable HTTP."""

    parser = argparse.ArgumentParser(
        prog="openwind-au-mcp",
        description="Run the OpenWind-AU MCP server.",
    )
    parser.add_argument(
        "--transport",
        choices=MCP_TRANSPORTS,
        default=None,
        help="MCP transport (default: OPENWIND_MCP_TRANSPORT or stdio)",
    )
    parser.add_argument(
        "--host",
        type=_host,
        default=None,
        help="HTTP bind host (default: OPENWIND_MCP_HOST or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=_port,
        default=None,
        help="HTTP bind port (default: OPENWIND_MCP_PORT or 8001)",
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        type=_allowed_host,
        default=None,
        help=(
            "Trusted HTTP Host header, repeatable. Required for wildcard binds; "
            "default: OPENWIND_MCP_ALLOWED_HOSTS."
        ),
    )
    parser.add_argument(
        "--allowed-origin",
        action="append",
        type=_allowed_origin,
        default=None,
        help=(
            "Trusted browser Origin, repeatable. Default: OPENWIND_MCP_ALLOWED_ORIGINS "
            "or origins derived from allowed hosts."
        ),
    )
    args = parser.parse_args(argv)

    transport = args.transport
    if transport is None:
        transport = _environment_value(
            parser,
            "OPENWIND_MCP_TRANSPORT",
            "stdio",
            _transport,
        )
    host = args.host
    if host is None:
        host = _environment_value(parser, "OPENWIND_MCP_HOST", "127.0.0.1", _host)
    port = args.port
    if port is None:
        port = _environment_value(parser, "OPENWIND_MCP_PORT", "8001", _port)
    allowed_hosts = args.allowed_host
    if allowed_hosts is None:
        allowed_hosts = _environment_list(
            parser,
            "OPENWIND_MCP_ALLOWED_HOSTS",
            _allowed_host,
        )
    allowed_origins = args.allowed_origin
    if allowed_origins is None:
        allowed_origins = _environment_list(
            parser,
            "OPENWIND_MCP_ALLOWED_ORIGINS",
            _allowed_origin,
        )

    mcp.settings.host = host
    mcp.settings.port = port
    if transport == "streamable-http":
        mcp.settings.transport_security = _transport_security_settings(
            parser,
            bind_host=host,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )
    mcp.run(transport=transport)
    return 0


def _environment_value(
    parser: argparse.ArgumentParser,
    name: str,
    fallback: str,
    converter,
):
    """Validate one MCP environment default and surface an argparse diagnostic."""

    try:
        return converter(os.environ.get(name, fallback))
    except argparse.ArgumentTypeError as exc:
        parser.error(f"{name}: {exc}")


def _environment_list(
    parser: argparse.ArgumentParser,
    name: str,
    converter,
) -> list[str]:
    """Parse a comma-separated MCP security allowlist."""

    raw_value = os.environ.get(name, "")
    if not raw_value.strip():
        return []
    values: list[str] = []
    for raw_item in raw_value.split(","):
        try:
            values.append(converter(raw_item))
        except argparse.ArgumentTypeError as exc:
            parser.error(f"{name}: {exc}")
    return values


def _transport(value: str) -> str:
    """Parse one supported MCP transport."""

    transport = value.strip()
    if transport not in MCP_TRANSPORTS:
        choices = ", ".join(MCP_TRANSPORTS)
        raise argparse.ArgumentTypeError(f"transport must be one of: {choices}")
    return transport


def _host(value: str) -> str:
    """Reject an empty MCP bind host."""

    host = value.strip()
    if not host:
        raise argparse.ArgumentTypeError("host must not be empty")
    if any(character.isspace() for character in host) or "/" in host or "@" in host or "*" in host:
        raise argparse.ArgumentTypeError("host must be a hostname or IP address without a port")
    if ":" in host:
        try:
            ipaddress.ip_address(host)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                "host must be a hostname or IP address without a port"
            ) from exc
    return host


def _port(value: str) -> int:
    """Parse one valid MCP TCP port."""

    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _allowed_host(value: str) -> str:
    """Validate one trusted Host-header value."""

    allowed_host = value.strip()
    if not allowed_host:
        raise argparse.ArgumentTypeError("allowed host must not be empty")
    if (
        any(character.isspace() for character in allowed_host)
        or "/" in allowed_host
        or "@" in allowed_host
        or ("*" in allowed_host and not allowed_host.endswith(":*"))
    ):
        raise argparse.ArgumentTypeError(
            "allowed host must be a hostname, IP, host:port, or host:* pattern"
        )
    if allowed_host.startswith("["):
        closing_bracket = allowed_host.find("]")
        if closing_bracket < 0:
            raise argparse.ArgumentTypeError("allowed host contains an invalid bracketed IPv6 IP")
        address_text = allowed_host[1:closing_bracket]
        suffix = allowed_host[closing_bracket + 1 :]
        try:
            address = ipaddress.ip_address(address_text)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                "allowed host contains an invalid bracketed IPv6 IP"
            ) from exc
        if address.version != 6 or (suffix and not _valid_port_suffix(suffix)):
            raise argparse.ArgumentTypeError(
                "allowed host must be a hostname, IP, host:port, or host:* pattern"
            )
        return allowed_host
    if ":" in allowed_host:
        try:
            address = ipaddress.ip_address(allowed_host)
        except ValueError:
            hostname, port = allowed_host.rsplit(":", 1)
            if not hostname or ":" in hostname or not _valid_port_suffix(f":{port}"):
                raise argparse.ArgumentTypeError(
                    "IPv6 allowed hosts must be a bare IP or use [address]:port syntax"
                ) from None
            return allowed_host
        if address.version == 6:
            return f"[{allowed_host}]"
    return allowed_host


def _allowed_origin(value: str) -> str:
    """Validate one trusted browser Origin-header value."""

    allowed_origin = value.strip().rstrip("/")
    try:
        parsed = urlsplit(allowed_origin)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("allowed origin contains an invalid host") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise argparse.ArgumentTypeError(
            "allowed origin must be an http(s) origin without credentials or a path"
        )
    return allowed_origin


def _transport_security_settings(
    parser: argparse.ArgumentParser,
    *,
    bind_host: str,
    allowed_hosts: Sequence[str],
    allowed_origins: Sequence[str],
) -> TransportSecuritySettings:
    """Build a protected HTTP allowlist for the selected bind interface."""

    trusted_hosts = list(LOOPBACK_ALLOWED_HOSTS)
    requested_hosts = list(allowed_hosts)
    wildcard_bind = _is_wildcard_bind_host(bind_host)
    if wildcard_bind and not requested_hosts:
        parser.error(
            "--allowed-host or OPENWIND_MCP_ALLOWED_HOSTS is required when binding "
            f"Streamable HTTP to {bind_host}"
        )
    if not wildcard_bind:
        requested_hosts.append(_host_header_name(bind_host))
    for allowed_host in requested_hosts:
        if allowed_host not in trusted_hosts:
            trusted_hosts.append(allowed_host)
        if not _host_has_port_pattern(allowed_host):
            wildcard_port = f"{allowed_host}:*"
            if wildcard_port not in trusted_hosts:
                trusted_hosts.append(wildcard_port)

    trusted_origins = list(LOOPBACK_ALLOWED_ORIGINS)
    derived_origins = [
        f"{scheme}://{allowed_host}"
        for allowed_host in trusted_hosts
        if allowed_host not in LOOPBACK_ALLOWED_HOSTS
        for scheme in ("http", "https")
    ]
    for allowed_origin in [*derived_origins, *allowed_origins]:
        if allowed_origin not in trusted_origins:
            trusted_origins.append(allowed_origin)

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=trusted_hosts,
        allowed_origins=trusted_origins,
    )


def _host_header_name(bind_host: str) -> str:
    """Return the Host-header representation for a concrete bind host."""

    try:
        address = ipaddress.ip_address(bind_host)
    except ValueError:
        return bind_host
    return f"[{bind_host}]" if address.version == 6 else bind_host


def _is_wildcard_bind_host(bind_host: str) -> bool:
    """Return whether a bind address listens on every interface."""

    try:
        return ipaddress.ip_address(bind_host).is_unspecified
    except ValueError:
        return False


def _host_has_port_pattern(allowed_host: str) -> bool:
    """Return whether an allowed Host value already fixes or wildcards a port."""

    if allowed_host.startswith("["):
        return "]:" in allowed_host
    return allowed_host.count(":") == 1


def _valid_port_suffix(suffix: str) -> bool:
    """Return whether a Host allowlist suffix is :*, or a valid TCP port."""

    if suffix == ":*":
        return True
    if not suffix.startswith(":") or not suffix[1:].isdigit():
        return False
    return 1 <= int(suffix[1:]) <= 65535


if __name__ == "__main__":
    raise SystemExit(main())
