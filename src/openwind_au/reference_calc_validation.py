"""Reference comparisons against prior project calculations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from openwind_au.models import (
    ObstructionInventoryResult,
    SiteAnalysisResult,
    TerrainCategoryEvidenceResult,
    WindClassMultiplierOverride,
)

ReferenceStatus = Literal["match", "mismatch", "not_available"]

REFERENCE_CALC_7989_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
REFERENCE_CALC_7989_SOURCE = (
    "C:\\Users\\nguye\\Downloads\\CALCS ___7989 - 6 Byambee St, Kenmore QLD 4069.pdf"
)
REFERENCE_TOPOGRAPHIC_T1_SLOPE = 0.18
REFERENCE_CALC_7989_OSM_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "validation"
    / "reference_calc_7989_osm_footprints.json"
)
REFERENCE_CALC_7989_TOPOGRAPHY = {
    "N": "T0",
    "NE": "T1",
    "E": "T1",
    "SE": "T0",
    "S": "T0",
    "SW": "T0",
    "W": "T0",
    "NW": "T0",
}


class ReferenceDirectionReference(BaseModel):
    """Expected reference calculation directional classes for one wind sector."""

    direction: str
    terrain_category: str
    shielding_class: str
    topographic_class: str


class ReferenceDirectionComparison(BaseModel):
    """OpenWind comparison against one reference calculation directional reference."""

    direction: str
    expected_terrain_category: str
    actual_terrain_category: str | None = None
    terrain_status: ReferenceStatus
    expected_shielding_class: str
    actual_shielding_class: str | None = None
    shielding_status: ReferenceStatus
    expected_topographic_class: str
    actual_topographic_class: str | None = None
    topographic_status: ReferenceStatus
    notes: list[str] = Field(default_factory=list)


class ReferenceCalc7989ComparisonReport(BaseModel):
    """Reference calculation 7989 comparison report."""

    case_id: str = "reference_calc-7989-byambee-kenmore"
    source_reference: str = REFERENCE_CALC_7989_SOURCE
    latitude: float = -27.520503
    longitude: float = 152.936814
    building_height_m: float = 4.0
    wind_region: str = "B1"
    vh_ult_mps: float = 40.0
    vh_serv_mps: float = 26.0
    critical_direction: str = "North"
    wind_class: str = "N2"
    wind_pressure_kpa: float = 0.9600
    summary: dict[str, int]
    directions: list[ReferenceDirectionComparison]
    notes: list[str] = Field(default_factory=list)


def reference_calc_7989_reference() -> list[ReferenceDirectionReference]:
    """Return the reference calculation 7989 directional class reference."""

    return [
        ReferenceDirectionReference(
            direction=direction,
            terrain_category="TC3",
            shielding_class="FS",
            topographic_class=REFERENCE_CALC_7989_TOPOGRAPHY[direction],
        )
        for direction in REFERENCE_CALC_7989_DIRECTIONS
    ]


def reference_calc_7989_class_overrides() -> list[WindClassMultiplierOverride]:
    """Return reviewed class overrides encoded from the reference calculation 7989 reference."""

    return [
        WindClassMultiplierOverride(
            direction=reference.direction,  # type: ignore[arg-type]
            terrain_category=reference.terrain_category,  # type: ignore[arg-type]
            shielding_class=reference.shielding_class,  # type: ignore[arg-type]
            topographic_class=reference.topographic_class,  # type: ignore[arg-type]
            reason="Reference calculation 7989 class from source calculation.",
            source_reference=REFERENCE_CALC_7989_SOURCE,
        )
        for reference in reference_calc_7989_reference()
    ]


def reference_calc_7989_osm_footprints() -> list[dict]:
    """Return the bundled OSM footprint snapshot for reference calculation 7989."""

    data = json.loads(REFERENCE_CALC_7989_OSM_FIXTURE.read_text(encoding="utf-8"))
    footprints = data.get("footprints", [])
    if not isinstance(footprints, list):
        return []
    return footprints


def compare_reference_calc_7989(
    *,
    site_result: SiteAnalysisResult,
    obstruction_result: ObstructionInventoryResult,
    terrain_result: TerrainCategoryEvidenceResult,
    class_overrides: list[WindClassMultiplierOverride] | None = None,
) -> ReferenceCalc7989ComparisonReport:
    """Compare OpenWind directional classes against the reference calculation 7989 reference."""

    overrides_by_direction = {
        override.direction: override for override in class_overrides or []
    }
    terrain_by_direction = {
        item.direction: item.recommended_terrain_category
        for item in terrain_result.mzcat_assessment
    }
    shielding_by_direction = {
        sector.direction: shielding_class_from_sector(
            sector.ns,
            sector.total_obstructions_in_sector,
        )
        for sector in obstruction_result.shielding_sectors
    }
    topography_by_direction = {
        feature.direction: topographic_class_from_feature(
            feature.feature_type,
            feature.average_upwind_slope,
        )
        for feature in site_result.features
    }
    comparisons = [
        _direction_comparison(
            reference,
            actual_terrain=(
                overrides_by_direction.get(reference.direction).terrain_category
                if overrides_by_direction.get(reference.direction)
                and overrides_by_direction[reference.direction].terrain_category
                else terrain_by_direction.get(reference.direction)
            ),
            actual_shielding=(
                overrides_by_direction.get(reference.direction).shielding_class
                if overrides_by_direction.get(reference.direction)
                and overrides_by_direction[reference.direction].shielding_class
                else shielding_by_direction.get(reference.direction)
            ),
            actual_topography=(
                overrides_by_direction.get(reference.direction).topographic_class
                if overrides_by_direction.get(reference.direction)
                and overrides_by_direction[reference.direction].topographic_class
                else topography_by_direction.get(reference.direction)
            ),
        )
        for reference in reference_calc_7989_reference()
    ]
    summary = {"match": 0, "mismatch": 0, "not_available": 0}
    for comparison in comparisons:
        for status in (
            comparison.terrain_status,
            comparison.shielding_status,
            comparison.topographic_status,
        ):
            summary[status] += 1
    notes = [
        "Reference calculation 7989 reports TC3 in all directions, FS shielding in all directions, "
        "and T1 topography for NE/E with T0 elsewhere.",
        "This comparison is class-level; it highlights data/classification gaps before "
        "final AS/NZS multipliers are used.",
    ]
    if obstruction_result.data_source_status == "unavailable":
        notes.append("OpenWind obstruction source was unavailable for this run.")
    if len(obstruction_result.obstructions) < 5:
        notes.append("OpenWind obstruction inventory has too few footprints for this reference.")
    return ReferenceCalc7989ComparisonReport(
        summary=summary,
        directions=comparisons,
        notes=notes,
    )


def shielding_class_from_sector(ns: int, total_obstructions_in_sector: int) -> str:
    """Return a coarse reference-style shielding class from OpenWind sector evidence."""

    if ns >= 2:
        return "FS"
    if ns == 1 or total_obstructions_in_sector:
        return "PS"
    return "NS"


def topographic_class_from_feature(feature_type: str, average_upwind_slope: float) -> str:
    """Return a coarse reference-style topographic class from OpenWind screening evidence."""

    if feature_type == "no significant feature":
        return "T0"
    if average_upwind_slope >= REFERENCE_TOPOGRAPHIC_T1_SLOPE:
        return "T1"
    return "T0"


def _direction_comparison(
    reference: ReferenceDirectionReference,
    *,
    actual_terrain: str | None,
    actual_shielding: str | None,
    actual_topography: str | None,
) -> ReferenceDirectionComparison:
    notes = []
    if actual_shielding in {"NS", "PS"} and reference.shielding_class == "FS":
        notes.append(
            "OpenWind shielding evidence is weaker than reference calculation for this direction."
        )
    if actual_terrain and actual_terrain != reference.terrain_category:
        notes.append("OpenWind terrain category recommendation differs from reference calculation.")
    return ReferenceDirectionComparison(
        direction=reference.direction,
        expected_terrain_category=reference.terrain_category,
        actual_terrain_category=actual_terrain,
        terrain_status=_status(actual_terrain, reference.terrain_category),
        expected_shielding_class=reference.shielding_class,
        actual_shielding_class=actual_shielding,
        shielding_status=_status(actual_shielding, reference.shielding_class),
        expected_topographic_class=reference.topographic_class,
        actual_topographic_class=actual_topography,
        topographic_status=_status(actual_topography, reference.topographic_class),
        notes=notes,
    )


def _status(actual: str | None, expected: str) -> ReferenceStatus:
    if actual is None:
        return "not_available"
    return "match" if actual == expected else "mismatch"
