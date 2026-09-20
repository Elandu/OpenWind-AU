"""Tests for DSM-DTM obstruction height enrichment."""

from __future__ import annotations

import math

import pytest

from openwind_au.elevation_enrichment import (
    classify_obstruction,
    enrich_obstruction_heights,
)
from openwind_au.geo import EARTH_RADIUS_M
from openwind_au.models import ObstructionInventoryRequest, ObstructionManualOverride
from openwind_au.obstructions import build_obstruction_records, run_obstruction_inventory

SITE_LAT = -33.86
SITE_LON = 151.21


class ConstantProvider:
    def __init__(self, value: float) -> None:
        self.value = value

    def elevation(self, latitude: float, longitude: float) -> float:
        return self.value


class SlopingGroundProvider:
    def elevation(self, latitude: float, longitude: float) -> float:
        north_m = math.radians(latitude - SITE_LAT) * EARTH_RADIUS_M
        return 50 + north_m * 0.05


class OffsetSurfaceProvider:
    def __init__(self, ground_provider, offset_m: float) -> None:
        self.ground_provider = ground_provider
        self.offset_m = offset_m

    def elevation(self, latitude: float, longitude: float) -> float:
        return self.ground_provider.elevation(latitude, longitude) + self.offset_m


def local_to_lonlat(east_m: float, north_m: float) -> tuple[float, float]:
    latitude = SITE_LAT + math.degrees(north_m / EARTH_RADIUS_M)
    longitude = SITE_LON + math.degrees(
        east_m / (EARTH_RADIUS_M * math.cos(math.radians(SITE_LAT)))
    )
    return longitude, latitude


def footprint(source_id: str, tags: dict, center_north_m: float = 80) -> dict:
    ring = [
        local_to_lonlat(-5, center_north_m - 5),
        local_to_lonlat(5, center_north_m - 5),
        local_to_lonlat(5, center_north_m + 5),
        local_to_lonlat(-5, center_north_m + 5),
        local_to_lonlat(-5, center_north_m - 5),
    ]
    return {
        "source_id": source_id,
        "footprint_geometry": {"type": "Polygon", "coordinates": [ring]},
        "tags": tags,
    }


def records_for(*footprints: dict):
    return build_obstruction_records(
        list(footprints),
        site_latitude=SITE_LAT,
        site_longitude=SITE_LON,
        radius_m=500,
    )


def test_flat_ground_building_gets_dsm_dtm_height() -> None:
    records = records_for(footprint("building-1", {"building": "yes"}))

    enriched, warnings = enrich_obstruction_heights(
        records,
        dsm_provider=ConstantProvider(62.4),
        dtm_provider=ConstantProvider(50.0),
    )

    assert warnings == []
    assert enriched[0].classification == "residential"
    assert enriched[0].ground_rl_m == pytest.approx(50.0)
    assert enriched[0].surface_rl_m == pytest.approx(62.4)
    assert enriched[0].obstruction_height_m == pytest.approx(12.4)
    assert enriched[0].height_m is None
    assert enriched[0].height_source == "missing"
    assert enriched[0].confidence == "unknown"
    assert enriched[0].enrichment_method == "DSM-DTM mean footprint samples"


def test_tree_canopy_gets_vegetation_classification_and_height() -> None:
    records = records_for(footprint("tree-canopy", {"natural": "wood"}))

    enriched, _warnings = enrich_obstruction_heights(
        records,
        dsm_provider=ConstantProvider(68.0),
        dtm_provider=ConstantProvider(50.0),
    )

    assert enriched[0].classification == "vegetation"
    assert enriched[0].obstruction_height_m == pytest.approx(18.0)
    assert enriched[0].height_source == "missing"


def test_mixed_vegetation_classification() -> None:
    assert classify_obstruction({"building": "yes", "natural": "wood"}) == "mixed"


def test_landuse_residential_is_not_treated_as_vegetation() -> None:
    assert classify_obstruction({"landuse": "residential"}) == "residential"
    assert classify_obstruction({"landuse": "forest"}) == "vegetation"


def test_sloping_terrain_uses_paired_dsm_dtm_difference() -> None:
    ground = SlopingGroundProvider()
    records = records_for(footprint("slope-building", {"building": "yes"}, center_north_m=100))

    enriched, _warnings = enrich_obstruction_heights(
        records,
        dsm_provider=OffsetSurfaceProvider(ground, 9.0),
        dtm_provider=ground,
    )

    assert enriched[0].obstruction_height_m == pytest.approx(9.0, abs=0.01)


def test_missing_dsm_and_missing_dtm_are_warned() -> None:
    records = records_for(footprint("building-1", {"building": "yes"}))

    no_dsm, no_dsm_warnings = enrich_obstruction_heights(
        records,
        dsm_provider=None,
        dtm_provider=ConstantProvider(50),
    )
    no_dtm, no_dtm_warnings = enrich_obstruction_heights(
        records,
        dsm_provider=ConstantProvider(60),
        dtm_provider=None,
    )

    assert no_dsm[0].height_source == "missing"
    assert "DSM unavailable" in no_dsm_warnings[0]
    assert no_dtm[0].height_source == "missing"
    assert "DTM unavailable" in no_dtm_warnings[0]


def test_negative_extreme_and_low_estimates_are_flagged() -> None:
    records = records_for(
        footprint("negative", {"building": "yes"}, center_north_m=50),
        footprint("extreme", {"building": "yes"}, center_north_m=100),
        footprint("low", {"building": "yes"}, center_north_m=150),
    )

    class SelectiveDsm:
        def elevation(self, latitude: float, longitude: float) -> float:
            north_m = math.radians(latitude - SITE_LAT) * EARTH_RADIUS_M
            if north_m < 75:
                return 49.0
            if north_m < 125:
                return 140.0
            return 50.5

    enriched, _warnings = enrich_obstruction_heights(
        records,
        dsm_provider=SelectiveDsm(),
        dtm_provider=ConstantProvider(50),
    )

    negative, extreme, low = enriched
    assert negative.obstruction_height_m is None
    assert any("Negative DSM-DTM" in warning for warning in negative.warnings)
    assert extreme.obstruction_height_m == pytest.approx(90.0)
    assert any("Extreme DSM-DTM" in warning for warning in extreme.warnings)
    assert low.obstruction_height_m == pytest.approx(0.5)
    assert any("Low confidence" in warning for warning in low.warnings)


def test_priority_order_manual_osm_levels_dsm_unknown() -> None:
    result = run_obstruction_inventory(
        ObstructionInventoryRequest(
            latitude=SITE_LAT,
            longitude=SITE_LON,
            radius_m=500,
            building_height_m=10,
            manual_overrides=[ObstructionManualOverride(obstruction_id="manual", height_m=20.0)],
        ),
        footprints=[
            footprint("manual", {"building": "yes"}),
            footprint("explicit", {"building": "yes", "height": "14"}),
            footprint("levels", {"building": "yes", "building:levels": "3"}),
            footprint("dsm", {"building": "yes"}),
            footprint("unknown", {"building": "yes"}),
        ],
        dsm_provider=ConstantProvider(62),
        dtm_provider=ConstantProvider(50),
    )

    by_id = {item.obstruction_id: item for item in result.obstructions}
    assert by_id["manual"].height_source == "manual_verified"
    assert by_id["manual"].height_m == pytest.approx(20)
    assert by_id["manual"].confidence == "high"
    assert by_id["explicit"].height_source == "DSM_DTM"
    assert by_id["levels"].height_source == "DSM_DTM"
    assert by_id["dsm"].height_source == "DSM_DTM"
    assert by_id["unknown"].height_source == "DSM_DTM"
    assert by_id["explicit"].raw_source_height_source == "OSM_HEIGHT"
    assert by_id["levels"].raw_source_height_source == "OSM_LEVELS"
    assert all(by_id[item].height_method == "dsm_dtm" for item in ("explicit", "levels", "dsm"))
    assert any(
        any("common datum exceeds the subject building" in warning for warning in sector.warnings)
        for sector in result.shielding_sectors
    )
