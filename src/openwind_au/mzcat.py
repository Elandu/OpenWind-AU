"""Indicative Mz,cat assessment from terrain-category evidence."""

from __future__ import annotations

from openwind_au.models import (
    MzCatAssessmentResult,
    MzCatDirectionAssessment,
    SiteAnalysisRequest,
    SiteLocation,
    TerrainCategoryDirectionEvidence,
)

SUPPORTED_TERRAIN_CATEGORIES: tuple[str, ...] = ("TC1", "TC1.5", "TC2", "TC2.5", "TC3", "TC4")

# Transparent screening reference values, not a replacement for the project standard.
# Rows are assessment height in metres; columns are terrain category labels.
INDICATIVE_MZCAT_REFERENCE: dict[float, dict[str, float]] = {
    5.0: {"TC1": 0.99, "TC1.5": 0.97, "TC2": 0.95, "TC2.5": 0.88, "TC3": 0.78, "TC4": 0.67},
    10.0: {"TC1": 1.05, "TC1.5": 1.02, "TC2": 1.00, "TC2.5": 0.96, "TC3": 0.91, "TC4": 0.83},
    20.0: {"TC1": 1.10, "TC1.5": 1.07, "TC2": 1.05, "TC2.5": 1.02, "TC3": 0.98, "TC4": 0.91},
    40.0: {"TC1": 1.14, "TC1.5": 1.12, "TC2": 1.10, "TC2.5": 1.07, "TC3": 1.04, "TC4": 0.98},
    80.0: {"TC1": 1.18, "TC1.5": 1.16, "TC2": 1.14, "TC2.5": 1.12, "TC3": 1.09, "TC4": 1.05},
}


def run_mzcat_assessment(
    *,
    request: SiteAnalysisRequest,
    site: SiteLocation,
    directions: list[TerrainCategoryDirectionEvidence],
) -> MzCatAssessmentResult:
    """Return indicative Mz,cat evidence for all directional evidence sectors."""

    assessments = [
        direction_mzcat_assessment(direction, request.building_height_m) for direction in directions
    ]
    warnings = [
        "Terrain category not confirmed.",
        "Mz,cat values are indicative only.",
        "Engineer review required.",
    ]
    if any(assessment.confidence == "low" for assessment in assessments):
        warnings.append("Significant uncertainty in obstruction coverage or category evidence.")
    return MzCatAssessmentResult(
        input=request,
        site=site,
        directions=assessments,
        warnings=warnings,
    )


def direction_mzcat_assessment(
    evidence: TerrainCategoryDirectionEvidence,
    assessment_height_m: float,
) -> MzCatDirectionAssessment:
    """Convert one terrain-category evidence sector into an indicative Mz,cat range."""

    lower_category, upper_category = category_bounds(evidence.suggested_category_range)
    lower_value = indicative_mzcat(lower_category, assessment_height_m)
    upper_value = indicative_mzcat(upper_category, assessment_height_m)
    confidence = mzcat_confidence(evidence, lower_category, upper_category)
    warnings = mzcat_warnings(evidence, confidence)
    return MzCatDirectionAssessment(
        direction=evidence.direction,
        azimuth_deg=evidence.azimuth_deg,
        suggested_terrain_category_range=evidence.suggested_category_range,
        lower_category_bound=lower_category,  # type: ignore[arg-type]
        upper_category_bound=upper_category,  # type: ignore[arg-type]
        assessment_height_m=assessment_height_m,
        lower_indicative_mzcat=round(min(lower_value, upper_value), 3),
        upper_indicative_mzcat=round(max(lower_value, upper_value), 3),
        confidence=confidence,  # type: ignore[arg-type]
        directional_fetch_distance_m=evidence.directional_fetch_distance_m,
        built_up_area_percentage=evidence.built_up_area_percentage,
        vegetation_area_percentage=evidence.vegetation_area_percentage,
        obstruction_density_per_km2=evidence.obstruction_density_per_km2,
        average_obstruction_height_m=evidence.average_obstruction_height_m,
        controlling_category_range=f"{lower_category}-{upper_category}",
        reasoning=mzcat_reasoning(evidence),
        warnings=warnings,
    )


def category_bounds(category_range: str) -> tuple[str, str]:
    """Parse and normalise supported terrain-category range labels."""

    cleaned = category_range.replace("–", "-").replace(" ", "")
    parts = [part for part in cleaned.split("-") if part]
    if not parts:
        return "TC2", "TC3"
    if len(parts) == 1:
        parts = [parts[0], parts[0]]
    lower = nearest_supported_category(parts[0])
    upper = nearest_supported_category(parts[1])
    lower_index = SUPPORTED_TERRAIN_CATEGORIES.index(lower)
    upper_index = SUPPORTED_TERRAIN_CATEGORIES.index(upper)
    if lower_index > upper_index:
        lower, upper = upper, lower
    return lower, upper


def nearest_supported_category(category: str) -> str:
    """Return the nearest supported category label."""

    if category in SUPPORTED_TERRAIN_CATEGORIES:
        return category
    if category == "TC3.5":
        return "TC4"
    if category == "TC0":
        return "TC1"
    return "TC2"


def indicative_mzcat(category: str, assessment_height_m: float) -> float:
    """Interpolate indicative Mz,cat for a terrain category and assessment height."""

    height = max(5.0, min(80.0, assessment_height_m))
    heights = sorted(INDICATIVE_MZCAT_REFERENCE)
    if height <= heights[0]:
        return INDICATIVE_MZCAT_REFERENCE[heights[0]][category]
    if height >= heights[-1]:
        return INDICATIVE_MZCAT_REFERENCE[heights[-1]][category]
    for lower_height, upper_height in zip(heights, heights[1:], strict=True):
        if lower_height <= height <= upper_height:
            lower_value = INDICATIVE_MZCAT_REFERENCE[lower_height][category]
            upper_value = INDICATIVE_MZCAT_REFERENCE[upper_height][category]
            ratio = (height - lower_height) / (upper_height - lower_height)
            return lower_value + (upper_value - lower_value) * ratio
    return INDICATIVE_MZCAT_REFERENCE[10.0][category]


def mzcat_confidence(
    evidence: TerrainCategoryDirectionEvidence,
    lower_category: str,
    upper_category: str,
) -> str:
    """Assign confidence to the indicative Mz,cat range."""

    category_width = abs(
        SUPPORTED_TERRAIN_CATEGORIES.index(upper_category)
        - SUPPORTED_TERRAIN_CATEGORIES.index(lower_category)
    )
    if evidence.confidence == "low" or evidence.obstruction_count < 3:
        return "low"
    if evidence.height_coverage_percentage < 50:
        return "low"
    if (
        evidence.confidence == "high"
        and category_width <= 1
        and evidence.height_coverage_percentage >= 80
    ):
        return "high"
    return "medium"


def mzcat_warnings(evidence: TerrainCategoryDirectionEvidence, confidence: str) -> list[str]:
    """Return warnings for one indicative Mz,cat direction."""

    warnings = [
        "Terrain category not confirmed.",
        "Mz,cat values are indicative only.",
        "Engineer review required.",
    ]
    if confidence == "low":
        warnings.append("Significant uncertainty in obstruction coverage.")
    if evidence.height_coverage_percentage < 80:
        warnings.append("Missing obstruction heights reduce confidence.")
    if evidence.directional_fetch_distance_m < 500:
        warnings.append(
            "Short fetch distance may not represent the full upwind terrain transition."
        )
    return warnings


def mzcat_reasoning(evidence: TerrainCategoryDirectionEvidence) -> list[str]:
    """Return concise evidence bullets for one direction."""

    height_text = (
        f"average obstruction height {evidence.average_obstruction_height_m:.1f} m"
        if evidence.average_obstruction_height_m is not None
        else "average obstruction height unavailable"
    )
    return [
        f"built-up coverage {evidence.built_up_area_percentage:.1f}%",
        f"vegetation coverage {evidence.vegetation_area_percentage:.1f}%",
        f"obstruction density {evidence.obstruction_density_per_km2:.1f}/km2",
        f"fetch distance {evidence.directional_fetch_distance_m:.0f} m",
        height_text,
    ]
