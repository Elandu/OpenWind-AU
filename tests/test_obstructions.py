"""Tests for building obstruction inventory."""

from __future__ import annotations

import pytest

import openwind_au.obstructions as obstructions_module
from openwind_au.models import ObstructionInventoryRequest, ObstructionManualOverride
from openwind_au.obstructions import (
    FootprintQueryError,
    apply_manual_overrides,
    build_obstruction_records,
    height_from_tags,
    parse_manual_overrides_csv,
    run_obstruction_inventory,
)


def square_footprint(
    source_id: str = "osm-way-1",
    tags: dict | None = None,
    lon_offset: float = 0.001,
) -> dict:
    lon = 151.21 + lon_offset
    lat = -33.86
    ring = [
        [lon - 0.00005, lat - 0.00005],
        [lon + 0.00005, lat - 0.00005],
        [lon + 0.00005, lat + 0.00005],
        [lon - 0.00005, lat + 0.00005],
        [lon - 0.00005, lat - 0.00005],
    ]
    return {
        "source_id": source_id,
        "footprint_geometry": {"type": "Polygon", "coordinates": [ring]},
        "tags": tags or {},
    }


def test_explicit_height_tag_wins_over_levels() -> None:
    result = height_from_tags({"height": "12.5 m", "building:levels": "3"})

    assert result["height_m"] == pytest.approx(12.5)
    assert result["building_levels"] == pytest.approx(3)
    assert result["height_source"] == "explicit_height"
    assert result["confidence"] == "high"
    assert result["manual_review_required"] is False


def test_building_levels_convert_using_configured_storey_height() -> None:
    result = height_from_tags({"building:levels": "4"}, default_storey_height_m=3.2)

    assert result["height_m"] == pytest.approx(12.8)
    assert result["building_levels"] == pytest.approx(4)
    assert result["height_source"] == "building_levels"
    assert result["confidence"] == "medium"
    assert result["manual_review_required"] is True


def test_missing_height_does_not_infer_from_footprint_size() -> None:
    result = height_from_tags({})

    assert result["height_m"] is None
    assert result["building_levels"] is None
    assert result["height_source"] == "missing"
    assert result["confidence"] == "unknown"
    assert result["manual_review_required"] is True


def test_manual_override_replaces_missing_height() -> None:
    records = build_obstruction_records(
        [square_footprint(tags={})],
        site_latitude=-33.86,
        site_longitude=151.21,
        radius_m=500,
    )

    updated = apply_manual_overrides(
        records,
        [ObstructionManualOverride(obstruction_id="osm-way-1", height_m=9.5)],
    )

    assert updated[0].height_m == pytest.approx(9.5)
    assert updated[0].height_source == "manual_override"
    assert updated[0].confidence == "verified"
    assert updated[0].manual_review_required is False


def test_distance_and_bearing_are_calculated_from_site_to_centroid() -> None:
    records = build_obstruction_records(
        [square_footprint(tags={"height": "6"}, lon_offset=0.001)],
        site_latitude=-33.86,
        site_longitude=151.21,
        radius_m=500,
    )

    assert len(records) == 1
    assert records[0].distance_m == pytest.approx(92, abs=10)
    assert records[0].bearing_deg == pytest.approx(90, abs=5)


def test_csv_overrides_parse_reviewed_heights() -> None:
    overrides = parse_manual_overrides_csv(
        "obstruction_id,height_m,building_levels,notes\nosm-way-1,8.2,2,checked"
    )

    assert overrides[0].obstruction_id == "osm-way-1"
    assert overrides[0].height_m == pytest.approx(8.2)
    assert overrides[0].building_levels == pytest.approx(2)
    assert overrides[0].notes == "checked"


def test_run_obstruction_inventory_uses_supplied_footprints() -> None:
    result = run_obstruction_inventory(
        ObstructionInventoryRequest(
            latitude=-33.86,
            longitude=151.21,
            radius_m=500,
            default_storey_height_m=3.0,
        ),
        footprints=[
            square_footprint("osm-way-height", {"height": "10"}),
            square_footprint("osm-way-levels", {"building:levels": "2"}, lon_offset=0.002),
            square_footprint("osm-way-missing", {}, lon_offset=0.003),
        ],
    )

    assert len(result.obstructions) == 3
    assert result.missing_height_count == 1
    assert {item.height_source for item in result.obstructions} == {
        "explicit_height",
        "building_levels",
        "missing",
    }


def test_run_obstruction_inventory_returns_warning_when_footprint_source_fails(
    monkeypatch,
) -> None:
    def fail_query(*_args, **_kwargs):
        raise FootprintQueryError("Overpass unavailable")

    monkeypatch.setattr(obstructions_module, "query_building_footprints", fail_query)

    result = run_obstruction_inventory(
        ObstructionInventoryRequest(
            latitude=-33.86,
            longitude=151.21,
            radius_m=500,
            default_storey_height_m=3.0,
        ),
    )

    assert result.data_source_status == "unavailable"
    assert result.obstructions == []
    assert result.warnings
    assert "Ms is not calculated" in result.warnings[0]
