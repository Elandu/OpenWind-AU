"""Tests for FastAPI endpoints."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import openwind_au.api as api_module
import openwind_au.validation as validation_module
from openwind_au.dem import DEMProvider
from openwind_au.obstructions import run_obstruction_inventory
from openwind_au.standard_lookup_tables import (
    MS_DATA_FILE,
    MZCAT_DATA_FILE,
    VERIFIED_LOOKUP_REVIEW_STATUS,
    VR_DATA_FILE,
    load_packaged_lookup_data,
)


class FlatDEM(DEMProvider):
    def elevation(self, latitude: float, longitude: float) -> float:
        return 75.0


def reviewed_lookup(filename: str) -> dict:
    data = load_packaged_lookup_data(filename)
    data["source"].update(
        {
            "review_status": VERIFIED_LOOKUP_REVIEW_STATUS,
            "reviewed_by": "Independent Test Engineer",
            "reviewed_on": "2026-07-12",
        }
    )
    return data


def test_health_distinguishes_liveness_from_readiness(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_RESULT_SIGNING_KEY", "test-result-signing-key-at-least-32-bytes")
    production_regions = ["A0", "A1", "A2", "A3", "A4", "A5", "B1", "B2", "C", "D"]
    monkeypatch.setattr(
        api_module,
        "dataset_metadata",
        lambda: {
            "dataset_name": "production-wind-regions",
            "polygon_count": 20,
            "is_test_fixture": False,
            "available_region_names": production_regions,
        },
    )
    monkeypatch.setattr(
        api_module,
        "load_md_tables",
        lambda: {
            "source": {
                "review_status": VERIFIED_LOOKUP_REVIEW_STATUS,
                "reviewed_by": "Independent Test Engineer",
                "reviewed_on": "2026-07-12",
            },
            "tables": {
                region: {direction: 1.0 for direction in api_module.DIRECTIONS}
                for region in production_regions
            },
        },
    )
    monkeypatch.setattr(api_module, "load_mzcat_table", lambda: reviewed_lookup(MZCAT_DATA_FILE))
    monkeypatch.setattr(api_module, "load_ms_table", lambda: reviewed_lookup(MS_DATA_FILE))
    monkeypatch.setattr(api_module, "load_vr_tables", lambda: reviewed_lookup(VR_DATA_FILE))
    client = TestClient(api_module.create_app())

    live = client.get("/health/live")
    ready = client.get("/health")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert all(check["ready"] for check in ready.json()["checks"].values())
    assert ready.json()["checks"]["terrain_height_multiplier_table"]["reviewed"] is True
    assert ready.json()["checks"]["shielding_multiplier_table"]["reviewed"] is True
    assert len(ready.json()["checks"]["terrain_height_multiplier_table"]["values_sha256"]) == 64
    assert len(ready.json()["checks"]["shielding_multiplier_table"]["values_sha256"]) == 64


def test_health_reports_missing_production_inputs(monkeypatch) -> None:
    monkeypatch.setattr(
        api_module,
        "dataset_metadata",
        lambda: {
            "dataset_name": "wind_regions_sample",
            "polygon_count": 12,
            "is_test_fixture": True,
        },
    )
    client = TestClient(api_module.create_app())

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["wind_region_dataset"]["ready"] is False
    assert response.json()["checks"]["terrain_height_multiplier_table"]["ready"] is False
    assert response.json()["checks"]["shielding_multiplier_table"]["ready"] is False
    assert "dataset_path" not in response.text


def test_health_distinguishes_missing_and_invalid_result_signing_keys(monkeypatch) -> None:
    monkeypatch.delenv("OPENWIND_RESULT_SIGNING_KEY", raising=False)
    missing = api_module.result_signing_readiness()
    monkeypatch.setenv("OPENWIND_RESULT_SIGNING_KEY", "too-short")
    invalid = api_module.result_signing_readiness()

    assert missing["ready"] is False
    assert missing["configured"] is False
    assert "ephemeral development key" in missing["detail"]
    assert invalid["ready"] is False
    assert invalid["configured"] is True
    assert "fewer than 32" in invalid["detail"]


def test_health_handles_malformed_lookup_configuration(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        api_module,
        "dataset_metadata",
        lambda: {
            "dataset_name": "production-wind-regions",
            "polygon_count": 1,
            "is_test_fixture": False,
            "available_region_names": ["A2"],
        },
    )
    monkeypatch.setattr(api_module, "load_md_tables", lambda: ["invalid"])
    monkeypatch.setattr(api_module, "load_vr_tables", lambda: {"tables": []})
    monkeypatch.setattr(api_module, "load_mzcat_table", lambda: {"values": []})
    monkeypatch.setattr(api_module, "load_ms_table", lambda: {"values": []})
    client = TestClient(api_module.create_app())

    with caplog.at_level(logging.ERROR, logger=api_module.LOGGER.name):
        response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["checks"]["direction_multiplier_table"]["ready"] is False
    assert body["checks"]["regional_wind_speed_table"]["ready"] is False
    assert body["checks"]["terrain_height_multiplier_table"]["ready"] is False
    assert body["checks"]["shielding_multiplier_table"]["ready"] is False
    assert "inspect the server logs" in response.text
    assert "Direction multiplier readiness check failed" in caplog.text
    assert "Regional wind speed readiness check failed" in caplog.text


def test_lookup_readiness_logs_loader_failures(caplog) -> None:
    def broken_loader():
        raise ValueError("synthetic lookup failure")

    with caplog.at_level(logging.ERROR, logger=api_module.LOGGER.name):
        check = api_module._standards_lookup_readiness(
            loader=broken_loader,
            validator=lambda _data, **_kwargs: [],
            label="synthetic lookup",
        )

    assert check["ready"] is False
    assert "synthetic lookup readiness check failed" in caplog.text


def sample_footprints() -> list[dict]:
    ring = [
        [151.21095, -33.86005],
        [151.21105, -33.86005],
        [151.21105, -33.85995],
        [151.21095, -33.85995],
        [151.21095, -33.86005],
    ]
    return [
        {
            "source_id": "osm-way-1",
            "footprint_geometry": {"type": "Polygon", "coordinates": [ring]},
            "tags": {"building": "yes", "height": "9"},
        }
    ]


def test_analyse_endpoint_with_coordinates(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())
    client = TestClient(api_module.create_app())

    response = client.post(
        "/api/analyse",
        json={
            "latitude": -33.86,
            "longitude": 151.21,
            "building_height_m": 10,
            "radius_m": 500,
            "sample_interval_m": 100,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["site"]["ground_elevation_m"] == 75
    assert [profile["direction"] for profile in body["profiles"]] == [
        "N",
        "NE",
        "E",
        "SE",
        "S",
        "SW",
        "W",
        "NW",
    ]
    assert [feature["direction"] for feature in body["features"]] == [
        "N",
        "NE",
        "E",
        "SE",
        "S",
        "SW",
        "W",
        "NW",
    ]
    assert all(feature["feature_type"] == "no significant feature" for feature in body["features"])
    assert all("competent engineer" in " ".join(feature["notes"]) for feature in body["features"])
    assert "not a certified" in body["disclaimer"]


def test_pdf_report_endpoint_returns_in_memory_download(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())
    monkeypatch.chdir(tmp_path)
    client = TestClient(api_module.create_app())

    response = client.post(
        "/api/report/pdf",
        json={
            "latitude": -33.86,
            "longitude": 151.21,
            "building_height_m": 10,
            "radius_m": 500,
            "sample_interval_m": 100,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert not (tmp_path / "reports").exists()


def test_pdf_report_failure_hides_internal_details_and_logs_incident(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())

    def fail_pdf(_result):
        raise RuntimeError(r"C:\private\project\font-cache failure")

    monkeypatch.setattr(api_module, "render_pdf_report", fail_pdf)
    client = TestClient(api_module.create_app())
    with caplog.at_level(logging.ERROR, logger=api_module.LOGGER.name):
        response = client.post(
            "/api/report/pdf",
            json={
                "latitude": -33.86,
                "longitude": 151.21,
                "building_height_m": 10,
                "radius_m": 500,
                "sample_interval_m": 100,
            },
        )

    assert response.status_code == 500
    assert response.json()["detail"] == ("Failed to generate PDF report; inspect the server logs.")
    assert "private" not in response.text
    assert "font-cache failure" in caplog.text


def test_vendored_map_assets_are_served() -> None:
    client = TestClient(api_module.create_app())

    for path in (
        "/static/vendor/leaflet/leaflet.js",
        "/static/vendor/leaflet/leaflet.css",
        "/static/vendor/jquery/jquery-3.7.1.min.js",
        "/static/vendor/bootstrap/bootstrap.bundle.min.js",
        "/static/vendor/fontawesome/all.min.css",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.content

    plotly = client.get("/vendor/plotly.min.js")
    assert plotly.status_code == 200
    assert plotly.headers["content-type"].startswith("application/javascript")
    assert plotly.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert b"plotly.js" in plotly.content[:500]


def test_geocode_suggest_endpoint(monkeypatch) -> None:
    def fake_suggestions(query, limit=5):
        assert query == "macquarie"
        assert limit == 3
        return [
            {
                "latitude": -33.85918,
                "longitude": 151.21319,
                "display_name": "1 Macquarie Street, Sydney NSW",
                "source": "OpenStreetMap Nominatim",
            }
        ]

    monkeypatch.setattr(api_module, "geocode_address_suggestions", fake_suggestions)
    client = TestClient(api_module.create_app())

    response = client.post(
        "/api/geocode/suggest",
        json={"query": "macquarie", "limit": 3},
    )

    assert response.status_code == 200
    assert response.json()["suggestions"][0]["display_name"] == "1 Macquarie Street, Sydney NSW"


def test_geocode_resolve_endpoint_and_errors(monkeypatch) -> None:
    def fake_geocode(query):
        assert query == "1 Macquarie Street Sydney"
        return {
            "latitude": -33.85918,
            "longitude": 151.21319,
            "display_name": "1 Macquarie Street, Sydney NSW",
            "source": "OpenStreetMap Nominatim",
        }

    monkeypatch.setattr(api_module, "geocode_address", fake_geocode)
    client = TestClient(api_module.create_app())

    response = client.post(
        "/api/geocode/resolve",
        json={"query": "1 Macquarie Street Sydney"},
    )

    assert response.status_code == 200
    assert response.json()["latitude"] == -33.85918

    monkeypatch.setattr(
        api_module,
        "geocode_address",
        lambda _query: (_ for _ in ()).throw(ValueError("No result")),
    )
    assert (
        client.post(
            "/api/geocode/resolve",
            json={"query": "missing"},
        ).status_code
        == 404
    )

    monkeypatch.setattr(
        api_module,
        "geocode_address",
        lambda _query: (_ for _ in ()).throw(RuntimeError("upstream unavailable")),
    )
    assert (
        client.post(
            "/api/geocode/resolve",
            json={"query": "failure"},
        ).status_code
        == 502
    )


def test_combined_map_endpoint_renders_all_layer_groups(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())

    def fake_inventory(request, *, resolved_site=None):
        return run_obstruction_inventory(
            request,
            footprints=sample_footprints(),
            resolved_site=resolved_site,
        )

    monkeypatch.setattr(api_module, "run_obstruction_inventory", fake_inventory)
    client = TestClient(api_module.create_app())

    response = client.post(
        "/api/map/combined",
        json={
            "latitude": -33.86,
            "longitude": 151.21,
            "building_height_m": 10,
            "radius_m": 500,
            "sample_interval_m": 100,
            "obstruction_radius_m": 500,
            "default_storey_height_m": 3.0,
        },
    )

    assert response.status_code == 200
    body = response.text
    # Folium renders feature group names into JavaScript with `&` escaped as \u0026,
    # so we assert on the layer-control wiring rather than on the literal name strings.
    assert "leaflet" in body.lower()
    assert "L.control.layers" in body
    assert "Design building" in body
    assert "openWindDesignBuilding" in body
    assert body.count("L.featureGroup") >= 4


def test_validation_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(validation_module, "SRTMProvider", lambda: FlatDEM())
    client = TestClient(api_module.create_app())

    page = client.get("/validation")
    cases = client.get("/api/validation/cases")
    report = client.get("/api/validation")
    html = client.get("/api/validation/report/html")

    assert page.status_code == 200
    assert "Validation Scope" in page.text
    assert cases.status_code == 200
    assert len(cases.json()) >= 5
    assert report.status_code == 200
    assert set(report.json()["summary"]) == {"pass", "warn", "fail"}
    assert "not proof of AS/NZS 1170.2 compliance" in report.json()["disclaimer"]
    assert html.status_code == 200
    assert "OpenWind-AU Validation Report" in html.text


def test_wind_region_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())
    monkeypatch.setenv(api_module.DEBUG_ENDPOINTS_ENV, "1")
    monkeypatch.setenv(
        "OPENWIND_WIND_REGION_DATASET",
        str(Path(__file__).parent / "fixtures" / "wind_regions_sample.geojson"),
    )
    client = TestClient(api_module.create_app())
    payload = {
        "latitude": -33.8688,
        "longitude": 151.2093,
        "building_height_m": 10,
        "radius_m": 500,
    }

    assessment = client.post("/api/wind-region", json=payload)
    fmap = client.post("/api/wind-region/map", json=payload)
    validation = client.get("/api/wind-region/validation")
    metadata = client.get("/api/debug/wind-region/dataset")
    debug = client.get(
        "/api/debug/wind-region",
        params={"latitude": -34.4278, "longitude": 150.8931},
    )

    assert assessment.status_code == 200
    assert assessment.json()["wind_region"] == "A2"
    assert assessment.json()["dataset_name"] == "wind_regions_sample"
    assert assessment.json()["polygon_count"] == 10
    assert "dataset_path" not in assessment.json()
    assert "region_polygon" not in assessment.json()
    assert "local path" not in assessment.text
    assert fmap.status_code == 200
    assert "Selected Wind Region A2" in fmap.text
    assert validation.status_code == 200
    wollongong = next(item for item in validation.json() if item["site"] == "Wollongong")
    assert wollongong["expected_region"] == "A2"
    assert wollongong["actual_region"] == "A3"
    assert wollongong["status"] == "fail"
    assert "test fixture" in wollongong["diagnosis"]
    assert metadata.status_code == 200
    assert metadata.json()["is_test_fixture"] is True
    assert debug.status_code == 200
    assert debug.json()["selected_polygon"]["region_name"] == "A3"


def test_wind_region_debug_endpoints_are_hidden_by_default(monkeypatch) -> None:
    monkeypatch.delenv(api_module.DEBUG_ENDPOINTS_ENV, raising=False)
    client = TestClient(api_module.create_app())

    responses = [
        client.get("/api/debug/wind-region/dataset"),
        client.get(
            "/api/debug/wind-region",
            params={"latitude": -33.86, "longitude": 151.21},
        ),
        client.post(
            "/api/debug/wind-region",
            json={
                "latitude": -33.86,
                "longitude": 151.21,
                "building_height_m": 10,
                "radius_m": 500,
            },
        ),
    ]

    assert all(response.status_code == 404 for response in responses)
    paths = client.get("/openapi.json").json()["paths"]
    assert not any(path.startswith("/api/debug/") for path in paths)


def test_wind_region_configuration_failure_hides_local_path(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())
    missing_path = tmp_path / "private-dataset" / "missing-regions.gpkg"
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", str(missing_path))
    client = TestClient(api_module.create_app())

    response = client.post(
        "/api/wind-region",
        json={
            "latitude": -33.86,
            "longitude": 151.21,
            "building_height_m": 10,
            "radius_m": 500,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Configured wind-region dataset does not exist."
    assert "private-dataset" not in response.text


def test_invalid_dem_configuration_is_a_service_readiness_failure(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_DEM_PROVIDER", "unknown")
    client = TestClient(api_module.create_app())

    response = client.post(
        "/api/analyse",
        json={
            "latitude": -33.86,
            "longitude": 151.21,
            "building_height_m": 10,
            "radius_m": 500,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Unsupported OPENWIND_DEM_PROVIDER setting. Configure 'srtm' or 'open-meteo'."
    )


def test_invalid_lookup_configuration_is_a_service_readiness_failure(
    monkeypatch,
    tmp_path,
) -> None:
    lookup_path = tmp_path / "mzcat.json"
    lookup_path.write_text('{"values": NaN}', encoding="utf-8")
    monkeypatch.setenv("OPENWIND_MZCAT_TABLE_PATH", str(lookup_path))
    client = TestClient(api_module.create_app())

    response = client.post(
        "/api/wind-workflow",
        json={
            "latitude": -33.86,
            "longitude": 151.21,
            "building_height_m": 10,
            "radius_m": 500,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Configured lookup data for OPENWIND_MZCAT_TABLE_PATH is invalid: "
        "Lookup JSON must not contain non-finite numeric constants"
    )
    assert str(tmp_path) not in response.text


def test_wind_workflow_stream_reports_missing_dataset_as_not_ready(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())
    monkeypatch.setenv("OPENWIND_WIND_REGION_DATASET", "missing-regions.gpkg")
    client = TestClient(api_module.create_app())

    response = client.post(
        "/api/wind-workflow/stream",
        json={
            "latitude": -33.8688,
            "longitude": 151.2093,
            "building_height_m": 10,
            "radius_m": 500,
        },
    )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.strip().splitlines()]
    assert events[-1]["stage"] == "error"
    assert events[-1]["data"]["status_code"] == 503
    assert events[-1]["label"] == "Configured wind-region dataset does not exist."


def test_wind_workflow_stream_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())
    monkeypatch.setenv(
        "OPENWIND_WIND_REGION_DATASET",
        str(Path(__file__).parent / "fixtures" / "wind_regions_sample.geojson"),
    )

    def fake_inventory(request, *, resolved_site=None):
        return run_obstruction_inventory(
            request,
            footprints=sample_footprints(),
            resolved_site=resolved_site,
        )

    monkeypatch.setattr(api_module, "run_obstruction_inventory", fake_inventory)
    client = TestClient(api_module.create_app())
    payload = {
        "latitude": -33.8688,
        "longitude": 151.2093,
        "building_height_m": 10,
        "radius_m": 500,
        "sample_interval_m": 100,
        "obstruction_radius_m": 500,
        "annual_exceedance_probability": "1/500",
    }

    response = client.post("/api/wind-workflow/stream", json=payload)

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.strip().splitlines()]
    stages = [event["stage"] for event in events]
    assert stages == [
        "start",
        "site",
        "wind_inputs",
        "obstructions",
        "terrain",
        "workflow",
        "map",
        "complete",
    ]
    workflow_event = next(event for event in events if event["stage"] == "workflow")
    map_event = next(event for event in events if event["stage"] == "map")
    assert workflow_event["data"]["workflow"]["wind_region_assessment"]["wind_region"] == "A2"
    assert workflow_event["data"]["workflow"]["regional_wind_speed_assessment"]["vr_ult"] == 45.0
    assert "L.control.layers" in map_event["data"]["map_html"]


def test_wind_workflow_stream_emits_sanitized_terminal_event_for_unexpected_error(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        api_module,
        "run_site_analysis",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyError("private detail")),
    )
    client = TestClient(api_module.create_app())

    response = client.post(
        "/api/wind-workflow/stream",
        json={
            "latitude": -33.8688,
            "longitude": 151.2093,
            "building_height_m": 10,
            "radius_m": 500,
        },
    )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.strip().splitlines()]
    assert events[-1]["stage"] == "error"
    assert events[-1]["data"]["status_code"] == 500
    assert "server logs" in events[-1]["label"]
    assert "private detail" not in response.text


def test_obstruction_inventory_endpoints(monkeypatch) -> None:
    def fake_inventory(request, *, resolved_site=None):
        return run_obstruction_inventory(
            request,
            footprints=sample_footprints(),
            resolved_site=resolved_site,
        )

    monkeypatch.setattr(api_module, "run_obstruction_inventory", fake_inventory)
    client = TestClient(api_module.create_app())

    payload = {
        "latitude": -33.86,
        "longitude": 151.21,
        "radius_m": 500,
        "building_height_m": 8,
        "default_storey_height_m": 3.0,
    }
    inventory = client.post("/api/obstructions/inventory", json=payload)
    fmap = client.post("/api/obstructions/map", json=payload)
    report = client.post("/api/obstructions/report/html", json=payload)
    csv_import = client.post(
        "/api/obstructions/import/csv",
        content="obstruction_id,height_m\nosm-way-1,8.5",
        headers={"content-type": "text/csv"},
    )
    json_import = client.post(
        "/api/obstructions/import/json",
        content='[{"obstruction_id":"osm-way-1","height_m":8.5}]',
        headers={"content-type": "application/json"},
    )
    assert inventory.status_code == 200
    body = inventory.json()
    assert body["obstructions"][0]["height_m"] == 9
    assert body["obstructions"][0]["height_source"] == "OSM_HEIGHT"
    assert body["obstructions"][0]["confidence"] == "medium"
    assert body["height_source_summary"]["OSM Height"] == 1
    assert body["data_quality"]["total_osm_building_footprints_found"] == 1
    assert body["data_quality"]["total_usable_obstruction_polygons"] == 1
    assert body["data_quality"]["source_summary"]["OSM"] == 1
    assert "raw_osm_building_footprints" not in body["data_quality"]
    assert "excluded_objects" not in body["data_quality"]
    assert "pipeline_log" not in body["data_quality"]
    assert "microsoft_cache_path" not in body["data_quality"]
    assert "raw_overpass_counts" not in body["data_quality"]
    assert "returned_geometry_bbox" not in body["data_quality"]
    assert len(body["shielding_sectors"]) == 8
    assert any(sector["ns"] == 1 for sector in body["shielding_sectors"])
    assert "Indicative Ms values are not certified" in body["disclaimer"]
    assert fmap.status_code == 200
    assert "leaflet" in fmap.text.lower()
    assert "Raw OSM building polygons before filtering" in fmap.text
    assert "OSM fallback and matched attributes" in fmap.text
    assert "Microsoft building footprints" in fmap.text
    assert "Vegetation polygons" in fmap.text
    assert "Excluded and skipped objects" in fmap.text
    assert "Shielding candidates" in fmap.text
    assert "Missing height objects" in fmap.text
    assert "Obstruction centroids" in fmap.text
    assert "openWindMapDiagnostics" in fmap.text
    assert report.status_code == 200
    assert "Missing Height Summary" in report.text
    assert "Obstruction Data Quality" in report.text
    assert "Footprint Source Summary" in report.text
    assert "Height Source Summary" in report.text
    assert "DSM-DTM estimate" in report.text
    assert "Overall confidence" in report.text
    assert "Class" in report.text
    assert "Preliminary Shielding Sector Analysis" in report.text
    assert "Indicative Ms" in report.text
    assert csv_import.json()[0]["height_m"] == 8.5
    assert json_import.json()[0]["height_m"] == 8.5


def test_obstruction_inventory_openapi_omits_private_diagnostics() -> None:
    schema = TestClient(api_module.create_app()).get("/openapi.json").json()
    operation = schema["paths"]["/api/obstructions/inventory"]["post"]
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]

    assert response_schema["$ref"].endswith("/PublicObstructionInventoryResult")
    quality = schema["components"]["schemas"]["PublicObstructionDataQuality"]["properties"]
    input_properties = schema["components"]["schemas"]["PublicObstructionInventoryInput"][
        "properties"
    ]
    for private_field in (
        "excluded_objects",
        "microsoft_cache_files",
        "microsoft_cache_path",
        "overpass_query",
        "pipeline_log",
        "raw_osm_building_footprints",
        "raw_overpass_counts",
        "returned_geometry_bbox",
        "sample_building_ids",
    ):
        assert private_field not in quality
    assert "reviewed_footprints" not in input_properties


@pytest.mark.parametrize(
    ("path", "content", "content_type", "expected_status"),
    [
        ("/api/obstructions/import/csv", b"\xff\xfe", "text/csv", 400),
        ("/api/obstructions/import/csv", b"wrong,value\nfoo,1", "text/csv", 400),
        (
            "/api/obstructions/import/csv",
            b"obstruction_id,height_m\nduplicate,2\nduplicate,3",
            "text/csv",
            400,
        ),
        ("/api/obstructions/import/json", b"{broken", "application/json", 400),
        ("/api/obstructions/import/json", b'{"unexpected": []}', "application/json", 400),
        ("/api/obstructions/import/json", b"[]", "text/plain", 415),
    ],
)
def test_obstruction_import_rejects_invalid_payloads(
    path: str,
    content: bytes,
    content_type: str,
    expected_status: int,
) -> None:
    client = TestClient(api_module.create_app())

    response = client.post(path, content=content, headers={"content-type": content_type})

    assert response.status_code == expected_status
    assert response.json()["detail"]


def test_obstruction_import_rejects_oversized_payload() -> None:
    client = TestClient(api_module.create_app())

    response = client.post(
        "/api/obstructions/import/csv",
        content=b"x" * (api_module.MAX_OBSTRUCTION_IMPORT_BYTES + 1),
        headers={"content-type": "text/csv"},
    )

    assert response.status_code == 413


def test_obstruction_debug_endpoint(monkeypatch) -> None:
    monkeypatch.setenv(api_module.DEBUG_ENDPOINTS_ENV, "1")

    def fake_inventory(request, *, resolved_site=None):
        return run_obstruction_inventory(
            request,
            footprints=sample_footprints(),
            resolved_site=resolved_site,
        )

    monkeypatch.setattr(api_module, "run_obstruction_inventory", fake_inventory)
    client = TestClient(api_module.create_app())

    response = client.get(
        "/api/obstructions/debug",
        params={"latitude": -33.86, "longitude": 151.21, "radius_m": 500},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query_centre"] == {"latitude": -33.86, "longitude": 151.21}
    assert body["radius"] == 500
    assert "raw_counts" in body
    assert "parsed_counts" in body
    assert "excluded_counts" in body
    assert "sample_building_ids" in body
    assert "returned_geometry_bbox" in body
    assert "pipeline_log" in body


def test_obstruction_debug_endpoint_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv(api_module.DEBUG_ENDPOINTS_ENV, raising=False)
    client = TestClient(api_module.create_app())

    response = client.get(
        "/api/obstructions/debug",
        params={"latitude": -33.86, "longitude": 151.21, "radius_m": 500},
    )

    assert response.status_code == 404
    assert "/api/obstructions/debug" not in client.get("/openapi.json").json()["paths"]


def test_terrain_category_evidence_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())

    def fake_inventory(request, *, resolved_site=None):
        return run_obstruction_inventory(
            request,
            footprints=sample_footprints(),
            resolved_site=resolved_site,
        )

    monkeypatch.setattr(api_module, "run_obstruction_inventory", fake_inventory)
    client = TestClient(api_module.create_app())
    payload = {
        "latitude": -33.86,
        "longitude": 151.21,
        "building_height_m": 10,
        "radius_m": 500,
        "sample_interval_m": 100,
        "obstruction_radius_m": 500,
        "default_storey_height_m": 3.0,
    }

    evidence = client.post("/api/terrain-category/evidence", json=payload)
    fmap = client.post("/api/terrain-category/map", json=payload)
    report = client.post("/api/terrain-category/report/html", json=payload)
    cases = client.get("/api/terrain-category/validation/cases")
    validation = client.get("/api/terrain-category/validation")
    page = client.get("/terrain-category")

    assert evidence.status_code == 200
    body = evidence.json()
    assert len(body["directions"]) == 8
    assert "final AS/NZS 1170.2 terrain category" in body["disclaimer"]
    assert "Mz,cat" in body["disclaimer"]
    assert "suggested_category_range" in body["directions"][0]
    assert len(body["mzcat_assessment"]) == 8
    assert "lower_indicative_mzcat" in body["mzcat_assessment"][0]
    assert "final_terrain_category" not in body["directions"][0]
    assert fmap.status_code == 200
    assert "Dominant obstruction zones" in fmap.text
    assert "Indicative Mz,cat ranges" in fmap.text
    assert report.status_code == 200
    assert "Terrain Category Evidence Summary" in report.text
    assert "Mz,cat" in report.text
    assert cases.status_code == 200
    assert len(cases.json()) == 6
    assert validation.status_code == 200
    assert all(item["status"] == "pass" for item in validation.json())
    assert page.status_code == 200
    assert 'id="visual-evidence"' in page.text
    assert "Map and Terrain Chart" in page.text
    assert "Shielding and topographic evidence map" in page.text
    assert "Terrain profile chart" in page.text
    assert "Advanced inputs" in page.text
    assert "Terrain profile summaries" in page.text
    assert "Analysis diagnostics" in page.text
    assert "Terrain category sectors and evidence" in page.text
    assert page.text.index("Map and Terrain Chart") < page.text.index("Terrain profile summaries")
    assert 'id="terrain-evidence"' in page.text
    assert 'id="shielding-evidence"' in page.text
    assert 'id="topographic-evidence"' in page.text
    assert 'id="profiles"' in page.text
    assert 'id="latitude" name="latitude" type="number" step="any"' in page.text
    assert 'id="longitude" name="longitude" type="number" step="any"' in page.text


def test_full_analysis_endpoint_runs_browser_workflow_once(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())
    calls = {"inventory": 0}

    def fake_inventory(request, *, resolved_site=None):
        calls["inventory"] += 1
        return run_obstruction_inventory(
            request,
            footprints=sample_footprints(),
            resolved_site=resolved_site,
        )

    monkeypatch.setattr(api_module, "run_obstruction_inventory", fake_inventory)
    client = TestClient(api_module.create_app())
    payload = {
        "latitude": -33.86,
        "longitude": 151.21,
        "building_height_m": 10,
        "radius_m": 500,
        "sample_interval_m": 100,
        "obstruction_radius_m": 500,
        "default_storey_height_m": 3.0,
        "mzcat_recommendation_mode": "best_estimate",
    }

    response = client.post("/api/full-analysis", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert calls["inventory"] == 1
    assert body["site_analysis"]["site"]["ground_elevation_m"] == 75
    assert len(body["obstruction_inventory"]["obstructions"]) == 1
    assert "raw_osm_building_footprints" not in body["obstruction_inventory"]["data_quality"]
    assert "pipeline_log" not in body["obstruction_inventory"]["data_quality"]
    assert len(body["obstruction_inventory"]["ms_lookup_provenance"]["values_sha256"]) == 64
    assert len(body["terrain_category_evidence"]["directions"]) == 8
    assert len(body["terrain_category_evidence"]["mzcat_assessment"]) == 8
    assert len(body["terrain_category_evidence"]["mzcat_lookup_provenance"]["values_sha256"]) == 64
    assert (
        body["terrain_category_evidence"]["mzcat_assessment"][0]["recommendation_mode"]
        == "best_estimate"
    )
    assert "plotly" in body["profile_plot_html"].lower()
    assert "openWindMapDiagnostics" in body["terrain_category_map_html"]
    assert "openWindMapDiagnostics" in body["combined_map_html"]
    assert "Shielding sectors" in body["combined_map_html"]
    assert r"Terrain profiles \u0026 topographic candidates" in body["combined_map_html"]


def test_address_workflow_reuses_one_geocoded_site(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())
    geocode_calls: list[str] = []

    def fake_geocode(query: str) -> dict:
        geocode_calls.append(query)
        return {
            "latitude": -33.86,
            "longitude": 151.21,
            "display_name": "Resolved test address",
            "source": "test geocoder",
        }

    monkeypatch.setattr("openwind_au.analysis.geocode_address", fake_geocode)

    def fake_inventory(request, *, resolved_site=None):
        assert request.latitude is None
        assert request.longitude is None
        assert resolved_site.latitude == pytest.approx(-33.86)
        assert resolved_site.longitude == pytest.approx(151.21)
        return run_obstruction_inventory(
            request,
            footprints=sample_footprints(),
            resolved_site=resolved_site,
        )

    monkeypatch.setattr(api_module, "run_obstruction_inventory", fake_inventory)
    client = TestClient(api_module.create_app())

    response = client.post(
        "/api/full-analysis",
        json={
            "address": "1 Test Street, Sydney NSW",
            "building_height_m": 10,
            "radius_m": 500,
            "sample_interval_m": 100,
            "obstruction_radius_m": 500,
        },
    )

    assert response.status_code == 200
    assert geocode_calls == ["1 Test Street, Sydney NSW"]
    assert response.json()["obstruction_inventory"]["site"]["source"] == "test geocoder"
    assert response.json()["obstruction_inventory"]["input"]["address"] == (
        "1 Test Street, Sydney NSW"
    )
    assert response.json()["obstruction_inventory"]["input"]["latitude"] is None
    assert response.json()["obstruction_inventory"]["input"]["longitude"] is None


def test_terrain_category_report_accepts_engineer_mzcat_reviews(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())

    def fake_inventory(request, *, resolved_site=None):
        return run_obstruction_inventory(
            request,
            footprints=sample_footprints(),
            resolved_site=resolved_site,
        )

    monkeypatch.setattr(api_module, "run_obstruction_inventory", fake_inventory)
    client = TestClient(api_module.create_app())
    payload = {
        "latitude": -33.86,
        "longitude": 151.21,
        "building_height_m": 10,
        "radius_m": 500,
        "sample_interval_m": 100,
        "obstruction_radius_m": 500,
        "default_storey_height_m": 3.0,
        "mzcat_reviews": [
            {
                "direction": "N",
                "final_terrain_category": "TC2.5",
                "final_mzcat": 0.96,
                "reviewed_by": "Engineer A",
                "review_notes": "Accepted after project review.",
                "review_status": "accepted",
            },
            {
                "direction": "NE",
                "review_notes": "Awaiting site photos.",
                "review_status": "unreviewed",
            },
        ],
    }

    response = client.post("/api/terrain-category/report/html", json=payload)

    assert response.status_code == 200
    assert "Engineer-selected Final Mz,cat" in response.text
    assert "0.960" in response.text
    assert "Engineer A" in response.text
    assert "Accepted after project review." in response.text
    assert "Awaiting site photos." in response.text
    assert "Engineer review required before final Mz,cat may be used." in response.text
