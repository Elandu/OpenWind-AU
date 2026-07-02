"""Tests for the AS/NZS site wind workflow layer."""

from __future__ import annotations

import json
from pathlib import Path

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
        "annual_exceedance_probability": "1/500",
        "importance_level": "IL2 / 1:500",
        "user_assumptions": (
            "Terrain and shielding inputs to be reviewed by the project engineer."
        ),
        "structure_type": "enclosed industrial building",
        "building_dimensions": "30 m x 20 m x 10 m",
        "design_life_years": 50,
    }


def sample_overrides() -> list[dict]:
    return [
        {
            "variable": "Md",
            "direction": "N",
            "override_value": 0.8,
            "reason": "Project engineer selected a directional override after review.",
        }
    ]


def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "SRTMProvider", lambda: FlatDEM())
    monkeypatch.setenv(
        "OPENWIND_WIND_REGION_DATASET",
        str(Path(__file__).parent / "fixtures" / "wind_regions_sample.geojson"),
    )

    def fake_inventory(request):
        return run_obstruction_inventory(request, footprints=sample_footprints())

    monkeypatch.setattr(api_module, "run_obstruction_inventory", fake_inventory)
    return TestClient(api_module.create_app())


def test_wind_workflow_page_loads_in_map_first_order(monkeypatch) -> None:
    test_client = client(monkeypatch)

    response = test_client.get("/")
    workflow_page = test_client.get("/wind-workflow")
    support_page = test_client.get("/site-analysis")
    script = test_client.get("/static/wind_workflow.js")

    assert response.status_code == 200
    assert workflow_page.status_code == 200
    assert support_page.status_code == 200
    assert script.status_code == 200
    body = response.text
    headings = [
        "Site Wind Assessment",
        "Run Assessment",
        "Interactive Wind Map",
        "Map Layers",
        "Resolved Site and Wind Inputs",
        "Regional Wind Speed, VR",
        "Wind Direction Multiplier, Md",
        "Terrain Category / Mz,cat",
        "Shielding Multiplier, Ms",
        "Topographic Multiplier, Mt",
        "Site Wind Speed, Vsit,b",
        "Report and Diagnostics",
    ]
    assert all(heading in body for heading in headings)
    assert [body.index(heading) for heading in headings] == sorted(
        body.index(heading) for heading in headings
    )
    assert "wind_workflow.js" in body
    assert 'class="dashboard-topbar"' in body
    assert "OpenWind" in body
    assert "<p>AU</p>" in body
    assert 'class="dashboard-project"' in body
    assert 'id="dashboard-project-number"' in body
    assert 'id="dashboard-address"' in body
    assert 'list="dashboard-address-suggestions"' in body
    assert 'id="dashboard-address-suggestions"' in body
    assert 'form="workflow-form"' in body
    assert 'name="address"' in body
    assert 'class="workflow-progress"' in body
    assert 'role="progressbar"' in body
    assert "Ready to run assessment" in body
    assert 'class="dashboard-kpis"' in body
    assert 'class="dashboard-shell workflow-only map-first-shell"' in body
    assert 'class="map-workspace"' in body
    assert 'class="map-control-rail"' in body
    assert 'class="map-canvas-panel"' in body
    assert 'class="workspace-tabs"' in body
    assert 'data-workspace-tab="map"' in body
    assert 'data-workspace-tab="raw-data"' in body
    assert 'data-workspace-tab="documents"' in body
    assert 'data-workspace-panel="raw-data"' in body
    assert 'data-workspace-panel="documents"' in body
    assert 'class="workflow-sidepanel"' not in body
    assert 'role="tablist"' in body
    assert 'data-sidepanel-tab="maps"' not in body
    assert 'aria-selected="true"' in body
    assert 'role="tabpanel"' in body
    assert "Design building footprint" in body
    assert 'class="evidence-sidebar"' not in body
    assert 'data-step="1"' in body
    assert 'data-step="9"' in body
    assert "20260702-map-workspace-6" in body
    assert "Open Site Wind Assessment Report" in body
    assert "<h2>1." not in body
    assert "<h2>2." not in body
    assert "<h2>9." not in body
    assert "Return period / importance level" in body
    assert "Engineer notes" not in body
    assert "Advanced inputs" in body
    assert body.count("<option value=") >= 17
    for orientation in [
        "-90",
        "-78.75",
        "-67.5",
        "-56.25",
        "-45",
        "-33.75",
        "-22.5",
        "-11.25",
        "0",
        "11.25",
        "22.5",
        "33.75",
        "45",
        "56.25",
        "67.5",
        "78.75",
        "90",
    ]:
        assert f'<option value="{orientation}"' in body
    assert "Street address" not in body
    assert "Assessment status" not in body
    assert "Resolved site data, wind-region lookup, and VR." in body
    assert "User assumptions" not in body
    assert "Structure type" not in body
    assert "Building dimensions" not in body
    assert "Design life" not in body
    assert 'id="latitude"' not in body
    assert 'id="longitude"' not in body
    assert 'id="wind_region"' not in body
    assert "Selected VR" not in body
    assert "Mz,cat recommendation mode" not in body
    assert "<th>Review</th>" not in body
    assert "Review status" not in body
    assert "Accept</button>" not in body
    assert "Override" not in body
    assert "source reference, and VR" in body
    assert "Wind Inputs Summary" in body
    assert "Interactive wind assessment map" in body
    assert 'id="workflow-map-frame"' in body
    assert "Terrain Profile Graph" in body
    assert 'id="terrain-profile-frame"' in body
    assert 'class="profile-iframe"' in body
    assert 'id="wind-region-frame"' not in body
    assert "Recommended TC, Final TC, Recommended Mz,cat, and Final Mz,cat" in body
    assert "Recommended Ms, Final Ms" in body
    assert "Recommended Mt, Final Mt" in body
    assert "Evidence tools" not in body
    assert "Supporting Evidence and Maps" not in body
    assert "Terrain Evidence" not in body
    assert "Shielding Evidence" not in body
    assert "Topographic Evidence" not in body
    assert "Validation" not in body
    assert "Region checks" not in body
    assert "Shielding candidates, sector polygons" not in body
    assert 'href="/site-analysis#terrain-evidence"' not in body
    assert 'href="/site-analysis#shielding-evidence"' not in body
    assert 'href="/site-analysis#topographic-evidence"' not in body
    assert 'href="/site-analysis#profiles"' not in body
    assert "Dataset details" in script.text
    assert "setWorkflowProgress" in script.text
    assert "hiddenWindInputWarningPatterns" in script.text
    assert "visibleWarnings" in script.text
    assert "activateWorkspaceTab" in script.text
    assert "syncDesignBuildingOverlay" in script.text
    assert "renderInitialMapFrame" in script.text
    assert "initialMapHtml" in script.text
    assert "zoomMapToAddress" in script.text
    assert "queueAddressSuggestions" in script.text
    assert "dashboard-address-suggestions" in script.text
    assert "/api/analyse" in script.text
    assert "/api/geocode/suggest" in script.text
    assert "keydown" in script.text
    assert "tile.openstreetmap.org" in script.text
    assert "orientationOptions" in script.text
    assert "openWindDesignBuilding" in script.text
    assert "openWindWorkflowMap" in script.text
    assert "nudgeDesignBuilding" in script.text
    assert "offset_east_m" in script.text
    assert "startOrientationDrag" in script.text
    assert "applyOrientationFromLatLng" in script.text
    assert "nearestOrientationOption" in script.text
    assert "openwind-design-building-change" in script.text
    assert "adjustedLocationFromDesignState" in script.text
    assert "/api/plots/profile" in script.text
    assert "ctrlKey" in script.text
    assert "aria-selected" in script.text
    assert "/api/wind-workflow/stream" in script.text
    assert "handleWorkflowStreamEvent" in script.text
    assert "Live progress unavailable" in script.text
    assert "renderSiteAnalysisProgress" in script.text
    assert "renderWindInputsProgress" in script.text
    assert "renderObstructionProgress" in script.text
    assert "renderTerrainProgress" in script.text
    assert "Validation checks" not in script.text
    assert "Evidence</a>" not in script.text
    assert "mdStandardCell" in script.text
    assert "md-standard-table" in script.text
    assert "Governing Md" not in script.text
    assert "inlineFinalValueCell" in script.text
    assert "tableCalculationSummary" in script.text
    assert "Override Value" not in script.text
    assert "Show calculation" not in script.text
    assert "Show details" not in script.text
    assert "Workflow diagnostics" in body
    stylesheet = test_client.get("/static/styles.css")
    assert stylesheet.status_code == 200
    assert ".workflow-sidepanel" in stylesheet.text
    assert "overflow: visible;" in stylesheet.text


def test_calculation_panel_content_in_workflow_report(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "engineer_notes": "Assessment reviewed for test issue.",
        "workflow_overrides": sample_overrides(),
    }

    response = test_client.post("/api/wind-workflow/report/html", json=payload)

    assert response.status_code == 200
    assert "Executive Summary" in response.text
    assert "2. Site Information" in response.text
    assert "3. Wind Assessment Summary" in response.text
    assert "4. Directional Results Table" in response.text
    assert "5. Terrain Category" in response.text
    assert "6. Shielding" in response.text
    assert "7. Topography" in response.text
    assert "8. Vsit,b" in response.text
    assert "9. Maps" in response.text
    assert "10. Profiles" in response.text
    assert "11. Engineer Notes" in response.text
    assert "12. Limitations" in response.text
    assert "Assessment status" not in response.text
    assert "<span>Status</span>" not in response.text
    assert "Variable Summary" in response.text
    assert "Wind Region Assessment" in response.text
    assert "Regional Wind Speed Assessment" in response.text
    assert "Direction Multiplier Assessment" in response.text
    assert "Geoscience Australia 1170.2 Wind Regions" in response.text
    assert "Editable regional wind speed lookup table" in response.text
    assert "Editable direction multiplier lookup table" in response.text
    assert "Overrides Applied" in response.text
    assert "Project engineer selected a directional override after review." in response.text
    assert "Assessment reviewed for test issue." in response.text
    assert "Review Status" not in response.text
    assert "Engineer Review Notes" not in response.text
    assert "enclosed industrial building" not in response.text
    assert "30 m x 20 m x 10 m" not in response.text
    assert "Formula / basis" in response.text
    assert "Source Reference" in response.text
    assert "Evidence Reference" not in response.text
    assert "Supporting Evidence" not in response.text
    assert "Evidence / source details" not in response.text
    assert "Vsit,b = VR x Md x Mz,cat x Ms x Mt" in response.text
    assert "No final design pressure calculations are included" in response.text
    assert "Pressure, cladding, Cpe, and Cpi calculations are outside this scope." in response.text


def test_wind_workflow_combined_map_has_toggle_layers(monkeypatch) -> None:
    test_client = client(monkeypatch)

    response = test_client.post("/api/wind-workflow/map", json=workflow_payload())

    assert response.status_code == 200
    body = response.text
    assert "L.control.layers" in body
    assert "Wind regions" in body
    assert "Mz,cat sectors" in body
    assert "Shielding sectors" in body
    assert "Shielding obstruction polygons" in body
    assert "Topographic feature candidates" in body
    assert "Nearby obstructions" in body
    assert "Design building" in body
    assert "openWindDesignBuilding" in body
    assert "openWindWorkflowMap" in body
    assert "nudgeDesignBuilding" in body
    assert "offset_east_m" in body
    assert "orientation_options" in body
    assert "setOrientation" in body
    assert "setDimensions" in body
    assert "startOrientationDrag" in body
    assert "applyOrientationFromLatLng" in body
    assert "Raw OSM building polygons before filtering" not in body
    assert "Manual reviewed obstruction geometry" not in body
    assert "Building footprints" in body
    assert "Microsoft building footprints" not in body
    assert "OSM fallback and matched attributes" not in body
    assert "Vegetation polygons" not in body
    assert "Shielding candidates" not in body
    assert "Topographic circles" not in body


def test_wind_workflow_stream_sends_incremental_stage_payloads(monkeypatch) -> None:
    test_client = client(monkeypatch)

    with test_client.stream(
        "POST", "/api/wind-workflow/stream", json=workflow_payload()
    ) as response:
        assert response.status_code == 200
        events = [json.loads(line) for line in response.iter_lines() if line]

    stages = [event["stage"] for event in events]
    labels = [event["label"] for event in events]
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
    assert "Resolving site location and elevation" in labels
    assert "Site resolved; calculating wind region, VR, and Md" in labels
    assert "Wind inputs calculated; building obstruction inventory" in labels
    assert "Obstructions analysed; calculating terrain category and Mz,cat" in labels
    assert "Terrain and Mz,cat calculated; calculating directional Vsit,b" in labels
    assert "Directional variables calculated; rendering combined map layers" in labels
    assert events[1]["data"]["site_analysis"]["site"]["ground_elevation_m"] == 75
    assert events[2]["data"]["wind_region_assessment"]["wind_region"] == "A2"
    assert events[3]["data"]["obstruction_summary"]["total_obstructions"] > 0
    assert events[4]["data"]["terrain_category_evidence"]["mzcat_assessment"]
    assert events[5]["data"]["workflow"]["governing_direction"] is not None
    assert "L.control.layers" in events[6]["data"]["map_html"]


def test_vsitb_calculates_without_variable_review(monkeypatch) -> None:
    test_client = client(monkeypatch)

    response = test_client.post("/api/wind-workflow", json=workflow_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["wind_region_assessment"]["wind_region"] == "A2"
    assert body["regional_wind_speed_assessment"]["vr_ult"] == 45.0
    assert body["regional_wind_speed_assessment"]["vr_serv"] == 37.0
    assert len(body["direction_multiplier_assessment"]["directions"]) == 8
    vr = next(item for item in body["variables"] if item["variable"] == "VR")
    md_north = next(
        item for item in body["variables"] if item["variable"] == "Md" and item["direction"] == "N"
    )
    mzcat_north = next(
        item
        for item in body["variables"]
        if item["variable"] == "Mzcat" and item["direction"] == "N"
    )
    assert vr["detail_label"] == "Show source"
    assert "regional wind speed lookup table" in vr["source_reference"]
    assert vr["final_value"] == 45.0
    assert vr["calculated_value"] == 45.0
    assert md_north["detail_label"] == "Show source"
    assert "Direction: N" in md_north["detail_items"]
    assert md_north["final_value"] == 0.85
    assert md_north["calculated_value"] == 0.85
    assert mzcat_north["detail_label"] == "Show details"
    assert "Recommended TC" in mzcat_north["recommended_label"]
    assert mzcat_north["final_value"] is not None
    assert any("Interpolation details" in item for item in mzcat_north["calculation_inputs"])
    ms_north = next(
        item for item in body["variables"] if item["variable"] == "Ms" and item["direction"] == "N"
    )
    mt_north = next(
        item for item in body["variables"] if item["variable"] == "Mt" and item["direction"] == "N"
    )
    assert ms_north["detail_label"] == "Show details"
    assert any("Contributing obstructions" in item for item in ms_north["detail_items"])
    assert any("Rejected obstructions" in item for item in ms_north["detail_items"])
    assert mt_north["detail_label"] == "Show details"
    north = next(row for row in body["directional_vsitb"] if row["direction"] == "N")
    assert north["status"] == "calculated"
    assert north["final_vsitb"] is not None
    assert not north["warnings"]
    assert all(row["status"] == "calculated" for row in body["directional_vsitb"])
    assert all(variable["final_value"] is not None for variable in body["variables"])
    assert all("review_status" not in variable for variable in body["variables"])
    assert all("review_status" not in row for row in body["directional_vsitb"])


def test_reasoned_override_values_propagate_to_workflow(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {"workflow_overrides": sample_overrides()}

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 200
    body = response.json()
    md_north = next(
        item for item in body["variables"] if item["variable"] == "Md" and item["direction"] == "N"
    )
    assert md_north["calculated_value"] == 0.85
    assert md_north["final_value"] == 0.8
    assert md_north["is_overridden"] is True
    assert (
        md_north["override_reason"]
        == "Project engineer selected a directional override after review."
    )
    vr = next(item for item in body["variables"] if item["variable"] == "VR")
    assert vr["final_value"] == 45
    north = next(row for row in body["directional_vsitb"] if row["direction"] == "N")
    assert north["md"] == 0.8
    assert north["final_vsitb"] is not None


def test_class_multiplier_overrides_drive_directional_variables(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "class_multiplier_overrides": [
            {
                "direction": "N",
                "terrain_category": "TC3",
                "shielding_class": "FS",
                "topographic_class": "T1",
                "reason": "Reference calculation classes accepted by engineer.",
                "source_reference": "reference calculation reference",
            }
        ]
    }

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 200
    body = response.json()
    mzcat_north = next(
        item
        for item in body["variables"]
        if item["variable"] == "Mzcat" and item["direction"] == "N"
    )
    ms_north = next(
        item for item in body["variables"] if item["variable"] == "Ms" and item["direction"] == "N"
    )
    mt_north = next(
        item for item in body["variables"] if item["variable"] == "Mt" and item["direction"] == "N"
    )

    assert mzcat_north["final_value"] == 0.91
    assert ms_north["final_value"] == 0.85
    assert mt_north["final_value"] == 1.08
    assert "Reviewed TC TC3" in mzcat_north["recommended_label"]
    assert "Reviewed FS" in ms_north["recommended_label"]
    assert "Reviewed T1" in mt_north["recommended_label"]
    assert any("Reference calculation classes" in item for item in mzcat_north["detail_items"])
    assert any("class override" in warning for warning in ms_north["warnings"])
    north = next(row for row in body["directional_vsitb"] if row["direction"] == "N")
    assert north["mzcat"] == 0.91
    assert north["ms"] == 0.85
    assert north["mt"] == 1.08
    assert north["final_vsitb"] is not None


def test_structured_building_inputs_are_preserved(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "structure_class": "building",
        "structure_orientation_deg": 0,
        "roof_shape": "gable",
        "building_width_m": 4,
        "building_length_m": 5,
        "roof_pitch_deg": 15,
        "average_height_m": 3,
        "base_rl_m": 0,
    }

    response = test_client.post("/api/wind-workflow", json=payload)
    report = test_client.post("/api/wind-workflow/report/html", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["input"]["structure_class"] == "building"
    assert body["input"]["structure_orientation_deg"] == 0
    assert body["input"]["roof_shape"] == "gable"
    assert body["input"]["building_width_m"] == 4
    assert body["input"]["building_length_m"] == 5
    assert body["input"]["base_rl_m"] == 0
    assert report.status_code == 200
    assert "Structure class" in report.text
    assert "Roof shape" in report.text
    assert "Base RL" in report.text


def test_vsitb_calculated_for_all_directions_immediately(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload()

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["governing_direction"] is not None
    assert body["governing_vsitb"] is not None
    north = next(row for row in body["directional_vsitb"] if row["direction"] == "N")
    assert north["status"] == "calculated"
    assert north["final_vsitb"] is not None
    assert all(row["final_vsitb"] is not None for row in body["directional_vsitb"])
    assert {item["variable"] for item in body["variables"] if item["direction"] in {None, "N"}} >= {
        "VR",
        "Md",
        "Mzcat",
        "Ms",
        "Mt",
        "Vsitb",
    }


def test_legacy_variable_reviews_do_not_gate_or_override_vsitb(monkeypatch) -> None:
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
    assert vsitb["final_value"] is not None
    assert vsitb["final_value"] != 42.75
    assert vsitb["is_overridden"] is False
    assert not vsitb["warnings"]


def test_override_requires_reason(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "workflow_overrides": [
            {
                "variable": "Md",
                "direction": "N",
                "override_value": 0.8,
                "reason": "",
            }
        ]
    }

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 422
