"""Tests for the AS/NZS site wind workflow layer."""

from __future__ import annotations

from fastapi.testclient import TestClient

import openwind_au.api as api_module
from openwind_au.obstructions import run_obstruction_inventory
from tests.test_api import FlatDEM, sample_footprints


def workflow_payload() -> dict:
    return {
        "latitude": -33.86,
        "longitude": 151.21,
        "building_height_m": 10,
        "radius_m": 500,
        "sample_interval_m": 100,
        "obstruction_radius_m": 500,
        "default_storey_height_m": 3.0,
        "wind_region": "A2",
        "annual_exceedance_probability": "1/500",
        "regional_wind_speed_mps": 45,
    }


def all_reviewed_inputs() -> list[dict]:
    reviews = [
        {
            "variable": "VR",
            "final_value": 45,
            "review_status": "accepted",
            "reviewed_by": "Engineer A",
        }
    ]
    for direction in ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]:
        reviews.extend(
            [
                {
                    "variable": "Md",
                    "direction": direction,
                    "final_value": 1.0,
                    "review_status": "accepted",
                },
                {
                    "variable": "Mzcat",
                    "direction": direction,
                    "final_value": 0.95,
                    "review_status": "accepted",
                },
                {
                    "variable": "Ms",
                    "direction": direction,
                    "final_value": 1.0,
                    "review_status": "accepted",
                },
                {
                    "variable": "Mt",
                    "direction": direction,
                    "final_value": 1.0,
                    "review_status": "accepted",
                },
            ]
        )
    return reviews


def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())

    def fake_inventory(request):
        return run_obstruction_inventory(request, footprints=sample_footprints())

    monkeypatch.setattr(api_module, "run_obstruction_inventory", fake_inventory)
    return TestClient(api_module.create_app())


def test_wind_workflow_page_loads_in_workflow_order(monkeypatch) -> None:
    test_client = client(monkeypatch)

    response = test_client.get("/")
    workflow_page = test_client.get("/wind-workflow")
    support_page = test_client.get("/site-analysis")

    assert response.status_code == 200
    assert workflow_page.status_code == 200
    assert support_page.status_code == 200
    body = response.text
    headings = [
        "1. Project and Site Inputs",
        "2. Wind Region / Regional Wind Speed, VR",
        "3. Wind Direction Multiplier, Md",
        "4. Terrain Category / Mz,cat",
        "5. Shielding Multiplier, Ms",
        "6. Topographic Multiplier, Mt",
        "7. Site Wind Speed, Vsit,b",
        "8. Evidence Maps and Reports",
    ]
    assert all(heading in body for heading in headings)
    assert [body.index(heading) for heading in headings] == sorted(
        body.index(heading) for heading in headings
    )
    assert "wind_workflow.js" in body


def test_calculation_panel_content_in_workflow_report(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {"workflow_reviews": all_reviewed_inputs()}

    response = test_client.post("/api/wind-workflow/report/html", json=payload)

    assert response.status_code == 200
    assert "Formula / basis" in response.text
    assert "Vsit,b = VR x Md x Mz,cat x Ms x Mt" in response.text
    assert "No final design pressure calculations are included" in response.text


def test_vsitb_blocked_when_variables_are_unreviewed(monkeypatch) -> None:
    test_client = client(monkeypatch)

    response = test_client.post("/api/wind-workflow", json=workflow_payload())

    assert response.status_code == 200
    body = response.json()
    north = next(row for row in body["directional_vsitb"] if row["direction"] == "N")
    assert north["status"] == "blocked"
    assert north["final_vsitb"] is None
    assert "Vsit,b blocked" in " ".join(north["warnings"])


def test_accepted_and_override_values_propagate_to_workflow(monkeypatch) -> None:
    test_client = client(monkeypatch)
    reviews = all_reviewed_inputs()
    reviews.append(
        {
            "variable": "Md",
            "direction": "N",
            "final_value": 0.9,
            "review_status": "overridden",
            "review_notes": "Directional multiplier overridden after review.",
        }
    )
    payload = workflow_payload() | {"workflow_reviews": reviews}

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 200
    body = response.json()
    md_north = next(
        item for item in body["variables"] if item["variable"] == "Md" and item["direction"] == "N"
    )
    assert md_north["final_value"] == 0.9
    assert md_north["review_status"] == "overridden"
    assert md_north["review_notes"] == "Directional multiplier overridden after review."
    vr = next(item for item in body["variables"] if item["variable"] == "VR")
    assert vr["final_value"] == 45
    assert vr["review_status"] == "accepted"


def test_vsitb_calculated_when_all_input_variables_are_reviewed(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {"workflow_reviews": all_reviewed_inputs()}

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 200
    body = response.json()
    north = next(row for row in body["directional_vsitb"] if row["direction"] == "N")
    assert north["status"] == "calculated"
    assert north["final_vsitb"] == 42.75
    assert {item["variable"] for item in body["variables"] if item["direction"] in {None, "N"}} >= {
        "VR",
        "Md",
        "Mzcat",
        "Ms",
        "Mt",
        "Vsitb",
    }


def test_vsitb_review_cannot_be_final_while_inputs_unreviewed(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "workflow_reviews": [
            {
                "variable": "Vsitb",
                "direction": "N",
                "final_value": 42.75,
                "review_status": "accepted",
            }
        ]
    }

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 200
    body = response.json()
    vsitb = next(
        item
        for item in body["variables"]
        if item["variable"] == "Vsitb" and item["direction"] == "N"
    )
    assert vsitb["final_value"] is None
    assert vsitb["review_status"] == "unreviewed"
    assert "review ignored" in " ".join(vsitb["warnings"])
