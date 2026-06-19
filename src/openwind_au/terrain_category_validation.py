"""Representative validation examples for terrain category evidence scoring."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from openwind_au.models import TerrainCategoryDirectionEvidence
from openwind_au.mzcat import direction_mzcat_assessment
from openwind_au.terrain_category import suggested_category_range, terrain_category_scores

TerrainCategoryValidationStatus = Literal["pass", "warn", "fail"]


class TerrainCategoryValidationCase(BaseModel):
    """Synthetic representative terrain-category evidence validation case."""

    case_id: str
    description: str
    built_up_area_percentage: float
    vegetation_area_percentage: float
    open_terrain_percentage: float
    obstruction_density_per_km2: float
    average_obstruction_height_m: float
    expected_suggested_ranges: tuple[str, ...]
    assessment_height_m: float = 10.0
    expected_indicative_mzcat_range: tuple[float, float]
    expected_confidence: Literal["high", "medium", "low"]


class TerrainCategoryValidationResult(BaseModel):
    """Validation result for one terrain category evidence example."""

    case: TerrainCategoryValidationCase
    suggested_category_range: str
    indicative_mzcat_range: tuple[float, float]
    mzcat_confidence: Literal["high", "medium", "low"]
    status: TerrainCategoryValidationStatus
    reasons: list[str]


DEFAULT_TERRAIN_CATEGORY_VALIDATION_CASES: tuple[TerrainCategoryValidationCase, ...] = (
    TerrainCategoryValidationCase(
        case_id="tc-coastal-open-terrain",
        description="Coastal open terrain with sparse low obstructions.",
        built_up_area_percentage=2,
        vegetation_area_percentage=3,
        open_terrain_percentage=95,
        obstruction_density_per_km2=10,
        average_obstruction_height_m=3,
        expected_suggested_ranges=("TC1.5-TC2", "TC2-TC2.5"),
        expected_indicative_mzcat_range=(1.00, 1.02),
        expected_confidence="medium",
    ),
    TerrainCategoryValidationCase(
        case_id="tc-suburban-housing",
        description="Suburban housing with moderate building footprint coverage.",
        built_up_area_percentage=30,
        vegetation_area_percentage=15,
        open_terrain_percentage=55,
        obstruction_density_per_km2=450,
        average_obstruction_height_m=6,
        expected_suggested_ranges=("TC2.5-TC3",),
        expected_indicative_mzcat_range=(0.91, 0.96),
        expected_confidence="medium",
    ),
    TerrainCategoryValidationCase(
        case_id="tc-dense-suburban",
        description="Dense suburban setting with closely spaced dwellings.",
        built_up_area_percentage=45,
        vegetation_area_percentage=10,
        open_terrain_percentage=45,
        obstruction_density_per_km2=900,
        average_obstruction_height_m=8,
        expected_suggested_ranges=("TC3-TC4",),
        expected_indicative_mzcat_range=(0.83, 0.91),
        expected_confidence="medium",
    ),
    TerrainCategoryValidationCase(
        case_id="tc-industrial-estate",
        description="Industrial estate with large and taller obstruction footprints.",
        built_up_area_percentage=45,
        vegetation_area_percentage=5,
        open_terrain_percentage=50,
        obstruction_density_per_km2=800,
        average_obstruction_height_m=12,
        expected_suggested_ranges=("TC3-TC4",),
        expected_indicative_mzcat_range=(0.83, 0.91),
        expected_confidence="medium",
    ),
    TerrainCategoryValidationCase(
        case_id="tc-cbd",
        description="CBD-like dense built-up setting with tall obstructions.",
        built_up_area_percentage=70,
        vegetation_area_percentage=5,
        open_terrain_percentage=25,
        obstruction_density_per_km2=2000,
        average_obstruction_height_m=25,
        expected_suggested_ranges=("TC3-TC4",),
        expected_indicative_mzcat_range=(0.83, 0.91),
        expected_confidence="medium",
    ),
    TerrainCategoryValidationCase(
        case_id="tc-rural-vegetation",
        description="Rural vegetation setting with low built-up coverage and tree cover.",
        built_up_area_percentage=5,
        vegetation_area_percentage=45,
        open_terrain_percentage=50,
        obstruction_density_per_km2=120,
        average_obstruction_height_m=8,
        expected_suggested_ranges=("TC2.5-TC3",),
        expected_indicative_mzcat_range=(0.91, 0.96),
        expected_confidence="medium",
    ),
)


def run_terrain_category_validation_cases(
    cases: tuple[TerrainCategoryValidationCase, ...]
    | list[TerrainCategoryValidationCase] = DEFAULT_TERRAIN_CATEGORY_VALIDATION_CASES,
) -> list[TerrainCategoryValidationResult]:
    """Validate representative terrain-category evidence scoring examples."""

    results = []
    for case in cases:
        scores = terrain_category_scores(
            built_up_area_percentage=case.built_up_area_percentage,
            vegetation_area_percentage=case.vegetation_area_percentage,
            open_terrain_percentage=case.open_terrain_percentage,
            obstruction_density_per_km2=case.obstruction_density_per_km2,
            average_obstruction_height_m=case.average_obstruction_height_m,
        )
        suggested_range = suggested_category_range(
            scores,
            case.built_up_area_percentage,
            case.obstruction_density_per_km2,
        )
        evidence = TerrainCategoryDirectionEvidence(
            direction="N",
            azimuth_deg=0,
            sector_start_deg=337.5,
            sector_end_deg=22.5,
            directional_fetch_distance_m=850,
            assessment_radius_m=850,
            built_up_area_percentage=case.built_up_area_percentage,
            vegetation_area_percentage=case.vegetation_area_percentage,
            open_terrain_percentage=case.open_terrain_percentage,
            average_obstruction_height_m=case.average_obstruction_height_m,
            median_obstruction_height_m=case.average_obstruction_height_m,
            maximum_obstruction_height_m=case.average_obstruction_height_m,
            obstruction_density_per_km2=case.obstruction_density_per_km2,
            average_obstruction_spacing_m=50,
            vegetation_density_per_km2=case.vegetation_area_percentage * 10,
            obstruction_count=12,
            vegetation_count=3,
            height_coverage_percentage=90,
            shielding_confidence="medium",
            evidence_scores=scores,
            suggested_category_range=suggested_range,
            confidence="medium",
        )
        mzcat = direction_mzcat_assessment(evidence, case.assessment_height_m)
        mzcat_range = (mzcat.lower_indicative_mzcat, mzcat.upper_indicative_mzcat)
        if (
            suggested_range in case.expected_suggested_ranges
            and mzcat_range == case.expected_indicative_mzcat_range
            and mzcat.confidence == case.expected_confidence
        ):
            status: TerrainCategoryValidationStatus = "pass"
            reasons = ["Suggested range and indicative Mz,cat are within expectation."]
        else:
            status = "warn"
            reasons = [
                "Suggested range or indicative Mz,cat differs from the representative expectation."
            ]
        results.append(
            TerrainCategoryValidationResult(
                case=case,
                suggested_category_range=suggested_range,
                indicative_mzcat_range=mzcat_range,
                mzcat_confidence=mzcat.confidence,  # type: ignore[arg-type]
                status=status,
                reasons=reasons,
            )
        )
    return results
