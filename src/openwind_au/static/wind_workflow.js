const workflowForm = document.getElementById("workflow-form");
const workflowSummary = document.getElementById("workflow-summary");
const siteInputSummary = document.getElementById("site-input-summary");
const windInputsSummary = document.getElementById("wind-inputs-summary");
const workflowMapFrame = document.getElementById("workflow-map-frame");
const terrainProfileFrame = document.getElementById("terrain-profile-frame");
const vsitbTable = document.getElementById("vsitb-table");
const rawProvenance = document.getElementById("raw-provenance");
const workflowReport = document.getElementById("workflow-report");
const workflowPdf = document.getElementById("workflow-pdf");
const reportStatus = document.getElementById("report-status");
const dashboardAddress = document.getElementById("dashboard-address");
const dashboardProjectNumber = document.getElementById("dashboard-project-number");
const dashboardRegion = document.getElementById("dashboard-region");
const dashboardGoverningDirection = document.getElementById("dashboard-governing-direction");
const dashboardGoverningVsitb = document.getElementById("dashboard-governing-vsitb");
const workflowProgress = document.querySelector(".workflow-progress");
const workflowProgressLabel = document.getElementById("workflow-progress-label");
const workflowProgressPercent = document.getElementById("workflow-progress-percent");
const workflowProgressTrack = document.getElementById("workflow-progress-track");
const workflowProgressBar = document.getElementById("workflow-progress-bar");
const workspaceTitle = document.querySelector(".map-toolbar strong");
const orientationControl = document.getElementById("structure_orientation_deg");
const orientationReadout = document.getElementById("orientation-readout");
const mapCoordinateReadout = document.getElementById("map-coordinate-readout");
const buildingWidthControl = document.getElementById("building_width_m");
const buildingLengthControl = document.getElementById("building_length_m");
const assessmentStatusControl = document.getElementById("assessment_status");
const reviewMetadataFields = document.getElementById("review-metadata-fields");
const reviewedByControl = document.getElementById("reviewed_by");
const engineerNotesControl = document.getElementById("engineer_notes");
const addressSuggestionsList = document.getElementById("dashboard-address-suggestions");
const DESIGN_LOCATION_STORAGE_KEY = "openwindDesignBuildingLocation";
const PROJECT_NUMBER_STORAGE_KEY = "openwindProjectNumber";
const DESIGN_LOCATION_STORAGE_VERSION = 1;
const SUPPORTED_LATITUDE_RANGE = [-44.5, -9.0];
const SUPPORTED_LONGITUDE_RANGE = [112.0, 154.5];

const orientationOptions = [
  -90,
  -78.75,
  -67.5,
  -56.25,
  -45,
  -33.75,
  -22.5,
  -11.25,
  0,
  11.25,
  22.5,
  33.75,
  45,
  56.25,
  67.5,
  78.75,
  90,
];
const directionOrder = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const variableOrder = ["VR", "Md", "Mzcat", "Ms", "Mt", "Vsitb"];
const variableAnchors = {
  VR: "wind-region-vr",
  Md: "wind-direction-md",
  Mzcat: "terrain-category-mzcat",
  Ms: "shielding-ms",
  Mt: "topographic-mt",
  Vsitb: "vsitb-summary",
};

const hiddenWindInputWarningPatterns = [
  /GIS interpretation/i,
  /table lookups/i,
  /automatically selected/i,
];

let currentWorkflow = null;
let currentWorkflowFingerprint = null;
let activeWorkflowPayload = null;
let activeWorkflowController = null;
let workflowRunId = 0;
let activeReportController = null;
let reportRequestId = 0;
let workflowOverrides = [];
let addressSuggestionTimer = null;
let addressSuggestionController = null;
let addressSuggestions = [];
let addressSuggestionIndex = -1;
let addressSuggestionMessage = "";
let addressSuggestionRequestId = 0;
let addressResolveController = null;
let addressResolveRequestId = 0;
let designBuildingState = null;
let coordinateOverride = null;
let locationMode = "address";
let currentMapSite = {
  latitude: -33.8688,
  longitude: 151.2093,
  display_name: "Sydney CBD",
};

if (dashboardProjectNumber) {
  try {
    dashboardProjectNumber.value = localStorage.getItem(PROJECT_NUMBER_STORAGE_KEY) || "";
  } catch (_error) {
    // Local storage can be unavailable in restrictive browser modes.
  }
  dashboardProjectNumber.addEventListener("input", () => {
    try {
      localStorage.setItem(PROJECT_NUMBER_STORAGE_KEY, dashboardProjectNumber.value);
    } catch (_error) {
      // Project changes must still invalidate state when persistence is unavailable.
    }
    invalidateDesignLocationForProject();
  });
}

restoreSavedDesignLocation();

const workspaceTabs = Array.from(document.querySelectorAll("[data-workspace-tab]"));
const mapWorkspace = document.querySelector(".map-workspace");

workspaceTabs.forEach((button) => {
  button.addEventListener("click", () => activateWorkspaceTab(button.dataset.workspaceTab));
  button.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const currentIndex = workspaceTabs.indexOf(button);
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? workspaceTabs.length - 1
        : (currentIndex + (event.key === "ArrowRight" ? 1 : -1) + workspaceTabs.length)
          % workspaceTabs.length;
    const nextTab = workspaceTabs[nextIndex];
    activateWorkspaceTab(nextTab.dataset.workspaceTab);
    nextTab.focus();
  });
});

window.addEventListener("message", (event) => {
  if (event.source !== workflowMapFrame?.contentWindow) return;
  if (event.data?.type !== "openwind-design-building-change") return;
  updateDesignBuildingState(event.data.state, { source: "map" });
});

function endMapDesignInteraction() {
  postWorkflowMapCommand("end-interaction");
}

window.addEventListener("mouseup", endMapDesignInteraction, true);
window.addEventListener("pointerup", endMapDesignInteraction, true);
window.addEventListener("blur", endMapDesignInteraction);

workflowForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (document.activeElement === dashboardAddress) {
    await zoomMapToAddress();
    return;
  }
  await runWorkflow();
});

workflowForm.addEventListener("input", () => {
  cancelActiveWorkflow();
  updateReportAvailability();
});

workflowForm.addEventListener("change", updateReportAvailability);

assessmentStatusControl?.addEventListener("change", syncReviewControls);
reviewedByControl?.addEventListener("input", syncReviewControls);
engineerNotesControl?.addEventListener("input", syncReviewControls);
syncReviewControls();

if (locationMode === "coordinates" && coordinateOverride) {
  renderInitialMapFrame("Saved project site restored.");
} else {
  renderPendingMapFrame("Enter an address and select a suggestion to position the building.");
}
syncDesignBuildingOverlay();

workflowMapFrame?.addEventListener("load", () => {
  syncCurrentMapSiteToFrame();
  syncDesignBuildingOverlay();
  invalidateWorkflowMap();
});

[orientationControl, buildingWidthControl, buildingLengthControl].forEach((control) => {
  control?.addEventListener("input", syncDesignBuildingOverlay);
  control?.addEventListener("change", syncDesignBuildingOverlay);
});

dashboardAddress?.addEventListener("input", () => {
  invalidateDesignLocationForAddress();
  queueAddressSuggestions(dashboardAddress.value);
});

dashboardAddress?.addEventListener("keydown", async (event) => {
  if (["ArrowDown", "ArrowUp"].includes(event.key) && addressSuggestions.length) {
    event.preventDefault();
    const direction = event.key === "ArrowDown" ? 1 : -1;
    addressSuggestionIndex = addressSuggestionIndex < 0
      ? (direction > 0 ? 0 : addressSuggestions.length - 1)
      : (addressSuggestionIndex + direction + addressSuggestions.length)
        % addressSuggestions.length;
    renderAddressSuggestions();
    return;
  }
  if (event.key === "Escape") {
    closeAddressSuggestions();
    return;
  }
  if (event.key !== "Enter") return;
  event.preventDefault();
  event.stopPropagation();
  const selected = addressSuggestions[addressSuggestionIndex]
    || suggestionForAddress(dashboardAddress.value);
  if (selected) {
    selectAddressSuggestion(selected);
    return;
  }
  await zoomMapToAddress();
});

dashboardAddress?.addEventListener("focus", () => renderAddressSuggestions());
dashboardAddress?.addEventListener("blur", () => setTimeout(closeAddressSuggestions, 120));

addressSuggestionsList?.addEventListener("mousedown", (event) => event.preventDefault());
addressSuggestionsList?.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  const target = event.target.closest("[data-address-suggestion-index]");
  if (!target) return;
  const suggestion = addressSuggestions[Number(target.dataset.addressSuggestionIndex)];
  if (suggestion) selectAddressSuggestion(suggestion);
});

workflowReport?.addEventListener("click", async () => {
  if (!assessmentIsCurrent()) {
    workflowSummary.textContent = "Run the assessment again before opening a report for changed inputs.";
    updateReportAvailability();
    return;
  }
  const reportFingerprint = currentWorkflowFingerprint;
  const reportPayload = currentWorkflow;
  const { requestId, controller } = startReportRequest();
  const reportWindow = window.open("about:blank", "_blank");
  if (reportWindow) reportWindow.document.body.textContent = "Generating HTML report...";
  try {
    const response = await postJson(
      "/api/wind-workflow/result/report/html",
      reportPayload,
      { signal: controller.signal },
    );
    const html = await response.text();
    if (!reportRequestIsCurrent(requestId, reportFingerprint)) {
      reportWindow?.close();
      return;
    }
    const reportUrl = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    if (reportWindow) reportWindow.location.replace(reportUrl);
    else window.open(reportUrl, "_blank", "noopener,noreferrer");
    setTimeout(() => URL.revokeObjectURL(reportUrl), 300000);
  } catch (error) {
    reportWindow?.close();
    if (error.name === "AbortError" || !reportRequestIsCurrent(requestId, reportFingerprint)) {
      return;
    }
    workflowSummary.textContent = `Workflow report failed: ${error.message}`;
  } finally {
    finishReportRequest(requestId);
  }
});

workflowPdf?.addEventListener("click", async () => {
  if (!assessmentIsCurrent()) {
    workflowSummary.textContent = "Run the assessment again before generating a PDF for changed inputs.";
    updateReportAvailability();
    return;
  }
  const reportFingerprint = currentWorkflowFingerprint;
  const reportPayload = currentWorkflow;
  const { requestId, controller } = startReportRequest();
  const reportWindow = window.open("about:blank", "_blank");
  if (reportWindow) reportWindow.document.body.textContent = "Generating PDF report...";
  workflowPdf.disabled = true;
  if (reportStatus) reportStatus.textContent = "Generating PDF from the completed assessment...";
  try {
    const response = await postJson(
      "/api/wind-workflow/result/report/pdf",
      reportPayload,
      { signal: controller.signal },
    );
    const pdf = await response.blob();
    if (!reportRequestIsCurrent(requestId, reportFingerprint)) {
      reportWindow?.close();
      return;
    }
    if (pdf.type !== "application/pdf" || pdf.size < 100) {
      throw new Error("The server did not return a valid PDF file.");
    }
    const reportUrl = URL.createObjectURL(pdf);
    if (reportWindow) {
      reportWindow.location.replace(reportUrl);
    } else {
      const link = document.createElement("a");
      link.href = reportUrl;
      link.download = "openwind-au-site-wind-assessment.pdf";
      document.body.appendChild(link);
      link.click();
      link.remove();
    }
    if (reportStatus) reportStatus.textContent = "PDF generated. Use the PDF viewer to save or print it.";
    setTimeout(() => URL.revokeObjectURL(reportUrl), 300000);
  } catch (error) {
    reportWindow?.close();
    if (error.name === "AbortError" || !reportRequestIsCurrent(requestId, reportFingerprint)) {
      return;
    }
    if (reportStatus) reportStatus.textContent = `PDF report failed: ${error.message}`;
    workflowSummary.textContent = `PDF report failed: ${error.message}`;
  } finally {
    finishReportRequest(requestId);
  }
});

async function runWorkflow() {
  syncReviewControls();
  if (!workflowForm.reportValidity()) {
    setWorkflowProgress(0, "Complete the required assessment inputs", "error");
    workflowSummary.textContent = "Complete the required assessment inputs before running the assessment.";
    return;
  }
  cancelAddressResolution();
  closeAddressSuggestions();
  cancelActiveWorkflow();
  const runId = workflowRunId;
  const controller = new AbortController();
  activeWorkflowController = controller;
  const requestPayload = workflowPayload();
  activeWorkflowPayload = requestPayload;
  setWorkflowProgress(4, "Resolving site location and elevation", "running");
  workflowSummary.textContent = "Resolving site location and elevation...";
  resetWorkflowSections();
  try {
    await runWorkflowStream(requestPayload, runId, controller.signal);
  } catch (error) {
    if (error.name === "AbortError" || runId !== workflowRunId) return;
    if (error.allowWorkflowFallback) {
      await runWorkflowFallback(error, requestPayload, runId, controller.signal);
    } else {
      renderWorkflowFailure(error);
    }
  } finally {
    if (runId === workflowRunId) activeWorkflowController = null;
  }
}

async function runWorkflowStream(requestPayload, runId, signal) {
  const response = await fetch("/api/wind-workflow/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(requestPayload),
    signal,
  });
  if (!response.ok || !response.body) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    const streamError = new Error(formatApiError(error.detail || response.statusText));
    streamError.allowWorkflowFallback = !response.body || [404, 405, 501].includes(response.status);
    throw streamError;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (runId !== workflowRunId) return;
      if (line.trim()) {
        handleWorkflowStreamEvent(JSON.parse(line), runId, requestPayload, signal);
      }
    }
    if (done) break;
  }
  if (runId === workflowRunId && buffer.trim()) {
    handleWorkflowStreamEvent(JSON.parse(buffer), runId, requestPayload, signal);
  }
}

function handleWorkflowStreamEvent(event, runId, requestPayload, signal) {
  if (runId !== workflowRunId) return;
  setWorkflowProgress(event.percent, event.label, event.stage === "error" ? "error" : "running");
  workflowSummary.textContent = `${event.label}\n${workflowSummary.textContent}`;
  if (event.stage === "error") {
    throw new Error(event.label || "Workflow failed");
  }
  if (event.data?.site_analysis) {
    renderSiteAnalysisProgress(event.data.site_analysis);
  }
  if (
    event.data?.wind_region_assessment ||
    event.data?.regional_wind_speed_assessment ||
    event.data?.direction_multiplier_assessment
  ) {
    renderWindInputsProgress(event.data);
  }
  if (event.data?.obstruction_summary) {
    renderObstructionProgress(event.data.obstruction_summary);
  }
  if (event.data?.terrain_category_evidence) {
    renderTerrainProgress(event.data.terrain_category_evidence);
  }
  if (event.data?.workflow) {
    currentWorkflow = event.data.workflow;
    renderWorkflow(currentWorkflow);
    currentWorkflowFingerprint = acceptedWorkflowFingerprint(requestPayload, currentWorkflow);
    updateReportAvailability();
  }
  if (event.data?.map_html && workflowMapFrame) {
    setIframeHtml(workflowMapFrame, event.data.map_html);
    setTimeout(() => {
      if (runId === workflowRunId) syncDesignBuildingOverlay();
    }, 80);
    renderTerrainProfileGraph(requestPayload, { runId, signal });
  }
  if (event.stage === "complete") {
    setWorkflowProgress(100, event.label, "complete");
  }
}

async function runWorkflowFallback(originalError, requestPayload, runId, signal) {
  try {
    const reason = originalError?.message ? ` (${originalError.message})` : "";
    setWorkflowProgress(32, `Live progress unavailable${reason}; calculating full workflow`, "running");
    const response = await postJson("/api/wind-workflow", requestPayload, { signal });
    if (runId !== workflowRunId) return;
    currentWorkflow = await response.json();
    renderSiteAnalysisProgress({
      input: currentWorkflow.input,
      site: currentWorkflow.site,
    });
    renderWorkflow(currentWorkflow);
    currentWorkflowFingerprint = acceptedWorkflowFingerprint(requestPayload, currentWorkflow);
    updateReportAvailability();
    setWorkflowProgress(78, "Rendering combined map layers", "running");
    await renderWorkflowMap(requestPayload, { runId, signal });
    await renderTerrainProfileGraph(requestPayload, { runId, signal });
    if (runId !== workflowRunId) return;
    setWorkflowProgress(100, "Assessment complete", "complete");
  } catch (fallbackError) {
    if (fallbackError.name === "AbortError" || runId !== workflowRunId) return;
    renderWorkflowFailure(fallbackError.message ? fallbackError : originalError);
  }
}

function workflowPayload() {
  const data = new FormData(workflowForm);
  const optionalNumber = (name) => {
    const value = data.get(name);
    return value === null || value === "" ? null : Number(value);
  };
  const payload = {
    address: data.get("address") || null,
    project_number: dashboardProjectNumber?.value.trim() || null,
    building_height_m: Number(data.get("building_height_m")),
    radius_m: Number(data.get("radius_m")),
    sample_interval_m: Number(data.get("sample_interval_m")),
    obstruction_radius_m: Number(data.get("obstruction_radius_m") || 500),
    default_storey_height_m: Number(data.get("default_storey_height_m") || 3),
    annual_exceedance_probability: data.get("annual_exceedance_probability") || "1/500",
    importance_level: data.get("importance_level") || null,
    structure_class: data.get("structure_class") || null,
    structure_orientation_deg: optionalNumber("structure_orientation_deg"),
    roof_shape: data.get("roof_shape") || null,
    building_width_m: optionalNumber("building_width_m"),
    building_length_m: optionalNumber("building_length_m"),
    roof_pitch_deg: optionalNumber("roof_pitch_deg"),
    average_height_m: optionalNumber("average_height_m"),
    base_rl_m: optionalNumber("base_rl_m"),
    assessment_status: data.get("assessment_status") || "draft",
    mzcat_recommendation_mode: "conservative",
    workflow_overrides: workflowOverrides,
  };
  if (payload.assessment_status === "reviewed") {
    payload.reviewed_by = String(data.get("reviewed_by") || "").trim();
    payload.engineer_notes = String(data.get("engineer_notes") || "").trim();
  }
  if (locationMode === "coordinates" && coordinateOverride) {
    payload.latitude = coordinateOverride.latitude;
    payload.longitude = coordinateOverride.longitude;
  }
  if (!payload.address) delete payload.address;
  if (!payload.project_number) delete payload.project_number;
  if (payload.importance_level === null) delete payload.importance_level;
  [
    "structure_class",
    "structure_orientation_deg",
    "roof_shape",
    "building_width_m",
    "building_length_m",
    "roof_pitch_deg",
    "average_height_m",
    "base_rl_m",
  ].forEach((key) => {
    if (payload[key] === null || Number.isNaN(payload[key])) delete payload[key];
  });
  return payload;
}

function syncReviewControls() {
  const reviewed = assessmentStatusControl?.value === "reviewed";
  if (assessmentStatusControl) {
    assessmentStatusControl.setAttribute("aria-expanded", String(reviewed));
  }
  if (reviewMetadataFields) reviewMetadataFields.hidden = !reviewed;
  [reviewedByControl, engineerNotesControl].forEach((control) => {
    if (!control) return;
    control.disabled = !reviewed;
    control.required = reviewed;
  });
  reviewedByControl?.setCustomValidity(
    reviewed && !reviewedByControl.value.trim() ? "Enter the reviewer name." : "",
  );
  engineerNotesControl?.setCustomValidity(
    reviewed && !engineerNotesControl.value.trim() ? "Enter engineer review notes." : "",
  );
}

function assessmentFingerprint() {
  return JSON.stringify(workflowPayload());
}

function acceptedWorkflowFingerprint(requestPayload, workflow) {
  const acceptedPayload = { ...requestPayload };
  if (
    acceptedPayload.latitude === undefined
    && acceptedPayload.longitude === undefined
    && Number.isFinite(Number(workflow?.site?.latitude))
    && Number.isFinite(Number(workflow?.site?.longitude))
  ) {
    acceptedPayload.latitude = Number(workflow.site.latitude);
    acceptedPayload.longitude = Number(workflow.site.longitude);
  }
  return JSON.stringify(acceptedPayload);
}

function assessmentIsCurrent() {
  return Boolean(
    currentWorkflow
    && currentWorkflowFingerprint
    && currentWorkflowFingerprint === assessmentFingerprint()
  );
}

function updateReportAvailability() {
  const isCurrent = assessmentIsCurrent();
  if (workflowPdf) workflowPdf.disabled = !isCurrent;
  if (workflowReport) workflowReport.disabled = !isCurrent;
  if (!reportStatus) return;
  if (currentWorkflow && !isCurrent) {
    reportStatus.textContent = "Inputs changed. Run the assessment again before generating reports.";
  } else if (isCurrent && !reportStatus.textContent.includes("generated")) {
    reportStatus.textContent = "Reports are ready for the current assessment.";
  } else if (!currentWorkflow) {
    reportStatus.textContent = "";
  }
}

function startReportRequest() {
  cancelActiveReportRequest();
  const controller = new AbortController();
  activeReportController = controller;
  return { requestId: reportRequestId, controller };
}

function reportRequestIsCurrent(requestId, fingerprint) {
  return Boolean(
    requestId === reportRequestId
    && fingerprint === currentWorkflowFingerprint
    && assessmentIsCurrent()
  );
}

function finishReportRequest(requestId) {
  if (requestId !== reportRequestId) return;
  activeReportController = null;
  updateReportAvailability();
}

function cancelActiveReportRequest() {
  reportRequestId += 1;
  activeReportController?.abort();
  activeReportController = null;
}

function cancelActiveWorkflow() {
  workflowRunId += 1;
  activeWorkflowController?.abort();
  activeWorkflowController = null;
  cancelActiveReportRequest();
}

function renderWorkflowFailure(error) {
  const message = formatApiError(error?.message || error || "Unknown error");
  setWorkflowProgress(100, "Assessment failed", "error");
  workflowSummary.textContent = `Workflow failed: ${message}`;
  vsitbTable.innerHTML = "<tr><td colspan=\"7\">Workflow failed.</td></tr>";
  currentWorkflow = null;
  currentWorkflowFingerprint = null;
  updateReportAvailability();
}

function formatApiError(detail) {
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const location = Array.isArray(item?.loc) ? item.loc.join(".") : "request";
      return `${location}: ${item?.msg || JSON.stringify(item)}`;
    }).join("; ");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return String(detail || "Request failed");
}

async function postJson(url, payload, options = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: options.signal,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(formatApiError(error.detail || response.statusText));
  }
  return response;
}

function renderWorkflow(workflow) {
  workflowSummary.textContent = JSON.stringify({
    site: workflow.site,
    overrides_applied: workflow.input?.workflow_overrides?.length || 0,
    warnings: visibleWarnings(workflow.warnings),
    vsitb_status: workflow.directional_vsitb.map((row) => ({
      direction: row.direction,
      status: row.status,
      vsitb: row.final_vsitb,
    })),
    disclaimer: workflow.disclaimer,
  }, null, 2);

  const grouped = groupVariables(workflow.variables || []);
  renderDashboardHeader(workflow);
  renderSiteInputs(workflow);
  renderWindInputs(workflow);
  variableOrder.forEach((variable) => {
    if (variable === "Vsitb") return;
    renderVariableSection(variable, grouped[variable] || []);
  });
  renderVsitbTable(workflow.directional_vsitb || []);
  renderRawProvenance(workflow.variables || []);
}

function renderDashboardHeader(workflow) {
  if (dashboardRegion) dashboardRegion.textContent = workflow.wind_region_assessment?.wind_region || "-";
  if (dashboardGoverningDirection) {
    dashboardGoverningDirection.textContent = workflow.governing_direction || "-";
  }
  if (dashboardGoverningVsitb) {
    dashboardGoverningVsitb.textContent = workflow.governing_vsitb === null || workflow.governing_vsitb === undefined
      ? "Review required"
      : `${Number(workflow.governing_vsitb).toFixed(3)} m/s`;
  }
}

async function renderWorkflowMap(
  requestPayload = activeWorkflowPayload || workflowPayload(),
  options = {},
) {
  if (!workflowMapFrame) return;
  renderInitialMapFrame("Rendering project site map...");
  try {
    const response = await postJson("/api/wind-workflow/map", requestPayload, options);
    const html = await response.text();
    if (options.runId && options.runId !== workflowRunId) return;
    setIframeHtml(workflowMapFrame, html);
    setTimeout(syncDesignBuildingOverlay, 80);
    setTimeout(invalidateWorkflowMap, 140);
  } catch (error) {
    if (error.name === "AbortError" || (options.runId && options.runId !== workflowRunId)) return;
    setIframeHtml(workflowMapFrame, `<p>Combined map failed: ${escapeHtml(error.message)}</p>`);
    throw error;
  }
}

async function renderTerrainProfileGraph(
  requestPayload = activeWorkflowPayload || workflowPayload(),
  options = {},
) {
  if (!terrainProfileFrame) return;
  setIframeHtml(terrainProfileFrame, "<p>Rendering terrain profile graph...</p>");
  try {
    const response = await postJson("/api/plots/profile", requestPayload, options);
    const html = await response.text();
    if (options.runId && options.runId !== workflowRunId) return;
    setIframeHtml(terrainProfileFrame, html);
  } catch (error) {
    if (error.name === "AbortError" || (options.runId && options.runId !== workflowRunId)) return;
    setIframeHtml(terrainProfileFrame, `<p>Terrain profile graph failed: ${escapeHtml(error.message)}</p>`);
  }
}

function renderInitialMapFrame(message, options = {}) {
  if (!workflowMapFrame) return;
  if ((workflowMapFrame.src || workflowMapFrame.srcdoc) && !options.force) return;
  setIframeHtml(workflowMapFrame, initialMapHtml(message));
}

function renderPendingMapFrame(message) {
  if (!workflowMapFrame) return;
  setIframeHtml(workflowMapFrame, pendingMapHtml(message));
}

function clearIframeHtml(frame) {
  if (!frame) return;
  frame.removeAttribute("src");
  frame.removeAttribute("srcdoc");
}

function setIframeHtml(frame, html) {
  if (!frame) return;
  clearIframeHtml(frame);
  frame.srcdoc = iframeHtml(html);
}

function iframeHtml(html) {
  const base = `<base href="${window.location.origin}/">`;
  if (!html || html.includes("<base ")) return html;
  if (html.includes("<head>")) return html.replace("<head>", `<head>${base}`);
  return `${base}${html}`;
}

function pendingMapHtml(message) {
  return `<!doctype html>
<html lang="en">
<head>
  <base href="${window.location.origin}/">
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    html, body { height: 100%; margin: 0; }
    body {
      display: grid;
      place-items: center;
      padding: 24px;
      box-sizing: border-box;
      background: #dfe6ee;
      color: #344054;
      font: 700 14px/1.5 Arial, sans-serif;
      text-align: center;
    }
  </style>
</head>
<body><p role="status">${escapeHtml(message || "Select a project site.")}</p></body>
</html>`;
}

function initialMapHtml(message) {
  const orientation = nearestOrientation(parseOptionalNumber(orientationControl?.value) ?? 0);
  const widthM = parseOptionalNumber(buildingWidthControl?.value) ?? 12;
  const lengthM = parseOptionalNumber(buildingLengthControl?.value) ?? 18;
  const safeMessage = escapeHtml(message || "Ready");
  return `<!doctype html>
<html lang="en">
<head>
  <base href="${window.location.origin}/">
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="/static/vendor/leaflet/leaflet.css" />
  <style>
    html,
    body,
    #map {
      width: 100%;
      height: 100%;
      margin: 0;
    }
    body {
      font-family: Arial, sans-serif;
      color: #172033;
      background: #dfe6ee;
    }
    .map-status {
      position: fixed;
      left: 16px;
      bottom: 16px;
      z-index: 999;
      max-width: 340px;
      border: 1px solid rgb(23 32 51 / 16%);
      border-radius: 4px;
      padding: 10px 12px;
      background: rgb(255 255 255 / 94%);
      box-shadow: 0 6px 20px rgb(16 24 40 / 14%);
      font-size: 13px;
      font-weight: 700;
      line-height: 1.35;
    }
    .map-status-error {
      background: #fff7ed;
      border-color: #fdba74;
      color: #7c2d12;
    }
  </style>
</head>
<body>
  <div id="map"></div>
  <div id="map-status" class="map-status">${safeMessage}</div>
  <script src="/static/vendor/leaflet/leaflet.js"></script>
  <script>
    (function () {
      const statusEl = document.getElementById("map-status");
      if (!window.L) {
        if (statusEl) {
          statusEl.classList.add("map-status-error");
          statusEl.textContent = "Map library failed to load. Check internet/CDN access, then reload the app.";
        }
        return;
      }
      const state = {
        latitude: ${jsonForInlineScript(currentMapSite.latitude)},
        longitude: ${jsonForInlineScript(currentMapSite.longitude)},
        display_name: ${jsonForInlineScript(currentMapSite.display_name || "Mapped site")},
        width_m: ${jsonForInlineScript(widthM)},
        length_m: ${jsonForInlineScript(lengthM)},
        orientation_deg: ${jsonForInlineScript(orientation)},
        offset_east_m: 0,
        offset_north_m: 0,
        user_modified: false,
        position_modified: false,
        orientation_modified: false,
        orientation_options: ${jsonForInlineScript(orientationOptions)}
      };
      const map = L.map("map", { zoomControl: true }).setView(
        [state.latitude, state.longitude],
        18
      );
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 20,
        attribution: "&copy; OpenStreetMap contributors"
      }).addTo(map);
      const designLayer = L.layerGroup().addTo(map);
      let footprint = null;
      let bearingLine = null;
      let pointsLayer = null;
      let orientationDrag = null;
      let buildingDragStart = null;
      let suppressOrientationClick = false;

      function clampDimension(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) && number > 0 ? number : fallback;
      }

      function formatDegrees(value) {
        return Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 2);
      }

      function nearestOrientationOption(value) {
        const number = Number(value);
        if (!Number.isFinite(number)) return 0;
        return state.orientation_options.reduce((best, option) => (
          Math.abs(option - number) < Math.abs(best - number) ? option : best
        ), state.orientation_options[0]);
      }

      function latLngFromMeters(eastM, northM) {
        const earthRadiusM = 6378137;
        const adjustedEastM = eastM + state.offset_east_m;
        const adjustedNorthM = northM + state.offset_north_m;
        const lat = state.latitude + (adjustedNorthM / earthRadiusM) * (180 / Math.PI);
        const lon = state.longitude
          + (adjustedEastM / (earthRadiusM * Math.cos(state.latitude * Math.PI / 180)))
          * (180 / Math.PI);
        return [lat, lon];
      }

      function metersDelta(fromLatLng, toLatLng) {
        const earthRadiusM = 6378137;
        const northM = (toLatLng.lat - fromLatLng.lat) * Math.PI / 180 * earthRadiusM;
        const eastM = (toLatLng.lng - fromLatLng.lng) * Math.PI / 180
          * earthRadiusM * Math.cos(state.latitude * Math.PI / 180);
        return { eastM, northM };
      }

      function footprintCorners() {
        const theta = Number(state.orientation_deg) * Math.PI / 180;
        const halfLength = clampDimension(state.length_m, 18) / 2;
        const halfWidth = clampDimension(state.width_m, 12) / 2;
        const lengthAxis = [Math.sin(theta), Math.cos(theta)];
        const widthAxis = [Math.cos(theta), -Math.sin(theta)];
        return [
          [halfLength, halfWidth],
          [halfLength, -halfWidth],
          [-halfLength, -halfWidth],
          [-halfLength, halfWidth]
        ].map(([lengthOffset, widthOffset]) => latLngFromMeters(
          lengthAxis[0] * lengthOffset + widthAxis[0] * widthOffset,
          lengthAxis[1] * lengthOffset + widthAxis[1] * widthOffset
        ));
      }

      function bearingEndpoint(distanceM) {
        const theta = Number(state.orientation_deg) * Math.PI / 180;
        return latLngFromMeters(Math.sin(theta) * distanceM, Math.cos(theta) * distanceM);
      }

      function centerLatLng() {
        return latLngFromMeters(0, 0);
      }

      function notifyParent() {
        try {
          window.parent.postMessage({
            type: "openwind-design-building-change",
            state: Object.assign({}, state)
          }, "*");
        } catch (_error) {
          // Parent notification is best-effort for embedded previews.
        }
      }

      function applyOrientationFromLatLng(latlng) {
        const center = centerLatLng();
        const delta = metersDelta({ lat: center[0], lng: center[1] }, latlng);
        const rawDegrees = Math.atan2(delta.eastM, delta.northM) * 180 / Math.PI;
        const snapped = nearestOrientationOption(rawDegrees);
        if (Number(state.orientation_deg) === Number(snapped)) return;
        if (orientationDrag) orientationDrag.moved = true;
        state.orientation_deg = snapped;
        state.user_modified = true;
        state.orientation_modified = true;
        redraw();
        notifyParent();
        state.orientation_modified = false;
      }

      function startOrientationDrag(event) {
        L.DomEvent.preventDefault(event.originalEvent);
        L.DomEvent.stopPropagation(event.originalEvent);
        orientationDrag = { moved: false };
        map.dragging.disable();
        map.getContainer().style.cursor = "grabbing";
        applyOrientationFromLatLng(event.latlng);
      }

      function stopOrientationDrag() {
        if (!orientationDrag) return;
        if (orientationDrag.moved) {
          suppressOrientationClick = true;
          setTimeout(() => {
            suppressOrientationClick = false;
          }, 0);
        }
        orientationDrag = null;
        map.dragging.enable();
        map.getContainer().style.cursor = "";
      }

      function stopDesignInteraction() {
        stopOrientationDrag();
        if (!buildingDragStart) return;
        buildingDragStart = null;
        map.dragging.enable();
        map.getContainer().style.cursor = "";
      }

      function renderOrientationPoints() {
        if (pointsLayer) designLayer.removeLayer(pointsLayer);
        pointsLayer = L.layerGroup();
        const radius = Math.max(28, Math.min(70, Math.max(state.width_m, state.length_m) * 1.15));
        state.orientation_options.forEach((option) => {
          const theta = Number(option) * Math.PI / 180;
          const point = latLngFromMeters(Math.sin(theta) * radius, Math.cos(theta) * radius);
          const active = Number(option) === Number(state.orientation_deg);
          const marker = L.circleMarker(point, {
            radius: active ? 5 : 3,
            color: active ? "#0f766e" : "#475569",
            weight: active ? 2 : 1,
            fillColor: active ? "#14b8a6" : "#ffffff",
            fillOpacity: active ? 0.95 : 0.8
          })
            .bindTooltip(formatDegrees(option) + " deg", { sticky: true })
            .on("click", () => {
              if (orientationDrag || suppressOrientationClick) return;
              state.orientation_deg = Number(option);
              state.user_modified = true;
              state.orientation_modified = true;
              redraw();
              notifyParent();
              state.orientation_modified = false;
            })
            .addTo(pointsLayer);
          if (active) {
            marker.on("mousedown", startOrientationDrag);
          }
        });
        pointsLayer.addTo(designLayer);
      }

      function redraw() {
        const corners = footprintCorners();
        if (!footprint) {
          footprint = L.polygon(corners, {
            color: "#ea580c",
            weight: 4,
            dashArray: "10 5",
            fillColor: "#fb923c",
            fillOpacity: 0.22
          }).addTo(designLayer);
          enableBuildingDrag(footprint);
        } else {
          footprint.setLatLngs(corners);
        }
        footprint.bindTooltip("Design building " + formatDegrees(state.orientation_deg) + " deg", {
          sticky: true
        });
        const bearingDistance = Math.max(state.length_m, 18) * 0.75;
        const line = [centerLatLng(), bearingEndpoint(bearingDistance)];
        if (!bearingLine) {
          bearingLine = L.polyline(line, {
            color: "#ea580c",
            weight: 3,
            dashArray: "4 4"
          }).addTo(designLayer);
        } else {
          bearingLine.setLatLngs(line);
        }
        renderOrientationPoints();
      }

      function nudgeDesignBuilding(eastM, northM) {
        const east = Number(eastM);
        const north = Number(northM);
        if (!Number.isFinite(east) || !Number.isFinite(north)) return;
        state.offset_east_m += east;
        state.offset_north_m += north;
        state.user_modified = true;
        state.position_modified = true;
        redraw();
        notifyParent();
        state.position_modified = false;
      }

      function enableBuildingDrag(layer) {
        layer.on("mousedown", (event) => {
          L.DomEvent.preventDefault(event.originalEvent);
          L.DomEvent.stopPropagation(event.originalEvent);
          buildingDragStart = {
            latlng: event.latlng,
            east: state.offset_east_m,
            north: state.offset_north_m
          };
          map.dragging.disable();
          map.getContainer().style.cursor = "move";
        });
        map.on("mousemove", (event) => {
          if (orientationDrag) {
            applyOrientationFromLatLng(event.latlng);
            return;
          }
          if (!buildingDragStart) return;
          const delta = metersDelta(buildingDragStart.latlng, event.latlng);
          state.offset_east_m = buildingDragStart.east + delta.eastM;
          state.offset_north_m = buildingDragStart.north + delta.northM;
          state.user_modified = true;
          state.position_modified = true;
          redraw();
          notifyParent();
          state.position_modified = false;
        });
        map.on("mouseup", stopDesignInteraction);
        window.addEventListener("mouseup", stopDesignInteraction, true);
        window.addEventListener("blur", stopDesignInteraction);
        document.documentElement.addEventListener("mouseleave", stopDesignInteraction);
      }

      window.openWindDesignBuilding = {
        setOrientation(value) {
          const number = Number(value);
          if (Number.isFinite(number)) {
            state.orientation_deg = number;
            state.orientation_modified = false;
            redraw();
            notifyParent();
          }
        },
        setDimensions(widthM, lengthM) {
          state.width_m = clampDimension(widthM, 12);
          state.length_m = clampDimension(lengthM, 18);
          redraw();
          notifyParent();
        },
        nudge(eastM, northM) {
          nudgeDesignBuilding(eastM, northM);
        },
        endInteraction() {
          stopDesignInteraction();
        },
        getState() {
          return Object.assign({}, state);
        }
      };

      window.openWindWorkflowMap = {
        setSite(site) {
          const latitude = Number(site && site.latitude);
          const longitude = Number(site && site.longitude);
          if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
          state.latitude = latitude;
          state.longitude = longitude;
          state.display_name = site.display_name || "Mapped site";
          state.offset_east_m = 0;
          state.offset_north_m = 0;
          state.user_modified = false;
          state.position_modified = false;
          state.orientation_modified = false;
          map.setView([state.latitude, state.longitude], 18);
          redraw();
          notifyParent();
        },
        invalidate() {
          map.invalidateSize();
        },
        getState() {
          return Object.assign({}, state);
        }
      };

      window.addEventListener("message", (event) => {
        if (event.source !== window.parent || event.data?.type !== "openwind-map-command") return;
        const payload = event.data.payload || {};
        if (event.data.action === "set-site") {
          window.openWindWorkflowMap.setSite(payload.site);
        } else if (event.data.action === "set-dimensions") {
          window.openWindDesignBuilding.setDimensions(payload.width_m, payload.length_m);
        } else if (event.data.action === "set-orientation") {
          window.openWindDesignBuilding.setOrientation(payload.orientation_deg);
        } else if (event.data.action === "nudge") {
          window.openWindDesignBuilding.nudge(payload.east_m, payload.north_m);
        } else if (event.data.action === "end-interaction") {
          window.openWindDesignBuilding.endInteraction();
        } else if (event.data.action === "invalidate") {
          window.openWindWorkflowMap.invalidate();
        }
      });

      redraw();
      notifyParent();
      setTimeout(() => map.invalidateSize(), 100);
    })();
  </script>
</body>
</html>`;
}

function setWorkflowProgress(percent, label, state = "running") {
  const bounded = Math.max(0, Math.min(100, Number(percent) || 0));
  if (workflowProgress) workflowProgress.dataset.progressState = state;
  if (workflowProgressLabel) workflowProgressLabel.textContent = label;
  if (workflowProgressPercent) workflowProgressPercent.textContent = `${Math.round(bounded)}%`;
  if (workflowProgressTrack) {
    workflowProgressTrack.setAttribute("aria-valuenow", String(Math.round(bounded)));
  }
  if (workflowProgressBar) workflowProgressBar.style.width = `${bounded}%`;
}

function activateWorkspaceTab(tabName) {
  if (!tabName) return;
  const canvasTab = tabName === "profile" ? "profile" : "map";
  const showsCanvas = tabName === "map" || tabName === "profile";
  document.body.classList.toggle("detail-workspace-active", !showsCanvas);
  if (mapWorkspace) mapWorkspace.hidden = !showsCanvas;
  document.querySelectorAll("[data-workspace-tab]").forEach((button) => {
    const isActive = button.dataset.workspaceTab === tabName;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", String(isActive));
    button.tabIndex = isActive ? 0 : -1;
  });
  document.querySelectorAll("[data-workspace-panel]").forEach((panel) => {
    const isActive = panel.dataset.workspacePanel === tabName;
    panel.classList.toggle("is-active", isActive);
    panel.hidden = !isActive;
  });
  if (workflowMapFrame) workflowMapFrame.hidden = canvasTab !== "map";
  if (terrainProfileFrame) terrainProfileFrame.hidden = canvasTab !== "profile";
  if (workspaceTitle) {
    workspaceTitle.textContent = canvasTab === "profile"
      ? "Terrain Profile Graph"
      : "Interactive Wind Map";
  }
  if (canvasTab === "map") invalidateWorkflowMap();
}

function syncDesignBuildingOverlay() {
  const orientation = nearestOrientation(parseOptionalNumber(orientationControl?.value) ?? 0);
  if (orientationControl && Number(orientationControl.value) !== orientation) {
    orientationControl.value = String(orientation);
  }
  if (orientationReadout) orientationReadout.textContent = `${formatOrientation(orientation)} deg`;
  updateDesignBuildingState(
    {
      ...(designBuildingState || currentMapSite),
      orientation_deg: orientation,
      width_m: parseOptionalNumber(buildingWidthControl?.value),
      length_m: parseOptionalNumber(buildingLengthControl?.value),
    },
    { source: "form" },
  );
  if (coordinateOverride) saveDesignLocation(coordinateOverride);
  postWorkflowMapCommand("set-dimensions", {
    width_m: parseOptionalNumber(buildingWidthControl?.value),
    length_m: parseOptionalNumber(buildingLengthControl?.value),
  });
  postWorkflowMapCommand("set-orientation", { orientation_deg: orientation });
}

function syncCurrentMapSiteToFrame() {
  if (locationMode !== "coordinates" || !coordinateOverride) return;
  postWorkflowMapCommand("set-site", {
    site: {
      ...coordinateOverride,
      display_name: coordinateOverride.display_name || currentMapSite.display_name,
    },
  });
}

function updateDesignBuildingState(state, options = {}) {
  if (!state) return;
  const previousOrientation = parseOptionalNumber(designBuildingState?.orientation_deg);
  designBuildingState = {
    ...(designBuildingState || {}),
    ...state,
  };
  const reportedOrientation = nearestOrientation(
    parseOptionalNumber(designBuildingState.orientation_deg) ?? 0,
  );
  const adjustedLocation = adjustedLocationFromDesignState(designBuildingState);
  const positionModified = options.source === "map" && designBuildingState.position_modified;
  const orientationModified = (
    options.source === "map"
    && Boolean(designBuildingState.orientation_modified)
  );
  const orientation = (
    options.source === "map"
    && !orientationModified
    && previousOrientation !== null
  ) ? nearestOrientation(previousOrientation) : reportedOrientation;
  designBuildingState.orientation_deg = orientation;
  const userMapChange = positionModified || orientationModified;
  if (positionModified && adjustedLocation) {
    coordinateOverride = {
      ...adjustedLocation,
      display_name: currentMapSite.display_name || "Saved building location",
    };
    locationMode = "coordinates";
    renderMapCoordinates(coordinateOverride);
    saveDesignLocation({
      ...coordinateOverride,
    });
    const latitudeCell = document.getElementById("resolved-site-latitude");
    const longitudeCell = document.getElementById("resolved-site-longitude");
    if (latitudeCell) latitudeCell.textContent = coordinateOverride.latitude.toFixed(6);
    if (longitudeCell) longitudeCell.textContent = coordinateOverride.longitude.toFixed(6);
  } else if (coordinateOverride) {
    renderMapCoordinates(coordinateOverride);
  }
  if (orientationControl && Number(orientationControl.value) !== orientation) {
    orientationControl.value = String(orientation);
  }
  if (orientationReadout) orientationReadout.textContent = `${formatOrientation(orientation)} deg`;
  if (userMapChange) {
    if (coordinateOverride) saveDesignLocation(coordinateOverride);
    cancelActiveWorkflow();
    updateReportAvailability();
  }
  if (userMapChange && currentWorkflow) {
    setWorkflowProgress(100, "Map adjusted; rerun assessment to refresh calculated layers", "complete");
  }
}

function adjustedLocationFromDesignState(state) {
  if (!state) return null;
  const latitude = Number(state.latitude);
  const longitude = Number(state.longitude);
  const eastM = Number(state.offset_east_m || 0);
  const northM = Number(state.offset_north_m || 0);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  const earthRadiusM = 6378137;
  const adjustedLatitude = latitude + (northM / earthRadiusM) * (180 / Math.PI);
  const metresPerDegreeLon = earthRadiusM * Math.cos(latitude * Math.PI / 180);
  const adjustedLongitude = longitude + (eastM / metresPerDegreeLon) * (180 / Math.PI);
  return {
    latitude: adjustedLatitude,
    longitude: adjustedLongitude,
  };
}

function renderMapCoordinates(location) {
  if (!mapCoordinateReadout) return;
  mapCoordinateReadout.textContent = location
    ? `${Number(location.latitude).toFixed(6)}, ${Number(location.longitude).toFixed(6)}`
    : "Not positioned";
}

function saveDesignLocation(location) {
  try {
    const projectNumber = dashboardProjectNumber?.value.trim() || "";
    if (!projectNumber) {
      clearSavedDesignLocation();
      return;
    }
    localStorage.setItem(DESIGN_LOCATION_STORAGE_KEY, JSON.stringify({
      version: DESIGN_LOCATION_STORAGE_VERSION,
      latitude: Number(location.latitude),
      longitude: Number(location.longitude),
      display_name: location.display_name || dashboardAddress?.value.trim() || "Saved building location",
      address: dashboardAddress?.value.trim() || location.display_name || "",
      project_number: projectNumber,
      orientation_deg: nearestOrientation(parseOptionalNumber(orientationControl?.value) ?? 0),
    }));
  } catch (_error) {
    // Coordinate persistence is best-effort when browser storage is unavailable.
  }
}

function clearSavedDesignLocation() {
  try {
    localStorage.removeItem(DESIGN_LOCATION_STORAGE_KEY);
  } catch (_error) {
    // Coordinate persistence is best-effort when browser storage is unavailable.
  }
}

function restoreSavedDesignLocation() {
  try {
    const savedLocation = JSON.parse(localStorage.getItem(DESIGN_LOCATION_STORAGE_KEY) || "null");
    const projectNumber = dashboardProjectNumber?.value.trim() || "";
    const savedProjectNumber = typeof savedLocation?.project_number === "string"
      ? savedLocation.project_number.trim()
      : "";
    const isCurrentFormat = savedLocation?.version === DESIGN_LOCATION_STORAGE_VERSION;
    const belongsToProject = Boolean(
      projectNumber
      && savedProjectNumber
      && savedProjectNumber === projectNumber
    );
    const hasCoordinates = (
      typeof savedLocation?.latitude === "number"
      && typeof savedLocation?.longitude === "number"
      && Number.isFinite(savedLocation.latitude)
      && Number.isFinite(savedLocation.longitude)
      && savedLocation.latitude >= SUPPORTED_LATITUDE_RANGE[0]
      && savedLocation.latitude <= SUPPORTED_LATITUDE_RANGE[1]
      && savedLocation.longitude >= SUPPORTED_LONGITUDE_RANGE[0]
      && savedLocation.longitude <= SUPPORTED_LONGITUDE_RANGE[1]
    );
    if (!isCurrentFormat || !belongsToProject || !hasCoordinates) {
      if (savedLocation) clearSavedDesignLocation();
      return;
    }
    currentMapSite = {
      latitude: Number(savedLocation.latitude),
      longitude: Number(savedLocation.longitude),
      display_name: savedLocation.display_name || "Saved building location",
    };
    coordinateOverride = { ...currentMapSite };
    locationMode = "coordinates";
    if (dashboardAddress && savedLocation.address) {
      dashboardAddress.value = savedLocation.address;
    }
    const savedOrientation = parseOptionalNumber(savedLocation.orientation_deg);
    if (orientationControl && savedOrientation !== null) {
      orientationControl.value = String(nearestOrientation(savedOrientation));
    }
  } catch (_error) {
    clearSavedDesignLocation();
  }
}

function invalidateDesignLocationForProject() {
  cancelAddressResolution();
  cancelActiveWorkflow();
  locationMode = "address";
  coordinateOverride = null;
  designBuildingState = null;
  clearSavedDesignLocation();
  renderMapCoordinates(null);
  renderPendingMapFrame("Enter an address for the selected project.");
  updateReportAvailability();
}

function invalidateDesignLocationForAddress() {
  cancelAddressResolution();
  cancelActiveWorkflow();
  locationMode = "address";
  coordinateOverride = null;
  designBuildingState = null;
  clearSavedDesignLocation();
  renderMapCoordinates(null);
  renderPendingMapFrame("Address changed. Select a suggestion or run the assessment to locate it.");
  updateReportAvailability();
  setWorkflowProgress(0, "Address changed; select a suggestion or run the assessment", "complete");
}

async function zoomMapToAddress() {
  const address = dashboardAddress?.value.trim();
  if (!address) {
    setWorkflowProgress(0, "Enter an address to zoom the map", "error");
    return;
  }
  cancelAddressResolution();
  const requestId = ++addressResolveRequestId;
  const controller = new AbortController();
  addressResolveController = controller;
  setWorkflowProgress(8, "Locating address on map", "running");
  closeAddressSuggestions();
  try {
    const response = await fetch("/api/geocode/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: address }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.detail || response.statusText);
    }
    const resolved = await response.json();
    if (
      requestId !== addressResolveRequestId
      || dashboardAddress?.value.trim() !== address
    ) return;
    applyAddressSuggestion(resolved);
  } catch (error) {
    if (error.name === "AbortError" || requestId !== addressResolveRequestId) return;
    setWorkflowProgress(0, "Address lookup failed", "error");
    workflowSummary.textContent = `Address lookup failed: ${error.message}`;
  } finally {
    if (requestId === addressResolveRequestId) addressResolveController = null;
  }
}

function cancelAddressResolution() {
  addressResolveRequestId += 1;
  addressResolveController?.abort();
  addressResolveController = null;
}

function queueAddressSuggestions(query) {
  const trimmed = String(query || "").trim();
  const requestId = ++addressSuggestionRequestId;
  clearTimeout(addressSuggestionTimer);
  if (addressSuggestionController) addressSuggestionController.abort();
  addressSuggestionIndex = -1;
  addressSuggestions = [];
  if (trimmed.length < 3) {
    addressSuggestions = [];
    addressSuggestionMessage = "";
    renderAddressSuggestions();
    return;
  }
  addressSuggestionMessage = "Searching Australian addresses...";
  renderAddressSuggestions();
  addressSuggestionTimer = setTimeout(async () => {
    addressSuggestionController = new AbortController();
    try {
      const response = await fetch("/api/geocode/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: trimmed, limit: 6 }),
        signal: addressSuggestionController.signal,
      });
      if (!response.ok) throw new Error(response.statusText || "Address lookup failed");
      const data = await response.json();
      if (requestId !== addressSuggestionRequestId || dashboardAddress?.value.trim() !== trimmed) {
        return;
      }
      addressSuggestions = data.suggestions || [];
      addressSuggestionMessage = addressSuggestions.length ? "" : "No matching Australian addresses found.";
      renderAddressSuggestions();
    } catch (error) {
      if (error.name !== "AbortError" && requestId === addressSuggestionRequestId) {
        addressSuggestions = [];
        addressSuggestionMessage = "Address suggestions are temporarily unavailable.";
        renderAddressSuggestions();
      }
    }
  }, 280);
}

function renderAddressSuggestions() {
  if (!addressSuggestionsList) return;
  const hasContent = addressSuggestions.length || addressSuggestionMessage;
  addressSuggestionsList.hidden = !hasContent;
  dashboardAddress?.setAttribute("aria-expanded", String(Boolean(hasContent)));
  dashboardAddress?.removeAttribute("aria-activedescendant");
  if (!hasContent) {
    addressSuggestionsList.innerHTML = "";
    return;
  }
  if (!addressSuggestions.length) {
    addressSuggestionsList.innerHTML = `
      <li class="address-suggestion-status" role="status">${escapeHtml(addressSuggestionMessage)}</li>
    `;
    return;
  }
  const optionsHtml = addressSuggestions.map((suggestion, index) => {
    const active = index === addressSuggestionIndex;
    const optionId = `address-suggestion-${index}`;
    if (active) dashboardAddress?.setAttribute("aria-activedescendant", optionId);
    return `
      <li
        id="${optionId}"
        role="option"
        aria-selected="${String(active)}"
        data-address-suggestion-index="${index}"
        class="${active ? "is-active" : ""}"
      >${escapeHtml(suggestion.display_name)}</li>
    `;
  }).join("");
  addressSuggestionsList.innerHTML = `${optionsHtml}
    <li class="address-suggestion-attribution" role="presentation">
      Address search: Photon / OpenStreetMap
    </li>
  `;
}

function closeAddressSuggestions() {
  addressSuggestionRequestId += 1;
  clearTimeout(addressSuggestionTimer);
  addressSuggestionController?.abort();
  addressSuggestionIndex = -1;
  addressSuggestionMessage = "";
  addressSuggestions = [];
  if (addressSuggestionsList) {
    addressSuggestionsList.hidden = true;
    addressSuggestionsList.innerHTML = "";
  }
  dashboardAddress?.setAttribute("aria-expanded", "false");
  dashboardAddress?.removeAttribute("aria-activedescendant");
}

function suggestionForAddress(value) {
  const normalized = String(value || "").trim();
  return addressSuggestions.find((suggestion) => suggestion.display_name === normalized) || null;
}

function applyAddressSuggestion(suggestion) {
  if (!suggestion) return;
  currentMapSite = {
    latitude: Number(suggestion.latitude),
    longitude: Number(suggestion.longitude),
    display_name: suggestion.display_name,
  };
  if (!Number.isFinite(currentMapSite.latitude) || !Number.isFinite(currentMapSite.longitude)) {
    return;
  }
  cancelActiveWorkflow();
  locationMode = "coordinates";
  coordinateOverride = { ...currentMapSite };
  designBuildingState = {
    latitude: currentMapSite.latitude,
    longitude: currentMapSite.longitude,
    display_name: currentMapSite.display_name,
    width_m: parseOptionalNumber(buildingWidthControl?.value),
    length_m: parseOptionalNumber(buildingLengthControl?.value),
    orientation_deg: nearestOrientation(parseOptionalNumber(orientationControl?.value) ?? 0),
    offset_east_m: 0,
    offset_north_m: 0,
    user_modified: false,
    position_modified: false,
  };
  saveDesignLocation(currentMapSite);
  renderMapCoordinates(currentMapSite);
  renderInitialMapFrame("Address located; run assessment when ready", { force: true });
  setWorkflowProgress(0, "Address located; run assessment when ready", "complete");
  updateReportAvailability();
}

function selectAddressSuggestion(suggestion) {
  cancelAddressResolution();
  if (dashboardAddress) dashboardAddress.value = suggestion.display_name;
  applyAddressSuggestion(suggestion);
  closeAddressSuggestions();
}

function invalidateWorkflowMap() {
  postWorkflowMapCommand("invalidate");
}

function postWorkflowMapCommand(action, payload = {}) {
  workflowMapFrame?.contentWindow?.postMessage({
    type: "openwind-map-command",
    action,
    payload,
  }, "*");
}

function nearestOrientation(value) {
  return orientationOptions.reduce((closest, option) =>
    Math.abs(option - value) < Math.abs(closest - value) ? option : closest
  , orientationOptions[0]);
}

function parseOptionalNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatOrientation(value) {
  return Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 2);
}

function renderSiteAnalysisProgress(siteAnalysis) {
  const input = siteAnalysis.input || {};
  const site = siteAnalysis.site || {};
  const resultAddress = String(input.address || "").trim();
  const currentAddress = String(dashboardAddress?.value || "").trim();
  const locationStillCurrent = !resultAddress || !currentAddress || resultAddress === currentAddress;
  if (
    locationStillCurrent
    && Number.isFinite(Number(site.latitude))
    && Number.isFinite(Number(site.longitude))
  ) {
    currentMapSite = {
      latitude: Number(site.latitude),
      longitude: Number(site.longitude),
      display_name: site.display_name || input.address || "Assessed site",
    };
    coordinateOverride = { ...currentMapSite };
    locationMode = "coordinates";
    saveDesignLocation(currentMapSite);
    renderMapCoordinates(currentMapSite);
  }
  if (!dashboardAddress?.value.trim() && input.address) {
    dashboardAddress.value = input.address;
  }
  siteInputSummary.innerHTML = `
    <div class="table-wrap">
      <table>
        <tbody>
          <tr><th>Address</th><td>${escapeHtml(input.address || site.display_name || "not supplied")}</td></tr>
          <tr><th>Latitude</th><td id="resolved-site-latitude">${formatNullableNumber(site.latitude, 6, "")}</td></tr>
          <tr><th>Longitude</th><td id="resolved-site-longitude">${formatNullableNumber(site.longitude, 6, "")}</td></tr>
          <tr><th>Ground elevation</th><td>${formatNullableNumber(site.ground_elevation_m, 2, "m")}</td></tr>
          <tr><th>Building height</th><td>${formatNullableNumber(input.building_height_m, 2, "m")}</td></tr>
        </tbody>
      </table>
    </div>
  `;
}

function renderWindInputsProgress(data) {
  renderWindInputs({
    wind_region_assessment: data.wind_region_assessment,
    regional_wind_speed_assessment: data.regional_wind_speed_assessment,
    direction_multiplier_assessment: data.direction_multiplier_assessment,
  });
  renderVrProgress(data.regional_wind_speed_assessment, data.wind_region_assessment);
  renderMdProgress(data.direction_multiplier_assessment);
  if (dashboardRegion) dashboardRegion.textContent = data.wind_region_assessment?.wind_region || "-";
}

function renderVrProgress(speed, region) {
  const section = document.getElementById(variableAnchors.VR);
  if (!section || !speed) return;
  replaceWorkflowCards(section, `
    <article class="workflow-card">
      <div class="table-wrap">
        <table>
          <tbody>
            <tr><th>Wind region</th><td>${escapeHtml(region?.wind_region || speed.wind_region || "-")}</td></tr>
            <tr><th>ARI</th><td>${escapeHtml(speed.ari_years || "-")} years</td></tr>
            <tr><th>VR,ult</th><td>${formatNullableNumber(speed.vr_ult, 1, "m/s")}</td></tr>
            <tr><th>VR,serv</th><td>${formatNullableNumber(speed.vr_serv, 1, "m/s")}</td></tr>
            <tr><th>Source</th><td>${escapeHtml(speed.selected_table || "Lookup source unavailable.")}</td></tr>
          </tbody>
        </table>
      </div>
    </article>
  `);
}

function renderMdProgress(md) {
  const section = document.getElementById(variableAnchors.Md);
  if (!section || !md) return;
  const byDirection = Object.fromEntries((md.directions || []).map((row) => [row.direction, row]));
  replaceWorkflowCards(section, `
    <article class="workflow-card">
      <div class="table-wrap md-standard-table">
        <table>
          <thead>
            <tr>
              <th>Wind region</th>
              ${directionOrder.map((direction) => `<th>${direction}</th>`).join("")}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>${escapeHtml(md.wind_region || "-")}</th>
              ${directionOrder.map((direction) => {
                const row = byDirection[direction];
                return `<td class="${row?.is_governing ? "governing-md-cell" : ""}">${row?.md === null || row?.md === undefined ? "manual" : Number(row.md).toFixed(2)}${row?.is_governing ? "<span class=\"muted\">governing</span>" : ""}</td>`;
              }).join("")}
            </tr>
          </tbody>
        </table>
      </div>
      <p class="note">Md values loaded from the selected region table. Selected values can be edited once directional variables are calculated.</p>
    </article>
  `);
}

function renderObstructionProgress(summary) {
  const section = document.getElementById(variableAnchors.Ms);
  if (!section) return;
  replaceWorkflowCards(section, `
    <article class="workflow-card">
      <div class="status-strip">
        <div>
          <span class="kicker">Obstructions</span>
          <strong>${escapeHtml(summary.total_obstructions ?? "0")}</strong>
          <span class="muted">found in inventory</span>
        </div>
        <div>
          <span class="kicker">Shielding sectors</span>
          <strong>${escapeHtml(summary.shielding_sectors ?? "0")}</strong>
          <span class="muted">prepared for Ms calculation</span>
        </div>
      </div>
      ${(summary.warnings || []).length ? `<div class="warning-list">${summary.warnings.map((warning) => `<p>${escapeHtml(warning)}</p>`).join("")}</div>` : ""}
    </article>
  `);
}

function renderTerrainProgress(terrain) {
  const section = document.getElementById(variableAnchors.Mzcat);
  if (!section) return;
  const directions = terrain.mzcat_assessment || [];
  replaceWorkflowCards(section, `
    <article class="workflow-card">
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Direction</th><th>Recommended TC</th><th>Mz,cat</th><th>Confidence</th></tr>
          </thead>
          <tbody>
            ${directions.map((row) => `
              <tr>
                <td>${escapeHtml(row.direction || "-")}</td>
                <td>${escapeHtml(row.recommended_terrain_category || row.final_terrain_category || "-")}</td>
                <td>${formatNullableNumber(row.recommended_mzcat ?? row.final_mzcat, 3, "")}</td>
                <td>${badge(row.confidence || "medium", row.confidence || "medium")}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      ${(terrain.warnings || []).length ? `<div class="warning-list">${terrain.warnings.map((warning) => `<p>${escapeHtml(warning)}</p>`).join("")}</div>` : ""}
    </article>
  `);
}

function replaceWorkflowCards(section, html) {
  section.querySelectorAll(".workflow-card").forEach((card) => card.remove());
  section.insertAdjacentHTML("beforeend", html);
}

function renderSiteInputs(workflow) {
  const input = workflow.input || {};
  const structureRows = [
    input.structure_class ? `<tr><th>Structure class</th><td>${escapeHtml(input.structure_class)}</td></tr>` : "",
    input.structure_orientation_deg !== null && input.structure_orientation_deg !== undefined ? `<tr><th>Orientation</th><td>${formatNullableNumber(input.structure_orientation_deg, 2, "deg")}</td></tr>` : "",
    input.roof_shape ? `<tr><th>Roof shape</th><td>${escapeHtml(input.roof_shape)}</td></tr>` : "",
    input.building_width_m !== null && input.building_width_m !== undefined ? `<tr><th>Width</th><td>${formatNullableNumber(input.building_width_m, 2, "m")}</td></tr>` : "",
    input.building_length_m !== null && input.building_length_m !== undefined ? `<tr><th>Length</th><td>${formatNullableNumber(input.building_length_m, 2, "m")}</td></tr>` : "",
    input.roof_pitch_deg !== null && input.roof_pitch_deg !== undefined ? `<tr><th>Roof pitch</th><td>${formatNullableNumber(input.roof_pitch_deg, 2, "deg")}</td></tr>` : "",
    input.average_height_m !== null && input.average_height_m !== undefined ? `<tr><th>Average height</th><td>${formatNullableNumber(input.average_height_m, 2, "m")}</td></tr>` : "",
    input.base_rl_m !== null && input.base_rl_m !== undefined ? `<tr><th>Base RL</th><td>${formatNullableNumber(input.base_rl_m, 2, "m")}</td></tr>` : "",
  ].join("");
  siteInputSummary.innerHTML = `
    <div class="table-wrap">
      <table>
        <tbody>
          <tr><th>Address</th><td>${escapeHtml(input.address || workflow.site?.display_name || "not supplied")}</td></tr>
          <tr><th>Latitude</th><td id="resolved-site-latitude">${formatNullableNumber(workflow.site?.latitude, 6, "")}</td></tr>
          <tr><th>Longitude</th><td id="resolved-site-longitude">${formatNullableNumber(workflow.site?.longitude, 6, "")}</td></tr>
          <tr><th>Elevation</th><td>${Number(workflow.site.ground_elevation_m).toFixed(2)} m</td></tr>
          <tr><th>Building height</th><td>${Number(input.building_height_m).toFixed(2)} m</td></tr>
          ${structureRows}
          <tr><th>Return period / importance level</th><td>${escapeHtml(input.importance_level || input.annual_exceedance_probability || "user input")}</td></tr>
        </tbody>
      </table>
    </div>
  `;
}

function renderWindInputs(workflow) {
  const region = workflow.wind_region_assessment;
  const speed = workflow.regional_wind_speed_assessment;
  const md = workflow.direction_multiplier_assessment;
  if (!region || !speed || !md) {
    windInputsSummary.innerHTML = "<p class=\"note\">Wind inputs were not generated.</p>";
    return;
  }
  windInputsSummary.innerHTML = `
    <div class="status-strip">
      <div>
        <span class="kicker">Wind region</span>
        <strong>${escapeHtml(region.wind_region)}${region.region_subclassification ? ` / ${escapeHtml(region.region_subclassification)}` : ""}</strong>
        <span class="muted">${region.near_boundary ? "Near boundary - review required" : "Matched GIS polygon"}</span>
      </div>
      <div>
        <span class="kicker">Return period</span>
        <strong>ARI ${Number(speed.ari_years)} years</strong>
        <span class="muted">${escapeHtml(speed.importance_level || "user-selected AEP")}</span>
      </div>
      <div>
        <span class="kicker">Confidence</span>
        ${badge(region.confidence, region.confidence)}
        <span class="muted">${escapeHtml(region.dataset_name || "dataset not configured")}</span>
      </div>
    </div>
  `;
}

function resetWorkflowSections() {
  currentWorkflow = null;
  currentWorkflowFingerprint = null;
  updateReportAvailability();
  if (terrainProfileFrame) {
    setIframeHtml(terrainProfileFrame, "<p>Run the assessment to display terrain profiles.</p>");
  }
  if (siteInputSummary) {
    siteInputSummary.innerHTML = "<p class=\"note\">Resolving site location and elevation...</p>";
  }
  if (windInputsSummary) {
    windInputsSummary.innerHTML = "<p class=\"note\">Waiting for wind-region and regional wind speed lookup...</p>";
  }
  if (workflowMapFrame) {
    clearIframeHtml(workflowMapFrame);
    if (locationMode === "coordinates" && coordinateOverride) {
      renderInitialMapFrame("Assessment running. The project map will replace this view.");
    } else {
      renderPendingMapFrame("Resolving the assessment address.");
    }
  }
  if (dashboardRegion) dashboardRegion.textContent = "-";
  if (dashboardGoverningDirection) dashboardGoverningDirection.textContent = "-";
  if (dashboardGoverningVsitb) dashboardGoverningVsitb.textContent = "Calculating";
  if (vsitbTable) {
    vsitbTable.innerHTML = "<tr><td colspan=\"7\">Waiting for directional variables.</td></tr>";
  }
  if (rawProvenance) {
    rawProvenance.innerHTML = "<p class=\"note\">Waiting for calculation sources and warnings...</p>";
  }
  variableOrder.forEach((variable) => {
    const section = document.getElementById(variableAnchors[variable]);
    if (section && variable !== "Vsitb") {
      section.querySelectorAll(".workflow-card").forEach((card) => card.remove());
      section.insertAdjacentHTML("beforeend", "<p class=\"note workflow-card\">Waiting for this workflow step...</p>");
    }
  });
}

function groupVariables(variables) {
  return variables.reduce((groups, item) => {
    groups[item.variable] = groups[item.variable] || [];
    groups[item.variable].push(item);
    return groups;
  }, {});
}

function renderVariableSection(variable, rows) {
  const section = document.getElementById(variableAnchors[variable]);
  if (!section) return;
  section.querySelectorAll(".workflow-card").forEach((card) => card.remove());
  const table = variable === "Md"
    ? mdWorkflowTable(rows)
    : variable === "VR"
      ? sourceWorkflowTable(rows)
      : workflowTable(rows);
  section.insertAdjacentHTML("beforeend", `
    <article class="workflow-card">
      ${table}
    </article>
  `);
  attachOverrideHandlers(section);
}

function workflowTable(rows) {
  if (!rows.length) return "<p class=\"note\">No workflow results generated.</p>";
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Direction</th>
            <th>Calculated</th>
            <th>Confidence</th>
            <th>Override (optional)</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => variableRow(row)).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function sourceWorkflowTable(rows) {
  if (!rows.length) return "<p class=\"note\">No workflow results generated.</p>";
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Value</th>
            <th>Calculated</th>
            <th>Confidence</th>
            <th>Override (optional)</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => variableRow(row)).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function mdWorkflowTable(rows) {
  if (!rows.length) return "<p class=\"note\">No Md rows generated.</p>";
  const byDirection = Object.fromEntries(rows.map((row) => [row.direction, row]));
  const highest = Math.max(
    ...rows
      .map((row) => row.recommended_value)
      .filter((value) => value !== null && value !== undefined)
      .map(Number),
  );
  return `
    <div class="table-wrap md-standard-table">
      <table>
        <thead>
          <tr>
            <th>Wind region</th>
            ${directionOrder.map((direction) => `<th>${direction}</th>`).join("")}
          </tr>
        </thead>
        <tbody>
          <tr>
            <th>${escapeHtml(currentWorkflow?.direction_multiplier_assessment?.wind_region || currentWorkflow?.wind_region_assessment?.wind_region || "-")}</th>
            ${directionOrder.map((direction) => mdStandardCell(byDirection[direction], highest)).join("")}
          </tr>
        </tbody>
      </table>
    </div>
    <p class="note">Governing direction is the highest Md in the selected table row.</p>
  `;
}

function mdStandardCell(row, highest) {
  if (!row || row.recommended_value === null || row.recommended_value === undefined) {
    return "<td>manual input required</td>";
  }
  const value = Number(row.recommended_value);
  const isGoverning = Number.isFinite(highest) && value === highest;
  return `<td class="${isGoverning ? "governing-md-cell" : ""}">${value.toFixed(2)}${isGoverning ? "<span class=\"muted\">governing</span>" : ""}</td>`;
}

function variableRow(row) {
  return `
    <tr>
      <td>${escapeHtml(row.direction || "all")}</td>
      <td>${recommendedCell(row)}</td>
      <td>${badge(row.confidence, row.confidence)}</td>
      <td>${inlineAssessmentValueCell(row)}</td>
    </tr>
  `;
}

function visibleWarnings(warnings) {
  return (warnings || []).filter((warning) =>
    !hiddenWindInputWarningPatterns.some((hidden) => hidden.test(String(warning)))
  );
}

function warningListHtml(warnings) {
  return warnings.length
    ? `<div class="warning-list">${warnings.map((warning) => `<p>${escapeHtml(warning)}</p>`).join("")}</div>`
    : "";
}

function renderVsitbTable(rows) {
  if (!rows.length) {
    vsitbTable.innerHTML = "<tr><td colspan=\"7\">No Vsit,b rows generated.</td></tr>";
    return;
  }
  vsitbTable.innerHTML = rows.map((row) => `
    <tr class="${row.is_governing ? "governing-row" : ""}">
      <td>${row.direction}${row.is_governing ? "<span class=\"muted\">governing direction</span>" : ""}</td>
      <td>${formatWorkflowValue(row.vr, "m/s")}</td>
      <td>${formatWorkflowValue(row.md, "")}</td>
      <td>${formatWorkflowValue(row.mzcat, "")}</td>
      <td>${formatWorkflowValue(row.ms, "")}</td>
      <td>${formatWorkflowValue(row.mt, "")}</td>
      <td>${row.final_vsitb === null || row.final_vsitb === undefined ? "blocked" : `${row.final_vsitb.toFixed(3)} m/s${row.is_governing ? "<span class=\"muted\">governing Vsit,b</span>" : ""}`}</td>
    </tr>
  `).join("");
}

function renderRawProvenance(variables) {
  if (!rawProvenance) return;
  const uniqueWarnings = [...new Set(
    variables.flatMap((row) => visibleWarnings(row.warnings || [])),
  )];
  const byVariable = variableOrder
    .filter((variable) => variable !== "Vsitb")
    .map((variable) => {
      const rows = variables.filter((row) => row.variable === variable);
      if (!rows.length) return null;
      return {
        variable,
        source: [...new Set(rows.map((row) => row.source_reference).filter(Boolean))].join(" "),
        method: rows.find((row) => row.formula_basis)?.formula_basis || "Engineer review required.",
      };
    })
    .filter(Boolean);
  rawProvenance.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Variable</th><th>Source</th><th>Method</th></tr></thead>
        <tbody>
          ${byVariable.map((row) => `
            <tr>
              <th>${escapeHtml(row.variable)}</th>
              <td>${escapeHtml(row.source || "Engineer review required.")}</td>
              <td>${escapeHtml(row.method)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
    ${warningListHtml(uniqueWarnings)}
  `;
}

function inlineAssessmentValueCell(row) {
  const key = overrideKey(row.variable, row.direction);
  const existing = overrideForKey(key);
  const finalValue = existing?.override_value ?? row.override_value ?? "";
  const placeholder = "optional override";
  const reason = existing?.reason || row.override_reason || "";
  return `
    <div class="inline-override" data-key="${key}">
      <input data-override-field="override_value" data-key="${key}" type="number" step="0.001" value="${finalValue}" placeholder="${escapeHtml(placeholder)}" aria-label="Optional ${escapeHtml(row.variable)} override for ${escapeHtml(row.direction || "all directions")}" />
      <input data-override-field="reason" data-key="${key}" value="${escapeHtml(reason)}" placeholder="reason if edited" aria-label="Override reason" />
      <button type="button" data-override-action="apply" data-key="${key}">Save</button>
      ${row.is_overridden || existing ? `<button type="button" data-override-action="clear" data-key="${key}">Reset</button>` : ""}
      ${row.is_overridden ? `<span class="badge badge-warn">override</span>` : ""}
    </div>
  `;
}

function recommendedCell(row) {
  const value = formatWorkflowValue(row.recommended_value, row.unit);
  return row.recommended_label
    ? `${escapeHtml(row.recommended_label)}<span class="muted">${value}</span>`
    : value;
}

function attachOverrideHandlers(scope) {
  scope.querySelectorAll("button[data-override-action]").forEach((button) => {
    button.addEventListener("click", () => updateOverride(button));
  });
}

async function updateOverride(button) {
  const key = button.dataset.key;
  const [variable, directionValue] = key.split(":");
  const direction = directionValue || null;
  if (button.dataset.overrideAction === "clear") {
    workflowOverrides = workflowOverrides.filter((item) =>
      !(item.variable === variable && (item.direction || null) === direction)
    );
    await runWorkflow();
    return;
  }
  const panel = button.closest(".inline-override") || button.closest(".override-panel");
  const valueInput = panel.querySelector("[data-override-field='override_value']");
  const reasonInput = panel.querySelector("[data-override-field='reason']");
  const overrideValue = valueInput.value === "" ? null : Number(valueInput.value);
  const reason = reasonInput.value.trim() || "Inline assessment value edited in Site Wind Assessment.";
  if (overrideValue === null || !Number.isFinite(overrideValue) || overrideValue <= 0) {
    workflowSummary.textContent = "Override value must be a number greater than zero.";
    return;
  }
  workflowOverrides = workflowOverrides.filter((item) =>
    !(item.variable === variable && (item.direction || null) === direction)
  );
  workflowOverrides.push({
    variable,
    direction,
    override_value: overrideValue,
    reason,
  });
  await runWorkflow();
}

function overrideForKey(key) {
  const [variable, directionValue] = key.split(":");
  const direction = directionValue || null;
  return workflowOverrides.find((item) =>
    item.variable === variable && (item.direction || null) === direction
  );
}

function overrideKey(variable, direction) {
  return `${variable}:${direction || ""}`;
}

function formatWorkflowValue(value, unit) {
  if (value === null || value === undefined) return "review required";
  return `${Number(value).toFixed(3)}${unit ? ` ${unit}` : ""}`;
}

function formatNullableNumber(value, decimals, unit) {
  if (value === null || value === undefined) return "manual input required";
  return `${Number(value).toFixed(decimals)}${unit ? ` ${unit}` : ""}`;
}

function badge(status, text) {
  const classes = {
    high: "badge-pass",
    medium: "badge-warn",
    low: "badge-fail",
    pass: "badge-pass",
    warning: "badge-warn",
    fail: "badge-fail",
    accepted: "badge-pass",
    overridden: "badge-warn",
    unreviewed: "badge-neutral",
    calculated: "badge-pass",
    blocked: "badge-fail",
    draft: "badge-neutral",
    reviewed: "badge-warn",
  };
  return `<span class="badge ${classes[status] || "badge-neutral"}">${escapeHtml(text)}</span>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#039;");
}

function jsonForInlineScript(value) {
  return JSON.stringify(value)
    .replaceAll("<", "\\u003c")
    .replaceAll(">", "\\u003e")
    .replaceAll("&", "\\u0026");
}
