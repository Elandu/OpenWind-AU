const workflowForm = document.getElementById("workflow-form");
const workflowSummary = document.getElementById("workflow-summary");
const siteInputSummary = document.getElementById("site-input-summary");
const windInputsSummary = document.getElementById("wind-inputs-summary");
const workflowMapFrame = document.getElementById("workflow-map-frame");
const terrainProfileFrame = document.getElementById("terrain-profile-frame");
const vsitbTable = document.getElementById("vsitb-table");
const vdesTable = document.getElementById("vdes-table");
const directionalEditRestrictions = document.getElementById("directional-edit-restrictions");
const rawProvenance = document.getElementById("raw-provenance");
const rawDataPanel = document.getElementById("workspace-panel-raw-data");
const rawDataSave = document.getElementById("raw-data-save");
const rawDataUseCalculated = document.getElementById("raw-data-use-calculated");
const rawDataDiscard = document.getElementById("raw-data-discard");
const rawDataEditReason = document.getElementById("raw-data-edit-reason");
const rawDataEditStatus = document.getElementById("raw-data-edit-status");
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
const buildingHeightControl = document.getElementById("building_height_m");
const orientationControl = document.getElementById("structure_orientation_deg");
const orientationReadout = document.getElementById("orientation-readout");
const mapCoordinateReadout = document.getElementById("map-coordinate-readout");
const buildingWidthControl = document.getElementById("building_width_m");
const buildingLengthControl = document.getElementById("building_length_m");
const sampleIntervalControl = document.getElementById("sample_interval_m");
const obstructionRadiusControl = document.getElementById("obstruction_radius_m");
const defaultStoreyHeightControl = document.getElementById("default_storey_height_m");
const roofPitchControl = document.getElementById("roof_pitch_deg");
const averageRoofHeightControl = document.getElementById("average_roof_height_m");
const baseRlControl = document.getElementById("base_rl_m");
const assessmentStatusControl = document.getElementById("assessment_status");
const reviewMetadataFields = document.getElementById("review-metadata-fields");
const reviewedByControl = document.getElementById("reviewed_by");
const engineerNotesControl = document.getElementById("engineer_notes");
const addressSuggestionsList = document.getElementById("dashboard-address-suggestions");
const mapNudgeButtons = Array.from(document.querySelectorAll("[data-map-nudge]"));
const windDirectionMultiplierCaseControl = document.getElementById("wind_direction_multiplier_case");
const DESIGN_LOCATION_STORAGE_KEY = "openwindDesignBuildingLocation";
const PROJECT_NUMBER_STORAGE_KEY = "openwindProjectNumber";
const WIND_DIRECTION_MULTIPLIER_CASE_STORAGE_KEY = "openwindWindDirectionMultiplierCase";
const DESIGN_LOCATION_STORAGE_VERSION = 1;
const SUPPORTED_LATITUDE_RANGE = [-44.5, -9.0];
const SUPPORTED_LONGITUDE_RANGE = [112.0, 154.5];

const orientationOptions = [0, 45, 90, 135, 180, 225, 270, 315];
const directionOrder = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const variableOrder = ["VR", "Mc", "Md", "Mzcat", "Ms", "Mt", "Vsitb"];
const variableAnchors = {
  VR: "wind-region-vr",
  Md: "wind-direction-md",
  Mzcat: "terrain-category-mzcat",
  Ms: "shielding-ms",
  Mt: "topographic-mt",
  Mc: "climate-change-mc",
  Vsitb: "vsitb-summary",
};
const workflowOverrideMaximums = Object.freeze({
  VR: 200,
  Md: 2,
  Mzcat: 10,
  Ms: 1,
  Mt: 10,
  Vsitb: 500,
});
const workflowOverrideReasonMaximum = 2000;
const rawDataDisplayDecimals = 6;
const rawDataDisplayTolerance = 0.5 * (10 ** -rawDataDisplayDecimals);

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
let rawDataEditorDirty = false;
let rawDataEditorSaving = false;
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
let designLocationProjectNumber = "";
let locationMode = "address";
let currentMapSite = {
  latitude: -33.8688,
  longitude: 151.2093,
  display_name: "Sydney CBD",
};

restoreWindDirectionMultiplierCase();
windDirectionMultiplierCaseControl?.addEventListener("change", persistWindDirectionMultiplierCase);

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
    const projectNumber = dashboardProjectNumber.value.trim();
    if (locationMode === "coordinates" && coordinateOverride && !designLocationProjectNumber) {
      const persistence = saveDesignLocation(coordinateOverride);
      cancelActiveWorkflow();
      updateReportAvailability();
      if (persistence.saved) {
        setWorkflowProgress(
          100,
          "Current building location saved to the new project number; rerun the assessment when ready",
          "complete",
        );
      } else if (persistence.reason === "storage-unavailable") {
        setWorkflowProgress(
          100,
          "Project number updated, but browser storage is unavailable; the location remains session-only",
          "complete",
        );
      }
      return;
    }
    if (projectNumber === designLocationProjectNumber) {
      cancelActiveWorkflow();
      updateReportAvailability();
      return;
    }
    invalidateDesignLocationForProject();
  });
  dashboardProjectNumber.addEventListener("change", () => {
    const projectNumber = dashboardProjectNumber.value.trim();
    if (
      projectNumber
      && locationMode === "coordinates"
      && coordinateOverride
      && !designLocationProjectNumber
    ) {
      designLocationProjectNumber = projectNumber;
      saveDesignLocation(coordinateOverride);
    }
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

mapNudgeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (locationMode !== "coordinates" || !coordinateOverride) return;
    postWorkflowMapCommand("nudge", {
      east_m: Number(button.dataset.mapNudgeEast || 0),
      north_m: Number(button.dataset.mapNudgeNorth || 0),
    });
  });
});

workflowForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (document.activeElement === dashboardAddress) {
    await zoomMapToAddress();
    return;
  }
  await runWorkflow();
});

workflowForm.addEventListener("input", () => {
  validateWorkflowInputs();
  cancelActiveWorkflow();
  updateReportAvailability();
});

workflowForm.addEventListener("change", () => {
  validateWorkflowInputs();
  cancelActiveWorkflow();
  updateReportAvailability();
});

rawDataPanel?.addEventListener("input", (event) => {
  if (event.target?.dataset?.rawValue === undefined) return;
  refreshRawDataEditorState();
});

rawDataSave?.addEventListener("click", saveRawDataEdits);
rawDataUseCalculated?.addEventListener("click", stageCalculatedRawDataValues);
rawDataDiscard?.addEventListener("click", discardRawDataEdits);

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
updateMapNudgeAvailability();

workflowMapFrame?.addEventListener("load", () => {
  syncCurrentMapSiteToFrame();
  syncDesignBuildingOverlay();
  invalidateWorkflowMap();
});

[orientationControl, buildingWidthControl, buildingLengthControl].forEach((control) => {
  control?.addEventListener("input", syncDesignBuildingOverlay);
  control?.addEventListener("change", syncDesignBuildingOverlay);
});

validateWorkflowInputs();

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
  workflowReport.disabled = true;
  if (reportStatus) reportStatus.textContent = "Generating HTML from the completed assessment...";
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
    if (reportWindow) {
      reportWindow.location.replace(reportUrl);
    } else {
      const link = document.createElement("a");
      link.href = reportUrl;
      link.download = "openwind-au-site-wind-assessment.html";
      document.body.appendChild(link);
      link.click();
      link.remove();
    }
    if (reportStatus) {
      reportStatus.textContent = "HTML report generated. Use the report window or download to save it.";
    }
    setTimeout(() => URL.revokeObjectURL(reportUrl), 300000);
  } catch (error) {
    reportWindow?.close();
    if (error.name === "AbortError" || !reportRequestIsCurrent(requestId, reportFingerprint)) {
      return;
    }
    if (reportStatus) reportStatus.textContent = `HTML report failed: ${error.message}`;
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

async function runWorkflow(options = {}) {
  syncReviewControls();
  const validationMessages = validateWorkflowInputs();
  const formIsValid = workflowForm.reportValidity();
  if (validationMessages.length || !formIsValid) {
    const detail = validationMessages[0] || "Complete the highlighted required assessment inputs.";
    setWorkflowProgress(0, `Check assessment inputs: ${detail}`, "error");
    workflowSummary.textContent = validationMessages.length
      ? `Assessment inputs need attention: ${validationMessages.join(" ")}`
      : "Complete the highlighted required assessment inputs before running the assessment.";
    return false;
  }
  if (options.workflowOverrides === undefined) {
    removeNowRestrictedWorkflowOverrides();
  }
  cancelAddressResolution();
  closeAddressSuggestions();
  cancelActiveWorkflow();
  const runId = workflowRunId;
  const controller = new AbortController();
  activeWorkflowController = controller;
  const requestPayload = workflowPayload(options.workflowOverrides ?? workflowOverrides);
  activeWorkflowPayload = requestPayload;
  setWorkflowProgress(4, "Resolving site location and elevation", "running");
  workflowSummary.textContent = "Resolving site location and elevation...";
  resetWorkflowSections();
  try {
    await runWorkflowStream(requestPayload, runId, controller.signal);
    if (runId !== workflowRunId) return false;
    if (!currentWorkflow || !currentWorkflowFingerprint) {
      renderWorkflowFailure(new Error("Workflow stream ended without a completed assessment result."));
      return false;
    }
    return true;
  } catch (error) {
    if (error.name === "AbortError" || runId !== workflowRunId) return false;
    if (error.allowWorkflowFallback) {
      return await runWorkflowFallback(error, requestPayload, runId, controller.signal);
    } else {
      renderWorkflowFailure(error);
      return false;
    }
  } finally {
    if (runId === workflowRunId) activeWorkflowController = null;
  }
}

function numberControlError(control, label, constraints = {}) {
  if (!control) return "";
  const raw = String(control.value ?? "").trim();
  if (!raw) return constraints.required ? `${label} is required.` : "";
  const value = Number(raw);
  if (!Number.isFinite(value)) return `${label} must be a finite number.`;
  if (constraints.integer && !Number.isInteger(value)) {
    return `${label} must be a whole number.`;
  }
  if (constraints.minExclusive !== undefined && value <= constraints.minExclusive) {
    return `${label} must be greater than ${constraints.minExclusive}.`;
  }
  if (constraints.min !== undefined && value < constraints.min) {
    return `${label} must be at least ${constraints.min}.`;
  }
  if (constraints.maxExclusive !== undefined && value >= constraints.maxExclusive) {
    return `${label} must be less than ${constraints.maxExclusive}.`;
  }
  if (constraints.max !== undefined && value > constraints.max) {
    return `${label} must not exceed ${constraints.max}.`;
  }
  return "";
}

function validateWorkflowInputs() {
  const controls = [
    [
      buildingHeightControl,
      numberControlError(buildingHeightControl, "Building height", {
        required: true,
        minExclusive: 0,
        max: 200,
      }),
    ],
    [
      orientationControl,
      numberControlError(orientationControl, "Orientation", {
        required: true,
        min: 0,
        maxExclusive: 360,
      }),
    ],
    [
      buildingWidthControl,
      numberControlError(buildingWidthControl, "Building breadth", {
        minExclusive: 0,
        max: 5000,
      }),
    ],
    [
      buildingLengthControl,
      numberControlError(buildingLengthControl, "Building depth", {
        minExclusive: 0,
        max: 5000,
      }),
    ],
    [
      sampleIntervalControl,
      numberControlError(sampleIntervalControl, "Sample interval", {
        required: true,
        min: 5,
        max: 500,
      }),
    ],
    [
      obstructionRadiusControl,
      numberControlError(obstructionRadiusControl, "Obstruction radius", {
        required: true,
        integer: true,
        min: 50,
        max: 4000,
      }),
    ],
    [
      defaultStoreyHeightControl,
      numberControlError(defaultStoreyHeightControl, "Storey height assumption", {
        minExclusive: 0,
        max: 6,
      }),
    ],
    [
      roofPitchControl,
      numberControlError(roofPitchControl, "Roof pitch", {
        min: 0,
        max: 90,
      }),
    ],
    [
      averageRoofHeightControl,
      numberControlError(averageRoofHeightControl, "Average roof height", {
        minExclusive: 0,
        max: 200,
      }),
    ],
    [
      baseRlControl,
      numberControlError(baseRlControl, "Base RL", {
        min: -500,
        max: 10000,
      }),
    ],
  ];
  const errorByControl = new Map(controls.map(([control, error]) => [control, error]));
  const widthPresent = String(buildingWidthControl?.value ?? "").trim() !== "";
  const lengthPresent = String(buildingLengthControl?.value ?? "").trim() !== "";
  if (widthPresent !== lengthPresent) {
    const pairMessage = "Enter both building breadth and building depth, or leave both blank.";
    if (!errorByControl.get(buildingWidthControl)) {
      errorByControl.set(buildingWidthControl, pairMessage);
    }
    if (!errorByControl.get(buildingLengthControl)) {
      errorByControl.set(buildingLengthControl, pairMessage);
    }
  }
  const buildingHeight = parseOptionalNumber(buildingHeightControl?.value);
  const averageRoofHeight = parseOptionalNumber(averageRoofHeightControl?.value);
  if (
    buildingHeight !== null
    && averageRoofHeight !== null
    && averageRoofHeight > buildingHeight
    && !errorByControl.get(averageRoofHeightControl)
  ) {
    errorByControl.set(
      averageRoofHeightControl,
      "Average roof height must not exceed the overall building height.",
    );
  }
  const referenceHeight = averageRoofHeight ?? buildingHeight;
  const obstructionRadius = parseOptionalNumber(obstructionRadiusControl?.value);
  if (
    referenceHeight !== null
    && referenceHeight <= 25
    && obstructionRadius !== null
    && obstructionRadius < 20 * referenceHeight
    && !errorByControl.get(obstructionRadiusControl)
  ) {
    errorByControl.set(
      obstructionRadiusControl,
      `Obstruction radius must be at least ${(20 * referenceHeight).toFixed(0)} m `
        + "to cover the full 20h shielding sector.",
    );
  }
  for (const [control] of controls) {
    control?.setCustomValidity(errorByControl.get(control) || "");
  }
  return [...new Set([...errorByControl.values()].filter(Boolean))];
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
    streamError.status = response.status;
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
  if (event.stage === "error" && currentWorkflow && currentWorkflowFingerprint) {
    const mapMessage = formatApiError(event.label || "Combined map rendering failed");
    setWorkflowProgress(100, "Assessment complete; combined map unavailable", "complete");
    workflowSummary.textContent = `Combined map unavailable: ${mapMessage}\n${workflowSummary.textContent}`;
    if (workflowMapFrame) {
      setIframeHtml(workflowMapFrame, `<p>Combined map failed: ${escapeHtml(mapMessage)}</p>`);
    }
    updateReportAvailability();
    renderTerrainProfileGraph(
      resolvedSiteRequestPayload(requestPayload, currentWorkflow),
      { runId, signal },
    );
    return;
  }
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
    activeWorkflowPayload = resolvedSiteRequestPayload(requestPayload, currentWorkflow);
    updateReportAvailability();
  }
  if (event.data?.map_html && workflowMapFrame) {
    setIframeHtml(workflowMapFrame, event.data.map_html);
    setTimeout(() => {
      if (runId === workflowRunId) syncDesignBuildingOverlay();
    }, 80);
    renderTerrainProfileGraph(
      resolvedSiteRequestPayload(requestPayload, currentWorkflow),
      { runId, signal },
    );
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
    if (runId !== workflowRunId) return false;
    currentWorkflow = await response.json();
    renderSiteAnalysisProgress({
      input: currentWorkflow.input,
      site: currentWorkflow.site,
    });
    renderWorkflow(currentWorkflow);
    currentWorkflowFingerprint = acceptedWorkflowFingerprint(requestPayload, currentWorkflow);
    activeWorkflowPayload = resolvedSiteRequestPayload(requestPayload, currentWorkflow);
    updateReportAvailability();
    setWorkflowProgress(78, "Rendering combined map layers", "running");
    const mapRendered = await renderWorkflowMap(activeWorkflowPayload, { runId, signal });
    await renderTerrainProfileGraph(activeWorkflowPayload, { runId, signal });
    if (runId !== workflowRunId) return false;
    setWorkflowProgress(
      100,
      mapRendered ? "Assessment complete" : "Assessment complete; combined map unavailable",
      "complete",
    );
    return true;
  } catch (fallbackError) {
    if (fallbackError.name === "AbortError" || runId !== workflowRunId) return false;
    renderWorkflowFailure(fallbackError.message ? fallbackError : originalError);
    return false;
  }
}

function workflowPayload(overrides = workflowOverrides) {
  const data = new FormData(workflowForm);
  const optionalNumber = (name) => {
    const value = data.get(name);
    return value === null || value === "" ? null : Number(value);
  };
  const requiredNumber = (name) => {
    const value = data.get(name);
    return value === null || String(value).trim() === "" ? null : Number(value);
  };
  const payload = {
    address: data.get("address") || null,
    project_number: dashboardProjectNumber?.value.trim() || null,
    building_height_m: Number(data.get("building_height_m")),
    radius_m: Number(data.get("radius_m")),
    sample_interval_m: requiredNumber("sample_interval_m"),
    obstruction_radius_m: Number(data.get("obstruction_radius_m") || 500),
    default_storey_height_m: Number(data.get("default_storey_height_m") || 3),
    annual_exceedance_probability: String(
      data.get("annual_exceedance_probability") ?? "",
    ).trim(),
    wind_direction_multiplier_case: data.get("wind_direction_multiplier_case") || "main_structure",
    importance_level: data.get("importance_level") || null,
    structure_class: data.get("structure_class") || null,
    structure_orientation_deg: optionalNumber("structure_orientation_deg"),
    roof_shape: data.get("roof_shape") || null,
    building_width_m: optionalNumber("building_width_m"),
    building_length_m: optionalNumber("building_length_m"),
    roof_pitch_deg: optionalNumber("roof_pitch_deg"),
    average_roof_height_m: optionalNumber("average_roof_height_m"),
    base_rl_m: optionalNumber("base_rl_m"),
    assessment_status: data.get("assessment_status") || "draft",
    mzcat_recommendation_mode: "conservative",
    workflow_overrides: overrides,
  };
  if (payload.assessment_status === "reviewed") {
    payload.reviewed_by = String(data.get("reviewed_by") || "").trim();
    payload.engineer_notes = String(data.get("engineer_notes") || "").trim();
  }
  if (locationMode === "coordinates" && coordinateOverride) {
    payload.latitude = coordinateOverride.latitude;
    payload.longitude = coordinateOverride.longitude;
    payload.site_label = payload.address || coordinateOverride.display_name || null;
    delete payload.address;
  }
  if (!payload.address) delete payload.address;
  if (!payload.site_label) delete payload.site_label;
  if (!payload.project_number) delete payload.project_number;
  if (payload.importance_level === null) delete payload.importance_level;
  [
    "structure_class",
    "structure_orientation_deg",
    "roof_shape",
    "building_width_m",
    "building_length_m",
    "roof_pitch_deg",
    "average_roof_height_m",
    "base_rl_m",
  ].forEach((key) => {
    if (payload[key] === null || Number.isNaN(payload[key])) delete payload[key];
  });
  return payload;
}

function resolvedSiteRequestPayload(requestPayload, workflow = null) {
  const payload = { ...(requestPayload || {}) };
  const payloadHasCoordinates = hasSupportedSiteCoordinates(payload);
  const workflowHasCoordinates = hasSupportedSiteCoordinates(workflow?.site);
  const overrideHasCoordinates = (
    locationMode === "coordinates"
    && hasSupportedSiteCoordinates(coordinateOverride)
  );
  const site = payloadHasCoordinates
    ? payload
    : workflowHasCoordinates
      ? workflow.site
      : overrideHasCoordinates
        ? coordinateOverride
        : null;
  if (!site) return payload;
  const originalAddress = String(payload.address || "").trim();
  payload.latitude = Number(site.latitude);
  payload.longitude = Number(site.longitude);
  payload.site_label = (
    payload.site_label
    || originalAddress
    || workflow?.site?.display_name
    || coordinateOverride?.display_name
    || "Assessed site"
  );
  delete payload.address;
  return payload;
}

function hasSupportedSiteCoordinates(site) {
  const rawLatitude = site?.latitude;
  const rawLongitude = site?.longitude;
  if (
    rawLatitude === null
    || rawLatitude === undefined
    || rawLatitude === ""
    || rawLongitude === null
    || rawLongitude === undefined
    || rawLongitude === ""
  ) {
    return false;
  }
  const latitude = Number(rawLatitude);
  const longitude = Number(rawLongitude);
  return (
    Number.isFinite(latitude)
    && Number.isFinite(longitude)
    && latitude >= SUPPORTED_LATITUDE_RANGE[0]
    && latitude <= SUPPORTED_LATITUDE_RANGE[1]
    && longitude >= SUPPORTED_LONGITUDE_RANGE[0]
    && longitude <= SUPPORTED_LONGITUDE_RANGE[1]
  );
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

function restoreWindDirectionMultiplierCase() {
  if (!windDirectionMultiplierCaseControl) return;
  try {
    const savedValue = localStorage.getItem(WIND_DIRECTION_MULTIPLIER_CASE_STORAGE_KEY);
    const allowedValues = Array.from(windDirectionMultiplierCaseControl.options || [])
      .map((option) => option.value);
    if (allowedValues.includes(savedValue)) windDirectionMultiplierCaseControl.value = savedValue;
  } catch (_error) {
    // Browser storage is optional; the visible default remains main structure.
  }
}

function persistWindDirectionMultiplierCase() {
  try {
    localStorage.setItem(
      WIND_DIRECTION_MULTIPLIER_CASE_STORAGE_KEY,
      windDirectionMultiplierCaseControl?.value || "main_structure",
    );
  } catch (_error) {
    // The selection still participates in the current workflow request.
  }
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
    acceptedPayload.site_label = acceptedPayload.address || workflow.site.display_name || null;
    delete acceptedPayload.address;
    if (!acceptedPayload.site_label) delete acceptedPayload.site_label;
  }
  return JSON.stringify(acceptedPayload);
}

function completedAssessmentMatchesInputs() {
  return Boolean(
    currentWorkflow
    && currentWorkflowFingerprint
    && currentWorkflowFingerprint === assessmentFingerprint()
  );
}

function assessmentIsCurrent() {
  return completedAssessmentMatchesInputs() && !rawDataEditorDirty && !rawDataEditorSaving;
}

function updateReportAvailability() {
  const isCurrent = assessmentIsCurrent();
  if (workflowPdf) workflowPdf.disabled = !isCurrent;
  if (workflowReport) workflowReport.disabled = !isCurrent;
  if (!reportStatus) return;
  if (currentWorkflow && rawDataEditorDirty) {
    reportStatus.textContent = "Raw Data has unsaved changes. Save or restore the values before generating reports.";
  } else if (currentWorkflow && !isCurrent) {
    reportStatus.textContent = "Inputs changed. Run the assessment again before generating reports.";
  } else if (
    isCurrent
    && !/\b(?:generating|generated|failed)\b/i.test(reportStatus.textContent)
  ) {
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
  const label = Number(error?.status) === 422
    ? "Assessment inputs need attention"
    : "Assessment failed";
  setWorkflowProgress(100, label, "error");
  workflowSummary.textContent = `Workflow failed: ${message}`;
  vsitbTable.innerHTML = "<tr><td colspan=\"6\">Workflow failed.</td></tr>";
  if (vdesTable) {
    vdesTable.innerHTML = "<tr><td colspan=\"6\">Workflow failed.</td></tr>";
  }
  currentWorkflow = null;
  currentWorkflowFingerprint = null;
  rawDataEditorDirty = false;
  rawDataEditorSaving = false;
  setRawDataEditorAvailability(false, "Assessment failed; no Raw Data changes were saved.");
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
    const requestError = new Error(formatApiError(error.detail || response.statusText));
    requestError.status = response.status;
    throw requestError;
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
    vdes_status: (workflow.design_wind_speeds || []).map((row) => ({
      face: row.face,
      theta_deg: row.theta_deg,
      beta_deg: row.beta_deg,
      vdes_theta_mps: row.vdes_theta_mps,
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
  renderVsitbTable(workflow.directional_vsitb || [], grouped);
  renderVdesTable(workflow.design_wind_speeds || []);
  renderRawProvenance(workflow.variables || [], workflow.warnings || []);
  setRawDataEditorAvailability(
    true,
    workflowOverrides.length
      ? `${workflowOverrides.length} saved edited value${workflowOverrides.length === 1 ? "" : "s"}.`
      : "All editable values currently match their calculated values.",
  );
}

function renderDashboardHeader(workflow) {
  if (dashboardRegion) dashboardRegion.textContent = workflow.wind_region_assessment?.wind_region || "-";
  if (dashboardGoverningDirection) {
    const governingDirections = Array.isArray(workflow.governing_directions)
      ? workflow.governing_directions.filter(Boolean)
      : [];
    dashboardGoverningDirection.textContent = governingDirections.length
      ? governingDirections.join(", ")
      : workflow.governing_direction || "-";
  }
  if (dashboardGoverningVsitb) {
    dashboardGoverningVsitb.textContent = workflow.governing_vsitb === null || workflow.governing_vsitb === undefined
      ? "Review required"
      : `${Number(workflow.governing_vsitb).toFixed(3)} m/s`;
  }
}

async function renderWorkflowMap(
  requestPayload = resolvedSiteRequestPayload(workflowPayload()),
  options = {},
) {
  if (!workflowMapFrame) return true;
  renderInitialMapFrame("Rendering project site map...");
  try {
    const response = await postJson(
      "/api/wind-workflow/map",
      resolvedSiteRequestPayload(requestPayload),
      options,
    );
    const html = await response.text();
    if (options.runId && options.runId !== workflowRunId) return false;
    setIframeHtml(workflowMapFrame, html);
    setTimeout(syncDesignBuildingOverlay, 80);
    setTimeout(invalidateWorkflowMap, 140);
    return true;
  } catch (error) {
    if (error.name === "AbortError" || (options.runId && options.runId !== workflowRunId)) {
      return false;
    }
    setIframeHtml(workflowMapFrame, `<p>Combined map failed: ${escapeHtml(error.message)}</p>`);
    return false;
  }
}

async function renderTerrainProfileGraph(
  requestPayload = resolvedSiteRequestPayload(workflowPayload()),
  options = {},
) {
  if (!terrainProfileFrame) return;
  setIframeHtml(terrainProfileFrame, "<p>Rendering terrain profile graph...</p>");
  try {
    const response = await postJson(
      "/api/plots/profile",
      terrainProfileRequestPayload(requestPayload),
      options,
    );
    const html = await response.text();
    if (options.runId && options.runId !== workflowRunId) return;
    setIframeHtml(terrainProfileFrame, html);
  } catch (error) {
    if (error.name === "AbortError" || (options.runId && options.runId !== workflowRunId)) return;
    setIframeHtml(terrainProfileFrame, `<p>Terrain profile graph failed: ${escapeHtml(error.message)}</p>`);
  }
}

function terrainProfileRequestPayload(requestPayload) {
  const resolved = resolvedSiteRequestPayload(requestPayload);
  const payload = {
    building_height_m: Number(resolved.building_height_m),
    radius_m: Number(resolved.radius_m),
    sample_interval_m: Number(resolved.sample_interval_m),
    mzcat_recommendation_mode: resolved.mzcat_recommendation_mode || "conservative",
  };
  if (hasSupportedSiteCoordinates(resolved)) {
    payload.latitude = Number(resolved.latitude);
    payload.longitude = Number(resolved.longitude);
    const siteLabel = String(resolved.site_label || "").trim();
    if (siteLabel) payload.site_label = siteLabel;
  } else {
    const address = String(resolved.address || "").trim();
    if (address) payload.address = address;
  }
  return payload;
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
  const enteredOrientation = parseOptionalNumber(orientationControl?.value);
  const orientation = validEngineeringAzimuth(enteredOrientation)
    ? normalizeOrientation(enteredOrientation)
    : 0;
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
    .design-face-tooltip {
      border: 1px solid rgb(154 52 18 / 42%);
      border-radius: 3px;
      padding: 2px 5px;
      background: rgb(255 247 237 / 92%);
      color: #7c2d12;
      box-shadow: none;
      font-size: 10px;
      font-weight: 800;
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
        dimensions_modified: false,
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
      let faceLabelsLayer = null;
      let resizeHandlesLayer = null;
      let orientationDrag = null;
      let resizeDrag = null;
      let buildingDragStart = null;
      let suppressOrientationClick = false;
      const dimensionMinimumM = 0.1;
      const dimensionMaximumM = 5000;
      const compassLabels = {
        0: "N",
        45: "NE",
        90: "E",
        135: "SE",
        180: "S",
        225: "SW",
        270: "W",
        315: "NW"
      };

      function clampDimension(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) && number > 0
          ? Math.min(dimensionMaximumM, Math.max(dimensionMinimumM, number))
          : fallback;
      }

      function formatDegrees(value) {
        return Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 1);
      }

      function normalizeOrientation(value) {
        const number = Number(value);
        if (!Number.isFinite(number)) return 0;
        const normalizedTenths = (
          (Math.round(number * 10) % 3600) + 3600
        ) % 3600;
        return normalizedTenths / 10;
      }

      function designAxes() {
        const theta = Number(state.orientation_deg) * Math.PI / 180;
        return {
          lengthAxis: [Math.sin(theta), Math.cos(theta)],
          widthAxis: [Math.cos(theta), -Math.sin(theta)]
        };
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
        const halfLength = clampDimension(state.length_m, 18) / 2;
        const halfWidth = clampDimension(state.width_m, 12) / 2;
        const { lengthAxis, widthAxis } = designAxes();
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
        const orientation = normalizeOrientation(rawDegrees);
        if (Number(state.orientation_deg) === Number(orientation)) return;
        if (orientationDrag) orientationDrag.moved = true;
        state.orientation_deg = orientation;
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

      function applyResizeFromLatLng(latlng) {
        if (!resizeDrag) return;
        const center = centerLatLng();
        const delta = metersDelta({ lat: center[0], lng: center[1] }, latlng);
        const { lengthAxis, widthAxis } = designAxes();
        const projectedLength = (
          delta.eastM * lengthAxis[0] + delta.northM * lengthAxis[1]
        ) * resizeDrag.lengthSign;
        const projectedWidth = (
          delta.eastM * widthAxis[0] + delta.northM * widthAxis[1]
        ) * resizeDrag.widthSign;
        const nextLength = Math.round(Math.min(
          dimensionMaximumM,
          Math.max(dimensionMinimumM, projectedLength * 2)
        ) * 10) / 10;
        const nextWidth = Math.round(Math.min(
          dimensionMaximumM,
          Math.max(dimensionMinimumM, projectedWidth * 2)
        ) * 10) / 10;
        if (
          Number(state.length_m) === nextLength
          && Number(state.width_m) === nextWidth
        ) return;
        resizeDrag.moved = true;
        state.length_m = nextLength;
        state.width_m = nextWidth;
        state.user_modified = true;
        state.dimensions_modified = true;
        redraw();
        notifyParent();
        state.dimensions_modified = false;
      }

      function startResizeDrag(event, lengthSign, widthSign) {
        L.DomEvent.preventDefault(event.originalEvent);
        L.DomEvent.stopPropagation(event.originalEvent);
        resizeDrag = { lengthSign, widthSign, moved: false };
        map.dragging.disable();
        map.getContainer().style.cursor = lengthSign === widthSign ? "nwse-resize" : "nesw-resize";
        applyResizeFromLatLng(event.latlng);
      }

      function stopResizeDrag() {
        if (!resizeDrag) return;
        resizeDrag = null;
        map.dragging.enable();
        map.getContainer().style.cursor = "";
      }

      function stopDesignInteraction() {
        stopOrientationDrag();
        stopResizeDrag();
        if (buildingDragStart) {
          buildingDragStart = null;
          map.dragging.enable();
          map.getContainer().style.cursor = "";
        }
      }

      function renderOrientationPoints() {
        if (pointsLayer) designLayer.removeLayer(pointsLayer);
        pointsLayer = L.layerGroup();
        const radius = Math.max(28, Math.min(70, Math.max(state.width_m, state.length_m) * 1.15));
        state.orientation_options.forEach((option) => {
          const theta = Number(option) * Math.PI / 180;
          const point = latLngFromMeters(Math.sin(theta) * radius, Math.cos(theta) * radius);
          L.circleMarker(point, {
            radius: 3,
            color: "#475569",
            weight: 1,
            fillColor: "#ffffff",
            fillOpacity: 0.8
          })
            .bindTooltip(
              compassLabels[option] + " - " + formatDegrees(option) + " deg clockwise from North",
              { sticky: true }
            )
            .on("click", () => {
              if (orientationDrag || suppressOrientationClick) return;
              state.orientation_deg = normalizeOrientation(option);
              state.user_modified = true;
              state.orientation_modified = true;
              redraw();
              notifyParent();
              state.orientation_modified = false;
            })
            .addTo(pointsLayer);
        });
        const activeTheta = Number(state.orientation_deg) * Math.PI / 180;
        const activePoint = latLngFromMeters(
          Math.sin(activeTheta) * radius,
          Math.cos(activeTheta) * radius
        );
        L.circleMarker(activePoint, {
          radius: 6,
          color: "#0f766e",
          weight: 2,
          fillColor: "#14b8a6",
          fillOpacity: 0.98
        })
          .bindTooltip(
            "Front theta=0 at beta=" + formatDegrees(state.orientation_deg)
              + " deg clockwise from North; drag to rotate",
            { sticky: true }
          )
          .on("mousedown", startOrientationDrag)
          .addTo(pointsLayer);
        pointsLayer.addTo(designLayer);
      }

      function renderResizeHandles(corners) {
        if (resizeHandlesLayer) designLayer.removeLayer(resizeHandlesLayer);
        resizeHandlesLayer = L.layerGroup();
        const signs = [[1, 1], [1, -1], [-1, -1], [-1, 1]];
        corners.forEach((corner, index) => {
          const [lengthSign, widthSign] = signs[index];
          L.circleMarker(corner, {
            radius: 6,
            color: "#9a3412",
            weight: 2,
            fillColor: "#fff7ed",
            fillOpacity: 1
          })
            .bindTooltip("Drag corner to resize breadth and depth", { sticky: true })
            .on("mousedown", (event) => startResizeDrag(event, lengthSign, widthSign))
            .addTo(resizeHandlesLayer);
        });
        resizeHandlesLayer.addTo(designLayer);
      }

      function renderFaceLabels() {
        if (faceLabelsLayer) designLayer.removeLayer(faceLabelsLayer);
        faceLabelsLayer = L.layerGroup();
        const { lengthAxis, widthAxis } = designAxes();
        const halfLength = clampDimension(state.length_m, 18) / 2;
        const halfWidth = clampDimension(state.width_m, 12) / 2;
        const labels = [
          ["Front", 0, lengthAxis[0] * (halfLength + 7), lengthAxis[1] * (halfLength + 7)],
          ["Right", 90, widthAxis[0] * (halfWidth + 7), widthAxis[1] * (halfWidth + 7)],
          ["Back", 180, -lengthAxis[0] * (halfLength + 7), -lengthAxis[1] * (halfLength + 7)],
          ["Left", 270, -widthAxis[0] * (halfWidth + 7), -widthAxis[1] * (halfWidth + 7)]
        ];
        labels.forEach(([label, theta, eastM, northM]) => {
          L.circleMarker(latLngFromMeters(eastM, northM), {
            radius: 1,
            opacity: 0,
            fillOpacity: 0,
            interactive: false
          })
            .bindTooltip(label + " theta=" + theta + " deg", {
              permanent: true,
              direction: "center",
              className: "design-face-tooltip"
            })
            .addTo(faceLabelsLayer);
        });
        faceLabelsLayer.addTo(designLayer);
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
        footprint.bindTooltip(
          "Design building " + formatDegrees(state.orientation_deg)
            + " deg clockwise from North; drag footprint to move; drag a corner to resize",
          { sticky: true }
        );
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
        renderResizeHandles(corners);
        renderFaceLabels();
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
          if (resizeDrag) {
            applyResizeFromLatLng(event.latlng);
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
            state.orientation_deg = normalizeOrientation(number);
            state.orientation_modified = false;
            redraw();
            notifyParent();
          }
        },
        setDimensions(widthM, lengthM) {
          state.width_m = clampDimension(widthM, 12);
          state.length_m = clampDimension(lengthM, 18);
          state.dimensions_modified = false;
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
          state.dimensions_modified = false;
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
  const enteredOrientation = parseOptionalNumber(orientationControl?.value);
  const previousOrientation = parseOptionalNumber(designBuildingState?.orientation_deg);
  const orientation = validEngineeringAzimuth(enteredOrientation)
    ? normalizeOrientation(enteredOrientation)
    : normalizeOrientation(previousOrientation ?? 0);
  if (
    orientationControl
    && validEngineeringAzimuth(enteredOrientation)
    && Number(orientationControl.value) !== orientation
  ) {
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
  const reportedOrientation = normalizeOrientation(
    parseOptionalNumber(designBuildingState.orientation_deg) ?? 0,
  );
  const adjustedLocation = adjustedLocationFromDesignState(designBuildingState);
  const positionModified = options.source === "map" && designBuildingState.position_modified;
  const orientationModified = (
    options.source === "map"
    && Boolean(designBuildingState.orientation_modified)
  );
  const dimensionsModified = (
    options.source === "map"
    && Boolean(designBuildingState.dimensions_modified)
  );
  const orientation = (
    options.source === "map"
    && !orientationModified
    && previousOrientation !== null
  ) ? normalizeOrientation(previousOrientation) : reportedOrientation;
  designBuildingState.orientation_deg = orientation;
  if (dimensionsModified) {
    const width = validBuildingDimension(designBuildingState.width_m)
      ? Number(designBuildingState.width_m)
      : null;
    const length = validBuildingDimension(designBuildingState.length_m)
      ? Number(designBuildingState.length_m)
      : null;
    if (width !== null && length !== null) {
      if (buildingWidthControl) buildingWidthControl.value = formatDimensionInput(width);
      if (buildingLengthControl) buildingLengthControl.value = formatDimensionInput(length);
      validateWorkflowInputs();
    }
  }
  const userMapChange = positionModified || orientationModified || dimensionsModified;
  if (positionModified && adjustedLocation) {
    clearWorkflowOverridesForSiteChange();
    coordinateOverride = {
      ...adjustedLocation,
      display_name: currentMapSite.display_name || "Building location",
    };
    currentMapSite = { ...coordinateOverride };
    locationMode = "coordinates";
    renderMapCoordinates(coordinateOverride);
    const latitudeCell = document.getElementById("resolved-site-latitude");
    const longitudeCell = document.getElementById("resolved-site-longitude");
    if (latitudeCell) latitudeCell.textContent = coordinateOverride.latitude.toFixed(6);
    if (longitudeCell) longitudeCell.textContent = coordinateOverride.longitude.toFixed(6);
  } else if (coordinateOverride) {
    renderMapCoordinates(coordinateOverride);
  }
  if (
    orientationControl
    && orientationModified
    && Number(orientationControl.value) !== orientation
  ) {
    orientationControl.value = String(orientation);
  }
  if (orientationReadout) orientationReadout.textContent = `${formatOrientation(orientation)} deg`;
  if (userMapChange) {
    const persistence = coordinateOverride
      ? saveDesignLocation(coordinateOverride)
      : { saved: false, reason: "location-unavailable" };
    cancelActiveWorkflow();
    updateReportAvailability();
    const nextStep = currentWorkflow
      ? "rerun assessment to refresh calculated layers"
      : "run the assessment when ready";
    if (persistence.saved) {
      setWorkflowProgress(100, `Map adjusted and saved; ${nextStep}`, "complete");
    } else if (persistence.reason === "project-number-required") {
      setWorkflowProgress(
        100,
        `Map adjusted for this session only; enter a project number to save the current location; ${nextStep}`,
        "complete",
      );
    } else if (persistence.reason === "storage-unavailable") {
      setWorkflowProgress(
        100,
        `Map adjusted for this session only; browser storage is unavailable, so it was not saved; ${nextStep}`,
        "complete",
      );
    } else {
      setWorkflowProgress(100, `Map adjusted but not saved; ${nextStep}`, "complete");
    }
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
  if (mapCoordinateReadout) {
    mapCoordinateReadout.textContent = location
      ? `${Number(location.latitude).toFixed(6)}, ${Number(location.longitude).toFixed(6)}`
      : "Not positioned";
  }
  updateMapNudgeAvailability();
}

function updateMapNudgeAvailability() {
  const positioned = locationMode === "coordinates" && Boolean(coordinateOverride);
  mapNudgeButtons.forEach((button) => {
    button.disabled = !positioned;
  });
}

function clearWorkflowOverridesForSiteChange() {
  workflowOverrides = [];
}

function saveDesignLocation(location) {
  try {
    const projectNumber = dashboardProjectNumber?.value.trim() || "";
    if (!projectNumber) {
      clearSavedDesignLocation();
      return { saved: false, reason: "project-number-required" };
    }
    if (!hasSupportedSiteCoordinates(location)) {
      return { saved: false, reason: "location-unavailable" };
    }
    const latitude = Number(location.latitude);
    const longitude = Number(location.longitude);
    const widthM = parseOptionalNumber(buildingWidthControl?.value);
    const lengthM = parseOptionalNumber(buildingLengthControl?.value);
    const dimensionsAreValid = (
      validBuildingDimension(widthM)
      && validBuildingDimension(lengthM)
    );
    const enteredOrientation = parseOptionalNumber(orientationControl?.value);
    localStorage.setItem(DESIGN_LOCATION_STORAGE_KEY, JSON.stringify({
      version: DESIGN_LOCATION_STORAGE_VERSION,
      latitude,
      longitude,
      display_name: location.display_name || dashboardAddress?.value.trim() || "Saved building location",
      address: dashboardAddress?.value.trim() || location.display_name || "",
      project_number: projectNumber,
      orientation_deg: validEngineeringAzimuth(enteredOrientation)
        ? normalizeOrientation(enteredOrientation)
        : normalizeOrientation(designBuildingState?.orientation_deg ?? 0),
      width_m: dimensionsAreValid ? Number(widthM) : null,
      length_m: dimensionsAreValid ? Number(lengthM) : null,
    }));
    return { saved: true, reason: null };
  } catch (_error) {
    // Coordinate persistence is best-effort when browser storage is unavailable.
    return { saved: false, reason: "storage-unavailable" };
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
    designLocationProjectNumber = projectNumber;
    if (dashboardAddress && savedLocation.address) {
      dashboardAddress.value = savedLocation.address;
    }
    const savedOrientation = parseOptionalNumber(savedLocation.orientation_deg);
    if (orientationControl && savedOrientation !== null) {
      orientationControl.value = String(normalizeOrientation(savedOrientation));
    }
    const savedWidth = parseOptionalNumber(savedLocation.width_m);
    const savedLength = parseOptionalNumber(savedLocation.length_m);
    if (
      validBuildingDimension(savedWidth)
      && validBuildingDimension(savedLength)
    ) {
      if (buildingWidthControl) buildingWidthControl.value = formatDimensionInput(savedWidth);
      if (buildingLengthControl) buildingLengthControl.value = formatDimensionInput(savedLength);
    }
  } catch (_error) {
    clearSavedDesignLocation();
  }
}

function invalidateDesignLocationForProject() {
  cancelAddressResolution();
  cancelActiveWorkflow();
  clearWorkflowOverridesForSiteChange();
  locationMode = "address";
  coordinateOverride = null;
  designLocationProjectNumber = "";
  designBuildingState = null;
  clearSavedDesignLocation();
  renderMapCoordinates(null);
  renderPendingMapFrame("Enter an address for the selected project.");
  updateReportAvailability();
}

function invalidateDesignLocationForAddress() {
  cancelAddressResolution();
  cancelActiveWorkflow();
  clearWorkflowOverridesForSiteChange();
  locationMode = "address";
  coordinateOverride = null;
  designLocationProjectNumber = "";
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
      addressSuggestions = Array.isArray(data.suggestions)
        ? data.suggestions.filter((suggestion) => (
          typeof suggestion?.display_name === "string"
          && suggestion.display_name.trim()
          && hasSupportedSiteCoordinates(suggestion)
        ))
        : [];
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
  const selectedSite = {
    latitude: Number(suggestion.latitude),
    longitude: Number(suggestion.longitude),
    display_name: String(suggestion.display_name || "").trim(),
  };
  if (
    !selectedSite.display_name
    || !hasSupportedSiteCoordinates(selectedSite)
  ) {
    setWorkflowProgress(0, "Address result is outside the supported Australian extent", "error");
    return;
  }
  currentMapSite = selectedSite;
  cancelActiveWorkflow();
  clearWorkflowOverridesForSiteChange();
  locationMode = "coordinates";
  coordinateOverride = { ...currentMapSite };
  designLocationProjectNumber = dashboardProjectNumber?.value.trim() || "";
  designBuildingState = {
    latitude: currentMapSite.latitude,
    longitude: currentMapSite.longitude,
    display_name: currentMapSite.display_name,
    width_m: parseOptionalNumber(buildingWidthControl?.value),
    length_m: parseOptionalNumber(buildingLengthControl?.value),
    orientation_deg: normalizeOrientation(parseOptionalNumber(orientationControl?.value) ?? 0),
    offset_east_m: 0,
    offset_north_m: 0,
    user_modified: false,
    position_modified: false,
    orientation_modified: false,
    dimensions_modified: false,
  };
  const persistence = saveDesignLocation(currentMapSite);
  renderMapCoordinates(currentMapSite);
  renderInitialMapFrame("Address located; run assessment when ready", { force: true });
  if (persistence.saved) {
    setWorkflowProgress(0, "Address located and saved; run assessment when ready", "complete");
  } else if (persistence.reason === "project-number-required") {
    setWorkflowProgress(
      0,
      "Address located for this session only; enter a project number to save the current location",
      "complete",
    );
  } else if (persistence.reason === "storage-unavailable") {
    setWorkflowProgress(
      0,
      "Address located for this session only; browser storage is unavailable",
      "complete",
    );
  } else {
    setWorkflowProgress(0, "Address located but not saved; run assessment when ready", "complete");
  }
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

function normalizeOrientation(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  const normalizedTenths = ((Math.round(number * 10) % 3600) + 3600) % 3600;
  return normalizedTenths / 10;
}

function validEngineeringAzimuth(value) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 && number < 360;
}

function validBuildingDimension(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 && number <= 5000;
}

function formatDimensionInput(value) {
  const number = Number(value);
  return Number.isInteger(number) ? String(number) : number.toFixed(1);
}

function parseOptionalNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatOrientation(value) {
  return Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 1);
}

function renderSiteAnalysisProgress(siteAnalysis) {
  const input = siteAnalysis.input || {};
  const site = siteAnalysis.site || {};
  const resultAddress = String(input.address || input.site_label || "").trim();
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
      display_name: site.display_name || input.address || input.site_label || "Assessed site",
    };
    coordinateOverride = { ...currentMapSite };
    locationMode = "coordinates";
    designLocationProjectNumber = dashboardProjectNumber?.value.trim() || "";
    saveDesignLocation(currentMapSite);
    renderMapCoordinates(currentMapSite);
  }
  if (!dashboardAddress?.value.trim() && (input.address || input.site_label)) {
    dashboardAddress.value = input.address || input.site_label;
  }
  siteInputSummary.innerHTML = `
    <div class="table-wrap">
      <table>
        <tbody>
          <tr><th>Address / site label</th><td>${escapeHtml(input.address || input.site_label || site.display_name || "not supplied")}</td></tr>
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
  const importanceMetadataRow = input.importance_level
    ? `<tr><th>Importance level (report metadata only)</th><td>${escapeHtml(input.importance_level)}; does not select AEP / ARI</td></tr>`
    : "";
  const structureRows = [
    input.structure_class ? `<tr><th>Structure class</th><td>${escapeHtml(input.structure_class)}</td></tr>` : "",
    input.structure_orientation_deg !== null && input.structure_orientation_deg !== undefined ? `<tr><th>Orientation</th><td>${formatNullableNumber(input.structure_orientation_deg, 2, "deg")}</td></tr>` : "",
    input.roof_shape ? `<tr><th>Roof shape</th><td>${escapeHtml(input.roof_shape)}</td></tr>` : "",
    input.building_width_m !== null && input.building_width_m !== undefined ? `<tr><th>Width</th><td>${formatNullableNumber(input.building_width_m, 2, "m")}</td></tr>` : "",
    input.building_length_m !== null && input.building_length_m !== undefined ? `<tr><th>Length</th><td>${formatNullableNumber(input.building_length_m, 2, "m")}</td></tr>` : "",
    input.roof_pitch_deg !== null && input.roof_pitch_deg !== undefined ? `<tr><th>Roof pitch</th><td>${formatNullableNumber(input.roof_pitch_deg, 2, "deg")}</td></tr>` : "",
    input.average_roof_height_m !== null && input.average_roof_height_m !== undefined ? `<tr><th>Average roof height</th><td>${formatNullableNumber(input.average_roof_height_m, 2, "m")}</td></tr>` : "",
    input.base_rl_m !== null && input.base_rl_m !== undefined ? `<tr><th>Base RL</th><td>${formatNullableNumber(input.base_rl_m, 2, "m")}</td></tr>` : "",
  ].join("");
  siteInputSummary.innerHTML = `
    <div class="table-wrap">
      <table>
        <tbody>
          <tr><th>Address / site label</th><td>${escapeHtml(input.address || input.site_label || workflow.site?.display_name || "not supplied")}</td></tr>
          <tr><th>Latitude</th><td id="resolved-site-latitude">${formatNullableNumber(workflow.site?.latitude, 6, "")}</td></tr>
          <tr><th>Longitude</th><td id="resolved-site-longitude">${formatNullableNumber(workflow.site?.longitude, 6, "")}</td></tr>
          <tr><th>Elevation</th><td>${Number(workflow.site.ground_elevation_m).toFixed(2)} m</td></tr>
          <tr><th>Building height</th><td>${Number(input.building_height_m).toFixed(2)} m</td></tr>
          ${structureRows}
          <tr><th>AEP / ARI</th><td>${escapeHtml(input.annual_exceedance_probability || "not supplied")}</td></tr>
          ${importanceMetadataRow}
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
  const selectedAep = speed.annual_exceedance_probability
    || workflow.input?.annual_exceedance_probability
    || "not supplied";
  const importanceMetadata = speed.importance_level || workflow.input?.importance_level;
  const returnPeriodNote = importanceMetadata
    ? `Selected AEP / ARI: ${selectedAep}; importance metadata: ${importanceMetadata} (does not select AEP / ARI)`
    : `Selected AEP / ARI: ${selectedAep}`;
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
        <span class="muted">${escapeHtml(returnPeriodNote)}</span>
      </div>
      <div>
        <span class="kicker">Confidence</span>
        ${badge(region.confidence, region.confidence)}
        <span class="muted">${escapeHtml(region.dataset_name || "dataset not configured")}</span>
      </div>
      <div>
        <span class="kicker">Md application</span>
        <strong>${escapeHtml(effectiveWindDirectionMultiplierCaseLabel(workflow))}</strong>
        <span class="muted">AS/NZS 1170.2 Clause 3.3 case</span>
      </div>
    </div>
  `;
}

function windDirectionMultiplierCaseLabel(value) {
  return {
    main_structure: "Main structure",
    cladding_or_immediate_support: "Cladding or immediate support",
    circular_or_polygonal_chimney_tank_or_pole: "Circular/polygonal chimney, tank or pole",
  }[value] || "Main structure";
}

function effectiveWindDirectionMultiplierCaseLabel(workflow) {
  const sourceTable = String(workflow?.direction_multiplier_assessment?.source_table || "");
  if (
    workflow?.input?.structure_class === "monopole"
    && /Clause 3\.3/i.test(sourceTable)
  ) {
    return `${windDirectionMultiplierCaseLabel(
      "circular_or_polygonal_chimney_tank_or_pole",
    )} (monopole)`;
  }
  return windDirectionMultiplierCaseLabel(workflow?.input?.wind_direction_multiplier_case);
}

function resetWorkflowSections() {
  currentWorkflow = null;
  currentWorkflowFingerprint = null;
  rawDataEditorDirty = false;
  setRawDataEditorAvailability(
    false,
    rawDataEditorSaving
      ? "Saving Raw Data changes and recalculating the assessment..."
      : "Assessment running; editable values will appear when it completes.",
  );
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
    vsitbTable.innerHTML = "<tr><td colspan=\"6\">Waiting for directional variables.</td></tr>";
  }
  if (directionalEditRestrictions) {
    directionalEditRestrictions.hidden = true;
    directionalEditRestrictions.textContent = "";
  }
  if (vdesTable) {
    vdesTable.innerHTML = "<tr><td colspan=\"6\">Waiting for design directions.</td></tr>";
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
    : ["VR", "Mc"].includes(variable)
      ? sourceWorkflowTable(rows, { allowOverride: variable === "VR" })
      : workflowTable(rows);
  section.insertAdjacentHTML("beforeend", `
    <article class="workflow-card">
      ${table}
    </article>
  `);
}

function workflowTable(rows) {
  if (!rows.length) return "<p class=\"note\">No workflow results generated.</p>";
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Direction</th>
            <th>Value</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => variableRow(row)).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function sourceWorkflowTable(rows, { allowOverride = true } = {}) {
  if (!rows.length) return "<p class=\"note\">No workflow results generated.</p>";
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Scope</th>
            <th>Value</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => variableRow(row, { allowOverride })).join("")}
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
      .map((row) => row.final_value ?? row.recommended_value)
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
  if (!row || (row.final_value ?? row.recommended_value) === null || (row.final_value ?? row.recommended_value) === undefined) {
    return "<td>manual input required</td>";
  }
  const value = Number(row.final_value ?? row.recommended_value);
  const isGoverning = Number.isFinite(highest) && value === highest;
  return `
    <td class="${isGoverning ? "governing-md-cell" : ""}">
      ${editableAssessmentValueCell(row, { compact: true })}
      ${isGoverning ? "<span class=\"muted\">governing</span>" : ""}
    </td>
  `;
}

function variableRow(row, { allowOverride = true } = {}) {
  return `
    <tr>
      <td>${escapeHtml(row.direction || "all")}</td>
      <td>${allowOverride ? editableAssessmentValueCell(row) : recommendedCell(row)}</td>
      <td>${badge(row.confidence, row.confidence)}</td>
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

function renderVsitbTable(rows, variableGroups = {}) {
  if (!rows.length) {
    if (directionalEditRestrictions) {
      directionalEditRestrictions.hidden = true;
      directionalEditRestrictions.textContent = "";
    }
    vsitbTable.innerHTML = "<tr><td colspan=\"6\">No Vsit,b rows generated.</td></tr>";
    return;
  }
  const restrictions = [...new Set(
    ["Md", "Mzcat", "Ms"]
      .map((variable) => rawDataEditRestriction(variable))
      .filter(Boolean),
  )];
  if (directionalEditRestrictions) {
    directionalEditRestrictions.hidden = !restrictions.length;
    directionalEditRestrictions.textContent = restrictions.join(" ");
  }
  const assessmentFor = (variable, row, fallbackValue, unit = "") => (
    (variableGroups[variable] || []).find((item) => item.direction === row.direction)
    || {
      variable,
      direction: row.direction,
      unit,
      calculated_value: fallbackValue,
      final_value: fallbackValue,
    }
  );
  vsitbTable.innerHTML = rows.map((row) => `
    <tr class="${row.is_governing ? "governing-row" : ""}">
      <td>${row.direction}${row.is_governing ? "<span class=\"muted\">governing direction</span>" : ""}</td>
      <td>${editableAssessmentValueCell(assessmentFor("Md", row, row.md), { compact: true })}</td>
      <td>${editableAssessmentValueCell(assessmentFor("Mzcat", row, row.mzcat), { compact: true })}</td>
      <td>${editableAssessmentValueCell(assessmentFor("Ms", row, row.ms), { compact: true })}</td>
      <td>${editableAssessmentValueCell(assessmentFor("Mt", row, row.mt), { compact: true })}</td>
      <td>
        ${row.final_vsitb === null || row.final_vsitb === undefined
          ? "blocked"
          : editableAssessmentValueCell(
            assessmentFor("Vsitb", row, row.recommended_vsitb ?? row.final_vsitb, "m/s"),
            { compact: true },
          )}
        ${row.is_governing ? "<span class=\"muted\">governing Vsit,b</span>" : ""}
      </td>
    </tr>
  `).join("");
}

function renderVdesTable(rows) {
  if (!vdesTable) return;
  if (!rows.length) {
    vdesTable.innerHTML = (
      "<tr><td colspan=\"6\">Vdes,theta requires the front orientation and all eight "
      + "directional Vsit,b values.</td></tr>"
    );
    return;
  }
  vdesTable.innerHTML = rows.map((row) => `
    <tr class="${row.is_governing ? "governing-row" : ""}">
      <td>${escapeHtml(row.face)}${row.is_governing ? "<span class=\"muted\">governing face</span>" : ""}</td>
      <td>${formatOrientation(row.theta_deg)} deg</td>
      <td>${formatOrientation(row.beta_deg)} deg</td>
      <td>${formatOrientation(row.sector_start_beta_deg)} to ${formatOrientation(row.sector_end_beta_deg)} deg</td>
      <td>${Number(row.raw_vdes_theta_mps).toFixed(3)} m/s</td>
      <td>${Number(row.vdes_theta_mps).toFixed(3)} m/s${row.minimum_uls_applied ? "<span class=\"muted\">30 m/s ULS minimum applied</span>" : ""}</td>
    </tr>
  `).join("");
}

function renderRawProvenance(variables, workflowWarnings = []) {
  if (!rawProvenance) return;
  const uniqueWarnings = [...new Set(
    [
      ...visibleWarnings(workflowWarnings),
      ...variables.flatMap((row) => visibleWarnings(row.warnings || [])),
    ],
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

function editableAssessmentValueCell(row, { compact = false } = {}) {
  const key = overrideKey(row.variable, row.direction);
  const existing = overrideForKey(key);
  const calculatedValue = finiteNumberOrNull(row.calculated_value ?? row.recommended_value);
  const finalValue = finiteNumberOrNull(
    existing?.override_value
      ?? row.final_value
      ?? row.override_value
      ?? calculatedValue,
  );
  const restriction = rawDataEditRestriction(row.variable);
  const maximum = workflowOverrideMaximums[row.variable];
  const maximumAttribute = maximum === undefined ? "" : ` max="${maximum}"`;
  const calculatedAttribute = calculatedValue === null ? "" : String(calculatedValue);
  const finalAttribute = finalValue === null ? "" : String(finalValue);
  const calculatedDisplayValue = rawDataEditableDisplayValue(calculatedValue);
  const finalDisplayValue = rawDataEditableDisplayValue(finalValue);
  const directionLabel = row.direction || "all directions";
  const unit = row.unit || "";
  const title = restriction || (
    calculatedValue === null
      ? "No calculated value is available; enter a reviewed value."
      : `Calculated value: ${calculatedAttribute}${unit ? ` ${unit}` : ""}`
  );
  return `
    <div class="inline-assessment-value${compact ? " is-compact" : ""}" data-key="${escapeHtml(key)}">
      <input
        data-raw-value
        data-key="${escapeHtml(key)}"
        data-variable="${escapeHtml(row.variable)}"
        data-direction="${escapeHtml(row.direction || "")}"
        data-calculated-value="${calculatedAttribute}"
        data-initial-value="${finalAttribute}"
        type="number"
        min="0.001"
        ${maximumAttribute}
        step="any"
        value="${finalDisplayValue}"
        placeholder="${calculatedValue === null ? "enter value" : calculatedDisplayValue}"
        aria-label="${escapeHtml(row.variable)} value for ${escapeHtml(directionLabel)}${unit ? ` (${escapeHtml(unit)})` : ""}"
        title="${escapeHtml(title)}"
        ${restriction ? "disabled" : ""}
      />
      ${unit ? `<span class="inline-value-unit">${escapeHtml(unit)}</span>` : ""}
      ${row.is_overridden || existing ? `<span class="badge badge-warn" title="${escapeHtml(existing?.reason || row.override_reason || "Saved edited value")}">edited</span>` : ""}
      ${restriction ? `<span class="inline-value-lock" title="${escapeHtml(restriction)}">locked</span>` : ""}
    </div>
  `;
}

function recommendedCell(row) {
  const value = formatWorkflowValue(row.recommended_value, row.unit);
  if (!row.recommended_label) return value;
  const label = String(row.recommended_label);
  const recommendedValue = Number(row.recommended_value);
  const labelNumbers = Array.from(
    label.matchAll(/(^|[^A-Za-z0-9_])([+-]?(?:\d+(?:\.\d*)?|\.\d+))/g),
    (match) => match[2],
  );
  const labelAlreadyContainsValue = Number.isFinite(recommendedValue) && labelNumbers.some((token) => {
    const candidate = Number(token);
    return Number.isFinite(candidate) && candidate.toFixed(3) === recommendedValue.toFixed(3);
  });
  return labelAlreadyContainsValue
    ? escapeHtml(label)
    : `${escapeHtml(label)}<span class="muted">${value}</span>`;
}

function finiteNumberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function rawDataEditableDisplayValue(value) {
  const number = finiteNumberOrNull(value);
  if (number === null) return "";
  return number.toFixed(rawDataDisplayDecimals).replace(/\.?0+$/, "");
}

function rawDataEditRestriction(variable) {
  if (variable === "Md") return mandatoryMdOverrideRestriction();
  if (variable === "Ms") return mandatoryMsOverrideRestriction();
  if (variable === "Mzcat") return mandatoryMzcatOverrideRestriction();
  return null;
}

function removeNowRestrictedWorkflowOverrides() {
  const retained = workflowOverrides.filter(
    (item) => !rawDataEditRestriction(item.variable),
  );
  const removedCount = workflowOverrides.length - retained.length;
  if (removedCount) workflowOverrides = retained;
  return removedCount;
}

function rawDataValueInputs() {
  return Array.from(rawDataPanel?.querySelectorAll("input[data-raw-value]") || []);
}

function rawDataValuesEqual(first, second) {
  if (first === null && second === null) return true;
  if (first === null || second === null) return false;
  return (
    Object.is(first, second)
    || Math.abs(first - second)
      <= rawDataDisplayTolerance
        + Number.EPSILON * Math.max(1, Math.abs(first), Math.abs(second))
  );
}

function rawDataInputChanged(input) {
  return !rawDataValuesEqual(
    finiteNumberOrNull(input.value),
    finiteNumberOrNull(input.dataset.initialValue),
  );
}

function rawDataCalculatedResetAvailable() {
  return rawDataValueInputs().some((input) => {
    if (input.disabled) return false;
    const calculated = finiteNumberOrNull(input.dataset.calculatedValue);
    return calculated !== null && !rawDataValuesEqual(finiteNumberOrNull(input.value), calculated);
  });
}

function setRawDataEditorAvailability(available, status) {
  rawDataEditorDirty = false;
  if (rawDataSave) rawDataSave.disabled = true;
  if (rawDataDiscard) rawDataDiscard.disabled = true;
  if (rawDataUseCalculated) {
    rawDataUseCalculated.disabled = (
      !available
      || rawDataEditorSaving
      || !rawDataCalculatedResetAvailable()
    );
  }
  if (rawDataEditReason) {
    rawDataEditReason.disabled = !available || rawDataEditorSaving;
    if (available && !rawDataEditorSaving) rawDataEditReason.value = "";
  }
  if (rawDataEditStatus) rawDataEditStatus.textContent = status;
  updateReportAvailability();
}

function refreshRawDataEditorState(status = null) {
  if (rawDataEditorSaving) return;
  const inputs = rawDataValueInputs();
  rawDataEditorDirty = inputs.some(rawDataInputChanged);
  const canSave = rawDataEditorDirty && completedAssessmentMatchesInputs();
  if (rawDataSave) rawDataSave.disabled = !canSave;
  if (rawDataDiscard) rawDataDiscard.disabled = !rawDataEditorDirty;
  if (rawDataUseCalculated) {
    rawDataUseCalculated.disabled = !currentWorkflow || !rawDataCalculatedResetAvailable();
  }
  if (rawDataEditReason) rawDataEditReason.disabled = !currentWorkflow;
  if (rawDataEditStatus) {
    const changedCount = inputs.filter(rawDataInputChanged).length;
    rawDataEditStatus.textContent = status || (
      rawDataEditorDirty
        ? `${changedCount} unsaved value${changedCount === 1 ? "" : "s"}. Reports are paused until the changes are saved or discarded.`
        : workflowOverrides.length
          ? `${workflowOverrides.length} saved edited value${workflowOverrides.length === 1 ? "" : "s"}.`
          : "All editable values currently match their calculated values."
    );
  }
  updateReportAvailability();
}

function stageCalculatedRawDataValues() {
  if (rawDataEditorSaving || !currentWorkflow) return;
  rawDataValueInputs().forEach((input) => {
    if (input.disabled) return;
    const calculated = finiteNumberOrNull(input.dataset.calculatedValue);
    if (calculated !== null) input.value = rawDataEditableDisplayValue(calculated);
  });
  refreshRawDataEditorState(
    "Calculated values are staged. Save changes to remove saved edits, or discard to undo.",
  );
}

function discardRawDataEdits() {
  if (rawDataEditorSaving) return;
  rawDataValueInputs().forEach((input) => {
    input.value = rawDataEditableDisplayValue(input.dataset.initialValue);
  });
  if (rawDataEditReason) rawDataEditReason.value = "";
  refreshRawDataEditorState("Unsaved Raw Data changes were discarded.");
}

function captureRawDataDraft() {
  return {
    reason: rawDataEditReason?.value || "",
    values: rawDataValueInputs().map((input) => ({
      key: input.dataset.key,
      value: input.value,
    })),
  };
}

function restoreRawDataDraft(draft, status) {
  const valuesByKey = new Map((draft?.values || []).map((item) => [item.key, item.value]));
  rawDataValueInputs().forEach((input) => {
    if (valuesByKey.has(input.dataset.key)) input.value = valuesByKey.get(input.dataset.key);
  });
  if (rawDataEditReason) rawDataEditReason.value = draft?.reason || "";
  refreshRawDataEditorState(status);
}

function validateAndBuildRawDataOverrides(inputs, reason) {
  if (reason.length > workflowOverrideReasonMaximum) {
    throw new Error(`Change reason must be ${workflowOverrideReasonMaximum} characters or fewer.`);
  }
  const candidateByKey = new Map(
    workflowOverrides.map((item) => [overrideKey(item.variable, item.direction), { ...item }]),
  );
  for (const input of inputs) {
    if (input.disabled || !rawDataInputChanged(input)) continue;
    const variable = input.dataset.variable;
    const direction = input.dataset.direction || null;
    const key = overrideKey(variable, direction);
    const value = finiteNumberOrNull(input.value);
    const calculated = finiteNumberOrNull(input.dataset.calculatedValue);
    if (value === null || value <= 0) {
      throw new Error(`${variable} ${direction || "value"} must be a number greater than zero.`);
    }
    const maximum = workflowOverrideMaximums[variable];
    if (maximum !== undefined && value > maximum) {
      throw new Error(`${variable} override must be no greater than ${maximum}.`);
    }
    const restriction = rawDataEditRestriction(variable);
    if (restriction) throw new Error(restriction);
    if (calculated !== null && rawDataValuesEqual(value, calculated)) {
      candidateByKey.delete(key);
      continue;
    }
    candidateByKey.set(key, {
      variable,
      direction,
      override_value: value,
      reason: reason || (
        "Raw Data value edited using global Save; no user change reason was provided."
      ),
    });
  }
  return [...candidateByKey.values()];
}

async function saveRawDataEdits() {
  if (rawDataEditorSaving || !rawDataEditorDirty) return false;
  if (!completedAssessmentMatchesInputs()) {
    const message = "Assessment inputs changed. Run the assessment again before saving Raw Data edits.";
    if (rawDataEditStatus) rawDataEditStatus.textContent = message;
    workflowSummary.textContent = message;
    return false;
  }
  const inputs = rawDataValueInputs();
  const reason = rawDataEditReason?.value.trim() || "";
  let candidateOverrides;
  try {
    candidateOverrides = validateAndBuildRawDataOverrides(inputs, reason);
  } catch (error) {
    const message = error.message || String(error);
    if (rawDataEditStatus) rawDataEditStatus.textContent = message;
    workflowSummary.textContent = message;
    return false;
  }
  const previousOverrides = workflowOverrides.map((item) => ({ ...item }));
  const previousState = captureCompletedWorkflowState();
  const draft = captureRawDataDraft();
  rawDataEditorSaving = true;
  setRawDataEditorAvailability(false, "Saving all Raw Data changes...");
  const outcome = await rerunAfterRawDataChange(
    candidateOverrides,
    previousOverrides,
    previousState,
  );
  rawDataEditorSaving = false;
  if (outcome === "saved") {
    workflowOverrides = candidateOverrides;
    if (Array.isArray(currentWorkflow?.variables)) renderWorkflow(currentWorkflow);
    setRawDataEditorAvailability(
      true,
      `${candidateOverrides.length} edited value${candidateOverrides.length === 1 ? "" : "s"} saved and the assessment recalculated.`,
    );
    return true;
  }
  if (outcome === "restored") {
    restoreRawDataDraft(
      draft,
      "Save failed. The previous completed assessment was restored; your unsaved values are still available to correct or discard.",
    );
  }
  return false;
}

async function rerunAfterRawDataChange(candidateOverrides, previousOverrides, previousState) {
  const runIdBeforeAttempt = workflowRunId;
  const succeeded = await runWorkflow({ workflowOverrides: candidateOverrides });
  if (succeeded) return "saved";
  if (workflowRunId > runIdBeforeAttempt + 1) {
    if (!currentWorkflow && !activeWorkflowController) {
      workflowOverrides = previousOverrides;
      restoreCompletedWorkflowState(
        previousState,
        "Raw Data save was cancelled because assessment inputs changed. "
          + "The previous completed assessment was restored.",
      );
      return "restored";
    }
    return "superseded";
  }
  const failureMessage = workflowSummary.textContent;
  workflowOverrides = previousOverrides;
  restoreCompletedWorkflowState(
    previousState,
    `Raw Data changes were not saved. The previous completed assessment was restored. ${failureMessage}`,
  );
  return "restored";
}

function captureCompletedWorkflowState() {
  return {
    workflow: currentWorkflow,
    fingerprint: currentWorkflowFingerprint,
    payload: activeWorkflowPayload,
    mapHtml: workflowMapFrame?.srcdoc || "",
    terrainProfileHtml: terrainProfileFrame?.srcdoc || "",
  };
}

function restoreCompletedWorkflowState(state, message) {
  currentWorkflow = state.workflow;
  currentWorkflowFingerprint = state.fingerprint;
  activeWorkflowPayload = state.payload;
  if (currentWorkflow) renderWorkflow(currentWorkflow);
  if (workflowMapFrame && state.mapHtml) setIframeHtml(workflowMapFrame, state.mapHtml);
  if (terrainProfileFrame && state.terrainProfileHtml) {
    setIframeHtml(terrainProfileFrame, state.terrainProfileHtml);
  }
  setWorkflowProgress(100, "Previous assessment restored", "complete");
  updateReportAvailability();
  workflowSummary.textContent = message;
}

function mandatoryMdOverrideRestriction() {
  const payload = workflowPayload();
  const designCase = payload.wind_direction_multiplier_case;
  if (
    designCase === "circular_or_polygonal_chimney_tank_or_pole"
    || payload.structure_class === "monopole"
  ) {
    return "Md cannot be overridden because the selected Clause 3.3 design case requires Md = 1.0.";
  }
  const windRegion = currentWorkflow?.direction_multiplier_assessment?.wind_region
    || currentWorkflow?.wind_region_assessment?.region_subclassification
    || currentWorkflow?.wind_region_assessment?.wind_region;
  if (designCase === "cladding_or_immediate_support" && ["B2", "C", "D"].includes(windRegion)) {
    return `Md cannot be overridden because Clause 3.3 requires Md = 1.0 for cladding and its immediate supporting structure in wind region ${windRegion}.`;
  }
  return null;
}

function mandatoryMsOverrideRestriction() {
  const payload = workflowPayload();
  const referenceHeight = Number(payload.average_roof_height_m ?? payload.building_height_m);
  if (referenceHeight > 25) {
    return "Ms cannot be overridden because Clause 4.3.1 requires Ms = 1.0 when average roof height h exceeds 25 m.";
  }
  return null;
}

function mandatoryMzcatOverrideRestriction() {
  const windRegion = currentWorkflow?.wind_region_assessment?.wind_region;
  if (windRegion === "A0") {
    return "Mz,cat cannot be overridden because the Region A0 Table 4.1 value is terrain-independent and mandatory.";
  }
  return null;
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
