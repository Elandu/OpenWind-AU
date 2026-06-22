"""AS/NZS 1170.2 site wind workflow through reviewed Vsit,b."""

from __future__ import annotations

from openwind_au.models import (
    DirectionMultiplierAssessment,
    ObstructionInventoryResult,
    RegionalWindSpeedAssessment,
    SiteAnalysisResult,
    SiteWindSpeedRow,
    TerrainCategoryEvidenceResult,
    WindDirection,
    WindRegionAssessment,
    WindVariableAssessment,
    WindVariableOverride,
    WindWorkflowRequest,
    WindWorkflowResult,
    WindWorkflowVariable,
)
from openwind_au.shielding import DIRECTION_AZIMUTHS
from openwind_au.wind_inputs import direction_multiplier_assessment, regional_wind_speed_assessment
from openwind_au.wind_region import assess_wind_region

DIRECTIONS: list[WindDirection] = [direction for direction, _azimuth in DIRECTION_AZIMUTHS]


def run_wind_workflow(
    *,
    request: WindWorkflowRequest,
    site_result: SiteAnalysisResult,
    obstruction_result: ObstructionInventoryResult,
    terrain_result: TerrainCategoryEvidenceResult,
    wind_region: WindRegionAssessment | None = None,
    regional_speed: RegionalWindSpeedAssessment | None = None,
    direction_multipliers: DirectionMultiplierAssessment | None = None,
) -> WindWorkflowResult:
    """Assemble reviewable AS/NZS 1170.2 site wind variables through Vsit,b."""

    overrides = override_lookup(request.workflow_overrides)
    variables: list[WindVariableAssessment] = []
    wind_region = wind_region or assess_wind_region(site_result.site)
    regional_speed = regional_speed or regional_wind_speed_assessment(
        wind_region,
        importance_level=request.importance_level,
        annual_exceedance_probability=request.annual_exceedance_probability,
    )
    direction_multipliers = direction_multipliers or direction_multiplier_assessment(wind_region)
    vr = vr_assessment(request, regional_speed, overrides)
    variables.append(vr)
    variables.extend(md_assessments(direction_multipliers, overrides))
    variables.extend(mzcat_assessments(terrain_result, overrides))
    variables.extend(ms_assessments(obstruction_result, overrides))
    variables.extend(mt_assessments(site_result, overrides))
    vsitb_rows = vsitb_directional_rows(variables)
    vsitb_rows = mark_governing_vsitb(vsitb_rows)
    variables.extend(vsitb_assessments(vsitb_rows, overrides))
    warnings = [
        (
            "Workflow values are calculated automatically and remain preliminary until "
            "engineering review."
        ),
        "Pressure calculations are not included.",
    ]
    warnings.extend(wind_region.warnings)
    warnings.extend(regional_speed.warnings)
    warnings.extend(direction_multipliers.warnings)
    return WindWorkflowResult(
        input=request,
        site=site_result.site,
        wind_region_assessment=wind_region,
        regional_wind_speed_assessment=regional_speed,
        direction_multiplier_assessment=direction_multipliers,
        assessment_status=request.assessment_status,
        engineer_notes=request.engineer_notes,
        overrides_applied=request.workflow_overrides,
        variables=variables,
        directional_vsitb=vsitb_rows,
        governing_direction=next(
            (row.direction for row in vsitb_rows if row.is_governing),
            None,
        ),
        governing_vsitb=next(
            (row.final_vsitb for row in vsitb_rows if row.is_governing),
            None,
        ),
        evidence_references=[
            "Wind region map",
            "Terrain and shielding map",
            "Terrain profiles",
            "Calculation details",
        ],
        warnings=warnings,
    )


def override_lookup(
    overrides: list[WindVariableOverride],
) -> dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride]:
    """Return the latest override keyed by variable and optional direction."""

    return {(override.variable, override.direction): override for override in overrides}


def apply_override(
    assessment: WindVariableAssessment,
    overrides: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride],
) -> WindVariableAssessment:
    override = overrides.get((assessment.variable, assessment.direction))
    if override is None:
        return assessment.model_copy(update={"calculated_value": assessment.final_value})
    return assessment.model_copy(
        update={
            "calculated_value": assessment.final_value,
            "final_value": override.override_value,
            "final_label": override.label or "Override value",
            "override_value": override.override_value,
            "override_reason": override.reason,
            "is_overridden": True,
        }
    )


def vr_assessment(
    request: WindWorkflowRequest,
    regional_speed: RegionalWindSpeedAssessment,
    overrides: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride],
) -> WindVariableAssessment:
    value = regional_speed.vr_ult
    warnings = list(regional_speed.warnings)
    if request.regional_wind_speed_mps is not None:
        warnings.append(
            "Legacy regional_wind_speed_mps input ignored; use workflow_overrides with a reason."
        )
    assessment = WindVariableAssessment(
        variable="VR",
        label="Regional wind speed, VR",
        unit="m/s",
        recommended_value=value,
        recommended_label=(
            f"VR,ult {value:.1f} m/s; VR,serv {regional_speed.vr_serv:.1f} m/s"
            if value is not None and regional_speed.vr_serv is not None
            else "VR manual input required"
        ),
        confidence="medium" if value is not None else "low",
        calculated_value=value,
        final_value=value,
        final_label="Calculated VR,ult lookup" if value is not None else None,
        warnings=warnings,
        evidence_link="#project-site-inputs",
        source_reference=regional_speed.selected_table,
        detail_label="Show source",
        formula_basis=(
            "Regional wind speed selected from assessed wind region and annual probability "
            "of exceedance."
        ),
        calculation_inputs=[
            f"Region: {regional_speed.wind_region}",
            f"Importance level / return period: {request.importance_level or 'user input'}",
            *regional_speed.lookup_values,
        ],
        detail_items=[
            f"Selected table: {regional_speed.selected_table}",
            f"Selected ARI: {regional_speed.ari_years} years",
            _format_lookup_detail("VR,ult", regional_speed.vr_ult, "m/s"),
            _format_lookup_detail("VR,serv", regional_speed.vr_serv, "m/s"),
            f"Interpolation: {regional_speed.interpolation or 'not required'}",
        ],
        calculation_result=(
            f"VR,ult = {value:.3f} m/s; VR,serv = {regional_speed.vr_serv:.3f} m/s"
            if value is not None and regional_speed.vr_serv is not None
            else "VR lookup incomplete; manual input required."
        ),
    )
    return apply_override(assessment, overrides)


def md_assessments(
    direction_multipliers: DirectionMultiplierAssessment,
    overrides: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride],
) -> list[WindVariableAssessment]:
    assessments = []
    for row in direction_multipliers.directions:
        direction = row.direction
        value = row.md
        assessment = WindVariableAssessment(
            variable="Md",
            label="Wind direction multiplier, Md",
            direction=direction,
            recommended_value=value,
            recommended_label=(
                f"Selected Md for {direction}"
                if value is not None
                else f"Md for {direction} required"
            ),
            confidence="medium" if value is not None else "low",
            calculated_value=value,
            final_value=value,
            final_label=f"Calculated Md lookup for {direction}" if value is not None else None,
            warnings=list(direction_multipliers.warnings),
            evidence_link="#wind-direction-md",
            source_reference=direction_multipliers.source_table,
            detail_label="Show source",
            formula_basis="Wind direction multiplier selected for the assessed wind direction.",
            calculation_inputs=[
                f"Selected region: {direction_multipliers.wind_region}",
                f"Direction: {direction}",
                _format_lookup_detail("Md", value, ""),
            ],
            detail_items=[
                f"Selected region: {direction_multipliers.wind_region}",
                f"Source table: {direction_multipliers.source_table}",
                f"Direction: {direction}",
                _format_lookup_detail("Lookup value: Md", value, ""),
            ],
            calculation_result=(
                f"Md = {value:.3f}"
                if value is not None
                else "Md lookup incomplete; manual input required."
            ),
        )
        assessments.append(apply_override(assessment, overrides))
    return assessments


def mzcat_assessments(
    terrain_result: TerrainCategoryEvidenceResult,
    overrides: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride],
) -> list[WindVariableAssessment]:
    assessments = []
    for item in terrain_result.mzcat_assessment:
        warnings = list(item.warnings)
        if item.recommended_mzcat is None:
            warnings.append("Mz,cat could not be calculated for this direction.")
        assessment = WindVariableAssessment(
            variable="Mzcat",
            label="Terrain height multiplier, Mz,cat",
            direction=item.direction,
            recommended_value=item.recommended_mzcat,
            recommended_label=(
                f"Recommended TC {item.recommended_terrain_category}; "
                f"Recommended Mz,cat {item.recommended_mzcat:.3f}"
                if item.recommended_mzcat is not None
                else "Recommended TC review required; Recommended Mz,cat review required"
            ),
            confidence=item.recommendation_confidence,
            calculated_value=item.recommended_mzcat,
            final_value=item.recommended_mzcat,
            final_label=(
                f"Calculated TC {item.recommended_terrain_category}"
                if item.recommended_mzcat is not None
                else None
            ),
            warnings=warnings,
            evidence_link="#terrain-category-mzcat",
            source_reference="Terrain category inputs and Mz,cat recommendation.",
            detail_label="Show details",
            formula_basis="Mz,cat selected from terrain category inputs and height.",
            calculation_inputs=[
                f"Built-up coverage: {item.built_up_area_percentage:.1f}%",
                f"Vegetation coverage: {item.vegetation_area_percentage:.1f}%",
                f"Obstruction density: {item.obstruction_density_per_km2:.1f}/km2",
                f"Fetch distance: {item.directional_fetch_distance_m:.1f} m",
                f"Confidence: {item.confidence}",
                f"Suggested terrain category range: {item.suggested_terrain_category_range}",
                f"Assessment height: {item.assessment_height_m:.3f} m",
                (
                    "Interpolation details: "
                    f"{item.lower_category_bound}-{item.upper_category_bound} at "
                    f"{item.assessment_height_m:.3f} m gives indicative Mz,cat range "
                    f"{item.lower_indicative_mzcat:.3f}-{item.upper_indicative_mzcat:.3f}"
                ),
            ],
            detail_items=[
                f"Built-up coverage: {item.built_up_area_percentage:.1f}%",
                f"Vegetation coverage: {item.vegetation_area_percentage:.1f}%",
                f"Obstruction density: {item.obstruction_density_per_km2:.1f}/km2",
                f"Fetch distance: {item.directional_fetch_distance_m:.1f} m",
                f"Confidence: {item.confidence}",
                (
                    "Interpolation details: "
                    f"{item.lower_category_bound}-{item.upper_category_bound} at "
                    f"{item.assessment_height_m:.3f} m gives indicative Mz,cat range "
                    f"{item.lower_indicative_mzcat:.3f}-{item.upper_indicative_mzcat:.3f}"
                ),
                *item.recommendation_reasoning,
                *item.reasoning,
            ],
            calculation_result=(
                f"Mz,cat = {item.recommended_mzcat:.3f}"
                if item.recommended_mzcat is not None
                else "Mz,cat recommendation requires review."
            ),
        )
        assessments.append(apply_override(assessment, overrides))
    return assessments


def ms_assessments(
    obstruction_result: ObstructionInventoryResult,
    overrides: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride],
) -> list[WindVariableAssessment]:
    assessments = []
    for sector in obstruction_result.shielding_sectors:
        assessment = WindVariableAssessment(
            variable="Ms",
            label="Shielding multiplier, Ms",
            direction=sector.direction,
            recommended_value=sector.indicative_ms,
            recommended_label=f"Recommended Ms {sector.indicative_ms:.3f}",
            confidence=_confidence(sector.overall_confidence),
            calculated_value=sector.indicative_ms,
            final_value=sector.indicative_ms,
            final_label="Calculated Ms",
            warnings=["Indicative Ms is preliminary.", *sector.warnings],
            evidence_link="#shielding-ms",
            source_reference="Shielding sector diagnostics from obstruction inventory.",
            detail_label="Show details",
            formula_basis="Shielding multiplier inferred from obstruction sector inputs.",
            calculation_inputs=[
                f"Sector: {sector.direction}",
                f"Radius: {sector.sector_radius_m:.1f} m",
                f"ns: {sector.ns}",
                f"hs: {_format_value(sector.average_hs_m)}",
                f"bs: {_format_value(sector.average_bs_m)}",
                f"ls: {_format_value(sector.ls_m)}",
                f"s: {_format_value(sector.s)}",
                f"Confidence: {sector.overall_confidence}",
                f"Contributing obstructions: {_format_ids(sector.included_obstruction_ids)}",
                (
                    "Rejected obstructions: "
                    f"{_format_rejected_obstructions(sector.rejected_obstructions)}"
                ),
            ],
            detail_items=[
                f"Sector: {sector.direction}",
                f"Radius: {sector.sector_radius_m:.1f} m",
                f"Shielding sector: {sector.sector_start_deg:.1f}-{sector.sector_end_deg:.1f} deg",
                f"Total obstructions in sector: {sector.total_obstructions_in_sector}",
                f"Contributing obstructions: {_format_ids(sector.included_obstruction_ids)}",
                (
                    "Rejected obstructions: "
                    f"{_format_rejected_obstructions(sector.rejected_obstructions)}"
                ),
                f"ns: {sector.ns}",
                f"hs: {_format_value(sector.average_hs_m)}",
                f"bs: {_format_value(sector.average_bs_m)}",
                f"ls: {_format_value(sector.ls_m)}",
                f"s: {_format_value(sector.s)}",
                f"Confidence: {sector.overall_confidence}",
                f"Rejection reasons: {sector.rejection_reason_counts}",
            ],
            calculation_result=f"Ms = {sector.indicative_ms:.3f}",
        )
        assessments.append(apply_override(assessment, overrides))
    return assessments


def mt_assessments(
    site_result: SiteAnalysisResult,
    overrides: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride],
) -> list[WindVariableAssessment]:
    assessments = []
    for feature in site_result.features:
        no_significant_feature = feature.feature_type == "no significant feature"
        warnings = []
        if not no_significant_feature:
            warnings.append("Candidate topographic feature requires engineer-selected Mt.")
        value = 1.0
        assessment = WindVariableAssessment(
            variable="Mt",
            label="Topographic multiplier, Mt",
            direction=feature.direction,
            recommended_value=value,
            recommended_label=f"Recommended Mt {value:.3f}",
            confidence="medium" if no_significant_feature else "low",
            calculated_value=value,
            final_value=value,
            final_label="Calculated Mt",
            warnings=warnings,
            evidence_link="#topographic-mt",
            source_reference="Topographic screening details for engineer-selected Mt.",
            detail_label="Show details",
            formula_basis="Topographic multiplier reviewed from topographic screening details.",
            calculation_inputs=[
                f"Feature: {feature.feature_type}",
                f"H: {feature.h_m:.3f} m",
                f"Lu: {feature.lu_m:.3f} m",
                f"x: {feature.x_m:.3f} m",
                f"Average upwind slope: {feature.average_upwind_slope:.3f}",
                f"Confidence: {feature.confidence}",
            ],
            detail_items=[
                f"Feature type: {feature.feature_type}",
                f"H: {feature.h_m:.3f} m",
                f"Lu: {feature.lu_m:.3f} m",
                f"x: {feature.x_m:.3f} m",
                f"Slope: {feature.average_upwind_slope:.3f}",
                f"Confidence: {feature.confidence}",
                *feature.notes,
                *warnings,
            ],
            calculation_result=f"Mt = {value:.3f}",
        )
        assessments.append(apply_override(assessment, overrides))
    return assessments


def vsitb_directional_rows(variables: list[WindVariableAssessment]) -> list[SiteWindSpeedRow]:
    rows = []
    vr = variable_for(variables, "VR", None)
    for direction in DIRECTIONS:
        md = variable_for(variables, "Md", direction)
        mzcat = variable_for(variables, "Mzcat", direction)
        ms = variable_for(variables, "Ms", direction)
        mt = variable_for(variables, "Mt", direction)
        input_variables = [vr, md, mzcat, ms, mt]
        values = [item.final_value for item in input_variables if item is not None]
        warnings = []
        complete = len(values) == 5 and all(value is not None for value in values)
        if not complete:
            warnings.append(
                "Vsit,b could not be calculated because one or more inputs are missing."
            )
        final_vsitb = _product(values) if complete else None
        rows.append(
            SiteWindSpeedRow(
                direction=direction,
                vr=vr.final_value if vr else None,
                md=md.final_value if md else None,
                mzcat=mzcat.final_value if mzcat else None,
                ms=ms.final_value if ms else None,
                mt=mt.final_value if mt else None,
                recommended_vsitb=final_vsitb,
                final_vsitb=final_vsitb,
                status="calculated" if complete else "blocked",
                warnings=warnings,
            )
        )
    return rows


def vsitb_assessments(
    rows: list[SiteWindSpeedRow],
    overrides: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride],
) -> list[WindVariableAssessment]:
    assessments = []
    for row in rows:
        warnings = list(row.warnings)
        override = overrides.get(("Vsitb", row.direction))
        final_value = row.final_vsitb
        final_label = "Calculated Vsit,b" if final_value is not None else None
        override_value = None
        override_reason = None
        is_overridden = False
        if row.status == "calculated" and override is not None:
            final_value = override.override_value
            final_label = override.label or "Override value"
            override_value = override.override_value
            override_reason = override.reason
            is_overridden = True
        elif override is not None:
            warnings.append("Vsit,b override ignored because calculated inputs are incomplete.")
        assessments.append(
            WindVariableAssessment(
                variable="Vsitb",
                label="Site wind speed, Vsit,b",
                direction=row.direction,
                unit="m/s",
                recommended_value=row.recommended_vsitb,
                recommended_label=(
                    "Calculated Vsit,b"
                    if row.recommended_vsitb is not None
                    else "Vsit,b unavailable"
                ),
                confidence="medium" if row.status == "calculated" else "low",
                calculated_value=row.final_vsitb,
                final_value=final_value,
                final_label=final_label,
                override_value=override_value,
                override_reason=override_reason,
                is_overridden=is_overridden,
                warnings=warnings,
                evidence_link="#vsitb-summary",
                source_reference="Reviewed site wind speed variable product.",
                detail_label="Show calculation",
                formula_basis="Vsit,b = VR x Md x Mz,cat x Ms x Mt",
                calculation_inputs=[
                    f"VR: {_format_value(row.vr)}",
                    f"Md: {_format_value(row.md)}",
                    f"Mz,cat: {_format_value(row.mzcat)}",
                    f"Ms: {_format_value(row.ms)}",
                    f"Mt: {_format_value(row.mt)}",
                ],
                calculation_result=(
                    f"Vsit,b = {row.recommended_vsitb:.3f} m/s"
                    if row.recommended_vsitb is not None
                    else "Vsit,b unavailable because one or more inputs are missing."
                ),
            )
        )
    return assessments


def mark_governing_vsitb(rows: list[SiteWindSpeedRow]) -> list[SiteWindSpeedRow]:
    calculated = [row for row in rows if row.final_vsitb is not None]
    if not calculated:
        return rows
    governing = max(calculated, key=lambda row: row.final_vsitb or 0)
    return [
        row.model_copy(update={"is_governing": row.direction == governing.direction})
        for row in rows
    ]


def variable_for(
    variables: list[WindVariableAssessment],
    variable: WindWorkflowVariable,
    direction: WindDirection | None,
) -> WindVariableAssessment | None:
    return next(
        (item for item in variables if item.variable == variable and item.direction == direction),
        None,
    )


def _confidence(value: str) -> str:
    return value if value in {"high", "medium", "low"} else "low"


def _product(values: list[float | None]) -> float:
    result = 1.0
    for value in values:
        result *= float(value)
    return round(result, 3)


def _format_ids(values: list[str]) -> str:
    if not values:
        return "none"
    shown = values[:10]
    suffix = f" (+{len(values) - len(shown)} more)" if len(values) > len(shown) else ""
    return ", ".join(shown) + suffix


def _format_rejected_obstructions(values: list[dict]) -> str:
    if not values:
        return "none"
    labels = []
    for item in values[:10]:
        obstruction_id = item.get("obstruction_id", "unknown")
        reason = item.get("reason") or item.get("rejection_reason") or "rejected"
        labels.append(f"{obstruction_id} ({reason})")
    suffix = f" (+{len(values) - len(labels)} more)" if len(values) > len(labels) else ""
    return ", ".join(labels) + suffix


def _format_value(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "not available"


def _format_lookup_detail(label: str, value: float | None, unit: str) -> str:
    if value is None:
        return f"{label}: manual input required"
    suffix = f" {unit}" if unit else ""
    return f"{label}: {value:.3f}{suffix}"
