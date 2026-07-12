"""Tests for building obstruction inventory."""

from __future__ import annotations

import pytest

import openwind_au.obstructions as obstructions_module
from openwind_au.microsoft_footprints import (
    MICROSOFT_FOOTPRINT_SOURCE,
    MicrosoftFootprintResult,
)
from openwind_au.models import (
    ObstructionInventoryRequest,
    ObstructionManualOverride,
    ReviewedFootprint,
    SiteLocation,
)
from openwind_au.obstructions import (
    COMMON_OSM_BUILDING_VALUES,
    FootprintQueryError,
    apply_manual_overrides,
    build_obstruction_records,
    build_overpass_building_query,
    geometry_overlap_ratio,
    height_from_tags,
    is_common_osm_building_tag,
    parse_manual_overrides_csv,
    query_building_footprints_with_debug,
    run_obstruction_inventory,
)


def square_footprint(
    source_id: str = "osm-way-1",
    tags: dict | None = None,
    lon_offset: float = 0.001,
    footprint_source: str = "OSM",
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
        "footprint_source": footprint_source,
    }


def microsoft_result(footprints: list[dict] | None = None) -> MicrosoftFootprintResult:
    return MicrosoftFootprintResult(
        footprints=footprints or [],
        source_status="available" if footprints else "unavailable",
        cache_status="hit" if footprints else "miss",
        cache_path="test-cache",
        cache_files=["test-cache/-34_151.geojson"] if footprints else [],
    )


def overpass_way(element_id: int, building: str, lon_offset: float) -> dict:
    lon = 151.21 + lon_offset
    lat = -33.86
    return {
        "type": "way",
        "id": element_id,
        "tags": {"building": building},
        "geometry": [
            {"lon": lon - 0.00003, "lat": lat - 0.00003},
            {"lon": lon + 0.00003, "lat": lat - 0.00003},
            {"lon": lon + 0.00003, "lat": lat + 0.00003},
            {"lon": lon - 0.00003, "lat": lat + 0.00003},
        ],
    }


def overpass_relation(element_id: int, building: str, lon_offset: float) -> dict:
    lon = 151.21 + lon_offset
    lat = -33.86
    return {
        "type": "relation",
        "id": element_id,
        "tags": {"building": building, "type": "multipolygon"},
        "members": [
            {
                "role": "outer",
                "type": "way",
                "ref": element_id * 10,
                "geometry": [
                    {"lon": lon - 0.00003, "lat": lat - 0.00003},
                    {"lon": lon + 0.00003, "lat": lat - 0.00003},
                    {"lon": lon + 0.00003, "lat": lat + 0.00003},
                    {"lon": lon - 0.00003, "lat": lat + 0.00003},
                ],
            }
        ],
    }


def test_explicit_height_tag_wins_over_levels() -> None:
    result = height_from_tags({"height": "12.5 m", "building:levels": "3"})

    assert result["height_m"] == pytest.approx(12.5)
    assert result["building_levels"] == pytest.approx(3)
    assert result["height_source"] == "OSM_HEIGHT"
    assert result["confidence"] == "medium"
    assert result["manual_review_required"] is True


@pytest.mark.parametrize(
    ("raw_height", "expected_m"),
    [("3000 mm", 3.0), ("350 cm", 3.5), ("10 ft", 3.048), ("12.5 m", 12.5)],
)
def test_height_tags_parse_supported_units(raw_height, expected_m) -> None:
    result = height_from_tags({"height": raw_height})

    assert result["height_m"] == pytest.approx(expected_m)


@pytest.mark.parametrize("raw_height", ["inf", "NaN", "600 m", "12 metres extra"])
def test_height_tags_reject_non_finite_or_implausible_values(raw_height) -> None:
    result = height_from_tags({"height": raw_height})

    assert result["height_m"] is None


def test_building_levels_convert_using_configured_storey_height() -> None:
    result = height_from_tags({"building:levels": "4"}, default_storey_height_m=3.2)

    assert result["height_m"] == pytest.approx(12.8)
    assert result["building_levels"] == pytest.approx(4)
    assert result["height_source"] == "OSM_LEVELS"
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
    assert updated[0].height_source == "manual_verified"
    assert updated[0].confidence == "high"
    assert updated[0].manual_review_required is False
    assert updated[0].review_required is False
    assert updated[0].selected_height_m == pytest.approx(9.5)


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
        "OSM_HEIGHT",
        "OSM_LEVELS",
        "missing",
    }
    assert result.height_source_summary["OSM Height"] == 1
    assert result.height_source_summary["OSM Levels"] == 1
    assert result.height_source_summary["Unknown"] == 1


def test_inventory_closes_environment_raster_providers(monkeypatch) -> None:
    class ClosableElevation:
        def __init__(self, value: float) -> None:
            self.value = value
            self.closed = False

        def elevation(self, latitude: float, longitude: float) -> float:
            del latitude, longitude
            return self.value

        def close(self) -> None:
            self.closed = True

    dsm = ClosableElevation(60)
    dtm = ClosableElevation(50)

    def fake_environment_providers(*, load_dsm: bool, load_dtm: bool):
        assert load_dsm is True
        assert load_dtm is True
        return dsm, dtm, []

    monkeypatch.setattr(
        obstructions_module,
        "elevation_providers_from_env",
        fake_environment_providers,
    )

    run_obstruction_inventory(
        ObstructionInventoryRequest(
            latitude=-33.86,
            longitude=151.21,
            radius_m=500,
        ),
        footprints=[square_footprint(tags={})],
    )

    assert dsm.closed is True
    assert dtm.closed is True


def test_inventory_uses_resolved_site_elevation_for_shielding_gradient() -> None:
    class ConstantElevation:
        def __init__(self, value: float) -> None:
            self.value = value

        def elevation(self, latitude: float, longitude: float) -> float:
            del latitude, longitude
            return self.value

    result = run_obstruction_inventory(
        ObstructionInventoryRequest(
            address="Resolved address",
            radius_m=500,
            building_height_m=10,
        ),
        footprints=[square_footprint(tags={})],
        dsm_provider=ConstantElevation(20),
        dtm_provider=ConstantElevation(10),
        resolved_site=SiteLocation(
            latitude=-33.86,
            longitude=151.21,
            ground_elevation_m=50,
            source="resolved test site",
            display_name="Resolved address",
        ),
    )

    east = next(sector for sector in result.shielding_sectors if sector.direction == "E")
    assert result.site.ground_elevation_m == 50
    assert east.ns == 0
    assert east.rejection_reason_counts == {"steep_upwind_ground_gradient": 1}


def test_run_obstruction_inventory_returns_warning_when_footprint_source_fails(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("OPENWIND_OSM_FOOTPRINT_CACHE", str(tmp_path))

    def fail_query(*_args, **_kwargs):
        raise FootprintQueryError("Overpass unavailable")

    def missing_microsoft(*_args, **_kwargs):
        return microsoft_result([])

    monkeypatch.setattr(
        obstructions_module, "query_microsoft_building_footprints", missing_microsoft
    )
    monkeypatch.setattr(obstructions_module, "query_building_footprints_with_debug", fail_query)

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
    assert any("indicative Ms cannot be calculated" in warning for warning in result.warnings)


def test_common_osm_building_tags_are_included() -> None:
    expected = {
        "yes",
        "house",
        "residential",
        "detached",
        "semidetached_house",
        "terrace",
        "apartments",
        "commercial",
        "industrial",
        "retail",
        "school",
        "roof",
        "garage",
        "shed",
    }

    assert expected <= COMMON_OSM_BUILDING_VALUES
    for value in expected:
        assert is_common_osm_building_tag({"building": value})


def test_overpass_building_query_is_broad_and_unrestricted() -> None:
    query = build_overpass_building_query(-33.86, 151.21, 500)

    assert 'way(around:500,-33.86,151.21)["building"]' in query
    assert 'relation(around:500,-33.86,151.21)["building"]' in query
    assert "out body geom" in query
    assert "building:levels" not in query
    assert "height" not in query
    assert "residential" not in query


def test_missing_height_buildings_are_retained() -> None:
    footprint = square_footprint(tags={"building": "house"})

    records = build_obstruction_records(
        [footprint],
        site_latitude=-33.86,
        site_longitude=151.21,
        radius_m=500,
    )

    assert len(records) == 1
    assert records[0].height_source == "missing"
    assert records[0].height_m is None
    assert records[0].footprint_geometry == footprint["footprint_geometry"]


def test_generic_osm_building_yes_gets_reviewable_residential_height() -> None:
    result = run_obstruction_inventory(
        ObstructionInventoryRequest(latitude=-33.86, longitude=151.21, radius_m=500),
        footprints=[square_footprint(tags={"building": "yes"})],
    )

    assert len(result.obstructions) == 1
    record = result.obstructions[0]
    assert record.classification == "residential"
    assert record.height_source == "ESTIMATED"
    assert record.selected_height_m == pytest.approx(3.0)
    assert record.review_required is True


def test_polygon_geometry_is_preserved_for_shielding_breadth() -> None:
    footprint = square_footprint(tags={"height": "7"})

    records = build_obstruction_records(
        [footprint],
        site_latitude=-33.86,
        site_longitude=151.21,
        radius_m=500,
    )

    assert (
        records[0].footprint_geometry["coordinates"][0]
        == footprint["footprint_geometry"]["coordinates"][0]
    )


def test_excluded_reason_tracking() -> None:
    invalid = {
        "source_id": "osm-way-invalid",
        "footprint_geometry": {"type": "Point", "coordinates": [151.21, -33.86]},
        "tags": {"building": "yes"},
    }
    outside = square_footprint(
        "osm-way-outside",
        {"building": "yes", "height": "5"},
        lon_offset=0.1,
    )
    inside = square_footprint("osm-way-inside", {"building": "yes", "height": "5"}, lon_offset=0)

    result = run_obstruction_inventory(
        ObstructionInventoryRequest(latitude=-33.86, longitude=151.21, radius_m=100),
        footprints=[invalid, outside, inside],
    )

    assert len(result.obstructions) == 1
    assert result.data_quality.number_excluded == 2
    assert result.data_quality.excluded_reasons["invalid_or_missing_polygon_geometry"] == 1
    assert result.data_quality.excluded_reasons["outside_inventory_radius"] == 1


def test_mocked_overpass_building_tags_and_relation_are_retained(monkeypatch) -> None:
    elements = [
        overpass_way(1, "yes", 0.0000),
        overpass_way(2, "house", 0.0002),
        overpass_way(3, "detached", 0.0004),
        overpass_way(4, "residential", 0.0006),
        overpass_way(5, "garage", 0.0008),
        overpass_way(6, "shed", 0.0010),
        overpass_relation(7, "yes", 0.0012),
    ]

    def fake_post_overpass(_query, _user_agent):
        return {"elements": elements}

    monkeypatch.setattr(obstructions_module, "_post_overpass", fake_post_overpass)

    footprints, debug = query_building_footprints_with_debug(-33.86, 151.21, 500)
    result = run_obstruction_inventory(
        ObstructionInventoryRequest(latitude=-33.86, longitude=151.21, radius_m=500),
        footprints=footprints,
    )

    assert len(footprints) == 7
    assert len(result.obstructions) == 7
    assert result.data_quality.total_osm_building_footprints_found == 7
    assert debug["raw_overpass_counts"]["building_tagged_ways"] == 6
    assert debug["raw_overpass_counts"]["building_tagged_relations"] == 1
    assert debug["parsed_counts"]["converted_way_polygons"] == 6
    assert debug["parsed_counts"]["converted_relation_polygons"] == 1
    assert all(record.height_source in {"missing", "ESTIMATED"} for record in result.obstructions)


def test_overpass_debug_reports_nodes_and_missing_geometry(monkeypatch) -> None:
    elements = [
        {"type": "node", "id": 100, "tags": {"building": "yes"}, "lat": -33.86, "lon": 151.21},
        {"type": "way", "id": 101, "tags": {"building": "yes"}},
    ]

    def fake_post_overpass(_query, _user_agent):
        return {"elements": elements}

    monkeypatch.setattr(obstructions_module, "_post_overpass", fake_post_overpass)

    footprints, debug = query_building_footprints_with_debug(-33.86, 151.21, 500)

    assert footprints == []
    assert debug["raw_overpass_counts"]["nodes"] == 1
    assert debug["raw_overpass_counts"]["building_tagged_ways"] == 1
    assert debug["parsed_counts"]["building_elements_without_polygon_geometry"] == 2
    assert "osm-node-100" in " ".join(debug["pipeline_log"])


def test_microsoft_footprints_are_used_when_overpass_fails(monkeypatch) -> None:
    microsoft = square_footprint(
        "ms-au-1",
        {},
        lon_offset=0,
        footprint_source=MICROSOFT_FOOTPRINT_SOURCE,
    )

    def fake_microsoft(*_args, **_kwargs):
        return microsoft_result([microsoft])

    def fail_query(*_args, **_kwargs):
        raise FootprintQueryError("Overpass unavailable")

    monkeypatch.setattr(obstructions_module, "query_microsoft_building_footprints", fake_microsoft)
    monkeypatch.setattr(obstructions_module, "query_building_footprints_with_debug", fail_query)

    result = run_obstruction_inventory(
        ObstructionInventoryRequest(latitude=-33.86, longitude=151.21, radius_m=500)
    )

    assert result.data_source_status == "ok"
    assert len(result.obstructions) == 1
    assert result.obstructions[0].footprint_source == MICROSOFT_FOOTPRINT_SOURCE
    assert result.data_quality.total_microsoft_building_footprints_found == 1
    assert result.data_quality.microsoft_cache_status == "hit"
    assert "live Overpass enrichment was skipped" in " ".join(result.warnings)


def test_osm_footprint_cache_reused_when_live_overpass_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENWIND_OSM_FOOTPRINT_CACHE", str(tmp_path))

    def missing_microsoft(*_args, **_kwargs):
        return microsoft_result([])

    footprints = [square_footprint("osm-cached", {"building": "yes"})]
    debug = obstructions_module.empty_overpass_debug(-33.86, 151.21, 500)
    debug["raw_overpass_counts"] = {
        "raw_elements": 1,
        "nodes": 0,
        "ways": 1,
        "relations": 0,
        "building_tagged_ways": 1,
        "building_tagged_relations": 0,
    }
    debug["parsed_counts"] = {
        "converted_to_polygons": 1,
        "converted_way_polygons": 1,
        "converted_relation_polygons": 0,
        "building_elements_without_polygon_geometry": 0,
        "relation_multipolygons_reported_incomplete": 0,
    }
    calls = {"count": 0}

    def flaky_osm(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return footprints, debug
        raise FootprintQueryError("Overpass unavailable")

    monkeypatch.setattr(
        obstructions_module, "query_microsoft_building_footprints", missing_microsoft
    )
    monkeypatch.setattr(obstructions_module, "query_building_footprints_with_debug", flaky_osm)

    request = ObstructionInventoryRequest(latitude=-33.86, longitude=151.21, radius_m=500)
    first = run_obstruction_inventory(request)
    second = run_obstruction_inventory(request)

    assert len(first.obstructions) == 1
    assert len(second.obstructions) == 1
    assert second.data_source_status == "ok"
    assert second.data_quality.total_osm_building_footprints_found == 1
    assert "reused cached OSM footprint geometry" in " ".join(second.warnings)


def test_reviewed_geometry_has_priority_over_microsoft(monkeypatch) -> None:
    microsoft = square_footprint(
        "ms-au-1",
        {},
        lon_offset=0,
        footprint_source=MICROSOFT_FOOTPRINT_SOURCE,
    )
    reviewed_geometry = microsoft["footprint_geometry"]

    def fake_microsoft(*_args, **_kwargs):
        return microsoft_result([microsoft])

    def fake_osm(*_args, **_kwargs):
        return [], obstructions_module.empty_overpass_debug(-33.86, 151.21, 500)

    monkeypatch.setattr(obstructions_module, "query_microsoft_building_footprints", fake_microsoft)
    monkeypatch.setattr(obstructions_module, "query_building_footprints_with_debug", fake_osm)
    monkeypatch.setenv("OPENWIND_OVERPASS_ENRICH_MICROSOFT", "1")

    result = run_obstruction_inventory(
        ObstructionInventoryRequest(
            latitude=-33.86,
            longitude=151.21,
            radius_m=500,
            reviewed_footprints=[
                ReviewedFootprint(
                    id="manual-reviewed-1",
                    geometry=reviewed_geometry,
                    classification="residential",
                    height_m=8.0,
                )
            ],
        )
    )

    assert len(result.obstructions) == 1
    assert result.obstructions[0].footprint_source == "manual_reviewed"
    assert result.obstructions[0].height_source == "manual_verified"
    assert result.obstructions[0].height_m == pytest.approx(8.0)
    assert result.data_quality.excluded_reasons["duplicate_manual_reviewed_overlap"] == 1


def test_osm_is_fallback_when_microsoft_cache_misses(monkeypatch) -> None:
    osm = square_footprint("osm-way-fallback", {"building": "yes", "height": "5"}, lon_offset=0)

    def fake_microsoft(*_args, **_kwargs):
        return microsoft_result([])

    def fake_osm(*_args, **_kwargs):
        return [osm], obstructions_module.empty_overpass_debug(-33.86, 151.21, 500)

    monkeypatch.setattr(obstructions_module, "query_microsoft_building_footprints", fake_microsoft)
    monkeypatch.setattr(obstructions_module, "query_building_footprints_with_debug", fake_osm)
    monkeypatch.setenv("OPENWIND_OVERPASS_ENRICH_MICROSOFT", "1")

    result = run_obstruction_inventory(
        ObstructionInventoryRequest(latitude=-33.86, longitude=151.21, radius_m=500)
    )

    assert len(result.obstructions) == 1
    assert result.obstructions[0].footprint_source == "OSM"
    assert result.data_quality.osm_fallback_used is True
    assert result.data_quality.total_microsoft_building_footprints_found == 0


def test_duplicate_overlap_prefers_microsoft_geometry_and_merges_osm_height(
    monkeypatch,
) -> None:
    osm = square_footprint("osm-way-duplicate", {"building": "yes", "height": "5"}, lon_offset=0)
    microsoft = {
        **square_footprint(
            "ms-au-duplicate",
            {},
            lon_offset=0,
            footprint_source=MICROSOFT_FOOTPRINT_SOURCE,
        ),
        "source_provenance": ["ms-au-duplicate"],
    }

    def fake_microsoft(*_args, **_kwargs):
        return microsoft_result([microsoft])

    def fake_osm(*_args, **_kwargs):
        return [osm], obstructions_module.empty_overpass_debug(-33.86, 151.21, 500)

    monkeypatch.setattr(obstructions_module, "query_microsoft_building_footprints", fake_microsoft)
    monkeypatch.setattr(obstructions_module, "query_building_footprints_with_debug", fake_osm)
    monkeypatch.setenv("OPENWIND_OVERPASS_ENRICH_MICROSOFT", "1")

    result = run_obstruction_inventory(
        ObstructionInventoryRequest(latitude=-33.86, longitude=151.21, radius_m=500)
    )

    assert len(result.obstructions) == 1
    obstruction = result.obstructions[0]
    assert obstruction.footprint_source == MICROSOFT_FOOTPRINT_SOURCE
    assert obstruction.height_m == pytest.approx(5.0)
    assert obstruction.height_source == "OSM_HEIGHT"
    assert obstruction.duplicate_source_ids == ["osm-way-duplicate"]
    assert result.data_quality.duplicate_overlap_count == 1
    assert result.data_quality.excluded_reasons["duplicate_microsoft_overlap"] == 1


def test_duplicate_overlap_uses_projected_polygon_area() -> None:
    geometry = square_footprint("a", {"building": "yes"})["footprint_geometry"]

    assert geometry_overlap_ratio(geometry, geometry) == pytest.approx(1.0)


def test_source_summary_metrics_do_not_count_estimates_as_height_data() -> None:
    result = run_obstruction_inventory(
        ObstructionInventoryRequest(latitude=-33.86, longitude=151.21, radius_m=500),
        footprints=[
            square_footprint("osm-way-height", {"building": "yes", "height": "6"}, lon_offset=0),
            square_footprint("osm-way-estimated", {"building": "house"}, lon_offset=0.001),
            square_footprint("osm-way-tree", {"natural": "wood"}, lon_offset=0.002),
        ],
    )

    assert result.data_quality.total_osm_building_footprints_found == 2
    assert result.data_quality.total_vegetation_polygons_found == 1
    assert result.data_quality.total_usable_obstruction_polygons == 3
    assert result.data_quality.source_summary["OSM"] == 3
    assert result.data_quality.percentage_with_height_data == pytest.approx(33.3)
    assert result.data_quality.percentage_requiring_manual_review == pytest.approx(100.0)
    assert "Missing footprints can materially affect shielding evidence." in result.warnings

    records = {record.obstruction_id: record for record in result.obstructions}
    building = records["osm-way-height"]
    vegetation = records["osm-way-tree"]
    assert building.obstruction_source_type == "building"
    assert building.source_dataset == "OpenStreetMap"
    assert building.height_method == "osm_height"
    assert building.is_vegetation_candidate is False
    assert vegetation.obstruction_source_type == "vegetation"
    assert vegetation.source_dataset == "OpenStreetMap"
    assert vegetation.height_method == "assumption"
    assert vegetation.is_vegetation_candidate is True
