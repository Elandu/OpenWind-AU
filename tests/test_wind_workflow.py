"""Tests for the AS/NZS site wind workflow layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import openwind_au.api as api_module
from openwind_au.models import WindVariableAssessment, WindWorkflowRequest
from openwind_au.obstructions import run_obstruction_inventory
from openwind_au.wind_workflow import mark_governing_vsitb, vsitb_directional_rows
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

    def fake_inventory(request, *, resolved_site=None):
        return run_obstruction_inventory(
            request,
            footprints=sample_footprints(),
            resolved_site=resolved_site,
        )

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
        "Assessment Basis",
        "Directional Site Wind Speed, Vsit,b",
        "Regional Wind Speed, VR",
        "Wind Direction Multiplier, Md",
        "Terrain Category / Mz,cat",
        "Shielding Multiplier, Ms",
        "Topographic Multiplier, Mt",
        "Reports",
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
    assert 'id="dashboard-address-suggestions"' in body
    assert 'role="combobox"' in body
    assert 'role="listbox"' in body
    assert 'aria-autocomplete="list"' in body
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
    assert 'data-workspace-tab="profile"' in body
    assert 'data-workspace-tab="raw-data"' in body
    assert 'data-workspace-tab="documents"' in body
    assert 'aria-selected="false" tabindex="-1"' in body
    assert 'data-workspace-panel="profile"' in body
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
    assert '<script src="/static/wind_workflow.js?v=' in body
    assert "detail-workspace-active" in script.text
    assert "setIframeHtml(workflowMapFrame, event.data.map_html)" in script.text
    assert '"ArrowLeft", "ArrowRight", "Home", "End"' in script.text
    assert "Generate PDF Report" in body
    assert "Open HTML Report" in body
    assert 'id="workflow-pdf"' in body
    assert "/api/wind-workflow/result/report/pdf" in script.text
    assert 'link.download = "openwind-au-site-wind-assessment.pdf"' in script.text
    assert "<h2>1." not in body
    assert "<h2>2." not in body
    assert "<h2>9." not in body
    assert "Return period / importance level" in body
    assert "Engineer notes" in body
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
    assert "Review and issue status" in body
    assert "Assessment status" in body
    assert "Directional values appear once below." in body
    assert "Engineering overrides" in body
    assert 'id="raw-provenance"' in body
    assert "required" not in body.split('id="dashboard-address"', 1)[1].split("/>", 1)[0]
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
    assert "Calculated regional speed available for engineering override." in body
    assert "Interactive wind assessment map" in body
    assert 'id="workflow-map-frame"' in body
    assert "Terrain Profile Graph" in body
    assert 'id="terrain-profile-frame"' in body
    assert 'class="map-iframe profile-iframe"' in body
    assert 'title="Terrain profile graph"' in body
    assert 'id="wind-region-frame"' not in body
    assert body.count("Directional calculated values with optional engineering overrides.") == 3
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
    assert "Wind input details and warnings" not in script.text
    assert "setWorkflowProgress" in script.text
    assert "hiddenWindInputWarningPatterns" in script.text
    assert "visibleWarnings" in script.text
    assert "Clause 4.4 inputs" not in script.text
    assert "Show geometry" not in script.text
    assert "activateWorkspaceTab" in script.text
    assert "terrainProfileFrame.hidden" in script.text
    assert "syncDesignBuildingOverlay" in script.text
    assert "renderInitialMapFrame" in script.text
    assert "initialMapHtml" in script.text
    assert "zoomMapToAddress" in script.text
    assert "queueAddressSuggestions" in script.text
    assert "dashboard-address-suggestions" in script.text
    assert "/api/geocode/suggest" in script.text
    assert "/api/geocode/resolve" in script.text
    assert "invalidateDesignLocationForAddress" in script.text
    assert 'locationMode = "address"' in script.text
    assert "coordinateOverride = null" in script.text
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
    assert script.text.index("const requestPayload = workflowPayload()") < script.text.index(
        "resetWorkflowSections();"
    )
    for step in range(1, 10):
        assert f'data-step="{step}"' in body
    assert "/api/plots/profile" in script.text
    assert "ctrlKey" not in script.text
    assert "enableBuildingDrag" in script.text
    assert "position_modified" in script.text
    assert "coordinateOverride" in script.text
    assert "assessmentFingerprint" in script.text
    assert "acceptedWorkflowFingerprint(requestPayload, currentWorkflow)" in script.text
    assert "assessmentIsCurrent" in script.text
    assert "activeWorkflowController" in script.text
    workflow_start_cancellation = (
        "cancelAddressResolution();\n  closeAddressSuggestions();\n  cancelActiveWorkflow();"
    )
    assert workflow_start_cancellation in script.text.replace("\r\n", "\n")
    assert "syncCurrentMapSiteToFrame" in script.text
    assert "startReportRequest" in script.text
    assert "reportRequestIsCurrent" in script.text
    assert "cancelActiveReportRequest" in script.text
    assert "allowWorkflowFallback" in script.text
    assert "formatApiError" in script.text
    assert body.count('sandbox="allow-scripts"') >= 2
    assert "allow-same-origin" not in body
    assert "jsonForInlineScript" in script.text
    assert "openwindDesignBuildingLocation" in script.text
    assert 'id="map-coordinate-readout"' in body
    assert 'id="resolved-site-latitude"' in script.text
    assert 'id="resolved-site-longitude"' in script.text
    assert "aria-selected" in script.text
    assert 'aria-controls="workspace-panel-map"' in body
    assert 'aria-labelledby="workspace-tab-map"' in body
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
    assert "inlineAssessmentValueCell" in script.text
    assert "Final editable values" not in script.text
    assert "renderRawProvenance" in script.text
    assert "<th>Source Reference</th>" not in script.text
    assert "Calculation provenance and warnings" in body
    assert "Override Value" not in script.text
    assert "Show calculation" not in script.text
    assert "Show details" not in script.text
    assert "Workflow diagnostics" in body
    stylesheet = test_client.get("/static/styles.css")
    assert stylesheet.status_code == 200
    assert ".workflow-sidepanel" in stylesheet.text
    assert "overflow: visible;" in stylesheet.text


def test_openapi_exposes_preliminary_status_contract_without_duplicate_result_fields(
    monkeypatch,
) -> None:
    test_client = client(monkeypatch)
    schemas = test_client.get("/openapi.json").json()["components"]["schemas"]

    request_properties = schemas["WindWorkflowRequest"]["properties"]
    result_properties = schemas["WindWorkflowResult"]["properties"]

    assert request_properties["assessment_status"]["enum"] == ["draft", "reviewed"]
    assert "reviewed_by" in request_properties
    assert "assessment_status" not in result_properties
    assert "reviewed_by" not in result_properties
    assert "engineer_notes" not in result_properties
    assert "overrides_applied" not in result_properties


def test_browser_review_controls_match_preliminary_api_contract(monkeypatch) -> None:
    test_client = client(monkeypatch)
    page = test_client.get("/")
    script = test_client.get("/static/wind_workflow.js")
    stylesheet = test_client.get("/static/styles.css")

    assert page.status_code == 200
    assert script.status_code == 200
    assert stylesheet.status_code == 200
    assert 'id="assessment_status"' in page.text
    assert 'name="assessment_status"' in page.text
    assert '<option value="draft" selected>Draft preliminary</option>' in page.text
    assert '<option value="reviewed">Reviewed preliminary</option>' in page.text
    assert 'id="review-metadata-fields" class="workflow-review" hidden' in page.text
    assert 'id="reviewed_by"' in page.text
    assert 'name="reviewed_by"' in page.text
    assert 'id="engineer_notes"' in page.text
    assert 'name="engineer_notes"' in page.text
    assert "syncReviewControls();" in script.text
    assert 'assessment_status: data.get("assessment_status") || "draft"' in script.text
    assert "payload.reviewed_by" in script.text
    assert "payload.engineer_notes" in script.text
    assert "setCustomValidity" in script.text
    assert "workflowForm.reportValidity()" in script.text
    assert ".workflow-review[hidden]" in stylesheet.text
    assert "20260712-review-controls-1" in page.text


def test_workflow_report_is_concise_and_keeps_decision_information(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "project_number": "OW-2026-017",
        "engineer_notes": "Assessment reviewed for test issue.",
        "workflow_overrides": sample_overrides(),
    }

    response = test_client.post("/api/wind-workflow/report/html", json=payload)

    assert response.status_code == 200
    assert "Project and outcome" in response.text
    assert "OW-2026-017" in response.text
    assert "Directional site wind speeds" in response.text
    assert "Review items" in response.text
    assert "Basis and limitations" in response.text
    assert response.text.count("<section") == 4
    assert "Assessment status" in response.text
    assert "Draft preliminary" in response.text
    assert "PRELIMINARY - NOT FOR CERTIFICATION" in response.text
    assert "Executive Summary" not in response.text
    assert "Variable Summary" not in response.text
    assert "Wind Region Assessment" not in response.text
    assert "Regional Wind Speed Assessment" not in response.text
    assert "Direction Multiplier Assessment" not in response.text
    assert "Maps" not in response.text
    assert "Profiles" not in response.text
    assert "configured Geoscience Australia 1170.2 GIS dataset" in response.text
    assert "Table 3.1(A)" in response.text
    assert "Table 3.2(A)" in response.text
    assert "verified_against_standard" not in response.text
    assert "local path" not in response.text
    assert "Overrides Applied" not in response.text
    assert "Project engineer selected a directional override after review." in response.text
    assert "Assessment reviewed for test issue." in response.text
    assert "enclosed industrial building" not in response.text
    assert "30 m x 20 m x 10 m" not in response.text
    assert "Vsit,b = VR x Md x Mz,cat x Ms x Mt" in response.text
    assert response.text.count("No final design pressures") == 1


def test_final_issue_status_is_rejected_by_workflow_and_request_report_routes(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {"assessment_status": "final"}

    for path in (
        "/api/wind-workflow",
        "/api/wind-workflow/stream",
        "/api/wind-workflow/report/html",
        "/api/wind-workflow/report/pdf",
    ):
        response = test_client.post(path, json=payload)

        assert response.status_code == 422
        assert "Final or certified issue is not supported" in response.text


def test_reviewed_preliminary_status_requires_reviewer_and_notes(monkeypatch) -> None:
    test_client = client(monkeypatch)

    missing_reviewer = test_client.post(
        "/api/wind-workflow",
        json=workflow_payload()
        | {"assessment_status": "reviewed", "engineer_notes": "Checked inputs."},
    )
    missing_notes = test_client.post(
        "/api/wind-workflow",
        json=workflow_payload() | {"assessment_status": "reviewed", "reviewed_by": "Engineer A"},
    )

    assert missing_reviewer.status_code == 422
    assert "reviewed_by is required" in missing_reviewer.text
    assert missing_notes.status_code == 422
    assert "engineer_notes are required" in missing_notes.text


def test_reviewed_preliminary_report_records_reviewer_without_duplicate_result_fields(
    monkeypatch,
) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "assessment_status": "reviewed",
        "reviewed_by": "Engineer A",
        "engineer_notes": "Reviewed terrain and multiplier inputs for preliminary issue.",
    }

    workflow = test_client.post("/api/wind-workflow", json=payload)
    report = test_client.post("/api/wind-workflow/report/html", json=payload)

    assert workflow.status_code == 200
    body = workflow.json()
    assert body["input"]["assessment_status"] == "reviewed"
    assert body["input"]["reviewed_by"] == "Engineer A"
    assert "assessment_status" not in {key for key in body if key != "input"}
    assert "engineer_notes" not in {key for key in body if key != "input"}
    assert report.status_code == 200
    assert "Reviewed preliminary - Engineer A" in report.text
    assert "PRELIMINARY - NOT FOR CERTIFICATION" in report.text


def test_completed_result_report_routes_reject_tampered_or_redundant_status(monkeypatch) -> None:
    test_client = client(monkeypatch)
    workflow = test_client.post("/api/wind-workflow", json=workflow_payload())
    assert workflow.status_code == 200
    tampered = workflow.json()
    tampered["input"]["assessment_status"] = "final"
    redundant = workflow.json() | {"assessment_status": "final"}

    for path in (
        "/api/wind-workflow/result/report/html",
        "/api/wind-workflow/result/report/pdf",
    ):
        tampered_response = test_client.post(path, json=tampered)
        redundant_response = test_client.post(path, json=redundant)

        assert tampered_response.status_code == 422
        assert "Final or certified issue is not supported" in tampered_response.text
        assert redundant_response.status_code == 422
        assert "Extra inputs are not permitted" in redundant_response.text


def test_completed_result_report_routes_require_valid_server_integrity_token(monkeypatch) -> None:
    test_client = client(monkeypatch)
    workflow = test_client.post("/api/wind-workflow", json=workflow_payload())
    assert workflow.status_code == 200
    authentic = workflow.json()
    assert authentic["integrity_token"].startswith("owau-hmac-sha256-v1:")

    tampered = json.loads(json.dumps(authentic))
    tampered["directional_vsitb"][0]["final_vsitb"] += 10
    unsigned = json.loads(json.dumps(authentic))
    unsigned.pop("integrity_token")

    for path in (
        "/api/wind-workflow/result/report/html",
        "/api/wind-workflow/result/report/pdf",
    ):
        tampered_response = test_client.post(path, json=tampered)
        unsigned_response = test_client.post(path, json=unsigned)

        assert tampered_response.status_code == 422
        assert "inconsistent" in tampered_response.text.lower()
        assert unsigned_response.status_code == 422
        assert "missing" in unsigned_response.text.lower()


def test_wind_workflow_pdf_endpoint_returns_compact_download(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {"project_number": "OW-2026-017"}

    response = test_client.post("/api/wind-workflow/report/pdf", json=payload)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        'attachment; filename="openwind-au-site-wind-assessment.pdf"'
    )
    assert response.content.startswith(b"%PDF-")
    assert len(response.content) > 2_000


def test_wind_workflow_pdf_escapes_untrusted_project_text(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "project_number": "OW-<b>unclosed & unsafe",
        "engineer_notes": "Check 5 < 6 & do not parse <font color='red'>markup",
    }

    response = test_client.post("/api/wind-workflow/report/pdf", json=payload)

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert len(response.content) > 2_000


def test_completed_workflow_pdf_endpoint_does_not_rerun_analysis(monkeypatch) -> None:
    test_client = client(monkeypatch)
    workflow_response = test_client.post("/api/wind-workflow", json=workflow_payload())
    assert workflow_response.status_code == 200

    def fail_if_rerun(*_args, **_kwargs):
        raise AssertionError("completed-result report endpoint reran the workflow")

    monkeypatch.setattr(api_module, "run_wind_workflow", fail_if_rerun)
    response = test_client.post(
        "/api/wind-workflow/result/report/pdf",
        json=workflow_response.json(),
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")


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
    assert r"Terrain profiles \u0026 topographic candidates" in body
    assert "Nearby obstructions" in body
    assert "openWindNearbyObstructionFootprintLayer" in body
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
    assert "enableBuildingDrag" in body
    assert "position_modified" in body
    assert "ctrlKey" not in body
    assert "Raw OSM building polygons before filtering" not in body
    assert "Manual reviewed obstruction geometry" not in body
    assert "Building footprints (source context)" not in body
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


def test_vsitb_override_updates_summary_and_governing_result(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "workflow_overrides": [
            {
                "variable": "Vsitb",
                "direction": "N",
                "override_value": 99,
                "reason": "Reviewed directional site wind speed.",
            }
        ]
    }

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 200
    body = response.json()
    north_row = next(row for row in body["directional_vsitb"] if row["direction"] == "N")
    north_variable = next(
        item
        for item in body["variables"]
        if item["variable"] == "Vsitb" and item["direction"] == "N"
    )
    assert north_row["recommended_vsitb"] != 99
    assert north_row["final_vsitb"] == 99
    assert north_row["is_governing"] is True
    assert north_variable["calculated_value"] == north_row["recommended_vsitb"]
    assert north_variable["final_value"] == 99
    assert north_variable["is_overridden"] is True
    assert body["governing_direction"] == "N"
    assert body["governing_vsitb"] == 99


def test_invalid_or_duplicate_override_scopes_are_rejected(monkeypatch) -> None:
    test_client = client(monkeypatch)
    invalid_overrides = [
        {
            "workflow_overrides": [
                {
                    "variable": "VR",
                    "direction": "N",
                    "override_value": 45,
                    "reason": "invalid",
                }
            ]
        },
        {"workflow_overrides": [{"variable": "Md", "override_value": 1, "reason": "invalid"}]},
        {"class_multiplier_overrides": [{"direction": "N", "ms": 0.9, "reason": "invalid"}]},
        {"class_multiplier_overrides": [{"direction": "N", "reason": "invalid"}]},
        {
            "workflow_overrides": [
                {"variable": "Md", "direction": "N", "override_value": 0.8, "reason": "first"},
                {"variable": "Md", "direction": "N", "override_value": 0.9, "reason": "second"},
            ]
        },
    ]

    for invalid in invalid_overrides:
        response = test_client.post("/api/wind-workflow", json=workflow_payload() | invalid)

        assert response.status_code == 422


def test_class_multiplier_overrides_drive_directional_variables(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "project_number": "OW-2026-018",
        "class_multiplier_overrides": [
            {
                "direction": "N",
                "terrain_category": "TC3",
                "shielding_class": "FS",
                "topographic_class": "T1",
                "ms": 0.85,
                "mt": 1.08,
                "reason": "Reference calculation classes accepted by engineer.",
                "source_reference": "reference calculation reference",
            }
        ],
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

    assert mzcat_north["final_value"] == 0.83
    assert ms_north["final_value"] == 0.85
    assert mt_north["final_value"] == 1.08
    assert "Reviewed TC TC3" in mzcat_north["recommended_label"]
    assert "Reviewed FS" in ms_north["recommended_label"]
    assert "Reviewed T1" in mt_north["recommended_label"]
    assert any("Reference calculation classes" in item for item in mzcat_north["detail_items"])
    assert any("explicit reviewed numeric override" in warning for warning in ms_north["warnings"])
    north = next(row for row in body["directional_vsitb"] if row["direction"] == "N")
    assert north["mzcat"] == 0.83
    assert north["ms"] == 0.85
    assert north["mt"] == 1.08
    assert north["final_vsitb"] is not None


def test_project_classes_without_numeric_values_do_not_invent_multipliers(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "class_multiplier_overrides": [
            {
                "direction": "N",
                "shielding_class": "FS",
                "topographic_class": "T1",
                "reason": "Reference classes recorded without reviewed numeric multipliers.",
            }
        ],
    }

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 200
    body = response.json()
    ms_north = next(
        item for item in body["variables"] if item["variable"] == "Ms" and item["direction"] == "N"
    )
    mt_north = next(
        item for item in body["variables"] if item["variable"] == "Mt" and item["direction"] == "N"
    )
    assert ms_north["final_value"] == ms_north["calculated_value"]
    assert mt_north["final_value"] == mt_north["calculated_value"]
    assert any("without a numeric Ms" in warning for warning in ms_north["warnings"])
    assert any("without a numeric Mt" in warning for warning in mt_north["warnings"])


def test_structured_building_inputs_are_preserved(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "project_number": "OW-2026-018",
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
    assert body["input"]["project_number"] == "OW-2026-018"
    assert body["input"]["structure_orientation_deg"] == 0
    assert body["input"]["roof_shape"] == "gable"
    assert body["input"]["building_width_m"] == 4
    assert body["input"]["building_length_m"] == 5
    assert body["input"]["base_rl_m"] == 0
    assert report.status_code == 200
    assert "OW-2026-018" in report.text
    assert "Height 10.00 m" in report.text
    assert "4.00 m x" in report.text
    assert "5.00 m" in report.text
    assert "; building" in report.text
    assert "Roof shape" not in report.text
    assert "Base RL" not in report.text


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
    mzcat_source = next(
        item["source_reference"] for item in body["variables"] if item["variable"] == "Mzcat"
    )
    ms_source = next(
        item["source_reference"] for item in body["variables"] if item["variable"] == "Ms"
    )
    assert "schema_version=1" in mzcat_source and "values_sha256=" in mzcat_source
    assert "schema_version=1" in ms_source and "values_sha256=" in ms_source
    for row in body["directional_vsitb"]:
        expected = row["vr"] * row["md"] * row["mzcat"] * row["ms"] * row["mt"]
        assert row["recommended_vsitb"] == pytest.approx(expected)
        assert row["final_vsitb"] == pytest.approx(expected)


def test_full_precision_product_controls_governing_direction_before_display_rounding() -> None:
    def variable(
        name: str,
        direction: str | None,
        value: float,
    ) -> WindVariableAssessment:
        return WindVariableAssessment(
            variable=name,  # type: ignore[arg-type]
            label=name,
            direction=direction,  # type: ignore[arg-type]
            calculated_value=value,
            final_value=value,
            evidence_link="#test",
            formula_basis="test input",
            calculation_result="test input",
        )

    variables = [variable("VR", None, 1.0)]
    for direction, md in (("N", 0.900040), ("NE", 0.900049)):
        variables.extend(
            [
                variable("Md", direction, md),
                variable("Mzcat", direction, 1.0),
                variable("Ms", direction, 1.0),
                variable("Mt", direction, 1.0),
            ]
        )

    rows = mark_governing_vsitb(vsitb_directional_rows(variables))
    north = next(row for row in rows if row.direction == "N")
    north_east = next(row for row in rows if row.direction == "NE")

    assert round(north.final_vsitb or 0.0, 3) == round(north_east.final_vsitb or 0.0, 3)
    assert north.is_governing is False
    assert north_east.is_governing is True


def test_average_height_cannot_exceed_overall_building_height() -> None:
    with pytest.raises(ValueError, match="[Aa]verage.*building height"):
        WindWorkflowRequest(
            latitude=-33.86,
            longitude=151.21,
            building_height_m=10.0,
            average_height_m=10.1,
            radius_m=500,
        )


def test_ignored_legacy_workflow_fields_are_rejected(monkeypatch) -> None:
    test_client = client(monkeypatch)
    obsolete_payloads = [
        {"wind_region": "A2"},
        {"regional_wind_speed_mps": 45},
        {"wind_direction_multipliers": {"N": 1.0}},
        {"workflow_reviews": []},
    ]

    for obsolete in obsolete_payloads:
        response = test_client.post(
            "/api/wind-workflow",
            json=workflow_payload() | obsolete,
        )

        assert response.status_code == 422
        assert "Extra inputs are not permitted" in response.text


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
