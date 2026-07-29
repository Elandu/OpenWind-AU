"""Tests for the AS/NZS site wind workflow layer."""

from __future__ import annotations

import base64
import json
import logging
import re
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PillowImage
from pydantic import BaseModel

import openwind_au.api as api_module
import openwind_au.reports as reports_module
import openwind_au.wind_workflow as workflow_module
from openwind_au.models import (
    WindRegionAssessment,
    WindVariableAssessment,
    WindWorkflowRequest,
    WindWorkflowResult,
)
from openwind_au.obstructions import run_obstruction_inventory
from openwind_au.reports import (
    WIND_WORKFLOW_REPORT_SCOPE,
    WIND_WORKFLOW_REPORT_SUBTITLE,
    _draw_wind_pdf_page,
    _validate_wind_pdf_map_screenshot,
    _validate_wind_pdf_map_screenshot_dimensions,
    concise_workflow_warnings,
    render_wind_workflow_pdf_report,
)
from openwind_au.standard_calculations import design_wind_speed
from openwind_au.wind_inputs import VR_EQUATION_REFERENCE
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


def map_screenshot_bytes(
    image_format: str = "PNG",
    size: tuple[int, int] = (1200, 675),
) -> bytes:
    output = BytesIO()
    image = PillowImage.new("RGB", size, color=(220, 235, 228))
    image.save(output, format=image_format)
    return output.getvalue()


def sample_overrides() -> list[dict]:
    return [
        {
            "variable": "Md",
            "direction": "N",
            "override_value": 0.8,
            "reason": "Project engineer selected a directional override after review.",
        }
    ]


def _pydantic_model_types(annotation):
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for argument in get_args(annotation):
        yield from _pydantic_model_types(argument)


def _nested_value(payload, path):
    value = payload
    for key in path:
        value = value[key]
    return value


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


def test_workflow_invalid_signing_configuration_returns_service_unavailable(monkeypatch) -> None:
    test_client = client(monkeypatch)
    monkeypatch.setenv("OPENWIND_RESULT_SIGNING_KEY", "too-short")

    response = test_client.post("/api/wind-workflow", json=workflow_payload())

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "OPENWIND_RESULT_SIGNING_KEY must contain at least 32 UTF-8 bytes."
    )


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
        "Editable assessment values",
        "Assessment Basis",
        "Regional Wind Speed, VR",
        "Climate Change Multiplier, Mc",
        "Directional Site Wind Speed, Vsit,b",
        "Building-Orthogonal Design Wind Speed",
        "Calculation provenance and warnings",
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
    assert 'data-workspace-tab="raw-data"' not in body
    assert 'data-workspace-tab="documents"' not in body
    assert 'aria-selected="false" tabindex="-1"' in body
    assert 'data-workspace-panel="profile"' in body
    assert 'id="workspace-panel-raw-data" class="below-map-output"' in body
    assert 'id="workspace-panel-documents" class="below-map-output"' in body
    assert 'data-workspace-panel="raw-data"' not in body
    assert 'data-workspace-panel="documents"' not in body
    assert 'class="workflow-sidepanel"' not in body
    assert 'role="tablist"' in body
    assert 'data-sidepanel-tab="maps"' not in body
    assert 'aria-selected="true"' in body
    assert 'role="tabpanel"' in body
    assert "Design building footprint" in body
    assert 'class="evidence-sidebar"' not in body
    assert 'data-step="1"' in body
    assert 'data-step="3"' in body
    assert 'data-step="10"' in body
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
    assert "Importance level (report metadata only)" in body
    assert "does not select AEP / ARI" in body
    assert "<tr><th>AEP / ARI</th>" in script.text
    assert "importance metadata:" in script.text
    assert "Engineer notes" not in body
    assert "Advanced inputs" in body
    assert 'id="structure_orientation_deg"' in body
    orientation_control = body.split('id="structure_orientation_deg"', 1)[1].split("/>", 1)[0]
    assert 'type="number"' in orientation_control
    assert 'min="0"' in orientation_control
    assert 'max="359.9"' in orientation_control
    assert 'step="0.1"' in orientation_control
    assert "required" in orientation_control
    assert '<select id="structure_orientation_deg"' not in body
    assert "Right, Back, and Left add" in body
    assert "drives the Clause 2.3" in body
    assert 'id="vdes-table"' in body
    assert "Street address" not in body
    assert "Review and issue status" not in body
    assert "Assessment status" not in body
    assert "Directional values appear once below." in body
    assert "Editable assessment values" in body
    assert 'id="raw-data-save"' in body
    assert "Save all changes" in body
    assert "Undo unsaved edits" in body
    assert "Reset to calculated values" in body
    assert "Engineering overrides" not in body
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
    assert "Regional speed is editable in place and saved with the other Raw Data changes." in body
    assert "Interactive wind assessment map" in body
    assert 'id="workflow-map-frame"' in body
    assert "Terrain Profile Graph" in body
    assert 'id="terrain-profile-frame"' in body
    assert 'class="map-iframe profile-iframe"' in body
    assert 'title="Terrain profile graph"' in body
    assert 'id="wind-region-frame"' not in body
    assert "Directional calculated values with optional engineering overrides." not in body
    assert 'id="wind-direction-md"' not in body
    assert 'id="terrain-category-mzcat"' not in body
    assert 'id="shielding-ms"' not in body
    assert 'id="topographic-mt"' not in body
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
    assert "nudgeDesignBuilding" not in script.text
    assert "offset_east_m" in script.text
    assert "startOrientationDrag" in script.text
    assert "applyOrientationFromLatLng" in script.text
    assert "normalizeOrientation" in script.text
    assert "nearestOrientationOption" not in script.text
    assert "startResizeDrag" in script.text
    assert "dimensions_modified" in script.text
    assert "renderFaceLabels" in script.text
    assert "openwind-design-building-change" in script.text
    assert "adjustedLocationFromDesignState" in script.text
    assert script.text.index(
        "const requestPayload = workflowPayload(options.workflowOverrides ?? workflowOverrides)"
    ) < script.text.index("resetWorkflowSections();")
    for step in (1, 2, 3, 4, 5, 10):
        assert f'data-step="{step}"' in body
    assert "/api/plots/profile" in script.text
    assert "terrainProfileRequestPayload" in script.text
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
    assert "Governing Md" not in script.text
    assert "editableAssessmentValueCell" in script.text
    assert "renderVsitbTable" in script.text
    assert "data-raw-value" in script.text
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
    wind_region_properties = schemas["PublicWindRegionAssessment"]["properties"]

    assert request_properties["assessment_status"]["enum"] == ["draft", "reviewed"]
    assert "reviewed_by" in request_properties
    assert "average_roof_height_m" in request_properties
    assert "average_height_m" not in request_properties
    assert request_properties["building_dimensions"]["deprecated"] is True
    assert "report metadata only" in request_properties["importance_level"]["description"]
    assert "report metadata only" in request_properties["design_life_years"]["description"]
    assert "assessment_status" not in result_properties
    assert "reviewed_by" not in result_properties
    assert "engineer_notes" not in result_properties
    assert "overrides_applied" not in result_properties
    assert "dataset_path" not in wind_region_properties
    assert "region_polygon" not in wind_region_properties


def test_browser_uses_draft_api_contract_without_review_or_nudge_controls(
    monkeypatch,
) -> None:
    test_client = client(monkeypatch)
    page = test_client.get("/")
    script = test_client.get("/static/wind_workflow.js")
    stylesheet = test_client.get("/static/styles.css")

    assert page.status_code == 200
    assert script.status_code == 200
    assert stylesheet.status_code == 200
    assert 'id="assessment_status"' not in page.text
    assert 'name="assessment_status"' not in page.text
    assert "Review and issue status" not in page.text
    assert 'id="reviewed_by"' not in page.text
    assert 'name="reviewed_by"' not in page.text
    assert 'id="engineer_notes"' not in page.text
    assert 'name="engineer_notes"' not in page.text
    assert "data-map-nudge" not in page.text
    assert "Move building 1 m" not in page.text
    assert 'id="average_roof_height_m"' in page.text
    assert 'name="average_roof_height_m"' in page.text
    assert "Average roof height (m)" in page.text
    assert "syncReviewControls" not in script.text
    assert 'assessment_status: "draft"' in script.text
    assert "payload.reviewed_by" not in script.text
    assert "payload.engineer_notes" not in script.text
    assert "mapNudgeButtons" not in script.text
    assert "workflowForm.reportValidity()" in script.text
    assert ".workflow-review" not in stylesheet.text
    assert ".map-nudge-control" not in stylesheet.text
    assert "20260729-simplified-controls-1" in page.text


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
    assert "Assessment status" not in response.text
    assert "Draft preliminary" not in response.text
    assert "Site wind inputs and calculated cardinal Vsit,b" in response.text
    assert "outside its scope" in response.text
    assert "certif" not in response.text.lower()
    assert "compliance" not in response.text.lower()
    assert "Executive Summary" not in response.text
    assert "Variable Summary" not in response.text
    assert "Wind Region Assessment" not in response.text
    assert "Regional Wind Speed Assessment" not in response.text
    assert "Direction Multiplier Assessment" not in response.text
    assert "Maps" not in response.text
    assert "Profiles" not in response.text
    assert "Configured test wind-region GIS fixture" in response.text
    assert "Table 3.1(A)" in response.text
    assert "Table 3.3" in response.text
    assert "Table 3.2(A)" in response.text
    assert "Clause 4.2.3 mixed-terrain weighted averaging is not automated" in response.text
    assert "Clause 4.4.2 most-adverse topographic cross-section" in response.text
    assert "verified_against_standard" not in response.text
    assert "local path" not in response.text
    assert "Overrides Applied" not in response.text
    assert "Project engineer selected a directional override after review." in response.text
    assert "Assessment reviewed for test issue." in response.text
    assert "enclosed industrial building" not in response.text
    assert "30 m x 20 m x 10 m" not in response.text
    assert "Vsit,b = VR x Mc x Md x Mz,cat x Ms x Mt" in response.text
    assert response.text.count("Final design pressures") == 1


def test_workflow_report_shows_effective_overrides_and_reference_heights(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "average_roof_height_m": 8.0,
        "base_rl_m": 125.5,
        "structure_class": "monopole",
        "workflow_overrides": [
            {
                "variable": "VR",
                "override_value": 50.0,
                "reason": "Reviewed regional wind speed.",
            },
            {
                "variable": "Vsitb",
                "direction": "N",
                "override_value": 99.0,
                "reason": "Reviewed directional site wind speed.",
            },
        ],
    }

    response = test_client.post("/api/wind-workflow/report/html", json=payload)

    assert response.status_code == 200
    assert "VR,ult (effective)" in response.text
    assert "50.0 m/s" in response.text
    assert "(reviewed override)" in response.text
    assert "Calculated Vsit,b" in response.text
    assert "Final Vsit,b" in response.text
    assert "99.000 m/s" in response.text
    assert "(override)" in response.text
    assert "average roof/reference height h,z 8.00 m" in response.text
    assert "reviewed base RL 125.50 m" in response.text
    assert "effective for monopole" in response.text


def test_cyclonic_coastal_vr_limit_is_prioritized_in_compact_reports(monkeypatch) -> None:
    test_client = client(monkeypatch)
    monkeypatch.setattr(
        workflow_module,
        "assess_wind_region",
        lambda _site: WindRegionAssessment(
            latitude=-20.0,
            longitude=146.0,
            wind_region="C",
            source="test reviewed region",
            confidence="low",
            near_boundary=True,
            warnings=[
                "Boundary distance requires project review.",
                "GIS interpretation requires independent confirmation.",
            ],
        ),
    )

    workflow_response = test_client.post("/api/wind-workflow", json=workflow_payload())
    report_response = test_client.post("/api/wind-workflow/report/html", json=workflow_payload())

    assert workflow_response.status_code == 200
    assert report_response.status_code == 200
    result = WindWorkflowResult.model_validate(workflow_response.json())
    compact_warnings = concise_workflow_warnings(result, limit=4)
    assert any("smoothed coastline" in warning for warning in compact_warnings)
    assert (
        "Region C distance-based coastal VR interpolation is not automated" in report_response.text
    )


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
        assert "Final issue is not supported" in response.text


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


def test_reviewed_preliminary_api_preserves_metadata_without_report_status(
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
    assert "Assessment status" not in report.text
    assert "Reviewed preliminary - Engineer A" not in report.text
    assert "certif" not in report.text.lower()
    assert "compliance" not in report.text.lower()


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
        assert "Final issue is not supported" in tampered_response.text
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
    mc_tampered = json.loads(json.dumps(authentic))
    mc_variable = next(item for item in mc_tampered["variables"] if item["variable"] == "Mc")
    mc_variable["final_value"] = 1.05
    md_source_tampered = json.loads(json.dumps(authentic))
    md_source_tampered["direction_multiplier_assessment"]["directions"][0]["md"] = 1.0
    unsigned = json.loads(json.dumps(authentic))
    unsigned.pop("integrity_token")

    for path in (
        "/api/wind-workflow/result/report/html",
        "/api/wind-workflow/result/report/pdf",
    ):
        tampered_response = test_client.post(path, json=tampered)
        mc_tampered_response = test_client.post(path, json=mc_tampered)
        md_source_tampered_response = test_client.post(path, json=md_source_tampered)
        unsigned_response = test_client.post(path, json=unsigned)

        assert tampered_response.status_code == 422
        assert "inconsistent" in tampered_response.text.lower()
        assert mc_tampered_response.status_code == 422
        assert "inconsistent" in mc_tampered_response.text.lower()
        assert md_source_tampered_response.status_code == 422
        assert "direction multiplier assessment" in md_source_tampered_response.text.lower()
        assert "inconsistent" in md_source_tampered_response.text.lower()
        assert unsigned_response.status_code == 422
        assert "missing" in unsigned_response.text.lower()


def test_completed_result_routes_reject_retired_generic_region_and_mandatory_ms_state(
    monkeypatch,
) -> None:
    test_client = client(monkeypatch)
    workflow = test_client.post("/api/wind-workflow", json=workflow_payload())
    assert workflow.status_code == 200
    authentic = workflow.json()

    generic_region = json.loads(json.dumps(authentic))
    generic_region["wind_region_assessment"]["wind_region"] = "A"
    high_reference_height = json.loads(json.dumps(authentic))
    high_reference_height["input"]["building_height_m"] = 30.0
    high_reference_height["input"]["average_roof_height_m"] = 30.0
    for item in high_reference_height["variables"]:
        if item["variable"] == "Ms":
            item["recommended_value"] = 0.8
            item["calculated_value"] = 0.8
            item["final_value"] = 0.8
    for row in high_reference_height["directional_vsitb"]:
        row["ms"] = 0.8
    a0_mzcat = json.loads(json.dumps(authentic))
    a0_mzcat["wind_region_assessment"]["wind_region"] = "A0"
    a0_mzcat["regional_wind_speed_assessment"]["wind_region"] = "A0"
    a0_mzcat["direction_multiplier_assessment"]["wind_region"] = "A0"

    for path in (
        "/api/wind-workflow/result/report/html",
        "/api/wind-workflow/result/report/pdf",
    ):
        generic_response = test_client.post(path, json=generic_region)
        ms_response = test_client.post(path, json=high_reference_height)
        a0_response = test_client.post(path, json=a0_mzcat)

        assert generic_response.status_code == 422
        assert "ambiguous wind region A" in generic_response.text
        assert ms_response.status_code == 422
        assert "Clause 4.3.1 mandatory Ms assessment is inconsistent" in ms_response.text
        assert a0_response.status_code == 422
        assert "Region A0 mandatory Mz,cat assessment is inconsistent" in a0_response.text


def test_completed_result_model_graph_is_strict_and_has_no_excluded_payload_fields() -> None:
    """Keep every accepted completed-result field inside the canonical signed projection."""

    models = {WindWorkflowResult}
    pending = [WindWorkflowResult]
    while pending:
        model = pending.pop()
        for field in model.model_fields.values():
            nested = list(_pydantic_model_types(field.annotation))
            for nested_model in nested:
                if nested_model not in models:
                    models.add(nested_model)
                    pending.append(nested_model)

    for model in models:
        assert model.model_config.get("extra") == "forbid", model.__name__
        assert model.model_config.get("strict") is True, model.__name__
        assert not {name for name, field in model.model_fields.items() if field.exclude is True}, (
            model.__name__
        )


def test_completed_result_report_routes_reject_unknown_nested_fields(monkeypatch) -> None:
    test_client = client(monkeypatch)
    workflow = test_client.post(
        "/api/wind-workflow",
        json=workflow_payload() | {"workflow_overrides": sample_overrides()},
    )
    assert workflow.status_code == 200
    authentic = workflow.json()
    nested_paths = (
        ("site",),
        ("wind_region_assessment",),
        ("regional_wind_speed_assessment",),
        ("direction_multiplier_assessment",),
        ("direction_multiplier_assessment", "directions", 0),
        ("variables", 0),
        ("directional_vsitb", 0),
        ("input", "workflow_overrides", 0),
    )

    for route in (
        "/api/wind-workflow/result/report/html",
        "/api/wind-workflow/result/report/pdf",
    ):
        for path in nested_paths:
            tampered = json.loads(json.dumps(authentic))
            target = _nested_value(tampered, path)
            target["unexpected_nested_field"] = "must not be discarded"

            response = test_client.post(route, json=tampered)

            assert response.status_code == 422
            assert "Extra inputs are not permitted" in response.text


def test_completed_result_report_routes_reject_null_core_assessments(monkeypatch) -> None:
    test_client = client(monkeypatch)
    workflow = test_client.post("/api/wind-workflow", json=workflow_payload())
    assert workflow.status_code == 200
    authentic = workflow.json()

    for field in (
        "wind_region_assessment",
        "regional_wind_speed_assessment",
        "direction_multiplier_assessment",
    ):
        tampered = json.loads(json.dumps(authentic))
        tampered[field] = None

        for route in (
            "/api/wind-workflow/result/report/html",
            "/api/wind-workflow/result/report/pdf",
        ):
            response = test_client.post(route, json=tampered)
            assert response.status_code == 422
            assert field in response.text


def test_completed_result_report_routes_reject_internal_region_polygon_tampering(
    monkeypatch,
) -> None:
    test_client = client(monkeypatch)
    workflow = test_client.post("/api/wind-workflow", json=workflow_payload())
    assert workflow.status_code == 200
    authentic = workflow.json()
    authentic_token = authentic["integrity_token"]
    assert "region_polygon" not in authentic["wind_region_assessment"]

    for route in (
        "/api/wind-workflow/result/report/html",
        "/api/wind-workflow/result/report/pdf",
    ):
        tampered = json.loads(json.dumps(authentic))
        tampered["wind_region_assessment"]["region_polygon"] = {
            "type": "Point",
            "coordinates": [0, 0],
        }
        assert tampered["integrity_token"] == authentic_token

        response = test_client.post(route, json=tampered)

        assert response.status_code == 422
        assert "region_polygon" in response.text
        assert "Extra inputs are not permitted" in response.text


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("site", "latitude"), "-33.86"),
        (("variables", 0, "final_value"), "45.0"),
        (("variables", 0, "is_overridden"), 0),
        (("directional_vsitb", 0, "is_governing"), 1),
    ],
)
def test_completed_result_report_routes_reject_coercible_representations(
    monkeypatch,
    path,
    replacement,
) -> None:
    test_client = client(monkeypatch)
    workflow = test_client.post("/api/wind-workflow", json=workflow_payload())
    assert workflow.status_code == 200
    tampered = workflow.json()
    parent = _nested_value(tampered, path[:-1])
    parent[path[-1]] = replacement

    for route in (
        "/api/wind-workflow/result/report/html",
        "/api/wind-workflow/result/report/pdf",
    ):
        response = test_client.post(route, json=tampered)

        assert response.status_code == 422
        assert "Input should be" in response.text


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


def test_wind_workflow_report_scope_and_pdf_footer_omit_claim_boilerplate() -> None:
    visible_copy = f"{WIND_WORKFLOW_REPORT_SUBTITLE} {WIND_WORKFLOW_REPORT_SCOPE}".lower()
    assert "certif" not in visible_copy
    assert "compliance" not in visible_copy
    assert "final design pressures" in visible_copy
    assert "outside its scope" in visible_copy

    rendered_strings = []

    class RecordingCanvas:
        def __getattr__(self, _name):
            def record(*args, **_kwargs):
                rendered_strings.extend(value for value in args if isinstance(value, str))

            return record

    _draw_wind_pdf_page(RecordingCanvas(), SimpleNamespace(page=2))
    footer_copy = " ".join(rendered_strings)
    assert "OpenWind-AU | Site Wind Assessment" in footer_copy
    assert "Page 2" in footer_copy
    assert "PRELIMINARY - NOT FOR CERTIFICATION" not in footer_copy
    assert "certif" not in footer_copy.lower()
    assert "compliance" not in footer_copy.lower()


def test_wind_workflow_pdf_embeds_validated_png_and_jpeg_map_screenshots(
    monkeypatch,
) -> None:
    test_client = client(monkeypatch)
    workflow_response = test_client.post("/api/wind-workflow", json=workflow_payload())

    assert workflow_response.status_code == 200
    result = WindWorkflowResult.model_validate(workflow_response.json())
    png = map_screenshot_bytes()
    jpeg = map_screenshot_bytes("JPEG", (900, 600))
    png_data_uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")

    validated_png = _validate_wind_pdf_map_screenshot(png)
    validated_uri = _validate_wind_pdf_map_screenshot(png_data_uri)
    validated_jpeg = _validate_wind_pdf_map_screenshot(jpeg)

    assert validated_png is not None
    assert validated_png.media_type == "image/png"
    assert (validated_png.width_px, validated_png.height_px) == (1200, 675)
    assert validated_uri == validated_png
    assert validated_jpeg is not None
    assert validated_jpeg.media_type == "image/jpeg"
    assert (validated_jpeg.width_px, validated_jpeg.height_px) == (900, 600)

    def reject_vector_fallback(*_args, **_kwargs):
        raise AssertionError("issued PDF called the retired vector schematic")

    monkeypatch.setattr(reports_module, "_wind_pdf_site_map", reject_vector_fallback)
    without_map = render_wind_workflow_pdf_report(result)
    with_png = render_wind_workflow_pdf_report(result, map_screenshot=png)
    with_png_uri = render_wind_workflow_pdf_report(result, map_screenshot=png_data_uri)
    with_jpeg = render_wind_workflow_pdf_report(result, map_screenshot=jpeg)

    assert b"/Subtype /Image" not in without_map
    for rendered in (with_png, with_png_uri, with_jpeg):
        assert rendered.startswith(b"%PDF-")
        assert b"/Subtype /Image" in rendered
        assert len(rendered) > len(without_map)


@pytest.mark.parametrize(
    "invalid_screenshot",
    [
        b"",
        b"not an image",
        b"\xff\xd8\xff\xd9",
        "https://example.test/map.png",
        "data:image/gif;base64,R0lGODlhAQABAIAAAAUEBA==",
        "data:image/png;base64,not-valid-***",
    ],
)
def test_wind_workflow_pdf_rejects_unsupported_or_malformed_map_screenshots(
    invalid_screenshot,
) -> None:
    with pytest.raises(ValueError, match="Map screenshot"):
        _validate_wind_pdf_map_screenshot(invalid_screenshot)


def test_wind_workflow_pdf_rejects_mime_mismatch_trailing_bytes_and_unsafe_dimensions() -> None:
    png = map_screenshot_bytes()
    mismatched_uri = "data:image/jpeg;base64," + base64.b64encode(png).decode("ascii")

    with pytest.raises(ValueError, match="declared MIME type"):
        _validate_wind_pdf_map_screenshot(mismatched_uri)
    with pytest.raises(ValueError, match="complete PNG"):
        _validate_wind_pdf_map_screenshot(png + b"trailing data")
    with pytest.raises(ValueError, match="at least 64 px"):
        _validate_wind_pdf_map_screenshot(map_screenshot_bytes(size=(63, 100)))
    with pytest.raises(ValueError, match="1.024 megapixel"):
        _validate_wind_pdf_map_screenshot_dimensions(8193, 100)
    with pytest.raises(ValueError, match="aspect ratio"):
        _validate_wind_pdf_map_screenshot_dimensions(1000, 100)


def test_wind_workflow_pdf_keeps_effective_override_summary_on_one_page(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "project_number": "OW-2026-PDF-QA",
        "average_roof_height_m": 8.0,
        "base_rl_m": 125.5,
        "structure_class": "monopole",
        "workflow_overrides": [
            {
                "variable": "VR",
                "override_value": 50.0,
                "reason": "Reviewed regional wind speed.",
            },
            {
                "variable": "Vsitb",
                "direction": "N",
                "override_value": 99.0,
                "reason": "Reviewed directional site wind speed.",
            },
        ],
    }

    response = test_client.post("/api/wind-workflow/report/pdf", json=payload)

    assert response.status_code == 200
    page_objects = re.findall(rb"/Type\s*/Page(?!s)\b", response.content)
    assert len(page_objects) == 1


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


def test_wind_workflow_pdf_failure_hides_internal_details_and_logs_incident(
    monkeypatch,
    caplog,
) -> None:
    test_client = client(monkeypatch)
    workflow_response = test_client.post("/api/wind-workflow", json=workflow_payload())
    assert workflow_response.status_code == 200

    def fail_pdf(_result):
        raise RuntimeError(r"C:\private\project\report-assets failure")

    monkeypatch.setattr(api_module, "render_wind_workflow_pdf_report", fail_pdf)
    with caplog.at_level(logging.ERROR, logger=api_module.LOGGER.name):
        response = test_client.post(
            "/api/wind-workflow/result/report/pdf",
            json=workflow_response.json(),
        )

    assert response.status_code == 500
    assert response.json()["detail"] == ("Failed to generate PDF report; inspect the server logs.")
    assert "private" not in response.text
    assert "report-assets failure" in caplog.text


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


def test_completed_workflow_pdf_accepts_browser_map_wrapper(monkeypatch) -> None:
    test_client = client(monkeypatch)
    workflow_response = test_client.post("/api/wind-workflow", json=workflow_payload())
    assert workflow_response.status_code == 200
    result = workflow_response.json()
    map_data_uri = "data:image/jpeg;base64," + base64.b64encode(
        map_screenshot_bytes("JPEG", (900, 600))
    ).decode("ascii")
    captured = {}

    def render_with_map(report_result, *, map_screenshot=None):
        captured["integrity_token"] = report_result.integrity_token
        captured["map_screenshot"] = map_screenshot
        return b"%PDF-" + b"browser-map" * 200

    monkeypatch.setattr(api_module, "render_wind_workflow_pdf_report", render_with_map)
    response = test_client.post(
        "/api/wind-workflow/result/report/pdf",
        json={"result": result, "map_screenshot": map_data_uri},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert captured == {
        "integrity_token": result["integrity_token"],
        "map_screenshot": map_data_uri,
    }


def test_completed_workflow_pdf_map_wrapper_rejects_invalid_map_and_tampered_result(
    monkeypatch,
) -> None:
    test_client = client(monkeypatch)
    workflow_response = test_client.post("/api/wind-workflow", json=workflow_payload())
    assert workflow_response.status_code == 200
    result = workflow_response.json()

    invalid_map = test_client.post(
        "/api/wind-workflow/result/report/pdf",
        json={"result": result, "map_screenshot": "data:image/png;base64,not-valid-***"},
    )
    tampered = json.loads(json.dumps(result))
    tampered["directional_vsitb"][0]["final_vsitb"] += 1
    tampered_result = test_client.post(
        "/api/wind-workflow/result/report/pdf",
        json={
            "result": tampered,
            "map_screenshot": (
                "data:image/png;base64," + base64.b64encode(map_screenshot_bytes()).decode("ascii")
            ),
        },
    )

    assert invalid_map.status_code == 422
    assert "Map screenshot" in invalid_map.text
    assert tampered_result.status_code == 422
    assert "inconsistent" in tampered_result.text.lower()


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
    assert "crossOrigin" in body
    assert '"anonymous"' in body
    assert "capture-screenshot" in body
    assert "openwind-map-screenshot" in body
    assert "drawVisibleTiles" in body
    assert "drawSvgOverlays" in body
    assert "window.openWindMapCapture" in body
    assert "nudgeDesignBuilding" in body
    assert "offset_east_m" in body
    assert "orientation_options" in body
    assert '"orientation_options": [0, 45, 90, 135, 180, 225, 270, 315]' in body
    assert "setOrientation" in body
    assert "setDimensions" in body
    assert "startOrientationDrag" in body
    assert "applyOrientationFromLatLng" in body
    assert "normalizeOrientation" in body
    assert "nearestOrientationOption" not in body
    assert '{ label: "Front", theta: 0 }' in body
    assert '{ label: "Right", theta: 90 }' in body
    assert '{ label: "Back", theta: 180 }' in body
    assert '{ label: "Left", theta: 270 }' in body
    assert "startResizeDrag" in body
    assert "applyResizeFromLatLng" in body
    assert "renderResizeHandles" in body
    assert "dimensions_modified" in body
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


def test_wind_workflow_map_capture_rebases_leaflet_svg_without_losing_viewbox(
    monkeypatch,
) -> None:
    test_client = client(monkeypatch)

    response = test_client.post("/api/wind-workflow/map", json=workflow_payload())

    assert response.status_code == 200
    body = response.text
    assert "function cloneSvgOverlayForCapture(svg, width, height)" in body
    assert 'const viewBox = svg.getAttribute("viewBox");' in body
    assert 'if (viewBox) clone.setAttribute("viewBox", viewBox);' in body
    assert 'clone.setAttribute("width", String(width));' in body
    assert 'clone.setAttribute("height", String(height));' in body
    assert 'clone.style.position = "static";' in body
    assert 'clone.style.left = "0px";' in body
    assert 'clone.style.top = "0px";' in body
    assert 'clone.style.transform = "none";' in body
    assert 'clone.style.webkitTransform = "none";' in body
    assert 'clone.style.transformOrigin = "0 0";' in body
    assert "const clone = cloneSvgOverlayForCapture(svg, rect.width, rect.height);" in body


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
    assert "Site resolved; calculating wind region, VR, Mc, and Md" in labels
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


def test_wind_workflow_stream_uses_effective_clause_3_3_md_values(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "wind_direction_multiplier_case": "circular_or_polygonal_chimney_tank_or_pole"
    }

    with test_client.stream("POST", "/api/wind-workflow/stream", json=payload) as response:
        assert response.status_code == 200
        events = [json.loads(line) for line in response.iter_lines() if line]

    wind_inputs = next(event for event in events if event["stage"] == "wind_inputs")["data"]
    assessment = wind_inputs["direction_multiplier_assessment"]
    workflow = next(event for event in events if event["stage"] == "workflow")["data"]["workflow"]
    assert "Clause 3.3" in assessment["source_table"]
    assert {row["md"] for row in assessment["directions"]} == {1.0}
    assert workflow["direction_multiplier_assessment"] == assessment


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
    mc = next(item for item in body["variables"] if item["variable"] == "Mc")
    md_north = next(
        item for item in body["variables"] if item["variable"] == "Md" and item["direction"] == "N"
    )
    mzcat_north = next(
        item
        for item in body["variables"]
        if item["variable"] == "Mzcat" and item["direction"] == "N"
    )
    assert vr["detail_label"] == "Show source"
    assert vr["source_reference"] == VR_EQUATION_REFERENCE
    assert vr["final_value"] == 45.0
    assert vr["calculated_value"] == 45.0
    assert mc["direction"] is None
    assert mc["final_value"] == 1.0
    assert "Table 3.3" in mc["source_reference"]
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
    assert any("Clause 4.2.3 mixed-terrain" in warning for warning in body["warnings"])
    assert any("Clause 4.4.2 most-adverse" in warning for warning in body["warnings"])


def test_orientation_drives_four_clause_2_3_design_wind_speeds(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {"structure_orientation_deg": 337.5}

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 200
    body = response.json()
    direction_speeds = {row["direction"]: row["final_vsitb"] for row in body["directional_vsitb"]}
    rows = body["design_wind_speeds"]
    assert [row["face"] for row in rows] == ["Front", "Right", "Back", "Left"]
    assert [row["theta_deg"] for row in rows] == [0.0, 90.0, 180.0, 270.0]
    assert [row["beta_deg"] for row in rows] == [337.5, 67.5, 157.5, 247.5]
    for row in rows:
        expected = design_wind_speed(
            theta_degrees=row["beta_deg"],
            direction_speeds=direction_speeds,
        )
        assert row["sector_start_beta_deg"] == pytest.approx(expected.sector_start_degrees)
        assert row["sector_end_beta_deg"] == pytest.approx(expected.sector_end_degrees)
        assert row["raw_vdes_theta_mps"] == pytest.approx(expected.raw_maximum_m_s)
        assert row["vdes_theta_mps"] == pytest.approx(expected.design_wind_speed_m_s)
        assert row["minimum_uls_applied"] is expected.minimum_applied
    governing_value = max(row["vdes_theta_mps"] for row in rows)
    assert body["governing_vdes_mps"] == pytest.approx(governing_value)
    assert body["governing_vdes_faces"] == [row["face"] for row in rows if row["is_governing"]]
    assert "Clause 2.3" in body["design_wind_speed_basis"]

    report = test_client.post("/api/wind-workflow/result/report/html", json=body)
    assert report.status_code == 200
    assert "Building-orthogonal design wind speeds" in report.text
    assert "337.5 deg" in report.text
    tampered = json.loads(json.dumps(body))
    tampered["design_wind_speeds"][0]["vdes_theta_mps"] += 1
    rejected = test_client.post("/api/wind-workflow/result/report/html", json=tampered)
    assert rejected.status_code == 422
    assert "Clause 2.3" in rejected.text


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
        {
            "workflow_overrides": [
                {
                    "variable": "Mc",
                    "override_value": 1.05,
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


@pytest.mark.parametrize("override_kind", ["workflow", "class"])
def test_high_reference_height_rejects_ms_overrides_in_every_direction(
    monkeypatch,
    override_kind: str,
) -> None:
    test_client = client(monkeypatch)
    directions = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    payload = workflow_payload() | {
        "building_height_m": 30.0,
        "average_roof_height_m": 30.0,
    }
    if override_kind == "workflow":
        payload["workflow_overrides"] = [
            {
                "variable": "Ms",
                "direction": direction,
                "override_value": 0.7,
                "reason": "Attempted reviewed shielding override above the height limit.",
            }
            for direction in directions
        ]
    else:
        payload["class_multiplier_overrides"] = [
            {
                "direction": direction,
                "shielding_class": "FS",
                "ms": 0.7,
                "reason": "Attempted reviewed shielding class above the height limit.",
            }
            for direction in directions
        ]

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 400
    assert "Clause 4.3.1 requires Ms = 1.0" in response.text
    assert "numeric Ms overrides are not permitted" in response.text


def test_ms_override_remains_available_at_exact_25_m_reference_height(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "building_height_m": 25.0,
        "average_roof_height_m": 25.0,
        "workflow_overrides": [
            {
                "variable": "Ms",
                "direction": "N",
                "override_value": 0.9,
                "reason": "Reviewed shielding override at the Clause 4.3.1 height boundary.",
            }
        ],
    }

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 200
    north = next(
        item
        for item in response.json()["variables"]
        if item["variable"] == "Ms" and item["direction"] == "N"
    )
    assert north["final_value"] == 0.9
    assert north["is_overridden"] is True


@pytest.mark.parametrize("override_kind", ["workflow", "class"])
def test_region_a0_rejects_numeric_mzcat_overrides_in_every_direction(
    monkeypatch,
    override_kind: str,
) -> None:
    test_client = client(monkeypatch)
    monkeypatch.setattr(
        workflow_module,
        "assess_wind_region",
        lambda _site: WindRegionAssessment(
            latitude=-33.86,
            longitude=151.21,
            wind_region="A0",
            source="test reviewed region",
            confidence="high",
        ),
    )
    directions = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    payload = workflow_payload()
    if override_kind == "workflow":
        payload["workflow_overrides"] = [
            {
                "variable": "Mzcat",
                "direction": direction,
                "override_value": 0.5,
                "reason": "Attempted numeric override of the Region A0 rule.",
            }
            for direction in directions
        ]
    else:
        payload["class_multiplier_overrides"] = [
            {
                "direction": direction,
                "terrain_category": "TC4",
                "mzcat": 0.5,
                "reason": "Attempted class override of the Region A0 rule.",
            }
            for direction in directions
        ]

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 400
    assert "Region A0 Table 4.1 Mz,cat is terrain-independent and mandatory" in response.text
    assert "numeric Mz,cat overrides are not permitted" in response.text


def test_region_a0_allows_terrain_class_provenance_without_numeric_override(monkeypatch) -> None:
    test_client = client(monkeypatch)
    monkeypatch.setattr(
        workflow_module,
        "assess_wind_region",
        lambda _site: WindRegionAssessment(
            latitude=-33.86,
            longitude=151.21,
            wind_region="A0",
            source="test reviewed region",
            confidence="high",
        ),
    )
    payload = workflow_payload() | {
        "class_multiplier_overrides": [
            {
                "direction": "N",
                "terrain_category": "TC4",
                "reason": "Terrain class retained for evidence only in Region A0.",
            }
        ]
    }

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 200
    mzcat_values = {
        item["final_value"] for item in response.json()["variables"] if item["variable"] == "Mzcat"
    }
    assert mzcat_values == {1.0}
    north = next(
        item
        for item in response.json()["variables"]
        if item["variable"] == "Mzcat" and item["direction"] == "N"
    )
    assert north["final_label"] == "Mandatory Region A0 Mz,cat"
    assert "test reviewed region" not in north["source_reference"]
    assert any("evidence only" in item for item in north["detail_items"])
    assert any("remains the mandatory" in warning for warning in north["warnings"])


def test_region_a0_default_label_discloses_mandatory_terrain_independent_value(
    monkeypatch,
) -> None:
    test_client = client(monkeypatch)
    monkeypatch.setattr(
        workflow_module,
        "assess_wind_region",
        lambda _site: WindRegionAssessment(
            latitude=-33.86,
            longitude=151.21,
            wind_region="A0",
            source="test reviewed region",
            confidence="high",
        ),
    )

    response = test_client.post("/api/wind-workflow", json=workflow_payload())

    assert response.status_code == 200
    mzcat = [item for item in response.json()["variables"] if item["variable"] == "Mzcat"]
    assert {item["final_value"] for item in mzcat} == {1.0}
    assert all(
        item["recommended_label"]
        == "Mandatory Region A0 Mz,cat 1.000; terrain category does not change this value"
        for item in mzcat
    )


def test_monopole_md_provenance_records_requested_and_effective_cases(monkeypatch) -> None:
    test_client = client(monkeypatch)

    response = test_client.post(
        "/api/wind-workflow",
        json=workflow_payload()
        | {
            "structure_class": "monopole",
            "wind_direction_multiplier_case": "main_structure",
        },
    )

    assert response.status_code == 200
    assessment = response.json()["direction_multiplier_assessment"]
    assert "Requested design case: main_structure" in assessment["lookup_values"]
    assert "Selected structure class: monopole" in assessment["lookup_values"]
    assert any(
        item.startswith("Effective Md rule: Clause 3.3 requires Md = 1.0")
        for item in assessment["lookup_values"]
    )


def test_numeric_class_override_preserves_standard_calculated_value(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "class_multiplier_overrides": [
            {
                "direction": "N",
                "terrain_category": "TC3",
                "mzcat": 0.9,
                "reason": "Reviewed numeric Mz,cat supplied for comparison.",
            }
        ]
    }

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 200
    north = next(
        item
        for item in response.json()["variables"]
        if item["variable"] == "Mzcat" and item["direction"] == "N"
    )
    assert north["final_value"] == 0.9
    assert north["calculated_value"] != north["final_value"]


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


def test_html_report_discloses_numeric_class_multiplier_overrides(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload() | {
        "class_multiplier_overrides": [
            {
                "direction": "N",
                "terrain_category": "TC3",
                "shielding_class": "FS",
                "topographic_class": "T1",
                "mzcat": 0.9,
                "ms": 0.85,
                "mt": 1.08,
                "reason": "Reviewed numeric multipliers supplied by the project engineer.",
            }
        ]
    }

    response = test_client.post("/api/wind-workflow/report/html", json=payload)

    assert response.status_code == 200
    assert "TC3; FS; T1; Mz,cat 0.900; Ms 0.850; Mt 1.080" in response.text
    assert "Reviewed numeric multipliers supplied by the project engineer." in response.text


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
    payload = workflow_payload()
    payload.pop("building_dimensions")
    payload |= {
        "project_number": "OW-2026-018",
        "structure_class": "building",
        "structure_orientation_deg": 0,
        "roof_shape": "gable",
        "building_width_m": 4,
        "building_length_m": 5,
        "roof_pitch_deg": 15,
        "average_roof_height_m": 3,
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
    assert body["input"]["average_roof_height_m"] == 3
    assert "average_height_m" not in body["input"]
    assert body["input"]["base_rl_m"] == 0
    assert report.status_code == 200
    assert "OW-2026-018" in report.text
    assert "overall height 10.00 m" in report.text
    assert "average roof/reference height h,z 3.00 m" in report.text
    assert "reviewed base RL 0.00 m" in report.text
    assert "breadth 4.00 m x front-to-back depth 5.00 m" in report.text
    assert "front beta 0.0 deg clockwise from true North" in report.text
    assert "gable roof at 15.0 deg" in report.text
    assert "; building" in report.text


def test_vsitb_calculated_for_all_directions_immediately(monkeypatch) -> None:
    test_client = client(monkeypatch)
    payload = workflow_payload()

    response = test_client.post("/api/wind-workflow", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["governing_direction"] is not None
    assert body["governing_vsitb"] is not None
    assert "dataset_path" not in body["wind_region_assessment"]
    assert "region_polygon" not in body["wind_region_assessment"]
    north = next(row for row in body["directional_vsitb"] if row["direction"] == "N")
    assert north["status"] == "calculated"
    assert north["final_vsitb"] is not None
    assert all(row["final_vsitb"] is not None for row in body["directional_vsitb"])
    assert {item["variable"] for item in body["variables"] if item["direction"] in {None, "N"}} >= {
        "VR",
        "Mc",
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
        expected = row["vr"] * row["mc"] * row["md"] * row["mzcat"] * row["ms"] * row["mt"]
        assert row["recommended_vsitb"] == pytest.approx(expected)
        assert row["final_vsitb"] == pytest.approx(expected)


def test_b2_workflow_applies_table_3_3_mc_and_clause_3_3_cladding_md(monkeypatch) -> None:
    test_client = client(monkeypatch)
    b2_site = workflow_payload() | {"latitude": -20.30, "longitude": 148.70}

    main_response = test_client.post("/api/wind-workflow", json=b2_site)
    cladding_response = test_client.post(
        "/api/wind-workflow",
        json=b2_site | {"wind_direction_multiplier_case": "cladding_or_immediate_support"},
    )

    assert main_response.status_code == 200
    assert cladding_response.status_code == 200
    main = main_response.json()
    cladding = cladding_response.json()
    mc = next(item for item in main["variables"] if item["variable"] == "Mc")
    main_north = next(row for row in main["directional_vsitb"] if row["direction"] == "N")
    cladding_north = next(row for row in cladding["directional_vsitb"] if row["direction"] == "N")

    assert mc["direction"] is None
    assert mc["final_value"] == 1.05
    assert main_north["mc"] == 1.05
    assert main_north["md"] == 0.9
    assert cladding_north["md"] == 1.0
    assert cladding_north["recommended_vsitb"] == pytest.approx(
        main_north["recommended_vsitb"] / 0.9
    )
    cladding_md = [item for item in cladding["variables"] if item["variable"] == "Md"]
    assert all(item["final_value"] == 1.0 for item in cladding_md)
    assert all("Clause 3.3" in item["source_reference"] for item in cladding_md)
    effective_assessment = cladding["direction_multiplier_assessment"]
    assert effective_assessment["source_table"] == "AS/NZS 1170.2:2021 Clause 3.3"
    assert effective_assessment["highest_md"] == 1.0
    assert effective_assessment["governing_directions"] == [
        "N",
        "NE",
        "E",
        "SE",
        "S",
        "SW",
        "W",
        "NW",
    ]
    assert all(row["md"] == 1.0 for row in effective_assessment["directions"])


def test_a2_clause_3_3_design_cases_are_applied_only_when_required(monkeypatch) -> None:
    test_client = client(monkeypatch)
    circular = test_client.post(
        "/api/wind-workflow",
        json=workflow_payload()
        | {"wind_direction_multiplier_case": "circular_or_polygonal_chimney_tank_or_pole"},
    )
    cladding = test_client.post(
        "/api/wind-workflow",
        json=workflow_payload()
        | {"wind_direction_multiplier_case": "cladding_or_immediate_support"},
    )

    assert circular.status_code == 200
    assert cladding.status_code == 200
    circular_body = circular.json()
    cladding_body = cladding.json()
    assert all(row["md"] == 1.0 for row in circular_body["directional_vsitb"])
    assert "Clause 3.3" in circular_body["direction_multiplier_assessment"]["source_table"]
    assert [
        row["md"] for row in cladding_body["direction_multiplier_assessment"]["directions"]
    ] == [
        0.85,
        0.75,
        0.85,
        0.95,
        0.95,
        0.95,
        1.0,
        0.95,
    ]


@pytest.mark.parametrize(
    ("region", "required_subregion"),
    [("A", "A0, A1, A2, A3, A4, or A5"), ("B", "B1 or B2")],
)
def test_workflow_rejects_ambiguous_generic_region(
    monkeypatch,
    region: str,
    required_subregion: str,
) -> None:
    test_client = client(monkeypatch)
    monkeypatch.setattr(
        workflow_module,
        "assess_wind_region",
        lambda _site: WindRegionAssessment(
            latitude=-33.86,
            longitude=151.21,
            wind_region=region,
            source="test reviewed region",
            confidence="high",
        ),
    )

    response = test_client.post("/api/wind-workflow", json=workflow_payload())

    assert response.status_code == 400
    assert "ambiguous" in response.text.lower()
    assert required_subregion in response.text


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

    variables = [variable("VR", None, 1.0), variable("Mc", None, 1.0)]
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


def test_equal_site_wind_speeds_mark_all_co_governing_directions() -> None:
    def variable(name: str, direction: str | None, value: float) -> WindVariableAssessment:
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

    variables = [variable("VR", None, 45.0), variable("Mc", None, 1.0)]
    for direction in ("N", "NE"):
        variables.extend(
            [
                variable("Md", direction, 0.9),
                variable("Mzcat", direction, 1.0),
                variable("Ms", direction, 1.0),
                variable("Mt", direction, 1.0),
            ]
        )

    rows = mark_governing_vsitb(vsitb_directional_rows(variables))

    assert [row.direction for row in rows if row.is_governing] == ["N", "NE"]


def test_near_tie_summary_uses_the_exact_maximum_row(monkeypatch) -> None:
    test_client = client(monkeypatch)
    response = test_client.post(
        "/api/wind-workflow",
        json=workflow_payload()
        | {
            "workflow_overrides": [
                {
                    "variable": "Vsitb",
                    "direction": "N",
                    "override_value": 99.0,
                    "reason": "Reviewed near-tie value.",
                },
                {
                    "variable": "Vsitb",
                    "direction": "NE",
                    "override_value": 99.0000000005,
                    "reason": "Reviewed exact maximum.",
                },
            ]
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["governing_directions"] == ["N", "NE"]
    assert result["governing_direction"] == "NE"
    assert result["governing_vsitb"] == pytest.approx(99.0000000005)


def test_average_height_cannot_exceed_overall_building_height() -> None:
    with pytest.raises(ValueError, match="[Aa]verage.*building height"):
        WindWorkflowRequest(
            latitude=-33.86,
            longitude=151.21,
            building_height_m=10.0,
            average_roof_height_m=10.1,
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
