# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Elandu and contributors

"""OpenCalcs-compatible registry backed by existing OpenWind functions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from openwind_au.as4055 import (
    HousingGeometry,
    HousingSurface,
    SiteClassification,
    SiteConditions,
    calculate_housing_loads,
    calculate_racking_force,
    calculate_uplift,
    classify_site,
    validate_classification,
)
from openwind_au.calculations.as4055_extensions import AS4055_EXTENSIONS, inline_schema
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
from openwind_au.wind_actions import WindFrameLoadRequest, calculate_wind_frame_loads

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


def _as4055_classification(inputs: Mapping[str, Any]) -> dict[str, Any]:
    result = classify_site(
        HousingGeometry(**inputs["geometry"]),
        SiteConditions(**inputs["site_conditions"]),
    )
    classification = asdict(result)
    return {
        **classification,
        "classification": classification,
    }


def _as4055_housing_loads(inputs: Mapping[str, Any]) -> dict[str, Any]:
    classification = validate_classification(SiteClassification(**inputs["classification"]))
    result = calculate_housing_loads(
        classification=classification,
        surfaces=tuple(HousingSurface(**surface) for surface in inputs["surfaces"]),
        limit_state=inputs["limit_state"],
        roof_pitch_degrees=inputs.get("roof_pitch_degrees"),
    )
    return {
        "surface_loads": [asdict(item) for item in result],
        "site_wind_classification": classification.site_wind_classification,
        "wall_classification": classification.wall_classification,
        "roof_classification": classification.roof_classification,
        "source_clauses": [*classification.source_clauses, "3.1", "3.2", "3.3", "3.4"],
        "source_tables": [
            *classification.source_tables,
            "Table 3.2.1",
            "Table 3.2.2(A)",
            "Table 3.2.2(B)",
        ],
        "lookup_digest": classification.lookup_digest,
        "uplift_force_kn": {
            "roof_structure_load_path": calculate_uplift(result, "roof_structure"),
            "roof_cladding_load_path": calculate_uplift(result, "roof_cladding"),
        },
        "status": "preliminary_independent_review_required",
    }


def _as4055_racking_force(inputs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "racking_force_kn": calculate_racking_force(
            inputs["elevation_area_m2"], inputs["lateral_pressure_kpa"]
        ),
        "status": "preliminary_independent_review_required",
        "limitations": [
            "Select lateral pressure separately from AS 4055 Tables 5.2(A) to 5.2(M).",
            "This result is not a bracing or foundation capacity design.",
        ],
    }


def _wind_frame_loads(inputs: Mapping[str, Any]) -> dict[str, Any]:
    result = calculate_wind_frame_loads(
        WindFrameLoadRequest.model_validate_json(json.dumps(inputs))
    )
    return result.model_dump(mode="json") | {
        "member_distributed_loads": result.member_distributed_loads
    }


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
                "ari_years": {
                    "type": "integer",
                    "anyOf": [{"const": 1}, {"minimum": 5}],
                },
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
    CalculationDefinition(
        id="au.wind.as4055.classify_housing_site",
        name="AS 4055 housing site classification",
        description="Classify an eligible house from reviewed AS 4055 site-condition categories.",
        discipline="structural",
        category="wind",
        jurisdiction="AU",
        version="1",
        standard=StandardReference(
            name="AS 4055",
            edition="2021",
            clauses=("1.1", "1.2", "2.1", "2.2", "2.6"),
            tables=(
                "Table 2.1(A)",
                "Table 2.1(B)",
                "Table 2.2",
                "Table 2.6.1(A)",
                "Table 2.6.1(B)",
            ),
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["geometry", "site_conditions"],
            "properties": {
                "geometry": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "building_class",
                        "eaves_height_m",
                        "roof_height_m",
                        "width_m",
                        "length_m",
                        "roof_pitch_degrees",
                    ],
                    "properties": {
                        "building_class": {"enum": ["1", "10a"]},
                        "eaves_height_m": {"type": "number", "exclusiveMinimum": 0},
                        "roof_height_m": {"type": "number", "exclusiveMinimum": 0},
                        "width_m": {"type": "number", "exclusiveMinimum": 0},
                        "length_m": {"type": "number", "exclusiveMinimum": 0},
                        "roof_pitch_degrees": {"type": "number", "minimum": 0, "maximum": 35},
                    },
                },
                "site_conditions": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "region",
                        "terrain_category",
                        "topographic_class",
                        "shielding_class",
                    ],
                    "properties": {
                        "region": {"enum": ["A", "B", "C", "D"]},
                        "terrain_category": {"enum": ["TC1", "TC2", "TC2.5", "TC3"]},
                        "topographic_class": {"enum": ["T0", "T1", "T2", "T3", "T4", "T5"]},
                        "shielding_class": {"enum": ["FS", "PS", "NS"]},
                        "distance_km": {"type": "number", "minimum": 0, "maximum": 50},
                        "distance_basis": {
                            "enum": ["smoothed_coastline", "higher_wind_region_boundary"]
                        },
                    },
                },
            },
        },
        output_schema={
            "type": "object",
            "required": [
                "classification",
                "site_wind_classification",
                "roof_classification",
                "wall_classification",
                "lookup_digest",
                "status",
            ],
            "properties": {
                "classification": {
                    "type": "object",
                    "description": (
                        "Complete AS 4055 classification record. Link this object into "
                        "the housing-load calculation input."
                    ),
                },
                "site_wind_classification": {"type": "string"},
                "roof_classification": {"type": "string"},
                "wall_classification": {"type": "string"},
                "lookup_digest": {"type": "string"},
                "status": {"type": "string"},
            },
        },
        executor=_as4055_classification,
    ),
    CalculationDefinition(
        id="au.wind.as4055.housing_surface_loads",
        name="AS 4055 housing surface pressures and forces",
        description=(
            "Calculate external, internal and net pressures and surface resultant forces "
            "from AS 4055 class speeds and component coefficients."
        ),
        discipline="structural",
        category="wind",
        jurisdiction="AU",
        version="1",
        standard=StandardReference(
            name="AS 4055",
            edition="2021",
            clauses=("2.1", "3.1", "3.2", "3.3", "3.4"),
            tables=(
                "Table 2.1(A)",
                "Table 2.1(B)",
                "Table 3.2.1",
                "Table 3.2.2(A)",
                "Table 3.2.2(B)",
            ),
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["classification", "surfaces", "limit_state"],
            "properties": {
                "classification": {"type": "object"},
                "surfaces": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["component", "zone", "area_m2"],
                        "properties": {
                            "component": {
                                "enum": [
                                    "roof_structure",
                                    "roof_cladding",
                                    "wall_structure",
                                    "wall_cladding",
                                ]
                            },
                            "zone": {"enum": ["G", "RE", "RC", "SC"]},
                            "area_m2": {"type": "number", "exclusiveMinimum": 0},
                        },
                    },
                },
                "limit_state": {"enum": ["serviceability", "ultimate"]},
                "roof_pitch_degrees": {"type": "number", "minimum": 0, "maximum": 35},
            },
        },
        output_schema={
            "type": "object",
            "required": [
                "surface_loads",
                "uplift_force_kn",
                "status",
                "lookup_digest",
                "site_wind_classification",
                "wall_classification",
                "roof_classification",
            ],
            "properties": {
                "surface_loads": {"type": "array", "items": {"type": "object"}},
                "uplift_force_kn": {"type": "object"},
                "site_wind_classification": {"type": "string"},
                "wall_classification": {"type": "string"},
                "roof_classification": {"type": "string"},
                "source_clauses": {"type": "array", "items": {"type": "string"}},
                "source_tables": {"type": "array", "items": {"type": "string"}},
                "lookup_digest": {"type": "string"},
                "status": {"type": "string"},
            },
        },
        executor=_as4055_housing_loads,
    ),
    CalculationDefinition(
        id="au.wind.as4055.racking_force",
        name="AS 4055 house racking force",
        description=(
            "Calculate total racking force from a reviewed Section 5 lateral pressure "
            "and elevation area."
        ),
        discipline="structural",
        category="wind",
        jurisdiction="AU",
        version="1",
        standard=StandardReference(
            name="AS 4055", edition="2021", clauses=("5.1",), tables=("Tables 5.2(A) to 5.2(M)",)
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["elevation_area_m2", "lateral_pressure_kpa"],
            "properties": {
                "elevation_area_m2": {"type": "number", "exclusiveMinimum": 0},
                "lateral_pressure_kpa": {"type": "number", "minimum": 0},
            },
        },
        output_schema={
            "type": "object",
            "required": ["racking_force_kn", "status", "limitations"],
            "properties": {
                "racking_force_kn": {"type": "number", "unit": "kN"},
                "status": {"type": "string"},
                "limitations": {"type": "array", "items": {"type": "string"}},
            },
        },
        executor=_as4055_racking_force,
    ),
    CalculationDefinition(
        id="au.wind.frame_loads",
        name="AS/NZS 1170.2 wind pressure and frame loads",
        description=(
            "Apply reviewed external/internal shape factors to explicit AS/NZS 1170.2 "
            "design speeds and distribute panel pressure to reviewed frame tributaries."
        ),
        discipline="structural",
        category="wind",
        jurisdiction="AU",
        version="1",
        standard=StandardReference(
            name=STANDARD.name,
            edition=STANDARD.edition,
            clauses=("2.3", "2.4.1", "2.5.3.1"),
        ),
        input_schema=inline_schema(WindFrameLoadRequest),
        output_schema={
            "type": "object",
            "required": ["panel_pressures", "member_loads", "member_distributed_loads"],
            "properties": {
                "panel_pressures": {"type": "array", "items": {"type": "object"}},
                "member_loads": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "member_id",
                            "load_case",
                            "direction",
                            "start_kn_m",
                            "end_kn_m",
                            "start_m",
                            "end_m",
                        ],
                    },
                },
                "member_distributed_loads": {"type": "array", "items": {"type": "object"}},
                "source_clauses": {"type": "array", "items": {"type": "string"}},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
        },
        executor=_wind_frame_loads,
    ),
)

CALCULATIONS += AS4055_EXTENSIONS

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
