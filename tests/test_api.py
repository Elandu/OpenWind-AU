"""Tests for FastAPI endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

import openwind_au.api as api_module
import openwind_au.validation as validation_module
from openwind_au.dem import DEMProvider
from openwind_au.obstructions import run_obstruction_inventory


class FlatDEM(DEMProvider):
    def elevation(self, latitude: float, longitude: float) -> float:
        return 75.0


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


def test_combined_map_endpoint_renders_all_layer_groups(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())

    def fake_inventory(request):
        return run_obstruction_inventory(request, footprints=sample_footprints())

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


def test_obstruction_inventory_endpoints(monkeypatch) -> None:
    def fake_inventory(request):
        return run_obstruction_inventory(request, footprints=sample_footprints())

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
    )
    json_import = client.post(
        "/api/obstructions/import/json",
        content='[{"obstruction_id":"osm-way-1","height_m":8.5}]',
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


def test_obstruction_debug_endpoint(monkeypatch) -> None:
    def fake_inventory(request):
        return run_obstruction_inventory(request, footprints=sample_footprints())

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


def test_terrain_category_evidence_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())

    def fake_inventory(request):
        return run_obstruction_inventory(request, footprints=sample_footprints())

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
    assert "Terrain Category Evidence" in page.text


def test_full_analysis_endpoint_runs_browser_workflow_once(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())
    calls = {"inventory": 0}

    def fake_inventory(request):
        calls["inventory"] += 1
        return run_obstruction_inventory(request, footprints=sample_footprints())

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
    assert len(body["terrain_category_evidence"]["directions"]) == 8
    assert len(body["terrain_category_evidence"]["mzcat_assessment"]) == 8
    assert (
        body["terrain_category_evidence"]["mzcat_assessment"][0]["recommendation_mode"]
        == "best_estimate"
    )
    assert "plotly" in body["profile_plot_html"].lower()
    assert "openWindMapDiagnostics" in body["terrain_category_map_html"]
    assert "openWindMapDiagnostics" in body["combined_map_html"]


def test_terrain_category_report_accepts_engineer_mzcat_reviews(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())

    def fake_inventory(request):
        return run_obstruction_inventory(request, footprints=sample_footprints())

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
