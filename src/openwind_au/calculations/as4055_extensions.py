# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Elandu and contributors

"""Host adapters for scoped housing zones, anchoring and racking demand."""

import math
from dataclasses import asdict

from openwind_au.as4055 import (
    AS4055AnchoringRequest,
    AS4055HousingAssessmentRequest,
    AS4055RackingPressureRequest,
    AS4055ZoneAreasRequest,
    HousingGeometry,
    SiteClassification,
    SiteConditions,
    calculate_housing_loads,
    calculate_pressure_zone_areas,
    calculate_racking_pressure,
    calculate_roof_anchoring,
    classify_site,
    source_lookup_digest,
)
from openwind_au.calculations.contracts import CalculationDefinition, StandardReference


def zone_areas(inputs):
    request = AS4055ZoneAreasRequest.model_validate(dict(inputs))
    surfaces = calculate_pressure_zone_areas(
        HousingGeometry(**request.geometry.model_dump()),
        request.roof_form,
    )
    return {
        "surfaces": [asdict(surface) for surface in surfaces],
        "source_figures": ["3.1(A)", "3.1(B)"],
        "lookup_digest": source_lookup_digest(),
        "status": "preliminary_independent_review_required",
        "limitations": [
            "Simple rectangular flat or symmetric gable roof without overhangs only.",
            "Roof edge distances are measured along each sloping roof surface.",
            "Wall panels and openings need individual checking: Table 3.2.1 Note 5 "
            "can classify a whole window or door as SC when 25% is near a corner.",
            "Roof and wall structural areas are separate load paths from cladding areas.",
        ],
    }


def roof_anchoring(inputs):
    request = AS4055AnchoringRequest.model_validate(dict(inputs))
    result = calculate_roof_anchoring(
        SiteClassification(**request.classification),
        request.roof_type,
        request.roof_surface_area_m2,
        request.limit_state,
        all_cladding_resists_design_wind=request.all_cladding_resists_design_wind,
    )
    return {
        **asdict(result),
        "lookup_digest": source_lookup_digest(),
        "standard": "AS 4055",
        "edition": "2021",
        "limitations": [
            "Table 4 already includes roof dead load; do not deduct it again.",
            "Apply to the entire roof surface, then design individual tie-downs.",
        ],
    }


def racking_pressure(inputs):
    request = AS4055RackingPressureRequest.model_validate(dict(inputs))
    values = request.model_dump()
    values["classification"] = SiteClassification(**values["classification"])
    return calculate_racking_pressure(**values)


def housing_assessment(inputs):
    """One saved housing run containing separate SLS, ULS and racking demands."""
    request = AS4055HousingAssessmentRequest.model_validate(dict(inputs))
    classification = classify_site(
        HousingGeometry(**request.geometry.model_dump()),
        SiteConditions(**request.site_conditions.model_dump()),
    )
    surfaces = calculate_pressure_zone_areas(classification.geometry, request.roof_form)
    roof_area = next(s.area_m2 for s in surfaces if s.component == "roof_structure")
    elevations = request.racking_elevations
    keys = [(e.storey, e.wind_on) for e in elevations]
    if len(set(keys)) != len(keys):
        raise ValueError("Each storey and wind direction must have one reviewed elevation area.")
    expected_storeys = {"single_or_upper"} if request.storeys == 1 else {"single_or_upper", "lower"}
    if {e.storey for e in elevations} != expected_storeys:
        raise ValueError("Supply every storey for the selected number of storeys.")
    for storey in {e.storey for e in elevations}:
        if {e.wind_on for e in elevations if e.storey == storey} != {"side", "end"}:
            raise ValueError("Both side and end wind directions are required for each storey.")
        dimensions = {
            (e.storey_height_m, e.floor_depth_m) for e in elevations if e.storey == storey
        }
        if len(dimensions) != 1:
            raise ValueError("Both directions must use the same storey height and floor depth.")
    side_elevations = [e for e in elevations if e.wind_on == "side"]
    expected_eaves = sum(e.storey_height_m for e in side_elevations)
    if request.storeys == 2:
        expected_eaves += next(e.floor_depth_m for e in side_elevations if e.storey == "lower")
    if not math.isclose(expected_eaves, request.geometry.eaves_height_m, abs_tol=0.01):
        raise ValueError(
            "Storey heights and inter-storey floor must match eaves height; "
            "subfloor buildings need a separate reviewed assessment."
        )
    racking = []
    for elevation in elevations:
        flat = request.roof_form == "flat" or elevation.wind_on == "end"
        result = calculate_racking_pressure(
            classification,
            "flat_vertical" if flat else "gable_side",
            storey=elevation.storey,
            wind_on=None if flat else elevation.wind_on,
            width_m=None if flat else request.geometry.width_m,
            roof_pitch_degrees=None if flat else request.geometry.roof_pitch_degrees,
            storey_height_m=elevation.storey_height_m,
            floor_depth_m=elevation.floor_depth_m,
            elevation_area_m2=elevation.elevation_area_m2,
        )
        racking.append(
            {
                **result,
                "building_wind_direction": elevation.wind_on,
                "area_review_reference": elevation.area_review_reference,
            }
        )
    loads = {}
    for state in ("serviceability", "ultimate"):
        loads[state] = {
            "surface_loads": [
                asdict(item)
                for item in calculate_housing_loads(
                    classification, surfaces, state, request.geometry.roof_pitch_degrees
                )
            ],
            "roof_anchoring": asdict(
                calculate_roof_anchoring(
                    classification,
                    request.roof_type,
                    roof_area,
                    state,
                    all_cladding_resists_design_wind=request.all_cladding_resists_design_wind,
                )
            ),
        }
    return {
        "standard": "AS 4055",
        "edition": "2021",
        "classification": asdict(classification),
        "site_wind_classification": classification.site_wind_classification,
        "roof_surface_area_m2": roof_area,
        "surfaces": [asdict(s) for s in surfaces],
        "serviceability_anchoring_force_kn": loads["serviceability"]["roof_anchoring"][
            "anchoring_force_kn"
        ],
        "ultimate_anchoring_force_kn": loads["ultimate"]["roof_anchoring"]["anchoring_force_kn"],
        "loads": loads,
        "racking": racking,
        "site_review_reference": request.site_review_reference,
        "lookup_digest": source_lookup_digest(),
        "status": "preliminary_independent_review_required",
        "limitations": [
            "Simple rectangular flat or symmetric gable house without overhangs only.",
            "Site categories and elevation areas are reviewed inputs; all supported storeys "
            "must be provided in both directions.",
            "Racking pressures are ultimate demand. Anchoring already includes Table 4 dead load.",
            "Independent engineering review, individual opening zones and member/connection "
            "capacity design remain required.",
        ],
    }


def inline_schema(request):
    """Expand local Pydantic refs for the host's nested form renderer."""
    schema = request.model_json_schema()
    definitions = schema.pop("$defs", {})

    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            value = {
                **definitions[value["$ref"].split("/")[-1]],
                **{key: item for key, item in value.items() if key != "$ref"},
            }
        return {key: expand(item) for key, item in value.items()}

    return expand(schema)


AS4055_EXTENSIONS = tuple(
    CalculationDefinition(
        id=f"au.wind.as4055.{identifier}",
        name=name,
        description=description,
        discipline="structural",
        category="wind",
        jurisdiction="AU",
        version="1",
        standard=StandardReference(name="AS 4055", edition="2021", clauses=clauses, tables=tables),
        input_schema=inline_schema(request),
        output_schema={
            "type": "object",
            "required": ["status", *outputs],
            "properties": {"status": {"type": "string"}, **outputs},
        },
        executor=executor,
    )
    for identifier, name, description, request, executor, clauses, tables, outputs in (
        (
            "housing_assessment",
            "AS 4055 housing wind assessment",
            "One housing assessment with classification, zones, SLS/ULS surface and anchoring "
            "loads, and reviewed elevation racking demands.",
            AS4055HousingAssessmentRequest,
            housing_assessment,
            ("1.2", "2", "3", "4", "5"),
            ("Table 2.2", "Table 4", "Tables 5.2(A-M)"),
            {
                "site_wind_classification": {"type": "string"},
                "roof_surface_area_m2": {"type": "number", "unit": "m2"},
                "serviceability_anchoring_force_kn": {"type": "number", "unit": "kN"},
                "ultimate_anchoring_force_kn": {"type": "number", "unit": "kN"},
                "racking": {"type": "array", "items": {"type": "object"}},
                "loads": {"type": "object"},
                "classification": {"type": "object"},
            },
        ),
        (
            "pressure_zone_areas",
            "AS 4055 housing pressure zones",
            "Partition a simple rectangular flat or gable house into surface pressure zones.",
            AS4055ZoneAreasRequest,
            zone_areas,
            ("3.1",),
            (),
            {"surfaces": {"type": "array", "items": {"type": "object"}}},
        ),
        (
            "roof_anchoring",
            "AS 4055 roof-to-wall anchoring",
            "Table 4 net upward anchoring demand over the entire roof surface.",
            AS4055AnchoringRequest,
            roof_anchoring,
            ("4",),
            ("Table 4",),
            {
                "net_upward_pressure_kpa": {"type": "number", "unit": "kPa"},
                "anchoring_force_kn": {"type": "number", "unit": "kN"},
            },
        ),
        (
            "racking_pressure",
            "AS 4055 housing racking pressure and force",
            "Select Tables 5.2(A-M) with interpolation and explicit elevation area.",
            AS4055RackingPressureRequest,
            racking_pressure,
            ("5.2",),
            tuple(f"Table 5.2({letter})" for letter in "ABCDEFGHIJKLM"),
            {
                "lateral_pressure_kpa": {"type": "number", "unit": "kPa"},
                "racking_force_kn": {"type": "number", "unit": "kN"},
            },
        ),
    )
)
