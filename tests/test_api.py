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
            "tags": {"height": "9"},
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
    assert body["obstructions"][0]["height_source"] == "explicit_height"
    assert "Ms cannot be assessed" in body["disclaimer"]
    assert fmap.status_code == 200
    assert "leaflet" in fmap.text.lower()
    assert report.status_code == 200
    assert "Missing Height Summary" in report.text
    assert "Ms cannot be assessed" in report.text
    assert csv_import.json()[0]["height_m"] == 8.5
    assert json_import.json()[0]["height_m"] == 8.5
