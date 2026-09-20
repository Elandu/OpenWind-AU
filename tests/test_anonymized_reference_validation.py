"""Tests for anonymized reference comparison helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from openwind_au.anonymized_reference_validation import (
    ANONYMIZED_REFERENCE_LATITUDE,
    ANONYMIZED_REFERENCE_LONGITUDE,
    ANONYMIZED_REFERENCE_WIND_REGION,
    anonymized_reference,
    anonymized_reference_class_overrides,
    anonymized_reference_fixture_metadata,
    anonymized_reference_osm_footprints,
    compare_anonymized_reference,
    shielding_class_from_sector,
    topographic_class_from_feature,
)
from openwind_au.models import SiteLocation
from openwind_au.wind_region import assess_wind_region

WIND_REGION_FIXTURE = Path(__file__).parent / "fixtures" / "wind_regions_sample.geojson"


def test_anonymized_reference_classes_are_encoded() -> None:
    reference = {item.direction: item for item in anonymized_reference()}

    assert len(reference) == 8
    assert {item.terrain_category for item in reference.values()} == {"TC3"}
    assert {item.shielding_class for item in reference.values()} == {"FS"}
    assert reference["NE"].topographic_class == "T1"
    assert reference["E"].topographic_class == "T1"
    assert reference["N"].topographic_class == "T0"


def test_anonymized_reference_class_overrides_are_encoded() -> None:
    overrides = {item.direction: item for item in anonymized_reference_class_overrides()}

    assert len(overrides) == 8
    assert overrides["N"].terrain_category == "TC3"
    assert overrides["N"].shielding_class == "FS"
    assert overrides["NE"].topographic_class == "T1"
    assert overrides["N"].reason
    assert overrides["N"].source_reference == "Anonymized class-level project reference"


def test_anonymized_osm_fixture_is_translated_stripped_and_attributed() -> None:
    metadata = anonymized_reference_fixture_metadata()
    footprints = anonymized_reference_osm_footprints()

    assert len(footprints) >= 100
    assert all(set(footprint) == {"footprint_geometry"} for footprint in footprints)
    assert metadata["fixture_id"] == "anonymized-reference-osm-footprints-v1"
    assert metadata["expected_wind_region"] == ANONYMIZED_REFERENCE_WIND_REGION == "B1"
    assert metadata["privacy"]["relative_geometry_preserved"] is True
    assert metadata["privacy"]["original_coordinates_included"] is False
    assert metadata["privacy"]["original_feature_identifiers_included"] is False
    assert metadata["privacy"]["source_tags_included"] is False
    assert metadata["attribution"]["copyright"] == "© OpenStreetMap contributors"
    assert "ODbL" in metadata["attribution"]["license"]


def test_anonymized_site_remains_in_fixture_region_b1(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(WIND_REGION_FIXTURE))
    site = SiteLocation(
        latitude=ANONYMIZED_REFERENCE_LATITUDE,
        longitude=ANONYMIZED_REFERENCE_LONGITUDE,
        ground_elevation_m=0.0,
        source="anonymized reference fixture",
    )

    assert assess_wind_region(site).wind_region == "B1"


def test_anonymized_reference_class_mapping_helpers() -> None:
    assert shielding_class_from_sector(ns=2, total_obstructions_in_sector=2) == "FS"
    assert shielding_class_from_sector(ns=1, total_obstructions_in_sector=3) == "PS"
    assert shielding_class_from_sector(ns=0, total_obstructions_in_sector=0) == "NS"

    assert topographic_class_from_feature("no significant feature", 0.0) == "T0"
    assert topographic_class_from_feature("ridge", 0.05) == "T0"
    assert topographic_class_from_feature("ridge", 0.12) == "T0"
    assert topographic_class_from_feature("ridge", 0.18) == "T1"


def test_compare_anonymized_reference_reports_directional_mismatches() -> None:
    directions = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    site_result = SimpleNamespace(
        features=[
            SimpleNamespace(
                direction=direction,
                feature_type="ridge" if direction in {"NE", "E"} else "no significant feature",
                average_upwind_slope=0.18 if direction in {"NE", "E"} else 0.0,
            )
            for direction in directions
        ]
    )
    obstruction_result = SimpleNamespace(
        data_source_status="ok",
        obstructions=[object()] * 8,
        shielding_sectors=[
            SimpleNamespace(direction=direction, ns=0, total_obstructions_in_sector=0)
            for direction in directions
        ],
    )
    terrain_result = SimpleNamespace(
        mzcat_assessment=[
            SimpleNamespace(direction=direction, recommended_terrain_category="TC2")
            for direction in directions
        ]
    )

    report = compare_anonymized_reference(
        site_result=site_result,
        obstruction_result=obstruction_result,
        terrain_result=terrain_result,
    )

    assert report.summary["mismatch"] == 16
    assert report.summary["match"] == 8
    north = next(item for item in report.directions if item.direction == "N")
    assert north.expected_terrain_category == "TC3"
    assert north.actual_terrain_category == "TC2"
    assert north.actual_shielding_class == "NS"
    assert report.wind_region == ANONYMIZED_REFERENCE_WIND_REGION
    assert report.latitude == ANONYMIZED_REFERENCE_LATITUDE
    assert report.longitude == ANONYMIZED_REFERENCE_LONGITUDE
    assert report.fixture_notice.startswith("Synthetic translated coordinates")
    assert report.data_attribution == "© OpenStreetMap contributors"
    assert "ODbL" in report.data_license


def test_compare_anonymized_reference_can_apply_reference_class_overrides() -> None:
    directions = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    site_result = SimpleNamespace(
        features=[
            SimpleNamespace(
                direction=direction,
                feature_type="no significant feature",
                average_upwind_slope=0.0,
            )
            for direction in directions
        ]
    )
    obstruction_result = SimpleNamespace(
        data_source_status="ok",
        obstructions=[],
        shielding_sectors=[
            SimpleNamespace(direction=direction, ns=0, total_obstructions_in_sector=0)
            for direction in directions
        ],
    )
    terrain_result = SimpleNamespace(
        mzcat_assessment=[
            SimpleNamespace(direction=direction, recommended_terrain_category="TC2")
            for direction in directions
        ]
    )

    report = compare_anonymized_reference(
        site_result=site_result,
        obstruction_result=obstruction_result,
        terrain_result=terrain_result,
        class_overrides=anonymized_reference_class_overrides(),
    )

    assert report.summary == {"match": 24, "mismatch": 0, "not_available": 0}
