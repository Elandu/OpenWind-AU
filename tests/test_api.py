"""Tests for FastAPI endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

import openwind_au.api as api_module
from openwind_au.dem import DEMProvider


class FlatDEM(DEMProvider):
    def elevation(self, latitude: float, longitude: float) -> float:
        return 75.0


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
