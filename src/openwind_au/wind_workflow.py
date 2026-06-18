"""AS/NZS 1170.2 site wind workflow through reviewed Vsit,b."""

from __future__ import annotations

from openwind_au.models import (
    ObstructionInventoryResult,
    SiteAnalysisResult,
    SiteWindSpeedRow,
    TerrainCategoryEvidenceResult,
    WindDirection,
    WindVariableAssessment,
    WindVariableReview,
    WindWorkflowRequest,
    WindWorkflowResult,
    WindWorkflowVariable,
)
from openwind_au.shielding import DIRECTION_AZIMUTHS

DIRECTIONS: list[WindDirection] = [direction for direction, _azimuth in DIRECTION_AZIMUTHS]
REVIEWED_STATUSES = {"accepted", "overridden"}


def run_wind_workflow(
    *,
    request: WindWorkflowRequest,
    site_result: SiteAnalysisResult,
    obstruction_result: ObstructionInventoryResult,
    terrain_result: TerrainCategoryEvidenceResult,
) -> WindWorkflowResult:
    """Assemble reviewable AS/NZS 1170.2 site wind variables through Vsit,b."""

    reviews = review_lookup(request.workflow_reviews)
    variables: list[WindVariableAssessment] = []
    vr = vr_assessment(request, reviews)
    variables.append(vr)
    variables.extend(md_assessments(request, reviews))
    variables.extend(mzcat_assessments(terrain_result, reviews))
    variables.extend(ms_assessments(obstruction_result, reviews))
    variables.extend(mt_assessments(site_result, reviews))
    vsitb_rows = vsitb_directional_rows(variables)
    variables.extend(vsitb_assessments(vsitb_rows, reviews))
    warnings = [
        "Workflow values are preliminary until reviewed by a competent engineer.",
        "Pressure calculations are not included.",
    ]
    if request.regional_wind_speed_mps is None:
        warnings.append("VR must be supplied or overridden before Vsit,b can be calculated.")
    return WindWorkflowResult(
        input=request,
        site=site_result.site,
        variables=variables,
        directional_vsitb=vsitb_rows,
        evidence_references=[
            "Project and site inputs",
            "Terrain category / Mz,cat evidence",
            "Obstruction inventory and shielding sectors",
            "Topographic screening",
            "Evidence maps",
        ],
        warnings=warnings,
    )


def review_lookup(
    reviews: list[WindVariableReview],
) -> dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableReview]:
    """Return the latest review keyed by variable and optional direction."""

    return {(review.variable, review.direction): review for review in reviews}


def apply_review(
    assessment: WindVariableAssessment,
    reviews: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableReview],
) -> WindVariableAssessment:
    review = reviews.get((assessment.variable, assessment.direction))
    if review is None:
        return assessment
    return assessment.model_copy(
        update={
            "final_value": review.final_value,
            "review_status": review.review_status,
            "reviewed_by": review.reviewed_by,
            "review_notes": review.review_notes,
        }
    )


def vr_assessment(
    request: WindWorkflowRequest,
    reviews: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableReview],
) -> WindVariableAssessment:
    value = request.regional_wind_speed_mps
    warnings = []
    confidence = "medium" if value is not None else "low"
    if value is None:
        warnings.append("Supply or override VR from the project wind region and AEP/ARI.")
    assessment = WindVariableAssessment(
        variable="VR",
        label="Regional wind speed, VR",
        unit="m/s",
        recommended_value=value,
        confidence=confidence,
        warnings=warnings,
        evidence_link="#project-site-inputs",
        formula_basis=(
            "Regional wind speed selected from wind region and annual probability of exceedance."
        ),
        calculation_inputs=[
            f"Region: {request.wind_region}",
            f"AEP / ARI: {request.annual_exceedance_probability}",
        ],
        calculation_result=(
            f"VR = {value:.3f} m/s"
            if value is not None
            else "VR requires engineer-supplied regional wind speed."
        ),
    )
    return apply_review(assessment, reviews)


def md_assessments(
    request: WindWorkflowRequest,
    reviews: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableReview],
) -> list[WindVariableAssessment]:
    assessments = []
    for direction in DIRECTIONS:
        supplied = direction in request.wind_direction_multipliers
        value = request.wind_direction_multipliers.get(direction, 1.0)
        warnings = []
        if not supplied:
            warnings.append("Default Md = 1.0 used as a review placeholder.")
        assessment = WindVariableAssessment(
            variable="Md",
            label="Wind direction multiplier, Md",
            direction=direction,
            recommended_value=value,
            confidence="medium" if supplied else "low",
            warnings=warnings,
            evidence_link="#wind-direction-md",
            formula_basis="Wind direction multiplier selected for the assessed wind direction.",
            calculation_inputs=[f"Direction: {direction}"],
            calculation_result=f"Md = {value:.3f}",
        )
        assessments.append(apply_review(assessment, reviews))
    return assessments


def mzcat_assessments(
    terrain_result: TerrainCategoryEvidenceResult,
    reviews: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableReview],
) -> list[WindVariableAssessment]:
    assessments = []
    for item in terrain_result.mzcat_assessment:
        warnings = list(item.warnings)
        if item.recommended_mzcat is None:
            warnings.append("Mz,cat requires engineer review before use in Vsit,b.")
        assessment = WindVariableAssessment(
            variable="Mzcat",
            label="Terrain height multiplier, Mz,cat",
            direction=item.direction,
            recommended_value=item.recommended_mzcat,
            confidence=item.recommendation_confidence,
            warnings=warnings,
            evidence_link="#terrain-category-mzcat",
            formula_basis="Mz,cat selected from reviewed terrain category evidence and height.",
            calculation_inputs=[
                f"Suggested terrain category range: {item.suggested_terrain_category_range}",
                f"Assessment height: {item.assessment_height_m:.3f} m",
            ],
            calculation_result=(
                f"Mz,cat = {item.recommended_mzcat:.3f}"
                if item.recommended_mzcat is not None
                else "Mz,cat recommendation requires review."
            ),
        )
        assessments.append(apply_review(assessment, reviews))
    return assessments


def ms_assessments(
    obstruction_result: ObstructionInventoryResult,
    reviews: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableReview],
) -> list[WindVariableAssessment]:
    assessments = []
    for sector in obstruction_result.shielding_sectors:
        assessment = WindVariableAssessment(
            variable="Ms",
            label="Shielding multiplier, Ms",
            direction=sector.direction,
            recommended_value=sector.indicative_ms,
            confidence=_confidence(sector.overall_confidence),
            warnings=[
                "Indicative Ms is preliminary and requires engineer review.",
                *sector.warnings,
            ],
            evidence_link="#shielding-ms",
            formula_basis=(
                "Shielding multiplier inferred from reviewed obstruction sector evidence."
            ),
            calculation_inputs=[
                f"Direction: {sector.direction}",
                f"Included shielding obstructions: {sector.ns}",
            ],
            calculation_result=f"Ms = {sector.indicative_ms:.3f}",
        )
        assessments.append(apply_review(assessment, reviews))
    return assessments


def mt_assessments(
    site_result: SiteAnalysisResult,
    reviews: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableReview],
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
            confidence="medium" if no_significant_feature else "low",
            warnings=warnings,
            evidence_link="#topographic-mt",
            formula_basis="Topographic multiplier reviewed from topographic screening evidence.",
            calculation_inputs=[
                f"Feature: {feature.feature_type}",
                f"Average upwind slope: {feature.average_upwind_slope:.3f}",
            ],
            calculation_result=f"Mt = {value:.3f}",
        )
        assessments.append(apply_review(assessment, reviews))
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
        reviewed = all(
            item is not None and item.review_status in REVIEWED_STATUSES and item.final_value
            for item in input_variables
        )
        warnings = []
        if not reviewed:
            warnings.append("Vsit,b blocked until VR, Md, Mz,cat, Ms, and Mt are reviewed.")
        final_vsitb = _product(values) if reviewed and len(values) == 5 else None
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
                review_status="accepted" if reviewed else "unreviewed",
                status="calculated" if reviewed else "blocked",
                warnings=warnings,
            )
        )
    return rows


def vsitb_assessments(
    rows: list[SiteWindSpeedRow],
    reviews: dict[tuple[WindWorkflowVariable, WindDirection | None], WindVariableReview],
) -> list[WindVariableAssessment]:
    assessments = []
    for row in rows:
        warnings = list(row.warnings)
        review = reviews.get(("Vsitb", row.direction))
        final_value = None
        review_status = "unreviewed"
        reviewed_by = None
        review_notes = None
        if row.status == "calculated" and review is not None:
            final_value = review.final_value
            review_status = review.review_status
            reviewed_by = review.reviewed_by
            review_notes = review.review_notes
        elif review is not None:
            warnings.append("Vsit,b review ignored until all input variables are reviewed.")
        assessments.append(
            WindVariableAssessment(
                variable="Vsitb",
                label="Site wind speed, Vsit,b",
                direction=row.direction,
                unit="m/s",
                recommended_value=row.recommended_vsitb,
                confidence="medium" if row.status == "calculated" else "low",
                final_value=final_value,
                review_status=review_status,
                reviewed_by=reviewed_by,
                review_notes=review_notes,
                warnings=warnings,
                evidence_link="#vsitb-summary",
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
                    else "Vsit,b blocked pending reviewed inputs."
                ),
            )
        )
    return assessments


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


def _format_value(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "unreviewed"
