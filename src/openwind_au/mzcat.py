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

# AS/NZS 1170.2:2021 Table 4.1 values for fully developed terrain in all
# Australian wind regions except A0. Intermediate heights and terrain
# categories are linearly interpolated as required by Clause 4.2.2.
INDICATIVE_MZCAT_REFERENCE: dict[float, dict[str, float]] = {
    3.0: {"TC1": 0.97, "TC2": 0.91, "TC2.5": 0.87, "TC3": 0.83, "TC4": 0.75},
    5.0: {"TC1": 1.01, "TC2": 0.91, "TC2.5": 0.87, "TC3": 0.83, "TC4": 0.75},
    10.0: {"TC1": 1.08, "TC2": 1.00, "TC2.5": 0.92, "TC3": 0.83, "TC4": 0.75},
    15.0: {"TC1": 1.12, "TC2": 1.05, "TC2.5": 0.97, "TC3": 0.89, "TC4": 0.75},
    20.0: {"TC1": 1.14, "TC2": 1.08, "TC2.5": 1.01, "TC3": 0.94, "TC4": 0.75},
    30.0: {"TC1": 1.18, "TC2": 1.12, "TC2.5": 1.06, "TC3": 1.00, "TC4": 0.80},
    40.0: {"TC1": 1.21, "TC2": 1.16, "TC2.5": 1.10, "TC3": 1.04, "TC4": 0.85},
    50.0: {"TC1": 1.23, "TC2": 1.18, "TC2.5": 1.13, "TC3": 1.07, "TC4": 0.90},
    75.0: {"TC1": 1.27, "TC2": 1.22, "TC2.5": 1.17, "TC3": 1.12, "TC4": 0.98},
    100.0: {"TC1": 1.31, "TC2": 1.24, "TC2.5": 1.20, "TC3": 1.16, "TC4": 1.03},
    150.0: {"TC1": 1.36, "TC2": 1.27, "TC2.5": 1.24, "TC3": 1.21, "TC4": 1.11},
    200.0: {"TC1": 1.39, "TC2": 1.29, "TC2.5": 1.27, "TC3": 1.24, "TC4": 1.16},
}

TABLE_TERRAIN_CATEGORIES: tuple[float, ...] = (1.0, 2.0, 2.5, 3.0, 4.0)


def run_mzcat_assessment(
    *,
    request: SiteAnalysisRequest,
    site: SiteLocation,
    directions: list[TerrainCategoryDirectionEvidence],
    recommendation_mode: str = "conservative",
) -> MzCatAssessmentResult:
    """Return indicative Mz,cat evidence for all directional evidence sectors."""

    assessments = [
        direction_mzcat_assessment(
            direction,
            request.building_height_m,
            recommendation_mode=recommendation_mode,
        )
        for direction in directions
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
        recommendation_mode=recommendation_mode,  # type: ignore[arg-type]
        warnings=warnings,
    )


def direction_mzcat_assessment(
    evidence: TerrainCategoryDirectionEvidence,
    assessment_height_m: float,
    *,
    recommendation_mode: str = "conservative",
) -> MzCatDirectionAssessment:
    """Convert one terrain-category evidence sector into an indicative Mz,cat range."""

    lower_category, upper_category = category_bounds(evidence.suggested_category_range)
    lower_value = indicative_mzcat(lower_category, assessment_height_m)
    upper_value = indicative_mzcat(upper_category, assessment_height_m)
    confidence = mzcat_confidence(evidence, lower_category, upper_category)
    warnings = mzcat_warnings(evidence, confidence)
    recommendation = mzcat_recommendation(
        evidence=evidence,
        lower_category=lower_category,
        upper_category=upper_category,
        lower_value=lower_value,
        upper_value=upper_value,
        confidence=confidence,
        mode=recommendation_mode,
    )
    return MzCatDirectionAssessment(
        direction=evidence.direction,
        azimuth_deg=evidence.azimuth_deg,
        recommendation_mode=recommendation_mode,  # type: ignore[arg-type]
        suggested_terrain_category_range=evidence.suggested_category_range,
        lower_category_bound=lower_category,  # type: ignore[arg-type]
        upper_category_bound=upper_category,  # type: ignore[arg-type]
        assessment_height_m=assessment_height_m,
        lower_indicative_mzcat=round(min(lower_value, upper_value), 3),
        upper_indicative_mzcat=round(max(lower_value, upper_value), 3),
        confidence=confidence,  # type: ignore[arg-type]
        recommended_terrain_category=recommendation["category"],
        recommended_mzcat=recommendation["mzcat"],
        recommendation_confidence=recommendation["confidence"],  # type: ignore[arg-type]
        recommendation_reasoning=recommendation["reasoning"],
        directional_fetch_distance_m=evidence.directional_fetch_distance_m,
        built_up_area_percentage=evidence.built_up_area_percentage,
        vegetation_area_percentage=evidence.vegetation_area_percentage,
        obstruction_density_per_km2=evidence.obstruction_density_per_km2,
        average_obstruction_height_m=evidence.average_obstruction_height_m,
        controlling_category_range=f"{lower_category}-{upper_category}",
        reasoning=mzcat_reasoning(evidence),
        warnings=warnings,
    )


def mzcat_recommendation(
    *,
    evidence: TerrainCategoryDirectionEvidence,
    lower_category: str,
    upper_category: str,
    lower_value: float,
    upper_value: float,
    confidence: str,
    mode: str,
) -> dict[str, object]:
    """Return an indicative recommendation for workflow calculation."""

    category_width = abs(
        SUPPORTED_TERRAIN_CATEGORIES.index(upper_category)
        - SUPPORTED_TERRAIN_CATEGORIES.index(lower_category)
    )
    if mode == "best_estimate":
        category = upper_category
        value = upper_value
        mode_reason = "Best-estimate mode selects the upper category bound within the narrow range."
    else:
        candidates = [(lower_category, lower_value), (upper_category, upper_value)]
        category, value = max(candidates, key=lambda item: item[1])
        mode_reason = (
            "Conservative mode selects the category bound with the larger indicative Mz,cat."
        )
    return {
        "category": category,
        "mzcat": round(value, 3),
        "confidence": confidence,
        "reasoning": [
            mode_reason,
            (
                "Evidence confidence is high and the suggested terrain category range is narrow."
                if confidence == "high" and category_width <= 1
                else (
                    "Automatic indicative value selected despite lower confidence or broad "
                    "terrain category range so the workflow can calculate through Vsit,b."
                )
            ),
            "Engineer review is handled at assessment level before reporting final issue.",
        ],
    }


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


def indicative_mzcat(
    category: str,
    assessment_height_m: float,
    *,
    wind_region: str | None = None,
) -> float:
    """Return Table 4.1 Mz,cat using linear height/category interpolation."""

    height = max(3.0, min(200.0, assessment_height_m))
    if wind_region == "A0":
        if height > 100.0:
            return 1.24
        category = "TC2"
    heights = sorted(INDICATIVE_MZCAT_REFERENCE)
    if height <= heights[0]:
        return _mzcat_for_category(INDICATIVE_MZCAT_REFERENCE[heights[0]], category)
    if height >= heights[-1]:
        return _mzcat_for_category(INDICATIVE_MZCAT_REFERENCE[heights[-1]], category)
    for lower_height, upper_height in zip(heights, heights[1:], strict=True):
        if lower_height <= height <= upper_height:
            lower_value = _mzcat_for_category(INDICATIVE_MZCAT_REFERENCE[lower_height], category)
            upper_value = _mzcat_for_category(INDICATIVE_MZCAT_REFERENCE[upper_height], category)
            ratio = (height - lower_height) / (upper_height - lower_height)
            return lower_value + (upper_value - lower_value) * ratio
    return _mzcat_for_category(INDICATIVE_MZCAT_REFERENCE[10.0], category)


def _mzcat_for_category(row: dict[str, float], category: str) -> float:
    """Linearly interpolate a Table 4.1 row for an intermediate category."""

    try:
        category_number = float(category.removeprefix("TC"))
    except ValueError as exc:
        raise ValueError(f"Unsupported terrain category: {category}") from exc
    if not TABLE_TERRAIN_CATEGORIES[0] <= category_number <= TABLE_TERRAIN_CATEGORIES[-1]:
        raise ValueError(f"Unsupported terrain category: {category}")
    exact_key = f"TC{category_number:g}"
    if exact_key in row:
        return row[exact_key]
    for lower_category, upper_category in zip(
        TABLE_TERRAIN_CATEGORIES,
        TABLE_TERRAIN_CATEGORIES[1:],
        strict=True,
    ):
        if lower_category <= category_number <= upper_category:
            lower_value = row[f"TC{lower_category:g}"]
            upper_value = row[f"TC{upper_category:g}"]
            ratio = (category_number - lower_category) / (upper_category - lower_category)
            return lower_value + (upper_value - lower_value) * ratio
    raise ValueError(f"Unsupported terrain category: {category}")


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
