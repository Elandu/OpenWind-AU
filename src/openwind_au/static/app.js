const form = document.getElementById("analysis-form");
const summary = document.getElementById("summary");
const profileFrame = document.getElementById("profile-frame");
const mapFrame = document.getElementById("map-frame");
const profileSummary = document.getElementById("profile-summary");
const topographySummary = document.getElementById("topography-summary");
const obstructionTable = document.getElementById("obstruction-table");
const obstructionWarning = document.getElementById("obstruction-warning");
const obstructionCsv = document.getElementById("obstruction-csv");
const obstructionJson = document.getElementById("obstruction-json");
const obstructionExport = document.getElementById("obstruction-export");

let reviewedObstructions = [];
let currentObstructionInventory = null;

function formPayload() {
  const data = new FormData(form);
  const payload = {
    address: data.get("address") || null,
    latitude: data.get("latitude") ? Number(data.get("latitude")) : null,
    longitude: data.get("longitude") ? Number(data.get("longitude")) : null,
    building_height_m: Number(data.get("building_height_m")),
    radius_m: Number(data.get("radius_m")),
    sample_interval_m: Number(data.get("sample_interval_m")),
  };
  if (!payload.address) delete payload.address;
  if (payload.latitude === null) delete payload.latitude;
  if (payload.longitude === null) delete payload.longitude;
  return payload;
}

function manualOverrides() {
  return reviewedObstructions
    .filter((item) => item.height_source === "manual_override")
    .map((item) => ({
      obstruction_id: item.obstruction_id,
      height_m: item.height_m,
      building_levels: item.building_levels,
      height_source: "manual_review",
      notes: "Reviewed in browser",
    }));
}

function obstructionPayload() {
  const data = new FormData(form);
  const payload = {
    address: data.get("address") || null,
    latitude: data.get("latitude") ? Number(data.get("latitude")) : null,
    longitude: data.get("longitude") ? Number(data.get("longitude")) : null,
    radius_m: Number(data.get("obstruction_radius_m") || 500),
    default_storey_height_m: Number(data.get("default_storey_height_m") || 3),
    manual_overrides: manualOverrides(),
  };
  if (!payload.address) delete payload.address;
  if (payload.latitude === null) delete payload.latitude;
  if (payload.longitude === null) delete payload.longitude;
  return payload;
}

function combinedMapPayload() {
  const data = new FormData(form);
  return {
    ...formPayload(),
    obstruction_radius_m: Number(data.get("obstruction_radius_m") || 500),
    default_storey_height_m: Number(data.get("default_storey_height_m") || 3),
    manual_overrides: manualOverrides(),
  };
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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = formPayload();
  const mapPayload = combinedMapPayload();
  summary.textContent = "Running analysis...";
  profileFrame.removeAttribute("srcdoc");
  mapFrame.removeAttribute("srcdoc");
  profileSummary.innerHTML = "<p>Running terrain profile analysis...</p>";
  topographySummary.innerHTML = "<tr><td colspan=\"10\">Running topographic screening...</td></tr>";
  obstructionTable.innerHTML = "<tr><td colspan=\"7\">Querying building footprints...</td></tr>";
  obstructionWarning.textContent = "Querying building footprints and height tags...";

  try {
    const resultResponse = await postJson("/api/analyse", payload);
    const result = await resultResponse.json();
    const significantFeatures = result.features.filter(
      (feature) => feature.feature_type !== "no significant feature",
    );
    summary.textContent = JSON.stringify({
      site: result.site,
      profile_directions: result.profiles.map((profile) => profile.direction),
      topographic_screening_count: result.features.length,
      candidate_feature_count: significantFeatures.length,
      topographic_screening: result.features,
      disclaimer: result.disclaimer,
    }, null, 2);
    renderProfileSummary(result.profiles);
    renderTopographySummary(result.features);

    const profileResponse = await postJson("/api/plots/profile", payload);
    profileFrame.srcdoc = await profileResponse.text();

    await runObstructionInventory();

    const mapResponse = await postJson("/api/map/combined", mapPayload);
    mapFrame.srcdoc = await mapResponse.text();
  } catch (error) {
    summary.textContent = `Analysis failed: ${error.message}`;
    profileSummary.innerHTML = "<p>Analysis failed.</p>";
    topographySummary.innerHTML = "<tr><td colspan=\"10\">Analysis failed.</td></tr>";
    obstructionTable.innerHTML = "<tr><td colspan=\"7\">Analysis failed.</td></tr>";
    obstructionWarning.textContent = "Obstruction inventory was not run.";
  }
});

function renderProfileSummary(profiles) {
  profileSummary.innerHTML = profiles.map((profile) => `
    <article class="profile-card">
      <h3>${profile.direction}</h3>
      <dl>
        <div><dt>Azimuth</dt><dd>${profile.azimuth_deg.toFixed(0)} deg</dd></div>
        <div><dt>Endpoint</dt><dd>${profile.endpoint_latitude.toFixed(5)}, ${profile.endpoint_longitude.toFixed(5)}</dd></div>
        <div><dt>Min RL</dt><dd>${profile.min_elevation_m.toFixed(2)} m</dd></div>
        <div><dt>Max RL</dt><dd>${profile.max_elevation_m.toFixed(2)} m</dd></div>
        <div><dt>Avg slope</dt><dd>${profile.average_slope.toFixed(4)}</dd></div>
      </dl>
    </article>
  `).join("");
}

function renderTopographySummary(features) {
  topographySummary.innerHTML = features.map((feature) => `
    <tr>
      <td>${feature.direction}</td>
      <td>${feature.feature_type}</td>
      <td>${feature.site_rl_m.toFixed(2)} m</td>
      <td>${feature.crest_rl_m.toFixed(2)} m</td>
      <td>${feature.base_rl_m.toFixed(2)} m</td>
      <td>${feature.h_m.toFixed(2)} m</td>
      <td>${feature.lu_m.toFixed(1)} m</td>
      <td>${feature.x_m.toFixed(1)} m</td>
      <td>${feature.average_upwind_slope.toFixed(3)}</td>
      <td>${feature.confidence}</td>
    </tr>
  `).join("");
}

async function runObstructionInventory() {
  const payload = obstructionPayload();
  const inventoryResponse = await postJson("/api/obstructions/inventory", payload);
  const inventory = await inventoryResponse.json();
  currentObstructionInventory = inventory;
  reviewedObstructions = inventory.obstructions;
  renderObstructionInventory(inventory);
}

function renderObstructionInventory(inventory) {
  const missing = inventory.obstructions.filter((item) => item.height_m === null).length;
  const warnings = inventory.warnings || [];
  const status =
    inventory.data_source_status === "unavailable"
      ? "Building footprint source unavailable. "
      : "";
  obstructionWarning.textContent = `${status}${inventory.obstructions.length} building footprints found within ${inventory.input?.radius_m || "the selected"} m. ${missing} require verified heights. Ms is not calculated.${warnings.length ? ` ${warnings[0]}` : ""}`;
  if (inventory.obstructions.length === 0) {
    obstructionTable.innerHTML = inventory.data_source_status === "unavailable"
      ? "<tr><td colspan=\"7\">Building footprints could not be retrieved. Try a smaller obstruction radius or import reviewed obstruction data after the footprint source is available.</td></tr>"
      : "<tr><td colspan=\"7\">No building footprints found in the selected radius.</td></tr>";
    return;
  }
  obstructionTable.innerHTML = inventory.obstructions.map((item) => obstructionRow(item)).join("");
  obstructionTable.querySelectorAll("input[data-id]").forEach((input) => {
    input.addEventListener("change", () => updateObstructionFromInput(input));
  });
}

function obstructionRow(item) {
  const heightValue = item.height_m === null ? "" : item.height_m.toFixed(2);
  const levelsValue = item.building_levels === null ? "" : item.building_levels;
  const missingClass = item.height_m === null ? "status-fail" : `status-${confidenceStatus(item.confidence)}`;
  return `
    <tr>
      <td>${item.obstruction_id}</td>
      <td>${item.distance_m.toFixed(1)} m</td>
      <td>${item.bearing_deg.toFixed(0)} deg</td>
      <td><input data-id="${item.obstruction_id}" data-field="height_m" type="number" step="0.1" value="${heightValue}" placeholder="missing" /></td>
      <td><input data-id="${item.obstruction_id}" data-field="building_levels" type="number" step="0.1" value="${levelsValue}" /></td>
      <td>${item.height_source}</td>
      <td class="${missingClass}">${item.confidence}${item.manual_review_required ? " review" : ""}</td>
    </tr>
  `;
}

function confidenceStatus(confidence) {
  if (confidence === "verified" || confidence === "high") return "pass";
  if (confidence === "medium") return "warn";
  return "fail";
}

function updateObstructionFromInput(input) {
  const item = reviewedObstructions.find(
    (obstruction) => obstruction.obstruction_id === input.dataset.id,
  );
  if (!item) return;
  const value = input.value === "" ? null : Number(input.value);
  if (input.dataset.field === "height_m") {
    item.height_m = value;
  }
  if (input.dataset.field === "building_levels") {
    item.building_levels = value;
    if (item.height_m === null && value !== null) {
      item.height_m = value * Number(document.getElementById("default_storey_height_m").value || 3);
    }
  }
  item.height_source = "manual_override";
  item.confidence = item.height_m === null ? "unknown" : "verified";
  item.manual_review_required = item.height_m === null;
  currentObstructionInventory = {
    ...(currentObstructionInventory || {}),
    obstructions: reviewedObstructions,
  };
  renderObstructionInventory(currentObstructionInventory);
}

obstructionCsv.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const overrides = parseCsvOverrides(await file.text());
  applyBrowserOverrides(overrides);
});

obstructionJson.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const imported = JSON.parse(await file.text());
  if (!Array.isArray(imported) && imported.site && imported.input) {
    currentObstructionInventory = imported;
    reviewedObstructions = imported.obstructions || [];
    renderObstructionInventory(currentObstructionInventory);
    return;
  }
  applyBrowserOverrides(Array.isArray(imported) ? imported : imported.obstructions || []);
});

obstructionExport.addEventListener("click", () => {
  const exportData = {
    ...(currentObstructionInventory || {}),
    obstructions: reviewedObstructions,
  };
  const blob = new Blob([JSON.stringify(exportData, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "openwind-au-reviewed-obstructions.json";
  link.click();
  URL.revokeObjectURL(url);
});

function parseCsvOverrides(text) {
  const lines = text.split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) return [];
  const headers = lines[0].split(",").map((header) => header.trim());
  return lines.slice(1).map((line) => {
    const values = line.split(",");
    return Object.fromEntries(headers.map((header, index) => [header, values[index]?.trim()]));
  });
}

function applyBrowserOverrides(overrides) {
  for (const override of overrides) {
    const id = override.obstruction_id;
    let item = reviewedObstructions.find((obstruction) => obstruction.obstruction_id === id);
    if (!item && override.footprint_geometry) {
      item = { ...override };
      reviewedObstructions.push(item);
    }
    if (!item) continue;
    item.height_m = parseOptionalNumber(override.height_m);
    item.building_levels = parseOptionalNumber(override.building_levels);
    if (item.height_m === null && item.building_levels !== null) {
      item.height_m = item.building_levels * Number(document.getElementById("default_storey_height_m").value || 3);
    }
    item.height_source = "manual_override";
    item.confidence = item.height_m === null ? "unknown" : "verified";
    item.manual_review_required = item.height_m === null;
  }
  const inventory = {
    ...(currentObstructionInventory || {}),
    input: currentObstructionInventory?.input || { radius_m: "imported" },
    site: currentObstructionInventory?.site,
    obstructions: reviewedObstructions,
    data_source_status: currentObstructionInventory?.data_source_status || "ok",
    warnings: currentObstructionInventory?.warnings || [],
  };
  currentObstructionInventory = inventory;
  renderObstructionInventory(inventory);
}

function parseOptionalNumber(value) {
  if (value === undefined || value === null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
