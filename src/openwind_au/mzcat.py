"""Indicative Mz,cat assessment from terrain-category evidence."""

from __future__ import annotations

import logging
import math
from typing import Any

from openwind_au.errors import ServiceNotReadyError
from openwind_au.models import (
    MzCatAssessmentResult,
    MzCatDirectionAssessment,
    SiteAnalysisRequest,
    SiteLocation,
    TerrainCategoryDirectionEvidence,
)
from openwind_au.standard_calculations import SUPPORTED_AU_WIND_REGIONS
from openwind_au.standard_lookup_tables import (
    MZCAT_DATA_FILE,
    MZCAT_EXPECTED_SHA256_ENV,
    MZCAT_TABLE_ENV,
    TRUSTED_PACKAGED_VALUES_SHA256,
    finite_lookup_number,
    load_lookup_data,
    load_packaged_lookup_data,
    lookup_metadata_warnings,
    lookup_provenance_issues,
    lookup_provenance_snapshot,
    source_reference,
    trusted_values_sha256,
)
from openwind_au.wind_region import assess_wind_region

SUPPORTED_TERRAIN_CATEGORIES: tuple[str, ...] = ("TC1", "TC1.5", "TC2", "TC2.5", "TC3", "TC4")
TABLE_TERRAIN_CATEGORIES: tuple[float, ...] = (1.0, 2.0, 2.5, 3.0, 4.0)
TABLE_HEIGHTS_M: tuple[float, ...] = (
    3.0,
    5.0,
    10.0,
    15.0,
    20.0,
    30.0,
    40.0,
    50.0,
    75.0,
    100.0,
    150.0,
    200.0,
)
MZCAT_METADATA_WARNING = (
    "Mz,cat lookup table does not have complete independent reviewer/date metadata."
)
MZCAT_SOURCE_CLAUSE = "Clauses 4.2.2 and 4.2.3"
MZCAT_STANDARD_REFERENCE = "AS/NZS 1170.2:2021 Clauses 4.2.2 and 4.2.3, Table 4.1"
EXPECTED_A0_RULE = {
    "category_at_or_below_100_m": 2.0,
    "constant_above_height_m": 100.0,
    "constant_above_value": 1.24,
}
LOGGER = logging.getLogger(__name__)


def load_mzcat_table() -> dict[str, Any]:
    """Load editable terrain/height-multiplier lookup data."""

    data = load_lookup_data(MZCAT_TABLE_ENV, MZCAT_DATA_FILE)
    issues = mzcat_lookup_issues(data, require_reviewed=False)
    if issues:
        LOGGER.error("Configured Table 4.1 lookup is invalid: %s", "; ".join(issues))
        raise ServiceNotReadyError(f"Invalid Table 4.1 lookup data: {'; '.join(issues)}")
    return data


def mzcat_lookup_issues(
    data: dict[str, Any],
    *,
    require_reviewed: bool = True,
) -> list[str]:
    """Return Table 4.1 structure and provenance validation failures."""

    try:
        expected_digest = trusted_values_sha256(
            package_file=MZCAT_DATA_FILE,
            expected_digest_env=MZCAT_EXPECTED_SHA256_ENV,
        )
    except ValueError as exc:
        issues = [str(exc)]
        expected_digest = TRUSTED_PACKAGED_VALUES_SHA256[MZCAT_DATA_FILE]
    else:
        issues = []
    issues.extend(
        lookup_provenance_issues(
            data,
            expected_clause=MZCAT_SOURCE_CLAUSE,
            expected_standard_reference=MZCAT_STANDARD_REFERENCE,
            expected_table="Table 4.1",
            expected_values_sha256=expected_digest,
            require_reviewed=require_reviewed,
        )
    )
    values = data.get("values")
    if not isinstance(values, dict):
        return [*issues, "values must be an object"]
    categories = values.get("categories")
    heights = values.get("heights_m")
    if categories != list(TABLE_TERRAIN_CATEGORIES):
        issues.append("categories must contain the Table 4.1 category nodes in order")
    if heights != list(TABLE_HEIGHTS_M):
        issues.append("heights_m must contain the Table 4.1 height nodes in order")
    rows = values.get("rows")
    if not isinstance(rows, list) or len(rows) != len(TABLE_HEIGHTS_M):
        issues.append("rows must contain one row for every Table 4.1 height")
    else:
        for row_index, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != len(TABLE_TERRAIN_CATEGORIES):
                issues.append(
                    f"rows[{row_index}] must contain one value for every terrain category"
                )
                continue
            if not all(finite_lookup_number(value, minimum=0, maximum=10) for value in row):
                issues.append(f"rows[{row_index}] contains an invalid multiplier")
    if values.get("height_bounds") != {"minimum_m": 3.0, "maximum_m": 200.0}:
        issues.append("height_bounds must match the first and last Table 4.1 rows")
    if values.get("interpolation") != "linear_in_height_and_category":
        issues.append("interpolation must be linear_in_height_and_category")
    if values.get("a0_rule") != EXPECTED_A0_RULE:
        issues.append("a0_rule must match the normative A0 Table 4.1 rule")
    return issues


def terrain_height_multiplier_reference(
    data: dict[str, Any] | None = None,
) -> dict[float, dict[str, float]]:
    """Return a validated height/category mapping from Table 4.1 lookup data."""

    lookup = data if data is not None else load_mzcat_table()
    issues = mzcat_lookup_issues(lookup, require_reviewed=False)
    if issues:
        raise ValueError(f"Invalid Table 4.1 lookup data: {'; '.join(issues)}")
    values = lookup["values"]
    categories = [float(category) for category in values["categories"]]
    return {
        float(height): {
            f"TC{category:g}": float(multiplier)
            for category, multiplier in zip(categories, row, strict=True)
        }
        for height, row in zip(values["heights_m"], values["rows"], strict=True)
    }


def mzcat_lookup_warnings(data: dict[str, Any] | None = None) -> list[str]:
    """Return source-review warnings for the active Table 4.1 lookup."""

    lookup = data if data is not None else load_mzcat_table()
    return lookup_metadata_warnings(lookup, MZCAT_METADATA_WARNING)


def mzcat_source_reference(data: dict[str, Any] | None = None) -> str:
    """Return the active Table 4.1 source reference."""

    lookup = data if data is not None else load_mzcat_table()
    return source_reference(lookup)


# Backwards-compatible snapshot of the packaged table. Calculations load the
# active configured data so deployment overrides are not silently ignored.
INDICATIVE_MZCAT_REFERENCE = terrain_height_multiplier_reference(
    load_packaged_lookup_data(MZCAT_DATA_FILE)
)


def run_mzcat_assessment(
    *,
    request: SiteAnalysisRequest,
    site: SiteLocation,
    directions: list[TerrainCategoryDirectionEvidence],
    recommendation_mode: str = "conservative",
    wind_region: str | None = None,
    lookup_data: dict[str, Any] | None = None,
) -> MzCatAssessmentResult:
    """Return indicative Mz,cat evidence for all directional evidence sectors."""

    lookup = lookup_data if lookup_data is not None else load_mzcat_table()
    issues = mzcat_lookup_issues(lookup, require_reviewed=False)
    if issues:
        raise ValueError(f"Invalid Table 4.1 lookup data: {'; '.join(issues)}")
    resolved_wind_region = wind_region
    region_warning: str | None = None
    if resolved_wind_region is None:
        try:
            resolved_wind_region = assess_wind_region(site).wind_region
        except (ServiceNotReadyError, ValueError):
            region_warning = (
                "Wind region was unavailable for Mz,cat evidence. The displayed numeric range "
                "uses the non-A0 Table 4.1 values and must not be used for a Region A0 site."
            )
    assessments = [
        direction_mzcat_assessment(
            direction,
            request.reference_height_m,
            recommendation_mode=recommendation_mode,
            wind_region=resolved_wind_region,
            lookup_data=lookup,
        )
        for direction in directions
    ]
    warnings = [
        "Terrain category not confirmed.",
        "Mz,cat values are indicative only.",
        "Engineer review required.",
    ]
    if resolved_wind_region == "A0":
        warnings.append("Region A0 Table 4.1 terrain-independent Mz,cat rule applied.")
    if region_warning:
        warnings.append(region_warning)
    warnings.extend(mzcat_lookup_warnings(lookup))
    if any(assessment.confidence == "low" for assessment in assessments):
        warnings.append("Significant uncertainty in obstruction coverage or category evidence.")
    return MzCatAssessmentResult(
        input=request,
        site=site,
        directions=assessments,
        recommendation_mode=recommendation_mode,  # type: ignore[arg-type]
        lookup_provenance=lookup_provenance_snapshot(lookup),
        warnings=warnings,
    )


def direction_mzcat_assessment(
    evidence: TerrainCategoryDirectionEvidence,
    assessment_height_m: float,
    *,
    recommendation_mode: str = "conservative",
    wind_region: str | None = None,
    lookup_data: dict[str, Any] | None = None,
) -> MzCatDirectionAssessment:
    """Convert one terrain-category evidence sector into an indicative Mz,cat range."""

    lower_category, upper_category = category_bounds(evidence.suggested_category_range)
    lower_value = indicative_mzcat(
        lower_category,
        assessment_height_m,
        wind_region=wind_region,
        lookup_data=lookup_data,
    )
    upper_value = indicative_mzcat(
        upper_category,
        assessment_height_m,
        wind_region=wind_region,
        lookup_data=lookup_data,
    )
    confidence = mzcat_confidence(evidence, lower_category, upper_category)
    warnings = mzcat_warnings(evidence, confidence)
    if wind_region == "A0":
        warnings.append("Region A0 Table 4.1 terrain-independent Mz,cat rule applied.")
    elif wind_region is None:
        warnings.append(
            "Wind region was not supplied; numeric Mz,cat evidence uses the non-A0 table and "
            "must not be used for Region A0."
        )
    recommendation = mzcat_recommendation(
        evidence=evidence,
        lower_category=lower_category,
        upper_category=upper_category,
        lower_value=lower_value,
        upper_value=upper_value,
        confidence=confidence,
        mode=recommendation_mode,
    )
    if wind_region == "A0":
        recommendation_reasoning = recommendation.get("reasoning", [])
        recommendation["reasoning"] = [
            "Region A0 overrides terrain category with the Table 4.1 A0 rule.",
            *(recommendation_reasoning if isinstance(recommendation_reasoning, list) else []),
        ]
    return MzCatDirectionAssessment(
        direction=evidence.direction,
        azimuth_deg=evidence.azimuth_deg,
        recommendation_mode=recommendation_mode,  # type: ignore[arg-type]
        suggested_terrain_category_range=evidence.suggested_category_range,
        lower_category_bound=lower_category,  # type: ignore[arg-type]
        upper_category_bound=upper_category,  # type: ignore[arg-type]
        assessment_height_m=assessment_height_m,
        lower_indicative_mzcat=min(lower_value, upper_value),
        upper_indicative_mzcat=max(lower_value, upper_value),
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
        "mzcat": value,
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
    lookup_data: dict[str, Any] | None = None,
) -> float:
    """Return Table 4.1 Mz,cat using linear height/category interpolation."""

    if not math.isfinite(assessment_height_m) or assessment_height_m <= 0:
        raise ValueError("Assessment height must be a finite number greater than zero.")
    if assessment_height_m > 200:
        raise ValueError(
            "Assessment height exceeds the 200 m scope and Table 4.1 range of AS/NZS 1170.2."
        )
    if wind_region is not None and wind_region not in SUPPORTED_AU_WIND_REGIONS:
        raise ValueError(f"Unsupported Australian wind region: {wind_region}")
    if wind_region == "A":
        raise ValueError(
            "Wind region A is ambiguous for Table 4.1 Mz,cat because Region A0 has "
            "special terrain-height rules; confirm A0, A1, A2, A3, A4, or A5."
        )
    data = lookup_data if lookup_data is not None else load_mzcat_table()
    reference = terrain_height_multiplier_reference(data)
    _terrain_category_number(category)
    values = data["values"]
    minimum_height = float(values["height_bounds"]["minimum_m"])
    height = max(minimum_height, assessment_height_m)
    if wind_region == "A0":
        a0_rule = values["a0_rule"]
        if height > float(a0_rule["constant_above_height_m"]):
            return float(a0_rule["constant_above_value"])
        category = f"TC{float(a0_rule['category_at_or_below_100_m']):g}"
    heights = sorted(reference)
    if height <= heights[0]:
        return _mzcat_for_category(reference[heights[0]], category)
    if height >= heights[-1]:
        return _mzcat_for_category(reference[heights[-1]], category)
    for lower_height, upper_height in zip(heights, heights[1:], strict=True):
        if lower_height <= height <= upper_height:
            lower_value = _mzcat_for_category(reference[lower_height], category)
            upper_value = _mzcat_for_category(reference[upper_height], category)
            ratio = (height - lower_height) / (upper_height - lower_height)
            return lower_value + (upper_value - lower_value) * ratio
    raise RuntimeError("Validated Table 4.1 lookup did not contain the assessment height.")


def _mzcat_for_category(row: dict[str, float], category: str) -> float:
    """Linearly interpolate a Table 4.1 row for an intermediate category."""

    category_number = _terrain_category_number(category)
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


def _terrain_category_number(category: str) -> float:
    try:
        category_number = float(category.removeprefix("TC"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"Unsupported terrain category: {category}") from exc
    if not TABLE_TERRAIN_CATEGORIES[0] <= category_number <= TABLE_TERRAIN_CATEGORIES[-1]:
        raise ValueError(f"Unsupported terrain category: {category}")
    return category_number


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
