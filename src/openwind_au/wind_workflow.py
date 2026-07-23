"""AS/NZS 1170.2 site wind workflow through reviewed Vsit,b."""

from __future__ import annotations

from openwind_au.models import (
    DirectionMultiplierAssessment,
    DirectionMultiplierRow,
    ObstructionInventoryResult,
    RegionalWindSpeedAssessment,
    SiteAnalysisResult,
    SiteWindSpeedRow,
    TerrainCategoryEvidenceResult,
    WindClassMultiplierOverride,
    WindDirection,
    WindRegionAssessment,
    WindVariableAssessment,
    WindVariableOverride,
    WindWorkflowRequest,
    WindWorkflowResult,
    WindWorkflowVariable,
)
from openwind_au.mzcat import (
    indicative_mzcat,
    load_mzcat_table,
    mzcat_lookup_issues,
    mzcat_lookup_warnings,
    mzcat_source_reference,
)
from openwind_au.result_integrity import seal_workflow_result
from openwind_au.shielding import DIRECTION_AZIMUTHS
from openwind_au.standard_calculations import (
    MC_STANDARD_REFERENCE,
    MS_METADATA_WARNING,
    climate_change_multiplier,
    shielding_reduction_height_limit_m,
    site_wind_speed,
)
from openwind_au.topographic_multiplier import calculate_topographic_multiplier
from openwind_au.wind_inputs import direction_multiplier_assessment, regional_wind_speed_assessment
from openwind_au.wind_region import assess_wind_region

DIRECTIONS: list[WindDirection] = [direction for direction, _azimuth in DIRECTION_AZIMUTHS]
MIXED_TERRAIN_REVIEW_WARNING = (
    "Clause 4.2.3 mixed-terrain weighted averaging is not automated; Mz,cat assumes "
    "one reviewed or recommended category at the common reference height."
)
TOPOGRAPHIC_SECTION_REVIEW_WARNING = (
    "Clause 4.4.2 most-adverse topographic cross-section within +/-22.5 degrees and "
    "escarpment downwind-slope eligibility are not automated; Mt requires engineer review."
)


def run_wind_workflow(
    *,
    request: WindWorkflowRequest,
    site_result: SiteAnalysisResult,
    obstruction_result: ObstructionInventoryResult,
    terrain_result: TerrainCategoryEvidenceResult,
    wind_region: WindRegionAssessment | None = None,
    regional_speed: RegionalWindSpeedAssessment | None = None,
    direction_multipliers: DirectionMultiplierAssessment | None = None,
    mzcat_lookup_data: dict | None = None,
) -> WindWorkflowResult:
    """Assemble reviewable AS/NZS 1170.2 site wind variables through Vsit,b."""

    overrides = override_lookup(request.workflow_overrides)
    class_overrides = class_override_lookup(request.class_multiplier_overrides)
    reject_mandatory_ms_overrides(request)
    variables: list[WindVariableAssessment] = []
    mzcat_lookup = mzcat_lookup_data if mzcat_lookup_data is not None else load_mzcat_table()
    mzcat_issues = mzcat_lookup_issues(mzcat_lookup, require_reviewed=False)
    if mzcat_issues:
        raise ValueError(f"Invalid Table 4.1 lookup data: {'; '.join(mzcat_issues)}")
    wind_region = wind_region or assess_wind_region(site_result.site)
    if wind_region.wind_region == "A":
        raise ValueError(
            "Wind region A is ambiguous for the site wind workflow; confirm whether the "
            "site is in A0, A1, A2, A3, A4, or A5."
        )
    if wind_region.wind_region == "B":
        raise ValueError(
            "Wind region B is ambiguous for the site wind workflow; confirm whether the "
            "site is in B1 or B2."
        )
    reject_mandatory_a0_mzcat_overrides(request, wind_region)
    regional_speed = regional_speed or regional_wind_speed_assessment(
        wind_region,
        importance_level=request.importance_level,
        annual_exceedance_probability=request.annual_exceedance_probability,
    )
    direction_multipliers = direction_multipliers or direction_multiplier_assessment(wind_region)
    direction_multipliers = effective_direction_multiplier_assessment(
        request,
        direction_multipliers,
    )
    vr = vr_assessment(request, regional_speed, overrides)
    variables.append(vr)
    variables.append(mc_assessment(wind_region, overrides))
    variables.extend(md_assessments(request, direction_multipliers, overrides))
    variables.extend(
        mzcat_assessments(
            request,
            terrain_result,
            wind_region,
            overrides,
            class_overrides,
            mzcat_lookup,
        )
    )
    variables.extend(ms_assessments(obstruction_result, overrides, class_overrides))
    variables.extend(
        mt_assessments(
            request,
            site_result,
            wind_region,
            overrides,
            class_overrides,
        )
    )
    vsitb_rows = vsitb_directional_rows(variables)
    vsitb_variables = vsitb_assessments(vsitb_rows, overrides)
    vsitb_rows = apply_vsitb_assessments_to_rows(vsitb_rows, vsitb_variables)
    vsitb_rows = mark_governing_vsitb(vsitb_rows)
    variables.extend(vsitb_variables)
    warnings = [
        (
            "Workflow values are calculated automatically and remain preliminary until "
            "engineering review."
        ),
        "Pressure calculations are not included.",
        MIXED_TERRAIN_REVIEW_WARNING,
        TOPOGRAPHIC_SECTION_REVIEW_WARNING,
    ]
    warnings.extend(wind_region.warnings)
    warnings.extend(regional_speed.warnings)
    warnings.extend(direction_multipliers.warnings)
    warnings.extend(mzcat_lookup_warnings(mzcat_lookup))
    if (
        obstruction_result.ms_lookup_provenance is not None
        and not obstruction_result.ms_lookup_provenance.independent_review_recorded
    ):
        warnings.append(MS_METADATA_WARNING)
    result = WindWorkflowResult(
        input=request,
        site=site_result.site,
        wind_region_assessment=wind_region,
        regional_wind_speed_assessment=regional_speed,
        direction_multiplier_assessment=direction_multipliers,
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
    return seal_workflow_result(result)


def override_lookup(
    overrides: list[WindVariableOverride],
) -> dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride]:
    """Return the latest override keyed by variable and optional direction."""

    return {(override.variable, override.direction): override for override in overrides}


def class_override_lookup(
    overrides: list[WindClassMultiplierOverride],
) -> dict[WindDirection, WindClassMultiplierOverride]:
    """Return the latest class override keyed by direction."""

    return {override.direction: override for override in overrides}


def reject_mandatory_a0_mzcat_overrides(
    request: WindWorkflowRequest,
    wind_region: WindRegionAssessment,
) -> None:
    """Reject numeric overrides of the terrain-independent Region A0 rule."""

    if wind_region.wind_region != "A0":
        return
    has_workflow_override = any(item.variable == "Mzcat" for item in request.workflow_overrides)
    has_class_override = any(item.mzcat is not None for item in request.class_multiplier_overrides)
    if has_workflow_override or has_class_override:
        raise ValueError(
            "Region A0 Table 4.1 Mz,cat is terrain-independent and mandatory; numeric "
            "Mz,cat overrides are not permitted."
        )


def reject_mandatory_ms_overrides(request: WindWorkflowRequest) -> None:
    """Reject override paths that could bypass the mandatory high-rise Ms value."""

    height_limit_m = shielding_reduction_height_limit_m()
    if request.reference_height_m <= height_limit_m:
        return
    has_workflow_override = any(item.variable == "Ms" for item in request.workflow_overrides)
    has_class_override = any(item.ms is not None for item in request.class_multiplier_overrides)
    if has_workflow_override or has_class_override:
        raise ValueError(
            "Clause 4.3.1 requires Ms = 1.0 when average roof height h exceeds "
            f"{height_limit_m:g} m; numeric Ms overrides are not permitted."
        )


def apply_override(
    assessment: WindVariableAssessment,
    overrides: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride],
) -> WindVariableAssessment:
    override = overrides.get((assessment.variable, assessment.direction))
    if override is None:
        return assessment
    return assessment.model_copy(
        update={
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
    request: WindWorkflowRequest,
    direction_multipliers: DirectionMultiplierAssessment,
    overrides: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride],
) -> list[WindVariableAssessment]:
    mandatory_one_reason = mandatory_md_one_reason(
        request,
        direction_multipliers.wind_region,
    )
    if mandatory_one_reason and any(key[0] == "Md" for key in overrides):
        raise ValueError(
            "Md overrides are not permitted because the selected Clause 3.3 design case "
            "requires Md = 1.0."
        )
    assessments = []
    for row in direction_multipliers.directions:
        direction = row.direction
        value = 1.0 if mandatory_one_reason else row.md
        warnings = list(direction_multipliers.warnings)
        if mandatory_one_reason and mandatory_one_reason not in warnings:
            warnings.append(mandatory_one_reason)
        assessment = WindVariableAssessment(
            variable="Md",
            label="Wind direction multiplier, Md",
            direction=direction,
            recommended_value=value,
            recommended_label=(
                "Clause 3.3 mandatory Md"
                if mandatory_one_reason
                else f"Selected Md for {direction}"
                if value is not None
                else f"Md for {direction} required"
            ),
            confidence="medium" if value is not None else "low",
            calculated_value=value,
            final_value=value,
            final_label=(
                "Clause 3.3 mandatory Md = 1.0"
                if mandatory_one_reason
                else f"Calculated Md lookup for {direction}"
                if value is not None
                else None
            ),
            warnings=warnings,
            evidence_link="#wind-direction-md",
            source_reference=(
                "AS/NZS 1170.2:2021 Clause 3.3"
                if mandatory_one_reason
                else direction_multipliers.source_table
            ),
            detail_label="Show source",
            formula_basis="Wind direction multiplier selected for the assessed wind direction.",
            calculation_inputs=[
                f"Selected region: {direction_multipliers.wind_region}",
                f"Direction: {direction}",
                _format_lookup_detail("Md", value, ""),
            ],
            detail_items=[
                f"Selected region: {direction_multipliers.wind_region}",
                (
                    "Source: AS/NZS 1170.2:2021 Clause 3.3"
                    if mandatory_one_reason
                    else f"Source table: {direction_multipliers.source_table}"
                ),
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


def mandatory_md_one_reason(
    request: WindWorkflowRequest,
    wind_region: str,
) -> str | None:
    """Return the Clause 3.3 reason that makes Md exactly 1.0, if applicable."""

    design_case = request.wind_direction_multiplier_case
    if (
        design_case == "circular_or_polygonal_chimney_tank_or_pole"
        or request.structure_class == "monopole"
    ):
        return "Clause 3.3 requires Md = 1.0 for circular or polygonal chimneys, tanks, and poles."
    if design_case == "cladding_or_immediate_support" and wind_region in {"B2", "C", "D"}:
        return (
            "Clause 3.3 requires Md = 1.0 for cladding and its immediate supporting "
            f"structure in wind region {wind_region}."
        )
    return None


def effective_direction_multiplier_assessment(
    request: WindWorkflowRequest,
    assessment: DirectionMultiplierAssessment,
) -> DirectionMultiplierAssessment:
    """Return the effective Md source and values for the selected design case."""

    reason = mandatory_md_one_reason(request, assessment.wind_region)
    if reason is None:
        return assessment
    directions = [
        DirectionMultiplierRow(direction=row.direction, md=1.0, is_governing=True)
        for row in assessment.directions
    ]
    return assessment.model_copy(
        update={
            "source_table": "AS/NZS 1170.2:2021 Clause 3.3",
            "directions": directions,
            "highest_md": 1.0,
            "governing_directions": [row.direction for row in directions],
            "lookup_values": [
                f"Selected wind region: {assessment.wind_region}",
                f"Selected design case: {request.wind_direction_multiplier_case}",
                *[f"{row.direction}: Md 1.00" for row in directions],
            ],
            "warnings": [reason],
        }
    )


def mc_assessment(
    wind_region: WindRegionAssessment,
    overrides: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride],
) -> WindVariableAssessment:
    """Build the non-directional Table 3.3 climate-change multiplier assessment."""

    value = climate_change_multiplier(wind_region.wind_region)
    warnings: list[str] = []
    assessment = WindVariableAssessment(
        variable="Mc",
        label="Climate change multiplier, Mc",
        recommended_value=value,
        recommended_label=f"Table 3.3 Mc for region {wind_region.wind_region}",
        confidence=wind_region.confidence,
        calculated_value=value,
        final_value=value,
        final_label="Calculated Mc lookup",
        warnings=warnings,
        evidence_link="#project-site-inputs",
        source_reference=MC_STANDARD_REFERENCE,
        detail_label="Show source",
        formula_basis="Climate-change multiplier selected for the assessed wind region.",
        calculation_inputs=[
            f"Assessed wind region: {wind_region.wind_region}",
            f"Table 3.3 Mc: {value:.3f}",
        ],
        detail_items=[
            f"Source: {MC_STANDARD_REFERENCE}",
            f"Assessed wind region: {wind_region.wind_region}",
            *warnings,
        ],
        calculation_result=f"Mc = {value:.3f}",
    )
    return apply_override(assessment, overrides)


def mzcat_assessments(
    request: WindWorkflowRequest,
    terrain_result: TerrainCategoryEvidenceResult,
    wind_region: WindRegionAssessment,
    overrides: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride],
    class_overrides: dict[WindDirection, WindClassMultiplierOverride],
    lookup_data: dict | None = None,
) -> list[WindVariableAssessment]:
    lookup = lookup_data if lookup_data is not None else load_mzcat_table()
    assessments = []
    for item in terrain_result.mzcat_assessment:
        class_override = class_overrides.get(item.direction)
        mandatory_a0 = wind_region.wind_region == "A0"
        if mandatory_a0 and (
            overrides.get(("Mzcat", item.direction)) is not None
            or (class_override is not None and class_override.mzcat is not None)
        ):
            raise ValueError(
                "Region A0 Table 4.1 Mz,cat is terrain-independent and mandatory; numeric "
                "Mz,cat overrides are not permitted."
            )
        warnings = list(item.warnings)
        calculated_value = (
            indicative_mzcat(
                item.recommended_terrain_category,
                request.reference_height_m,
                wind_region=wind_region.wind_region,
                lookup_data=lookup,
            )
            if item.recommended_terrain_category
            else None
        )
        value = calculated_value
        final_label = (
            f"Calculated TC {item.recommended_terrain_category}"
            if item.recommended_mzcat is not None
            else None
        )
        class_inputs: list[str] = []
        class_details: list[str] = []
        source_reference = mzcat_source_reference(lookup)
        confidence = item.recommendation_confidence
        if class_override and class_override.terrain_category:
            value = class_override.mzcat or indicative_mzcat(
                class_override.terrain_category,
                request.reference_height_m,
                wind_region=wind_region.wind_region,
                lookup_data=lookup,
            )
            final_label = f"Reviewed TC {class_override.terrain_category}"
            confidence = "high" if class_override.mzcat else "medium"
            source_reference = class_override.source_reference or source_reference
            class_inputs = [
                f"Reviewed terrain category: {class_override.terrain_category}",
                f"Review reason: {class_override.reason}",
            ]
            if class_override.mzcat is not None:
                class_inputs.append(f"Reviewed Mz,cat: {class_override.mzcat:.3f}")
            class_details = [
                "Reviewed terrain category class override applied.",
                *class_inputs,
            ]
            warnings.append("Mz,cat uses reviewed class override.")
        if value is None:
            warnings.append("Mz,cat could not be calculated for this direction.")
        assessment = WindVariableAssessment(
            variable="Mzcat",
            label="Terrain height multiplier, Mz,cat",
            direction=item.direction,
            recommended_value=value,
            recommended_label=(
                f"Reviewed TC {class_override.terrain_category}; Mz,cat {value:.3f}"
                if class_override and class_override.terrain_category and value is not None
                else (
                    f"Recommended TC {item.recommended_terrain_category}; "
                    f"Recommended Mz,cat {value:.3f}"
                )
                if value is not None
                else "Recommended TC review required; Recommended Mz,cat review required"
            ),
            confidence=confidence,
            calculated_value=calculated_value,
            final_value=value,
            final_label=final_label,
            warnings=warnings,
            evidence_link="#terrain-category-mzcat",
            source_reference=source_reference,
            detail_label="Show details",
            formula_basis="Mz,cat selected from terrain category inputs and height.",
            calculation_inputs=[
                *class_inputs,
                f"Built-up coverage: {item.built_up_area_percentage:.1f}%",
                f"Vegetation coverage: {item.vegetation_area_percentage:.1f}%",
                f"Obstruction density: {item.obstruction_density_per_km2:.1f}/km2",
                f"Fetch distance: {item.directional_fetch_distance_m:.1f} m",
                f"Confidence: {item.confidence}",
                f"Suggested terrain category range: {item.suggested_terrain_category_range}",
                f"Assessment height: {item.assessment_height_m:.3f} m",
                f"Wind region: {wind_region.wind_region}",
                (
                    "Interpolation details: "
                    f"{item.lower_category_bound}-{item.upper_category_bound} at "
                    f"{item.assessment_height_m:.3f} m gives indicative Mz,cat range "
                    f"{item.lower_indicative_mzcat:.3f}-{item.upper_indicative_mzcat:.3f}"
                ),
            ],
            detail_items=[
                *class_details,
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
                f"Mz,cat = {value:.3f}"
                if value is not None
                else "Mz,cat recommendation requires review."
            ),
        )
        assessments.append(apply_override(assessment, overrides))
    return assessments


def ms_assessments(
    obstruction_result: ObstructionInventoryResult,
    overrides: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride],
    class_overrides: dict[WindDirection, WindClassMultiplierOverride],
) -> list[WindVariableAssessment]:
    assessments = []
    height_limit_m = shielding_reduction_height_limit_m()
    for sector in obstruction_result.shielding_sectors:
        class_override = class_overrides.get(sector.direction)
        mandatory_ms = sector.subject_height_m > height_limit_m
        if mandatory_ms and (
            overrides.get(("Ms", sector.direction)) is not None
            or (class_override is not None and class_override.ms is not None)
        ):
            raise ValueError(
                "Clause 4.3.1 requires Ms = 1.0 when average roof height h exceeds "
                f"{height_limit_m:g} m; numeric Ms overrides are not permitted."
            )
        calculated_value = sector.indicative_ms
        if mandatory_ms:
            calculated_value = 1.0
        value = calculated_value
        confidence = _confidence(sector.overall_confidence)
        final_label = "Calculated Ms"
        source_reference = (
            obstruction_result.ms_lookup_provenance.source_reference
            if obstruction_result.ms_lookup_provenance is not None
            else "Shielding lookup provenance unavailable."
        )
        class_inputs: list[str] = []
        class_details: list[str] = []
        warnings = [
            "Indicative Ms is preliminary.",
            *sector.warnings,
        ]
        if class_override and class_override.shielding_class:
            source_reference = class_override.source_reference or source_reference
            class_inputs = [
                f"Reviewed shielding class: {class_override.shielding_class}",
                f"Review reason: {class_override.reason}",
            ]
            if class_override.ms is not None:
                value = class_override.ms
                confidence = "high"
                final_label = f"Reviewed shielding class {class_override.shielding_class}"
                class_inputs.append(f"Reviewed Ms: {class_override.ms:.3f}")
                class_details = ["Reviewed numeric Ms override applied.", *class_inputs]
                warnings.append("Ms uses an explicit reviewed numeric override.")
            else:
                class_details = ["Reviewed shielding class recorded for provenance.", *class_inputs]
                warnings.append(
                    "Shielding class recorded without a numeric Ms; calculated Ms retained."
                )
        assessment = WindVariableAssessment(
            variable="Ms",
            label="Shielding multiplier, Ms",
            direction=sector.direction,
            recommended_value=value,
            recommended_label=(
                f"Reviewed {class_override.shielding_class}; Ms {value:.3f}"
                if class_override
                and class_override.shielding_class
                and class_override.ms is not None
                else (
                    f"Calculated Ms {value:.3f}; reviewed class "
                    f"{class_override.shielding_class} recorded"
                )
                if class_override and class_override.shielding_class
                else f"Recommended Ms {sector.indicative_ms:.3f}"
            ),
            confidence=confidence,
            calculated_value=calculated_value,
            final_value=value,
            final_label=final_label,
            warnings=warnings,
            evidence_link="#shielding-ms",
            source_reference=source_reference,
            detail_label="Show details",
            formula_basis="Shielding multiplier inferred from obstruction sector inputs.",
            calculation_inputs=[
                *class_inputs,
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
                *class_details,
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
            calculation_result=f"Ms = {value:.3f}",
        )
        assessments.append(apply_override(assessment, overrides))
    return assessments


def mt_assessments(
    request: WindWorkflowRequest,
    site_result: SiteAnalysisResult,
    wind_region: WindRegionAssessment,
    overrides: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableOverride],
    class_overrides: dict[WindDirection, WindClassMultiplierOverride],
) -> list[WindVariableAssessment]:
    assessments = []
    for feature in site_result.features:
        class_override = class_overrides.get(feature.direction)
        no_significant_feature = feature.feature_type == "no significant feature"
        unresolved_geometry = (
            feature.feature_type in {"hill", "ridge", "escarpment"}
            and not feature.mt_geometry_resolved
        )
        reference_height_m = request.reference_height_m
        calculation = calculate_topographic_multiplier(
            feature_type=feature.feature_type,
            h_m=feature.h_m,
            lu_m=feature.lu_m,
            x_m=feature.x_m,
            z_m=reference_height_m,
            average_roof_height_m=reference_height_m,
            wind_region=wind_region.wind_region,
            site_elevation_m=site_result.site.ground_elevation_m,
        )
        warnings = list(calculation.warnings)
        if unresolved_geometry:
            warnings.append(
                "Mt is unavailable because the upwind half-height point defining Lu "
                "was not resolved by the DEM profile."
            )
        elif not no_significant_feature:
            warnings.append(
                "Mt is calculated from public DEM geometry and requires engineering review."
            )
        calculated_value = None if unresolved_geometry else calculation.mt
        value = calculated_value
        confidence = "medium" if no_significant_feature else "low"
        final_label = None if unresolved_geometry else "Calculated Mt from terrain profile"
        source_reference = "AS/NZS 1170.2:2021 Clause 4.4 and sampled DEM terrain profile."
        class_inputs: list[str] = []
        class_details: list[str] = []
        if class_override and class_override.topographic_class:
            source_reference = class_override.source_reference or source_reference
            class_inputs = [
                f"Reviewed topographic class: {class_override.topographic_class}",
                f"Review reason: {class_override.reason}",
            ]
            if class_override.mt is not None:
                value = class_override.mt
                confidence = "high"
                final_label = f"Reviewed topographic class {class_override.topographic_class}"
                class_inputs.append(f"Reviewed Mt: {class_override.mt:.3f}")
                class_details = ["Reviewed numeric Mt override applied.", *class_inputs]
                warnings.append("Mt uses an explicit reviewed numeric override.")
            else:
                class_details = [
                    "Reviewed topographic class recorded for provenance.",
                    *class_inputs,
                ]
                warnings.append(
                    "Topographic class recorded without a numeric Mt; Clause 4.4 value retained."
                )
        assessment = WindVariableAssessment(
            variable="Mt",
            label="Topographic multiplier, Mt",
            direction=feature.direction,
            recommended_value=value,
            recommended_label=(
                f"Reviewed {class_override.topographic_class}; Mt {value:.3f}"
                if class_override
                and class_override.topographic_class
                and class_override.mt is not None
                and value is not None
                else (
                    f"Calculated Mt {value:.3f}; reviewed class "
                    f"{class_override.topographic_class} recorded"
                )
                if class_override and class_override.topographic_class and value is not None
                else (
                    f"Calculated Mt {value:.3f}"
                    if value is not None
                    else "Mt unavailable; resolve Clause 4.4 upwind geometry"
                )
            ),
            confidence=confidence,
            calculated_value=calculated_value,
            final_value=value,
            final_label=final_label,
            warnings=warnings,
            evidence_link="#topographic-mt",
            source_reference=source_reference,
            detail_label="Show details",
            formula_basis=(
                "Clause 4.4 calculation blocked because the DEM profile does not resolve Lu."
                if unresolved_geometry and not (class_override and class_override.mt is not None)
                else calculation.equation
            ),
            calculation_inputs=[
                *class_inputs,
                f"Wind region: {wind_region.wind_region}",
                f"Site elevation E: {site_result.site.ground_elevation_m:.3f} m",
                f"Reference height z: {reference_height_m:.3f} m",
                f"Feature: {feature.feature_type}",
                f"Clause 4.4 geometry resolved: {feature.mt_geometry_resolved}",
                f"H: {feature.h_m:.3f} m",
                f"Lu: {feature.lu_m:.3f} m",
                f"x: {feature.x_m:.3f} m",
                f"H/(2Lu): {calculation.slope_parameter:.3f}",
                f"L1: {_format_value(None if unresolved_geometry else calculation.l1_m)}",
                f"L2: {_format_value(None if unresolved_geometry else calculation.l2_m)}",
                ("Mh: not calculated" if unresolved_geometry else f"Mh: {calculation.mh:.3f}"),
                f"Mlee: {calculation.mlee:.3f}",
                f"Elevation factor: {calculation.elevation_factor:.3f}",
                f"Confidence: {feature.confidence}",
            ],
            detail_items=[
                *class_details,
                f"Feature type: {feature.feature_type}",
                f"Clause 4.4 geometry resolved: {feature.mt_geometry_resolved}",
                f"H: {feature.h_m:.3f} m",
                f"Lu: {feature.lu_m:.3f} m",
                f"x: {feature.x_m:.3f} m",
                f"H/(2Lu): {calculation.slope_parameter:.3f}",
                f"L1: {_format_value(None if unresolved_geometry else calculation.l1_m)}",
                f"L2: {_format_value(None if unresolved_geometry else calculation.l2_m)}",
                ("Mh: not calculated" if unresolved_geometry else f"Mh: {calculation.mh:.3f}"),
                f"Mlee: {calculation.mlee:.3f}",
                f"Confidence: {feature.confidence}",
                *feature.notes,
                *warnings,
            ],
            calculation_result=(
                f"Mt = {value:.3f}"
                if value is not None
                else "Mt unavailable because Clause 4.4 geometry is unresolved."
            ),
        )
        assessments.append(apply_override(assessment, overrides))
    return assessments


def vsitb_directional_rows(variables: list[WindVariableAssessment]) -> list[SiteWindSpeedRow]:
    rows = []
    vr = variable_for(variables, "VR", None)
    mc = variable_for(variables, "Mc", None)
    for direction in DIRECTIONS:
        md = variable_for(variables, "Md", direction)
        mzcat = variable_for(variables, "Mzcat", direction)
        ms = variable_for(variables, "Ms", direction)
        mt = variable_for(variables, "Mt", direction)
        input_variables = [vr, mc, md, mzcat, ms, mt]
        values = [item.final_value for item in input_variables if item is not None]
        warnings = []
        complete = len(values) == 6 and all(value is not None for value in values)
        if not complete:
            warnings.append(
                "Vsit,b could not be calculated because one or more inputs are missing."
            )
        final_vsitb = (
            site_wind_speed(
                vr=float(values[0]),
                mc=float(values[1]),
                md=float(values[2]),
                mzcat=float(values[3]),
                ms=float(values[4]),
                mt=float(values[5]),
            )
            if complete
            else None
        )
        rows.append(
            SiteWindSpeedRow(
                direction=direction,
                vr=vr.final_value if vr else None,
                mc=mc.final_value if mc else None,
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
                formula_basis="Vsit,b = VR x Mc x Md x Mz,cat x Ms x Mt",
                calculation_inputs=[
                    f"VR: {_format_value(row.vr)}",
                    f"Mc: {_format_value(row.mc)}",
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


def apply_vsitb_assessments_to_rows(
    rows: list[SiteWindSpeedRow],
    assessments: list[WindVariableAssessment],
) -> list[SiteWindSpeedRow]:
    """Keep summary rows consistent with any reviewed directional Vsit,b overrides."""

    by_direction = {assessment.direction: assessment for assessment in assessments}
    return [
        row.model_copy(update={"final_vsitb": by_direction[row.direction].final_value})
        if row.direction in by_direction
        else row
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
