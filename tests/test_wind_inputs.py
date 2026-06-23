"""Tests for wind region, VR, and Md inputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openwind_au.models import SiteLocation
from openwind_au.wind_inputs import (
    MD_METADATA_WARNING,
    VR_METADATA_WARNING,
    direction_multiplier_assessment,
    lookup_vr,
    parse_ari_years,
    regional_wind_speed_assessment,
    wind_region_map_html,
)
from openwind_au.wind_region import assess_wind_region, dataset_metadata, wind_region_debug


def sample_wind_regions_path() -> Path:
    return Path(__file__).parent / "fixtures" / "wind_regions_sample.geojson"


def production_wind_regions_path() -> Path:
    return (
        Path(__file__).parents[1]
        / "data"
        / "wind-region"
        / "ga-1170-2-wind-regions"
        / "as1170windzones.shp"
    )


def site(latitude: float, longitude: float, name: str = "test") -> SiteLocation:
    return SiteLocation(
        latitude=latitude,
        longitude=longitude,
        ground_elevation_m=0,
        source="test",
        display_name=name,
    )


def test_region_polygon_lookup_from_configured_geojson(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(sample_wind_regions_path()))

    assessment = assess_wind_region(site(-33.86, 151.21, "Sydney"))

    assert assessment.wind_region == "A2"
    assert "Geoscience Australia 1170.2 Wind Regions" in assessment.source
    assert assessment.confidence == "high"
    assert assessment.region_polygon is not None


def test_dataset_metadata_flags_sample_fixture(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(sample_wind_regions_path()))

    metadata = dataset_metadata()

    assert metadata["dataset_name"] == "wind_regions_sample"
    assert metadata["polygon_count"] == 12
    assert metadata["is_test_fixture"] is True
    assert metadata["available_region_names"] == [
        "A0",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
        "B1",
        "B2",
        "C",
        "D",
    ]


def test_debug_explains_fixture_wollongong_a3(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(sample_wind_regions_path()))
    location = site(-34.4278, 150.8931, "Wollongong")

    debug = wind_region_debug(location)

    assert debug["dataset"]["is_test_fixture"] is True
    assert debug["selected_polygon"]["region_name"] == "A3"
    assert debug["matched_polygons"][0]["region_name"] == "A3"
    assert debug["selection_rule"] == "Selected the only polygon covering the site."


def test_region_boundary_warning(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(sample_wind_regions_path()))
    monkeypatch.setenv("OPENWIND_WIND_REGION_BOUNDARY_WARNING_M", "20000")

    assessment = assess_wind_region(site(-33.86, 151.595, "Near boundary"))

    assert assessment.wind_region == "A2"
    assert assessment.near_boundary is True
    assert assessment.confidence == "medium"
    assert any("near a wind-region boundary" in warning for warning in assessment.warnings)


@pytest.mark.skipif(
    not production_wind_regions_path().exists(),
    reason="Production GA wind-region shapefile is not available in the local runtime cache.",
)
@pytest.mark.parametrize(
    ("name", "latitude", "longitude", "expected_region"),
    [
        ("Wollongong", -34.4278, 150.8931, "A2"),
        ("Sydney", -33.8688, 151.2093, "A2"),
        ("Newcastle", -32.9283, 151.7817, "A2"),
        ("Canberra", -35.2809, 149.1300, "A3"),
    ],
)
def test_production_wind_region_validation_cases(
    monkeypatch,
    name,
    latitude,
    longitude,
    expected_region,
) -> None:
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(production_wind_regions_path()))

    assessment = assess_wind_region(site(latitude, longitude, name))

    assert assessment.wind_region == expected_region
    assert assessment.dataset_name == "Geoscience Australia as1170windzones"
    assert assessment.polygon_count == 20
    assert assessment.available_region_names == [
        "A0",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "B1",
        "B2",
        "C",
        "D",
    ]


@pytest.mark.skipif(
    not production_wind_regions_path().exists(),
    reason="Production GA wind-region shapefile is not available in the local runtime cache.",
)
def test_production_dataset_classifies_bourke_as_a0(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(production_wind_regions_path()))

    debug = wind_region_debug(site(-30.0901, 145.9360, "Bourke"))

    assert debug["selected_polygon"]["region_name"] == "A0"
    assert debug["matched_polygons"][0]["area_name"] == "Interior"


@pytest.mark.skipif(
    not production_wind_regions_path().exists(),
    reason="Production GA wind-region shapefile is not available in the local runtime cache.",
)
def test_validation_diagnosis_accepts_bourke_a0(monkeypatch) -> None:
    from openwind_au.wind_inputs import run_wind_region_validation_cases

    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(production_wind_regions_path()))

    result = next(item for item in run_wind_region_validation_cases() if item["site"] == "Bourke")

    assert result["expected_region"] == "A0"
    assert result["actual_region"] == "A0"
    assert result["status"] == "pass"
    assert result["diagnosis"] == "Active dataset matches the expected validation region."


@pytest.mark.parametrize(
    ("latitude", "longitude", "expected_region"),
    [
        (-31.95, 115.86, "A0"),
        (-34.92, 138.60, "A1"),
        (-33.86, 151.21, "A2"),
        (-34.43, 150.89, "A3"),
        (-37.81, 144.96, "A4"),
        (-42.88, 147.33, "A5"),
        (-36.70, 147.10, "A6"),
        (-34.35, 118.00, "A7"),
        (-27.47, 153.03, "B1"),
        (-20.30, 148.70, "B2"),
        (-12.46, 130.85, "C"),
        (-20.31, 118.58, "D"),
    ],
)
def test_supported_region_labels(monkeypatch, latitude, longitude, expected_region) -> None:
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(sample_wind_regions_path()))

    assessment = assess_wind_region(site(latitude, longitude))

    assert assessment.wind_region == expected_region


def test_vr_lookup_from_editable_data(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(sample_wind_regions_path()))
    region = assess_wind_region(site(-33.86, 151.21, "Sydney"))

    speed = regional_wind_speed_assessment(
        region,
        importance_level="IL2",
        annual_exceedance_probability="1/500",
    )
    interpolated, note = lookup_vr({25: 37, 100: 41, 500: 45}, 250)

    assert speed.wind_region == "A2"
    assert speed.ari_years == 500
    assert speed.vr_ult == 45.0
    assert speed.vr_serv == 37.0
    assert "Editable regional wind speed" in speed.selected_table
    assert parse_ari_years("1:1000") == 1000
    assert interpolated == pytest.approx(43.2, abs=0.1)
    assert "Interpolated" in note


def test_missing_vr_table_value_warns(monkeypatch, tmp_path) -> None:
    table_path = tmp_path / "vr.json"
    table_path.write_text(
        json.dumps(
            {
                "source": {"title": "test VR", "standard_reference": "test", "status": "test"},
                "tables": {"A": {"ultimate": {"25": 37.0}, "serviceability": {}}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(sample_wind_regions_path()))
    monkeypatch.setenv("OPENWIND_VR_TABLE_PATH", str(table_path))
    region = assess_wind_region(site(-33.86, 151.21, "Sydney"))

    speed = regional_wind_speed_assessment(
        region,
        importance_level="IL2",
        annual_exceedance_probability="1/500",
    )

    assert speed.vr_ult is None
    assert speed.vr_serv is None
    assert any("manual input required" in warning for warning in speed.warnings)


def test_unverified_vr_table_metadata_warns(monkeypatch, tmp_path) -> None:
    table_path = tmp_path / "vr.json"
    table_path.write_text(
        json.dumps(
            {
                "source": {"title": "test VR", "standard_reference": "test", "status": "test"},
                "tables": {
                    "A": {"ultimate": {"500": 45.0}, "serviceability": {"25": 37.0}},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(sample_wind_regions_path()))
    monkeypatch.setenv("OPENWIND_VR_TABLE_PATH", str(table_path))
    region = assess_wind_region(site(-33.86, 151.21, "Sydney"))

    speed = regional_wind_speed_assessment(
        region,
        importance_level="IL2",
        annual_exceedance_probability="1/500",
    )

    assert speed.vr_ult == 45.0
    assert VR_METADATA_WARNING in speed.warnings


def test_md_lookup_and_governing_rows(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(sample_wind_regions_path()))
    region = assess_wind_region(site(-27.47, 153.03, "Brisbane"))

    md = direction_multiplier_assessment(region)

    assert region.wind_region == "B1"
    assert len(md.directions) == 8
    assert md.highest_md == 0.95
    assert md.governing_directions == ["S", "SW", "W"]
    assert "Editable direction multiplier" in md.source_table


def test_missing_md_table_value_warns(monkeypatch, tmp_path) -> None:
    table_path = tmp_path / "md.json"
    table_path.write_text(
        json.dumps(
            {
                "source": {"title": "test Md", "standard_reference": "test", "status": "test"},
                "tables": {"A": {"N": 1.0}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(sample_wind_regions_path()))
    monkeypatch.setenv("OPENWIND_MD_TABLE_PATH", str(table_path))
    region = assess_wind_region(site(-33.86, 151.21, "Sydney"))

    md = direction_multiplier_assessment(region)

    assert md.highest_md == 1.0
    assert next(row for row in md.directions if row.direction == "NE").md is None
    assert any("Md table value missing for NE" in warning for warning in md.warnings)


def test_unverified_md_table_metadata_warns(monkeypatch, tmp_path) -> None:
    table_path = tmp_path / "md.json"
    table_path.write_text(
        json.dumps(
            {
                "source": {"title": "test Md", "standard_reference": "test", "status": "test"},
                "tables": {
                    "A2": {
                        "N": 0.85,
                        "NE": 0.75,
                        "E": 0.85,
                        "SE": 0.95,
                        "S": 0.95,
                        "SW": 0.95,
                        "W": 1.0,
                        "NW": 0.95,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(sample_wind_regions_path()))
    monkeypatch.setenv("OPENWIND_MD_TABLE_PATH", str(table_path))
    region = assess_wind_region(site(-33.86, 151.21, "Sydney"))

    md = direction_multiplier_assessment(region)

    assert md.highest_md == 1.0
    assert MD_METADATA_WARNING in md.warnings


def test_wind_region_map_html(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(sample_wind_regions_path()))
    location = site(-33.86, 151.21, "Sydney")
    assessment = assess_wind_region(location)

    html = wind_region_map_html(location, assessment)

    assert "leaflet" in html.lower()
    assert "Selected Wind Region A2" in html
