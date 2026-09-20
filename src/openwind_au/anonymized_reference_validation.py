"""Anonymized reference comparisons for deterministic regression testing."""

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

AnonymizedReferenceStatus = Literal["match", "mismatch", "not_available"]

ANONYMIZED_REFERENCE_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
ANONYMIZED_REFERENCE_SOURCE = "Anonymized class-level project reference"
ANONYMIZED_REFERENCE_FIXTURE_ID = "anonymized-reference-osm-footprints-v1"
ANONYMIZED_REFERENCE_LATITUDE = -27.395503
ANONYMIZED_REFERENCE_LONGITUDE = 152.811814
ANONYMIZED_REFERENCE_WIND_REGION = "B1"
REFERENCE_TOPOGRAPHIC_T1_SLOPE = 0.18
_PACKAGED_ANONYMIZED_REFERENCE_OSM_FIXTURE = (
    Path(__file__).resolve().parent / "data" / "anonymized_reference_osm_footprints.json"
)
_SOURCE_ANONYMIZED_REFERENCE_OSM_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "validation"
    / "anonymized_reference_osm_footprints.json"
)
ANONYMIZED_REFERENCE_TOPOGRAPHY = {
    "N": "T0",
    "NE": "T1",
    "E": "T1",
    "SE": "T0",
    "S": "T0",
    "SW": "T0",
    "W": "T0",
    "NW": "T0",
}


class AnonymizedReferenceDirection(BaseModel):
    """Expected anonymized reference classes for one wind sector."""

    direction: str
    terrain_category: str
    shielding_class: str
    topographic_class: str


class AnonymizedDirectionComparison(BaseModel):
    """OpenWind comparison against one anonymized directional reference."""

    direction: str
    expected_terrain_category: str
    actual_terrain_category: str | None = None
    terrain_status: AnonymizedReferenceStatus
    expected_shielding_class: str
    actual_shielding_class: str | None = None
    shielding_status: AnonymizedReferenceStatus
    expected_topographic_class: str
    actual_topographic_class: str | None = None
    topographic_status: AnonymizedReferenceStatus
    notes: list[str] = Field(default_factory=list)


class AnonymizedReferenceComparisonReport(BaseModel):
    """Anonymized reference comparison report."""

    case_id: str = "anonymized-reference-b1"
    source_reference: str = ANONYMIZED_REFERENCE_SOURCE
    fixture_id: str = ANONYMIZED_REFERENCE_FIXTURE_ID
    fixture_notice: str = (
        "Synthetic translated coordinates; original project and source-feature identifiers removed."
    )
    data_attribution: str = "© OpenStreetMap contributors"
    data_license: str = "Open Data Commons Open Database License (ODbL) 1.0"
    latitude: float = ANONYMIZED_REFERENCE_LATITUDE
    longitude: float = ANONYMIZED_REFERENCE_LONGITUDE
    building_height_m: float = 4.0
    wind_region: str = ANONYMIZED_REFERENCE_WIND_REGION
    vh_ult_mps: float = 40.0
    vh_serv_mps: float = 26.0
    critical_direction: str = "North"
    wind_class: str = "N2"
    wind_pressure_kpa: float = 0.9600
    summary: dict[str, int]
    directions: list[AnonymizedDirectionComparison]
    notes: list[str] = Field(default_factory=list)


def anonymized_reference() -> list[AnonymizedReferenceDirection]:
    """Return the anonymized directional class reference."""

    return [
        AnonymizedReferenceDirection(
            direction=direction,
            terrain_category="TC3",
            shielding_class="FS",
            topographic_class=ANONYMIZED_REFERENCE_TOPOGRAPHY[direction],
        )
        for direction in ANONYMIZED_REFERENCE_DIRECTIONS
    ]


def anonymized_reference_class_overrides() -> list[WindClassMultiplierOverride]:
    """Return reviewed class overrides encoded from the anonymized reference."""

    return [
        WindClassMultiplierOverride(
            direction=reference.direction,  # type: ignore[arg-type]
            terrain_category=reference.terrain_category,  # type: ignore[arg-type]
            shielding_class=reference.shielding_class,  # type: ignore[arg-type]
            topographic_class=reference.topographic_class,  # type: ignore[arg-type]
            reason="Anonymized reference class from a reviewed source calculation.",
            source_reference=ANONYMIZED_REFERENCE_SOURCE,
        )
        for reference in anonymized_reference()
    ]


def anonymized_reference_fixture_metadata() -> dict:
    """Return public metadata for the anonymized OSM-derived fixture."""

    data = _load_anonymized_reference_fixture()
    metadata = data.get("metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def anonymized_reference_osm_footprints() -> list[dict]:
    """Return the bundled anonymized and translated OSM-derived footprints."""

    data = _load_anonymized_reference_fixture()
    site = data.get("site", {})
    if not isinstance(site, dict) or site.get("wind_region") != ANONYMIZED_REFERENCE_WIND_REGION:
        raise ValueError("Anonymized reference fixture must identify expected wind Region B1.")
    if (
        site.get("latitude") != ANONYMIZED_REFERENCE_LATITUDE
        or site.get("longitude") != ANONYMIZED_REFERENCE_LONGITUDE
    ):
        raise ValueError(
            "Anonymized reference fixture site does not match the published constants."
        )
    footprints = data.get("footprints", [])
    if not isinstance(footprints, list):
        return []
    return footprints


def _load_anonymized_reference_fixture() -> dict:
    """Load the source-tree or installed-wheel anonymized fixture."""

    fixture_path = (
        _PACKAGED_ANONYMIZED_REFERENCE_OSM_FIXTURE
        if _PACKAGED_ANONYMIZED_REFERENCE_OSM_FIXTURE.exists()
        else _SOURCE_ANONYMIZED_REFERENCE_OSM_FIXTURE
    )
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Anonymized reference fixture must be a JSON object.")
    return data


def compare_anonymized_reference(
    *,
    site_result: SiteAnalysisResult,
    obstruction_result: ObstructionInventoryResult,
    terrain_result: TerrainCategoryEvidenceResult,
    class_overrides: list[WindClassMultiplierOverride] | None = None,
) -> AnonymizedReferenceComparisonReport:
    """Compare OpenWind directional classes against the anonymized reference."""

    overrides_by_direction = {override.direction: override for override in class_overrides or []}
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
        for reference in anonymized_reference()
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
        "The anonymized reference reports TC3 in all directions, FS shielding in all directions, "
        "and T1 topography for NE/E with T0 elsewhere.",
        "This comparison is class-level; it highlights data/classification gaps before "
        "final AS/NZS multipliers are used.",
    ]
    if obstruction_result.data_source_status == "unavailable":
        notes.append("OpenWind obstruction source was unavailable for this run.")
    if len(obstruction_result.obstructions) < 5:
        notes.append("OpenWind obstruction inventory has too few footprints for this reference.")
    return AnonymizedReferenceComparisonReport(
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
    reference: AnonymizedReferenceDirection,
    *,
    actual_terrain: str | None,
    actual_shielding: str | None,
    actual_topography: str | None,
) -> AnonymizedDirectionComparison:
    notes = []
    if actual_shielding in {"NS", "PS"} and reference.shielding_class == "FS":
        notes.append(
            "OpenWind shielding evidence is weaker than reference calculation for this direction."
        )
    if actual_terrain and actual_terrain != reference.terrain_category:
        notes.append("OpenWind terrain category recommendation differs from reference calculation.")
    return AnonymizedDirectionComparison(
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


def _status(actual: str | None, expected: str) -> AnonymizedReferenceStatus:
    if actual is None:
        return "not_available"
    return "match" if actual == expected else "mismatch"
