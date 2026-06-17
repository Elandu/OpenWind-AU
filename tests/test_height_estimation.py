"""Tests for obstruction height source selection and assumptions."""

from __future__ import annotations

import pytest

from openwind_au.height_estimation import (
    HeightEstimationConfig,
    estimate_height_from_assumptions,
    resolve_operational_height,
)
from openwind_au.models import ObstructionRecord


def record(
    *,
    obstruction_id: str = "test",
    classification: str = "unknown",
    height_m: float | None = None,
    height_source: str = "missing",
    obstruction_height_m: float | None = None,
    building_levels: float | None = None,
    confidence: str = "unknown",
    warnings: list[str] | None = None,
    footprint_size: float = 0.00005,
) -> ObstructionRecord:
    lon = 151.21
    lat = -33.86
    ring = [
        [lon - footprint_size, lat - footprint_size],
        [lon + footprint_size, lat - footprint_size],
        [lon + footprint_size, lat + footprint_size],
        [lon - footprint_size, lat + footprint_size],
        [lon - footprint_size, lat - footprint_size],
    ]
    return ObstructionRecord(
        obstruction_id=obstruction_id,
        source_id=obstruction_id,
        classification=classification,  # type: ignore[arg-type]
        footprint_geometry={"type": "Polygon", "coordinates": [ring]},
        centroid_latitude=lat,
        centroid_longitude=lon,
        distance_m=100,
        bearing_deg=0,
        height_m=height_m,
        selected_height_m=height_m,
        raw_source_height_m=height_m,
        raw_source_height_source=height_source if height_source != "missing" else None,
        obstruction_height_m=obstruction_height_m,
        building_levels=building_levels,
        height_source=height_source,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        manual_review_required=True,
        review_required=True,
        tags={},
        warnings=warnings or [],
    )


def test_source_priority_manual_then_dsm_then_osm_then_estimated() -> None:
    config = HeightEstimationConfig()

    manual = resolve_operational_height(
        record(height_m=15, height_source="manual_verified", obstruction_height_m=20),
        config,
    )
    dsm_over_osm = resolve_operational_height(
        record(height_m=12, height_source="OSM_HEIGHT", obstruction_height_m=18),
        config,
    )
    osm_height = resolve_operational_height(
        record(height_m=12, height_source="OSM_HEIGHT"),
        config,
    )
    osm_levels = resolve_operational_height(
        record(height_m=9, height_source="OSM_LEVELS", building_levels=3),
        config,
    )
    estimated = resolve_operational_height(
        record(classification="residential"),
        config,
    )
    unknown = resolve_operational_height(record(classification="mixed"), config)

    assert manual.height_source == "manual_verified"
    assert manual.height_m == pytest.approx(15)
    assert manual.confidence == "high"
    assert manual.review_required is False
    assert dsm_over_osm.height_source == "DSM_DTM"
    assert dsm_over_osm.height_m == pytest.approx(18)
    assert dsm_over_osm.raw_source_height_m == pytest.approx(12)
    assert dsm_over_osm.raw_source_height_source == "OSM_HEIGHT"
    assert osm_height.height_source == "OSM_HEIGHT"
    assert osm_height.confidence == "medium"
    assert osm_levels.height_source == "OSM_LEVELS"
    assert osm_levels.confidence == "medium"
    assert estimated.height_source == "ESTIMATED"
    assert estimated.height_m == pytest.approx(3)
    assert estimated.confidence == "low"
    assert unknown.height_source == "missing"
    assert unknown.confidence == "unknown"


def test_configurable_class_assumptions_do_not_use_footprint_area() -> None:
    config = HeightEstimationConfig(
        residential_storey_height_m=3.2,
        residential_two_storey_height_m=6.4,
        commercial_storey_height_m=4.5,
    )

    small_residential = record(classification="residential", footprint_size=0.00002)
    large_residential = record(classification="residential", footprint_size=0.0002)
    two_storey = record(classification="residential", building_levels=2)
    commercial = record(classification="commercial", building_levels=3)
    apartment = record(classification="apartment", building_levels=4)

    assert estimate_height_from_assumptions(small_residential, config) == pytest.approx(3.2)
    assert estimate_height_from_assumptions(large_residential, config) == pytest.approx(3.2)
    assert estimate_height_from_assumptions(two_storey, config) == pytest.approx(6.4)
    assert estimate_height_from_assumptions(commercial, config) == pytest.approx(13.5)
    assert estimate_height_from_assumptions(apartment, config) == pytest.approx(12)


def test_dsm_warnings_downgrade_confidence_and_require_review() -> None:
    resolved = resolve_operational_height(
        record(obstruction_height_m=0.5, warnings=["Low confidence DSM-DTM height estimate."]),
        HeightEstimationConfig(),
    )

    assert resolved.height_source == "DSM_DTM"
    assert resolved.confidence == "low"
    assert resolved.review_required is True
