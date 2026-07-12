const workflowForm = document.getElementById("workflow-form");
const workflowSummary = document.getElementById("workflow-summary");
const siteInputSummary = document.getElementById("site-input-summary");
const windInputsSummary = document.getElementById("wind-inputs-summary");
const workflowMapFrame = document.getElementById("workflow-map-frame");
const vsitbTable = document.getElementById("vsitb-table");
const workflowReport = document.getElementById("workflow-report");
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
const orientationControl = document.getElementById("structure_orientation_deg");
const orientationReadout = document.getElementById("orientation-readout");
const buildingWidthControl = document.getElementById("building_width_m");
const buildingLengthControl = document.getElementById("building_length_m");
const addressSuggestionsList = document.getElementById("dashboard-address-suggestions");

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
let workflowOverrides = [];
let addressSuggestionTimer = null;
let addressSuggestionController = null;
let addressSuggestions = [];
let currentMapSite = {
  latitude: -33.8688,
  longitude: 151.2093,
  display_name: "Sydney CBD",
};

try {
  if (dashboardProjectNumber) {
    dashboardProjectNumber.value = localStorage.getItem("openwindProjectNumber") || "";
    dashboardProjectNumber.addEventListener("input", () => {
      localStorage.setItem("openwindProjectNumber", dashboardProjectNumber.value);
    });
  }
} catch (_error) {
  // Local storage can be unavailable in restrictive browser modes.
}

document.querySelectorAll("[data-workspace-tab]").forEach((button) => {
  button.addEventListener("click", () => activateWorkspaceTab(button.dataset.workspaceTab));
});

workflowForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (document.activeElement === dashboardAddress) {
    await zoomMapToAddress();
    return;
  }
  await runWorkflow();
});

renderInitialMapFrame("Run an assessment to load the project site map.");
syncDesignBuildingOverlay();

workflowMapFrame?.addEventListener("load", () => {
  syncDesignBuildingOverlay();
  invalidateWorkflowMap();
});

[orientationControl, buildingWidthControl, buildingLengthControl].forEach((control) => {
  control?.addEventListener("input", syncDesignBuildingOverlay);
  control?.addEventListener("change", syncDesignBuildingOverlay);
});

dashboardAddress?.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  event.stopPropagation();
  await zoomMapToAddress();
});

dashboardAddress?.addEventListener("input", () => {
  const matchedSuggestion = suggestionForAddress(dashboardAddress.value);
  if (matchedSuggestion) {
    applyAddressSuggestion(matchedSuggestion, { zoom: false });
    return;
  }
  queueAddressSuggestions(dashboardAddress.value);
});

dashboardAddress?.addEventListener("change", () => {
  const matchedSuggestion = suggestionForAddress(dashboardAddress.value);
  if (matchedSuggestion) applyAddressSuggestion(matchedSuggestion, { zoom: true });
});

workflowReport?.addEventListener("click", async () => {
  if (!currentWorkflow) {
    workflowSummary.textContent = "Run the workflow before opening a report.";
    return;
  }
  try {
    const response = await postJson("/api/wind-workflow/report/html", workflowPayload());
    const html = await response.text();
    const reportUrl = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    const reportWindow = window.open(reportUrl, "_blank", "noopener,noreferrer");
    setTimeout(() => URL.revokeObjectURL(reportUrl), 30000);
    if (!reportWindow) {
      workflowSummary.textContent = "Workflow report generated, but the browser blocked the report window.";
    }
  } catch (error) {
    workflowSummary.textContent = `Workflow report failed: ${error.message}`;
  }
});

async function runWorkflow() {
  setWorkflowProgress(4, "Resolving site location and elevation", "running");
  workflowSummary.textContent = "Resolving site location and elevation...";
  resetWorkflowSections();
  try {
    await runWorkflowStream();
  } catch (error) {
    await runWorkflowFallback(error);
  }
}

async function runWorkflowStream() {
  const response = await fetch("/api/wind-workflow/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(workflowPayload()),
  });
  if (!response.ok || !response.body) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || response.statusText);
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
      if (line.trim()) handleWorkflowStreamEvent(JSON.parse(line));
    }
    if (done) break;
  }
  if (buffer.trim()) handleWorkflowStreamEvent(JSON.parse(buffer));
}

function handleWorkflowStreamEvent(event) {
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
  }
  if (event.data?.map_html && workflowMapFrame) {
    workflowMapFrame.srcdoc = event.data.map_html;
    setTimeout(syncDesignBuildingOverlay, 80);
  }
  if (event.stage === "complete") {
    setWorkflowProgress(100, event.label, "complete");
  }
}

async function runWorkflowFallback(originalError) {
  try {
    const reason = originalError?.message ? ` (${originalError.message})` : "";
    setWorkflowProgress(32, `Live progress unavailable${reason}; calculating full workflow`, "running");
    const response = await postJson("/api/wind-workflow", workflowPayload());
    currentWorkflow = await response.json();
    renderWorkflow(currentWorkflow);
    setWorkflowProgress(78, "Rendering combined map layers", "running");
    await renderWorkflowMap();
    setWorkflowProgress(100, "Assessment complete", "complete");
  } catch (fallbackError) {
    setWorkflowProgress(100, "Assessment failed", "error");
    workflowSummary.textContent = `Workflow failed: ${fallbackError.message || originalError.message}`;
    vsitbTable.innerHTML = "<tr><td colspan=\"7\">Workflow failed.</td></tr>";
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
    building_height_m: Number(data.get("building_height_m")),
    radius_m: Number(data.get("radius_m")),
    sample_interval_m: Number(data.get("sample_interval_m")),
    obstruction_radius_m: Number(data.get("obstruction_radius_m") || 500),
    default_storey_height_m: Number(data.get("default_storey_height_m") || 3),
    wind_region: "A2",
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
    mzcat_recommendation_mode: "conservative",
    workflow_overrides: workflowOverrides,
  };
  if (!payload.address) delete payload.address;
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

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || response.statusText);
  }
  return response;
}

function renderWorkflow(workflow) {
  workflowSummary.textContent = JSON.stringify({
    site: workflow.site,
    overrides_applied: workflow.overrides_applied?.length || 0,
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

async function renderWorkflowMap() {
  if (!workflowMapFrame) return;
  renderInitialMapFrame("Rendering project site map...");
  try {
    const response = await postJson("/api/wind-workflow/map", workflowPayload());
    workflowMapFrame.srcdoc = await response.text();
    setTimeout(syncDesignBuildingOverlay, 80);
    setTimeout(invalidateWorkflowMap, 140);
  } catch (error) {
    workflowMapFrame.srcdoc = `<p>Combined map failed: ${escapeHtml(error.message)}</p>`;
    throw error;
  }
}

function renderInitialMapFrame(message, options = {}) {
  if (!workflowMapFrame) return;
  if (workflowMapFrame.srcdoc && !options.force) return;
  workflowMapFrame.srcdoc = initialMapHtml(message);
}

function initialMapHtml(message) {
  const orientation = nearestOrientation(parseOptionalNumber(orientationControl?.value) ?? 0);
  const widthM = parseOptionalNumber(buildingWidthControl?.value) ?? 12;
  const lengthM = parseOptionalNumber(buildingLengthControl?.value) ?? 18;
  const safeMessage = escapeHtml(message || "Ready");
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css" />
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
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="map-status">${safeMessage}</div>
  <script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"></script>
  <script>
    (function () {
      const state = {
        latitude: ${JSON.stringify(currentMapSite.latitude)},
        longitude: ${JSON.stringify(currentMapSite.longitude)},
        display_name: ${JSON.stringify(currentMapSite.display_name || "Mapped site")},
        width_m: ${JSON.stringify(widthM)},
        length_m: ${JSON.stringify(lengthM)},
        orientation_deg: ${JSON.stringify(orientation)},
        offset_east_m: 0,
        offset_north_m: 0,
        orientation_options: ${JSON.stringify(orientationOptions)}
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

      function clampDimension(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) && number > 0 ? number : fallback;
      }

      function formatDegrees(value) {
        return Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 2);
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

      function renderOrientationPoints() {
        if (pointsLayer) designLayer.removeLayer(pointsLayer);
        pointsLayer = L.layerGroup();
        const radius = Math.max(28, Math.min(70, Math.max(state.width_m, state.length_m) * 1.15));
        state.orientation_options.forEach((option) => {
          const theta = Number(option) * Math.PI / 180;
          const point = latLngFromMeters(Math.sin(theta) * radius, Math.cos(theta) * radius);
          const active = Number(option) === Number(state.orientation_deg);
          L.circleMarker(point, {
            radius: active ? 5 : 3,
            color: active ? "#0f766e" : "#475569",
            weight: active ? 2 : 1,
            fillColor: active ? "#14b8a6" : "#ffffff",
            fillOpacity: active ? 0.95 : 0.8
          }).bindTooltip(formatDegrees(option) + " deg", { sticky: true }).addTo(pointsLayer);
        });
        pointsLayer.addTo(designLayer);
      }

      function redraw() {
        const corners = footprintCorners();
        if (!footprint) {
          footprint = L.polygon(corners, {
            color: "#155eef",
            weight: 3,
            fillColor: "#3b82f6",
            fillOpacity: 0.28
          }).addTo(designLayer);
          enableCtrlDrag(footprint);
        } else {
          footprint.setLatLngs(corners);
        }
        footprint.bindTooltip("Design building " + formatDegrees(state.orientation_deg) + " deg", {
          sticky: true
        });
        const bearingDistance = Math.max(state.length_m, 18) * 0.75;
        const line = [[state.latitude, state.longitude], bearingEndpoint(bearingDistance)];
        if (!bearingLine) {
          bearingLine = L.polyline(line, {
            color: "#155eef",
            weight: 2,
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
        redraw();
      }

      function enableCtrlDrag(layer) {
        let dragStart = null;
        layer.on("mousedown", (event) => {
          if (!event.originalEvent.ctrlKey) return;
          L.DomEvent.preventDefault(event.originalEvent);
          L.DomEvent.stopPropagation(event.originalEvent);
          dragStart = {
            latlng: event.latlng,
            east: state.offset_east_m,
            north: state.offset_north_m
          };
          map.dragging.disable();
          map.getContainer().style.cursor = "move";
        });
        map.on("mousemove", (event) => {
          if (!dragStart) return;
          const delta = metersDelta(dragStart.latlng, event.latlng);
          state.offset_east_m = dragStart.east + delta.eastM;
          state.offset_north_m = dragStart.north + delta.northM;
          redraw();
        });
        map.on("mouseup", () => {
          if (!dragStart) return;
          dragStart = null;
          map.dragging.enable();
          map.getContainer().style.cursor = "";
        });
      }

      window.openWindDesignBuilding = {
        setOrientation(value) {
          const number = Number(value);
          if (Number.isFinite(number)) {
            state.orientation_deg = number;
            redraw();
          }
        },
        setDimensions(widthM, lengthM) {
          state.width_m = clampDimension(widthM, 12);
          state.length_m = clampDimension(lengthM, 18);
          redraw();
        },
        nudge(eastM, northM) {
          nudgeDesignBuilding(eastM, northM);
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
          map.setView([state.latitude, state.longitude], 18);
          redraw();
        },
        invalidate() {
          map.invalidateSize();
        },
        getState() {
          return Object.assign({}, state);
        }
      };

      redraw();
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
  document.querySelectorAll("[data-workspace-tab]").forEach((button) => {
    const isActive = button.dataset.workspaceTab === tabName;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  });
  document.querySelectorAll("[data-workspace-panel]").forEach((panel) => {
    const isActive = panel.dataset.workspacePanel === tabName;
    panel.classList.toggle("is-active", isActive);
    panel.hidden = !isActive;
  });
}

function syncDesignBuildingOverlay() {
  const orientation = nearestOrientation(parseOptionalNumber(orientationControl?.value) ?? 0);
  if (orientationControl && Number(orientationControl.value) !== orientation) {
    orientationControl.value = String(orientation);
  }
  if (orientationReadout) orientationReadout.textContent = `${formatOrientation(orientation)} deg`;
  const overlay = workflowMapFrame?.contentWindow?.openWindDesignBuilding;
  if (!overlay) return;
  overlay.setDimensions(
    parseOptionalNumber(buildingWidthControl?.value),
    parseOptionalNumber(buildingLengthControl?.value),
  );
  overlay.setOrientation(orientation);
}

async function zoomMapToAddress() {
  const address = dashboardAddress?.value.trim();
  if (!address) {
    setWorkflowProgress(0, "Enter an address to zoom the map", "error");
    return;
  }
  setWorkflowProgress(8, "Locating address on map", "running");
  try {
    const response = await postJson("/api/analyse", workflowPayload());
    const siteAnalysis = await response.json();
    currentMapSite = {
      latitude: siteAnalysis.site.latitude,
      longitude: siteAnalysis.site.longitude,
      display_name: siteAnalysis.site.display_name || address,
    };
    renderSiteAnalysisProgress(siteAnalysis);
    const mapApi = workflowMapFrame?.contentWindow?.openWindWorkflowMap;
    if (mapApi?.setSite) {
      mapApi.setSite(currentMapSite);
      mapApi.invalidate?.();
    } else {
      renderInitialMapFrame("Address located. Run the assessment when ready.", { force: true });
    }
    setWorkflowProgress(0, "Address located; run assessment when ready", "complete");
  } catch (error) {
    setWorkflowProgress(0, "Address lookup failed", "error");
    workflowSummary.textContent = `Address lookup failed: ${error.message}`;
  }
}

function queueAddressSuggestions(query) {
  const trimmed = String(query || "").trim();
  clearTimeout(addressSuggestionTimer);
  if (addressSuggestionController) addressSuggestionController.abort();
  if (trimmed.length < 3) {
    addressSuggestions = [];
    renderAddressSuggestions();
    return;
  }
  addressSuggestionTimer = setTimeout(async () => {
    addressSuggestionController = new AbortController();
    try {
      const params = new URLSearchParams({ q: trimmed, limit: "6" });
      const response = await fetch(`/api/geocode/suggest?${params}`, {
        signal: addressSuggestionController.signal,
      });
      if (!response.ok) return;
      const data = await response.json();
      addressSuggestions = data.suggestions || [];
      renderAddressSuggestions();
    } catch (error) {
      if (error.name !== "AbortError") {
        addressSuggestions = [];
        renderAddressSuggestions();
      }
    }
  }, 280);
}

function renderAddressSuggestions() {
  if (!addressSuggestionsList) return;
  addressSuggestionsList.innerHTML = addressSuggestions
    .map((suggestion) => `<option value="${escapeHtml(suggestion.display_name)}"></option>`)
    .join("");
}

function suggestionForAddress(value) {
  const normalized = String(value || "").trim();
  return addressSuggestions.find((suggestion) => suggestion.display_name === normalized) || null;
}

function applyAddressSuggestion(suggestion, options = {}) {
  if (!suggestion) return;
  currentMapSite = {
    latitude: suggestion.latitude,
    longitude: suggestion.longitude,
    display_name: suggestion.display_name,
  };
  if (options.zoom) {
    const mapApi = workflowMapFrame?.contentWindow?.openWindWorkflowMap;
    if (mapApi?.setSite) {
      mapApi.setSite(currentMapSite);
      mapApi.invalidate?.();
      setWorkflowProgress(0, "Address located; run assessment when ready", "complete");
    }
  }
}

function invalidateWorkflowMap() {
  try {
    workflowMapFrame?.contentWindow?.openWindWorkflowMap?.invalidate?.();
  } catch (_error) {
    // Cross-frame map invalidation is best-effort only.
  }
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
  if (!dashboardAddress?.value.trim() && input.address) {
    dashboardAddress.value = input.address;
  }
  siteInputSummary.innerHTML = `
    <div class="table-wrap">
      <table>
        <tbody>
          <tr><th>Address</th><td>${escapeHtml(input.address || site.display_name || "not supplied")}</td></tr>
          <tr><th>Latitude</th><td>${formatNullableNumber(site.latitude, 5, "")}</td></tr>
          <tr><th>Longitude</th><td>${formatNullableNumber(site.longitude, 5, "")}</td></tr>
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
      <p class="note">Md values loaded from the selected region table. Final editable values are available once directional variables are calculated.</p>
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
  const warnings = visibleWarnings([
    ...(region.warnings || []),
    ...(speed.warnings || []),
    ...(md.warnings || []),
  ]);
  windInputsSummary.innerHTML = `
    <h3>Wind Inputs Summary</h3>
    <div class="status-strip">
      <div>
        <span class="kicker">Wind region</span>
        <strong>${escapeHtml(region.wind_region)}${region.region_subclassification ? ` / ${escapeHtml(region.region_subclassification)}` : ""}</strong>
        <span class="muted">${region.near_boundary ? "Near boundary - review required" : "Matched GIS polygon"}</span>
      </div>
      <div>
        <span class="kicker">VR,ult</span>
        <strong>${formatNullableNumber(speed.vr_ult, 1, "m/s")}</strong>
        <span class="muted">ARI ${Number(speed.ari_years)} years</span>
      </div>
      <div>
        <span class="kicker">Confidence</span>
        ${badge(region.confidence, region.confidence)}
        <span class="muted">${escapeHtml(region.dataset_name || "dataset not configured")}</span>
      </div>
    </div>
    ${warningListHtml(warnings)}
    <div class="table-wrap">
      <table>
        <tbody>
          <tr><th>Wind Region</th><td>${escapeHtml(region.wind_region)}${region.region_subclassification ? ` (${escapeHtml(region.region_subclassification)})` : ""}</td></tr>
          <tr><th>Confidence</th><td>${badge(region.confidence, region.confidence)}</td></tr>
          <tr><th>Importance Level</th><td>${escapeHtml(speed.importance_level || "not supplied")}</td></tr>
          <tr><th>ARI</th><td>${Number(speed.ari_years)} years</td></tr>
          <tr><th>VR,ult</th><td>${formatNullableNumber(speed.vr_ult, 1, "m/s")}</td></tr>
          <tr><th>VR,serv</th><td>${formatNullableNumber(speed.vr_serv, 1, "m/s")}</td></tr>
        </tbody>
      </table>
    </div>
    <details class="diagnostic-details">
      <summary>Dataset details</summary>
      <div class="table-wrap">
        <table>
          <tbody>
            <tr><th>Dataset name</th><td>${escapeHtml(region.dataset_name || "not configured")}</td></tr>
            <tr><th>Dataset path</th><td class="code-cell">${escapeHtml(region.dataset_path || "not configured")}</td></tr>
            <tr><th>Polygon count</th><td>${escapeHtml(region.polygon_count ?? "not available")}</td></tr>
            <tr><th>Available regions</th><td>${escapeHtml((region.available_region_names || []).join(", ") || "not available")}</td></tr>
            <tr><th>Source</th><td>${escapeHtml(region.source)}</td></tr>
            <tr><th>Map status</th><td>${region.near_boundary ? "near boundary" : "matched GIS polygon"}</td></tr>
          </tbody>
        </table>
      </div>
    </details>
    <details class="diagnostic-details">
      <summary>Lookup sources</summary>
      <div class="calc-panel">
        <p><strong>Wind region source:</strong> ${escapeHtml(region.source)}</p>
        <p><strong>VR source:</strong> ${escapeHtml(speed.selected_table)}</p>
        <ul>
          ${(speed.lookup_values || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
        </ul>
      </div>
    </details>
  `;
}

function resetWorkflowSections() {
  currentWorkflow = null;
  if (siteInputSummary) {
    siteInputSummary.innerHTML = "<p class=\"note\">Resolving site location and elevation...</p>";
  }
  if (windInputsSummary) {
    windInputsSummary.innerHTML = "<p class=\"note\">Waiting for wind-region and regional wind speed lookup...</p>";
  }
  if (workflowMapFrame) {
    workflowMapFrame.srcdoc = "";
    renderInitialMapFrame("Assessment running. The project map will replace this view.");
  }
  if (dashboardRegion) dashboardRegion.textContent = "-";
  if (dashboardGoverningDirection) dashboardGoverningDirection.textContent = "-";
  if (dashboardGoverningVsitb) dashboardGoverningVsitb.textContent = "Calculating";
  if (vsitbTable) {
    vsitbTable.innerHTML = "<tr><td colspan=\"7\">Waiting for directional variables.</td></tr>";
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

function renderVsitbCards(rows) {
  const section = document.getElementById(variableAnchors.Vsitb);
  if (!section) return;
  section.querySelectorAll(".workflow-card").forEach((card) => card.remove());
  section.insertAdjacentHTML("beforeend", `
    <article class="workflow-card">
      ${workflowTable(rows)}
    </article>
  `);
  attachOverrideHandlers(section);
}

function workflowTable(rows) {
  if (!rows.length) return "<p class=\"note\">No workflow results generated.</p>";
  const showCalculationSummary = rows.some((row) => ["Mzcat", "Ms", "Mt"].includes(row.variable));
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Direction</th>
            <th>Calculated</th>
            <th>Confidence</th>
            <th>Final</th>
            <th>Source Reference</th>
            <th>Warnings</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => variableRow(row)).join("")}
        </tbody>
      </table>
    </div>
    ${showCalculationSummary ? tableCalculationSummary(rows) : sharedSourceDetails(rows)}
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
            <th>Final</th>
            <th>Warnings</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => compactVariableRow(row)).join("")}
        </tbody>
      </table>
    </div>
    ${sharedSourceDetails(rows)}
  `;
}

function mdWorkflowTable(rows) {
  if (!rows.length) return "<p class=\"note\">No Md rows generated.</p>";
  const byDirection = Object.fromEntries(rows.map((row) => [row.direction, row]));
  const sourceReferences = [...new Set(rows.map((row) => row.source_reference).filter(Boolean))];
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
    <details class="diagnostic-details source-details">
      <summary>Show source</summary>
      <div class="calc-panel">
        <p><strong>Source:</strong> ${escapeHtml(sourceReferences.join(" ") || "Engineer review required.")}</p>
        <p>Values are editable data-table lookups and must be checked against the licensed Standard.</p>
      </div>
    </details>
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

function compactVariableRow(row) {
  return `
    <tr>
      <td>${escapeHtml(row.direction || row.label || "all")}</td>
      <td>${recommendedCell(row)}</td>
      <td>${badge(row.confidence, row.confidence)}</td>
      <td>${finalValueCell(row)}</td>
      <td>${warningsCell(row)}</td>
    </tr>
  `;
}

function variableRow(row) {
  return `
    <tr>
      <td>${escapeHtml(row.direction || "all")}</td>
      <td>${recommendedCell(row)}</td>
      <td>${badge(row.confidence, row.confidence)}</td>
      <td>${inlineFinalValueCell(row)}</td>
      <td>${escapeHtml(row.source_reference || "Engineer review required.")}</td>
      <td>${warningsCell(row)}</td>
    </tr>
  `;
}

function tableCalculationSummary(rows) {
  const sourceReferences = [...new Set(rows.map((row) => row.source_reference).filter(Boolean))];
  const first = rows[0];
  return `
    <div class="table-summary calc-panel">
      <p><strong>Source:</strong> ${escapeHtml(sourceReferences.join(" ") || "Engineer review required.")}</p>
      <p><strong>Basis:</strong> ${escapeHtml(first?.formula_basis || "Calculation basis unavailable.")}</p>
      <div class="table-wrap compact-table">
        <table>
          <thead>
            <tr><th>Direction</th><th>Source details</th><th>Calculation result</th></tr>
          </thead>
          <tbody>
            ${rows.map((row) => `
              <tr>
                <td>${escapeHtml(row.direction || "all")}</td>
                <td>${summaryItems(row)}</td>
                <td>${escapeHtml(row.calculation_result || "not available")}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function sharedSourceDetails(rows) {
  const first = rows[0];
  if (!first) return "";
  const sourceReferences = [...new Set(rows.map((row) => row.source_reference).filter(Boolean))];
  const detailItems = [...new Set(rows.flatMap((row) => row.detail_items || []))];
  return `
    <details class="diagnostic-details source-details">
      <summary>Source and calculation basis</summary>
      <div class="calc-panel">
        <p><strong>Source:</strong> ${escapeHtml(sourceReferences.join(" ") || "Engineer review required.")}</p>
        <p><strong>Basis:</strong> ${escapeHtml(first.formula_basis || "Calculation basis unavailable.")}</p>
        ${detailItems.length ? `<ul>${detailItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
      </div>
    </details>
  `;
}

function warningsCell(row) {
  const warnings = visibleWarnings(row.warnings || []);
  return warnings.length
    ? warnings.map(escapeHtml).join(" ")
    : "<span class=\"muted\">None</span>";
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

function finalValueCell(row) {
  if (row.final_value === null || row.final_value === undefined) return "not available";
  const value = formatWorkflowValue(row.final_value, row.unit);
  const calculated = row.calculated_value === null || row.calculated_value === undefined
    ? ""
    : `<span class="muted">calculated ${formatWorkflowValue(row.calculated_value, row.unit)}</span>`;
  const override = row.is_overridden
    ? `<span class="badge badge-warn">override</span><span class="muted">${escapeHtml(row.override_reason || "")}</span>`
    : "";
  return `${row.final_label ? escapeHtml(row.final_label) : "Calculated value"}<span class="muted">${value}</span>${override || calculated}`;
}

function inlineFinalValueCell(row) {
  const key = overrideKey(row.variable, row.direction);
  const existing = overrideForKey(key);
  const finalValue = existing?.override_value ?? row.override_value ?? row.final_value ?? "";
  const reason = existing?.reason || row.override_reason || "";
  return `
    <div class="inline-override" data-key="${key}">
      <input data-override-field="override_value" data-key="${key}" type="number" step="0.001" value="${finalValue}" aria-label="Final ${escapeHtml(row.variable)} value for ${escapeHtml(row.direction || "all directions")}" />
      <input data-override-field="reason" data-key="${key}" value="${escapeHtml(reason)}" placeholder="reason if edited" aria-label="Override reason" />
      <button type="button" data-override-action="apply" data-key="${key}">Save</button>
      ${row.is_overridden || existing ? `<button type="button" data-override-action="clear" data-key="${key}">Reset</button>` : ""}
      ${row.is_overridden ? `<span class="badge badge-warn">override</span>` : ""}
      <span class="muted">calculated ${formatWorkflowValue(row.calculated_value, row.unit)}</span>
    </div>
  `;
}

function simpleFinalValueCell(row) {
  if (row.final_value === null || row.final_value === undefined) return "not available";
  const value = formatWorkflowValue(row.final_value, row.unit);
  if (row.is_overridden) {
    return `${value}<span class="badge badge-warn">override</span><span class="muted">${escapeHtml(row.override_reason || "")}</span>`;
  }
  if (row.calculated_value !== null && row.calculated_value !== undefined && row.calculated_value !== row.final_value) {
    return `${value}<span class="muted">calculated ${formatWorkflowValue(row.calculated_value, row.unit)}</span>`;
  }
  return value;
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
  workflowOverrides = workflowOverrides.filter((item) =>
    !(item.variable === variable && (item.direction || null) === direction)
  );
  if (button.dataset.overrideAction === "clear") {
    await runWorkflow();
    return;
  }
  const panel = button.closest(".inline-override") || button.closest(".override-panel");
  const valueInput = panel.querySelector("[data-override-field='override_value']");
  const reasonInput = panel.querySelector("[data-override-field='reason']");
  const overrideValue = valueInput.value === "" ? null : Number(valueInput.value);
  const reason = reasonInput.value.trim() || "Inline final value edited in Site Wind Assessment.";
  if (!overrideValue || !reason) {
    workflowSummary.textContent = "Override value and reason are required.";
    return;
  }
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

function summaryItems(row) {
  const items = [...(row.detail_items || []), ...(row.calculation_inputs || [])];
  if (!items.length) return "<span class=\"muted\">No source details generated.</span>";
  return `<ul>${items.slice(0, 8).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
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
    final: "badge-pass",
  };
  return `<span class="badge ${classes[status] || "badge-neutral"}">${escapeHtml(text)}</span>`;
}

function titleCase(value) {
  return String(value || "").charAt(0).toUpperCase() + String(value || "").slice(1);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#039;");
}
