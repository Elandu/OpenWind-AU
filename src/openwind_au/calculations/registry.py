"""OpenCalcs-compatible registry backed by existing OpenWind functions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from openwind_au.calculations.contracts import (
    CalculationDefinition,
    StandardReference,
)
from openwind_au.standard_calculations import (
    climate_change_multiplier,
    design_wind_speed,
    direction_multiplier_values,
    ms_from_shielding_parameter,
    regional_wind_speed,
    site_wind_speed,
)

STANDARD = StandardReference(
    name="AS/NZS 1170.2",
    edition="2021",
)

DIRECTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
    "properties": {
        direction: {"type": "number", "exclusiveMinimum": 0}
        for direction in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    },
}


def _regional_wind_speed(inputs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "regional_wind_speed_m_s": regional_wind_speed(
            region=inputs["region"],
            ari_years=inputs["ari_years"],
        )
    }


def _climate_change_multiplier(inputs: Mapping[str, Any]) -> dict[str, Any]:
    return {"climate_change_multiplier": climate_change_multiplier(inputs["region"])}


def _direction_multiplier_values(inputs: Mapping[str, Any]) -> dict[str, Any]:
    return {"direction_multipliers": direction_multiplier_values(inputs["region"])}


def _shielding_multiplier(inputs: Mapping[str, Any]) -> dict[str, Any]:
    return {"shielding_multiplier": ms_from_shielding_parameter(inputs["shielding_parameter"])}


def _site_wind_speed(inputs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "site_wind_speed_m_s": site_wind_speed(
            vr=inputs["vr"],
            mc=inputs["mc"],
            md=inputs["md"],
            mzcat=inputs["mzcat"],
            ms=inputs["ms"],
            mt=inputs["mt"],
        )
    }


def _design_wind_speed(inputs: Mapping[str, Any]) -> dict[str, Any]:
    result = design_wind_speed(
        theta_degrees=inputs["theta_degrees"],
        direction_speeds=inputs["direction_speeds"],
        ultimate_limit_state=inputs.get("ultimate_limit_state", True),
    )
    return asdict(result)


CALCULATIONS: tuple[CalculationDefinition, ...] = (
    CalculationDefinition(
        id="au.wind.regional_wind_speed",
        name="Regional wind speed",
        description="Calculate VR for an Australian wind region and annual recurrence interval.",
        discipline="structural",
        category="wind",
        jurisdiction="AU",
        version="1",
        standard=StandardReference(
            name=STANDARD.name,
            edition=STANDARD.edition,
            clauses=("3.2",),
            tables=("Table 3.1(A)",),
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["region", "ari_years"],
            "properties": {
                "region": {"type": "string"},
                "ari_years": {"type": "integer", "minimum": 1},
            },
        },
        output_schema={
            "type": "object",
            "required": ["regional_wind_speed_m_s"],
            "properties": {"regional_wind_speed_m_s": {"type": "number", "unit": "m/s"}},
        },
        executor=_regional_wind_speed,
    ),
    CalculationDefinition(
        id="au.wind.climate_change_multiplier",
        name="Climate change multiplier",
        description="Return Mc for the selected Australian wind region.",
        discipline="structural",
        category="wind",
        jurisdiction="AU",
        version="1",
        standard=StandardReference(
            name=STANDARD.name,
            edition=STANDARD.edition,
            clauses=("3.4",),
            tables=("Table 3.3",),
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["region"],
            "properties": {"region": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "required": ["climate_change_multiplier"],
            "properties": {"climate_change_multiplier": {"type": "number"}},
        },
        executor=_climate_change_multiplier,
    ),
    CalculationDefinition(
        id="au.wind.direction_multipliers",
        name="Wind direction multipliers",
        description="Return the configured Md values for the eight principal directions.",
        discipline="structural",
        category="wind",
        jurisdiction="AU",
        version="1",
        standard=StandardReference(
            name=STANDARD.name,
            edition=STANDARD.edition,
            clauses=("3.3",),
            tables=("Table 3.2(A)",),
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["region"],
            "properties": {"region": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "required": ["direction_multipliers"],
            "properties": {"direction_multipliers": DIRECTION_SCHEMA},
        },
        executor=_direction_multiplier_values,
    ),
    CalculationDefinition(
        id="au.wind.shielding_multiplier",
        name="Shielding multiplier",
        description="Interpolate Ms from shielding parameter s.",
        discipline="structural",
        category="wind",
        jurisdiction="AU",
        version="1",
        standard=StandardReference(
            name=STANDARD.name,
            edition=STANDARD.edition,
            clauses=("4.3",),
            tables=("Table 4.2",),
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["shielding_parameter"],
            "properties": {
                "shielding_parameter": {"type": "number", "minimum": 0},
            },
        },
        output_schema={
            "type": "object",
            "required": ["shielding_multiplier"],
            "properties": {"shielding_multiplier": {"type": "number"}},
        },
        executor=_shielding_multiplier,
    ),
    CalculationDefinition(
        id="au.wind.site_wind_speed",
        name="Site wind speed",
        description="Calculate Vsit,b from VR, Mc, Md, Mz,cat, Ms and Mt.",
        discipline="structural",
        category="wind",
        jurisdiction="AU",
        version="1",
        standard=StandardReference(
            name=STANDARD.name,
            edition=STANDARD.edition,
            clauses=("2.2",),
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["vr", "mc", "md", "mzcat", "ms", "mt"],
            "properties": {
                name: {"type": "number", "exclusiveMinimum": 0}
                for name in ("vr", "mc", "md", "mzcat", "ms", "mt")
            },
        },
        output_schema={
            "type": "object",
            "required": ["site_wind_speed_m_s"],
            "properties": {"site_wind_speed_m_s": {"type": "number", "unit": "m/s"}},
        },
        executor=_site_wind_speed,
    ),
    CalculationDefinition(
        id="au.wind.design_wind_speed",
        name="Design wind speed",
        description="Calculate Vdes,theta from eight directional site wind speeds.",
        discipline="structural",
        category="wind",
        jurisdiction="AU",
        version="1",
        standard=StandardReference(
            name=STANDARD.name,
            edition=STANDARD.edition,
            clauses=("2.3",),
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["theta_degrees", "direction_speeds"],
            "properties": {
                "theta_degrees": {"type": "number", "minimum": 0, "exclusiveMaximum": 360},
                "direction_speeds": DIRECTION_SCHEMA,
                "ultimate_limit_state": {"type": "boolean", "default": True},
            },
        },
        output_schema={
            "type": "object",
            "required": [
                "theta_degrees",
                "sector_start_degrees",
                "sector_end_degrees",
                "candidates",
                "raw_maximum_m_s",
                "design_wind_speed_m_s",
                "minimum_applied",
            ],
            "properties": {
                "theta_degrees": {"type": "number"},
                "sector_start_degrees": {"type": "number"},
                "sector_end_degrees": {"type": "number"},
                "candidates": {"type": "array"},
                "raw_maximum_m_s": {"type": "number", "unit": "m/s"},
                "design_wind_speed_m_s": {"type": "number", "unit": "m/s"},
                "minimum_applied": {"type": "boolean"},
            },
        },
        executor=_design_wind_speed,
    ),
)

_CALCULATIONS_BY_ID = {definition.id: definition for definition in CALCULATIONS}


def list_calculations() -> list[dict[str, Any]]:
    """Return host-facing metadata for all registered calculations."""

    return [definition.descriptor() for definition in CALCULATIONS]


def get_calculation(calculation_id: str) -> CalculationDefinition:
    """Return one registered calculation by stable identifier."""

    try:
        return _CALCULATIONS_BY_ID[calculation_id]
    except KeyError as exc:
        raise KeyError(f"Unknown calculation: {calculation_id}") from exc


def run_calculation(calculation_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Dispatch to an existing OpenWind calculation function."""

    return get_calculation(calculation_id).run(inputs)
