"""Tests for reference calculation reference comparison helpers."""

from __future__ import annotations

from types import SimpleNamespace

from openwind_au.reference_calc_validation import (
    compare_reference_calc_7989,
    reference_calc_7989_class_overrides,
    reference_calc_7989_osm_footprints,
    reference_calc_7989_reference,
    shielding_class_from_sector,
    topographic_class_from_feature,
)


def test_reference_calc_7989_reference_classes_are_encoded() -> None:
    reference = {item.direction: item for item in reference_calc_7989_reference()}

    assert len(reference) == 8
    assert {item.terrain_category for item in reference.values()} == {"TC3"}
    assert {item.shielding_class for item in reference.values()} == {"FS"}
    assert reference["NE"].topographic_class == "T1"
    assert reference["E"].topographic_class == "T1"
    assert reference["N"].topographic_class == "T0"


def test_reference_calc_7989_class_overrides_are_encoded() -> None:
    overrides = {item.direction: item for item in reference_calc_7989_class_overrides()}

    assert len(overrides) == 8
    assert overrides["N"].terrain_category == "TC3"
    assert overrides["N"].shielding_class == "FS"
    assert overrides["NE"].topographic_class == "T1"
    assert overrides["N"].reason
    assert "7989" in (overrides["N"].source_reference or "")


def test_reference_calc_7989_osm_fixture_loads_bundled_footprints() -> None:
    footprints = reference_calc_7989_osm_footprints()

    assert len(footprints) >= 100
    assert all("footprint_geometry" in footprint for footprint in footprints)


def test_reference_calc_class_mapping_helpers() -> None:
    assert shielding_class_from_sector(ns=2, total_obstructions_in_sector=2) == "FS"
    assert shielding_class_from_sector(ns=1, total_obstructions_in_sector=3) == "PS"
    assert shielding_class_from_sector(ns=0, total_obstructions_in_sector=0) == "NS"

    assert topographic_class_from_feature("no significant feature", 0.0) == "T0"
    assert topographic_class_from_feature("ridge", 0.05) == "T0"
    assert topographic_class_from_feature("ridge", 0.12) == "T1"


def test_compare_reference_calc_7989_reports_directional_mismatches() -> None:
    directions = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    site_result = SimpleNamespace(
        features=[
            SimpleNamespace(
                direction=direction,
                feature_type="ridge" if direction in {"NE", "E"} else "no significant feature",
                average_upwind_slope=0.12 if direction in {"NE", "E"} else 0.0,
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

    report = compare_reference_calc_7989(
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


def test_compare_reference_calc_7989_can_apply_reference_class_overrides() -> None:
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

    report = compare_reference_calc_7989(
        site_result=site_result,
        obstruction_result=obstruction_result,
        terrain_result=terrain_result,
        class_overrides=reference_calc_7989_class_overrides(),
    )

    assert report.summary == {"match": 24, "mismatch": 0, "not_available": 0}
