const form = document.getElementById("analysis-form");
const summary = document.getElementById("summary");
const profileFrame = document.getElementById("profile-frame");
const mapFrame = document.getElementById("map-frame");
const profileSummary = document.getElementById("profile-summary");
const topographySummary = document.getElementById("topography-summary");
const obstructionTable = document.getElementById("obstruction-table");
const obstructionWarning = document.getElementById("obstruction-warning");
const shieldingSectorTable = document.getElementById("shielding-sector-table");
const shieldingThresholdNote = document.getElementById("shielding-threshold-note");
const msExplanationSector = document.getElementById("ms-explanation-sector");
const msExplanation = document.getElementById("ms-explanation");
const terrainCategoryTable = document.getElementById("terrain-category-table");
const mzCatTable = document.getElementById("mzcat-table");
const terrainCategoryFrame = document.getElementById("terrain-category-frame");
const obstructionCsv = document.getElementById("obstruction-csv");
const obstructionJson = document.getElementById("obstruction-json");
const obstructionExport = document.getElementById("obstruction-export");
const obstructionFilter = document.getElementById("obstruction-filter");
const mapDisplayMode = document.getElementById("map_display_mode");
const obstructionQualityTable = document.getElementById("obstruction-quality-table");

let reviewedObstructions = [];
let currentObstructionInventory = null;
let currentTerrainCategoryEvidence = null;

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
    .filter((item) => item.height_source === "manual_verified")
    .map((item) => ({
      obstruction_id: item.obstruction_id,
      height_m: item.height_m,
      building_levels: item.building_levels,
      height_source: "manual_verified",
      notes: "Reviewed in browser",
    }));
}

function reviewedFootprints() {
  return reviewedObstructions
    .filter((item) => item.footprint_source === "manual_reviewed" && item.footprint_geometry)
    .map((item) => ({
      id: item.obstruction_id,
      geometry: item.footprint_geometry,
      classification: item.classification || "unknown",
      height_m: item.height_m,
      building_levels: item.building_levels,
      source: "reviewed obstruction JSON",
      notes: (item.notes || []).join("; "),
    }));
}

function obstructionPayload() {
  const data = new FormData(form);
  const payload = {
    address: data.get("address") || null,
    latitude: data.get("latitude") ? Number(data.get("latitude")) : null,
    longitude: data.get("longitude") ? Number(data.get("longitude")) : null,
    radius_m: Number(data.get("obstruction_radius_m") || 500),
    building_height_m: Number(data.get("building_height_m")),
    default_storey_height_m: Number(data.get("default_storey_height_m") || 3),
    residential_storey_height_m: Number(data.get("residential_storey_height_m") || 3),
    residential_two_storey_height_m: Number(data.get("residential_two_storey_height_m") || 6),
    commercial_storey_height_m: Number(data.get("commercial_storey_height_m") || 4),
    manual_overrides: manualOverrides(),
    reviewed_footprints: reviewedFootprints(),
    map_display_mode: data.get("map_display_mode") || "nearest_500",
    map_max_display_obstructions: 500,
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
    residential_storey_height_m: Number(data.get("residential_storey_height_m") || 3),
    residential_two_storey_height_m: Number(data.get("residential_two_storey_height_m") || 6),
    commercial_storey_height_m: Number(data.get("commercial_storey_height_m") || 4),
    manual_overrides: manualOverrides(),
    reviewed_footprints: reviewedFootprints(),
    map_display_mode: data.get("map_display_mode") || "nearest_500",
    map_max_display_obstructions: 500,
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
  terrainCategoryFrame.removeAttribute("srcdoc");
  profileSummary.innerHTML = "<p>Running terrain profile analysis...</p>";
  topographySummary.innerHTML = "<tr><td colspan=\"10\">Running topographic screening...</td></tr>";
  obstructionTable.innerHTML = "<tr><td colspan=\"10\">Querying obstruction footprints...</td></tr>";
  obstructionQualityTable.innerHTML = "<tr><td>Querying obstruction source quality...</td></tr>";
  shieldingSectorTable.innerHTML = "<tr><td colspan=\"10\">Preparing shielding sectors...</td></tr>";
  terrainCategoryTable.innerHTML = "<tr><td colspan=\"12\">Preparing terrain category evidence...</td></tr>";
  obstructionWarning.textContent = "Querying obstruction footprints and height tags...";

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
    await runTerrainCategoryEvidence(mapPayload);

    const mapResponse = await postJson("/api/map/combined", mapPayload);
    mapFrame.srcdoc = await mapResponse.text();
  } catch (error) {
    summary.textContent = `Analysis failed: ${error.message}`;
    profileSummary.innerHTML = "<p>Analysis failed.</p>";
    topographySummary.innerHTML = "<tr><td colspan=\"10\">Analysis failed.</td></tr>";
    obstructionTable.innerHTML = "<tr><td colspan=\"10\">Analysis failed.</td></tr>";
    obstructionQualityTable.innerHTML = "<tr><td>Analysis failed.</td></tr>";
    shieldingSectorTable.innerHTML = "<tr><td colspan=\"10\">Analysis failed.</td></tr>";
    terrainCategoryTable.innerHTML = "<tr><td colspan=\"12\">Analysis failed.</td></tr>";
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

async function runTerrainCategoryEvidence(payload) {
  const evidenceResponse = await postJson("/api/terrain-category/evidence", payload);
  const evidence = await evidenceResponse.json();
  currentTerrainCategoryEvidence = evidence;
  renderTerrainCategoryEvidence(evidence);

  const mapResponse = await postJson("/api/terrain-category/map", payload);
  terrainCategoryFrame.srcdoc = await mapResponse.text();
}

function renderObstructionInventory(inventory) {
  const missing = inventory.obstructions.filter((item) => isMissingSourceHeight(item)).length;
  const warnings = inventory.warnings || [];
  const status =
    inventory.data_source_status === "unavailable"
      ? "Building footprint source unavailable. "
      : "";
  obstructionWarning.textContent = `${status}${inventory.obstructions.length} obstruction footprints found within ${inventory.input?.radius_m || "the selected"} m. ${missing} require verified heights. Indicative Ms values are preliminary.${warnings.length ? ` ${warnings[0]}` : ""}`;
  renderObstructionDataQuality(inventory.data_quality);
  renderShieldingSectors(inventory.shielding_sectors || []);
  if (inventory.obstructions.length === 0) {
    obstructionTable.innerHTML = inventory.data_source_status === "unavailable"
      ? "<tr><td colspan=\"10\">Obstruction footprints could not be retrieved. Try a smaller obstruction radius or import reviewed obstruction data after the footprint source is available.</td></tr>"
      : "<tr><td colspan=\"10\">No obstruction footprints found in the selected radius.</td></tr>";
    return;
  }
  const filtered = filterObstructions(inventory.obstructions);
  if (!filtered.length) {
    obstructionTable.innerHTML = "<tr><td colspan=\"10\">No obstructions match the selected filter.</td></tr>";
    return;
  }
  obstructionTable.innerHTML = filtered.map((item) => obstructionRow(item)).join("");
  obstructionTable.querySelectorAll("input[data-id]").forEach((input) => {
    input.addEventListener("change", () => updateObstructionFromInput(input));
  });
}

function renderObstructionDataQuality(dataQuality) {
  if (!dataQuality) {
    obstructionQualityTable.innerHTML = "<tr><td>No obstruction source diagnostics available.</td></tr>";
    return;
  }
  const excludedReasons = Object.entries(dataQuality.excluded_reasons || {})
    .map(([reason, count]) => `${escapeHtml(reason)} (${count})`)
    .join(", ") || "None";
  const sources = Object.entries(dataQuality.source_summary || {})
    .map(([source, count]) => `${escapeHtml(source)} (${count})`)
    .join(", ") || "None";
  const rawCounts = Object.entries(dataQuality.raw_overpass_counts || {})
    .map(([name, count]) => `${escapeHtml(name)}: ${count}`)
    .join(", ") || "None";
  const parsedCounts = Object.entries(dataQuality.parsed_counts || {})
    .map(([name, count]) => `${escapeHtml(name)}: ${count}`)
    .join(", ") || "None";
  const warnings = (dataQuality.warnings || []).map((warning) => escapeHtml(warning)).join("<br>") || "None";
  const microsoftFiles = (dataQuality.microsoft_cache_files || [])
    .map((path) => escapeHtml(path))
    .join("<br>") || "None";
  obstructionQualityTable.innerHTML = `
    <tr><th>Query centre</th><td>${formatQueryCentre(dataQuality.query_centre)}</td></tr>
    <tr><th>Query radius</th><td>${dataQuality.query_radius_m || "-"} m</td></tr>
    <tr><th>Microsoft source status</th><td>${escapeHtml(dataQuality.microsoft_source_status || "unavailable")}</td></tr>
    <tr><th>Microsoft cache status</th><td>${escapeHtml(dataQuality.microsoft_cache_status || "miss")}</td></tr>
    <tr><th>Microsoft cache path</th><td>${escapeHtml(dataQuality.microsoft_cache_path || "-")}</td></tr>
    <tr><th>Microsoft cache files</th><td>${microsoftFiles}</td></tr>
    <tr><th>Raw Overpass counts</th><td>${rawCounts}</td></tr>
    <tr><th>Parsed counts</th><td>${parsedCounts}</td></tr>
    <tr><th>Total Microsoft building footprints found</th><td>${dataQuality.total_microsoft_building_footprints_found || 0}</td></tr>
    <tr><th>Total OSM building footprints found</th><td>${dataQuality.total_osm_building_footprints_found}</td></tr>
    <tr><th>OSM fallback used</th><td>${dataQuality.osm_fallback_used ? "Yes" : "No"}</td></tr>
    <tr><th>Total vegetation polygons found</th><td>${dataQuality.total_vegetation_polygons_found}</td></tr>
    <tr><th>Total usable obstruction polygons</th><td>${dataQuality.total_usable_obstruction_polygons}</td></tr>
    <tr><th>Number excluded</th><td>${dataQuality.number_excluded}</td></tr>
    <tr><th>Reason for exclusion</th><td>${excludedReasons}</td></tr>
    <tr><th>Percentage with height data</th><td>${(dataQuality.percentage_with_height_data || 0).toFixed(1)}%</td></tr>
    <tr><th>Percentage requiring manual review</th><td>${(dataQuality.percentage_requiring_manual_review || 0).toFixed(1)}%</td></tr>
    <tr><th>Source summary</th><td>${sources}</td></tr>
    <tr><th>Duplicate overlaps removed</th><td>${dataQuality.duplicate_overlap_count || 0}</td></tr>
    <tr><th>Warnings</th><td>${warnings}</td></tr>
  `;
}

function isMissingSourceHeight(item) {
  return ["missing", "ESTIMATED"].includes(item.height_source) || (
    item.raw_source_height_m === null &&
    !["manual_verified", "IMPORTED", "OSM_HEIGHT", "OSM_LEVELS", "DSM_DTM"].includes(item.raw_source_height_source)
  );
}

function formatQueryCentre(queryCentre) {
  if (!queryCentre) return "-";
  return `${Number(queryCentre.latitude).toFixed(6)}, ${Number(queryCentre.longitude).toFixed(6)}`;
}

function renderTerrainCategoryEvidence(evidence) {
  const directions = evidence.directions || [];
  if (!directions.length) {
    terrainCategoryTable.innerHTML = "<tr><td colspan=\"12\">No terrain category evidence generated.</td></tr>";
    renderMzCatAssessment([]);
    return;
  }
  terrainCategoryTable.innerHTML = directions.map((direction) => `
    <tr>
      <td>${direction.direction}</td>
      <td>${direction.built_up_area_percentage.toFixed(1)}%</td>
      <td>${direction.vegetation_area_percentage.toFixed(1)}%</td>
      <td>${direction.open_terrain_percentage.toFixed(1)}%</td>
      <td>${formatMaybeNumber(direction.average_obstruction_height_m, " m")}</td>
      <td>${formatMaybeNumber(direction.maximum_obstruction_height_m, " m")}</td>
      <td>${direction.obstruction_density_per_km2.toFixed(1)}/km2</td>
      <td>${formatMaybeNumber(direction.average_obstruction_spacing_m, " m")}</td>
      <td>${direction.directional_fetch_distance_m.toFixed(0)} m</td>
      <td>${badge("neutral", direction.suggested_category_range)}</td>
      <td>${badge(direction.confidence, direction.confidence)}</td>
      <td>${(direction.warnings || []).join(" ")}</td>
    </tr>
  `).join("");
  renderMzCatAssessment(evidence.mzcat_assessment || []);
}

function renderMzCatAssessment(assessments) {
  if (!mzCatTable) return;
  if (!assessments.length) {
    mzCatTable.innerHTML = "<tr><td colspan=\"6\">Indicative Mz,cat evidence will appear after analysis.</td></tr>";
    return;
  }
  mzCatTable.innerHTML = assessments.map((assessment) => `
    <tr>
      <td>${assessment.direction}</td>
      <td>${badge("neutral", assessment.controlling_category_range || assessment.suggested_terrain_category_range)}</td>
      <td>${assessment.lower_indicative_mzcat.toFixed(3)}-${assessment.upper_indicative_mzcat.toFixed(3)}</td>
      <td>${badge(assessment.confidence, assessment.confidence)}</td>
      <td><ul>${(assessment.reasoning || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></td>
      <td>${(assessment.warnings || []).map(escapeHtml).join(" ")}</td>
    </tr>
  `).join("");
}

function renderShieldingSectors(sectors) {
  if (!sectors.length) {
    shieldingThresholdNote.textContent = "Current subject building height threshold z will appear after analysis.";
    shieldingSectorTable.innerHTML = "<tr><td colspan=\"11\">No shielding sectors calculated.</td></tr>";
    renderMsExplanation([]);
    return;
  }
  const subjectHeight = sectors[0].subject_height_m;
  shieldingThresholdNote.textContent = `Current subject building height threshold z = ${subjectHeight.toFixed(2)} m. Obstructions with selected hs >= z are included in preliminary shielding.`;
  shieldingSectorTable.innerHTML = sectors.map((sector) => `
    <tr>
      <td>${sector.direction}</td>
      <td>${sector.sector_start_deg.toFixed(1)}-${sector.sector_end_deg.toFixed(1)} deg</td>
      <td>${sector.sector_radius_m.toFixed(1)} m</td>
      <td>${sector.ns}</td>
      <td>${formatMaybeNumber(sector.average_hs_m, " m")}</td>
      <td>${formatMaybeNumber(sector.average_bs_m, " m")}</td>
      <td>${formatMaybeNumber(sector.ls_m, " m")}</td>
      <td>${formatMaybeNumber(sector.s, "")}</td>
      <td>${sector.indicative_ms.toFixed(3)}</td>
      <td>${rejectionSummary(sector)}</td>
      <td>
        ${badge(sector.overall_confidence || "unknown", `confidence ${sector.overall_confidence || "unknown"}`)}
        <span class="muted">high ${sector.high_confidence_count || 0}, est ${sector.estimated_height_count || 0}, unknown ${sector.unknown_height_count || 0}</span>
      </td>
    </tr>
    ${(sector.warnings || []).length ? `<tr><td></td><td colspan="10">${sector.warnings.join(" ")}</td></tr>` : ""}
  `).join("");
  renderMsExplanation(sectors);
}

function rejectionSummary(sector) {
  const counts = sector.rejection_reason_counts || {};
  const entries = Object.entries(counts).filter(([, count]) => count);
  if (!entries.length) return "-";
  return entries.map(([reason, count]) => `${reasonLabel(reason)} ${count}`).join(", ");
}

function renderMsExplanation(sectors) {
  if (!msExplanationSector || !msExplanation) return;
  if (!sectors.length) {
    msExplanationSector.innerHTML = "";
    msExplanation.textContent = "Run an analysis to inspect shielding rejection reasons.";
    return;
  }
  const previous = msExplanationSector.value;
  msExplanationSector.innerHTML = sectors.map((sector) =>
    `<option value="${sector.direction}">${sector.direction} - Ms ${sector.indicative_ms.toFixed(3)}</option>`
  ).join("");
  const selectedDirection = sectors.some((sector) => sector.direction === previous) ? previous : sectors[0].direction;
  msExplanationSector.value = selectedDirection;
  const sector = sectors.find((item) => item.direction === selectedDirection) || sectors[0];
  const rejected = sector.rejected_obstructions || [];
  const reasonRows = Object.entries(sector.rejection_reason_counts || {})
    .filter(([, count]) => count)
    .sort((a, b) => b[1] - a[1])
    .map(([reason, count]) => `<li>${reasonLabel(reason)}: ${count}</li>`)
    .join("");
  const rejectedRows = rejected.length
    ? `<table class="debug-table"><thead><tr><th>ID</th><th>Reason</th><th>Distance</th><th>Bearing</th><th>Height</th><th>Source</th></tr></thead><tbody>${rejected.map((item) => `
        <tr>
          <td>${escapeHtml(item.obstruction_id)}</td>
          <td>${reasonLabel(item.reason)}</td>
          <td>${formatMaybeNumber(item.distance_m, " m")}</td>
          <td>${formatMaybeNumber(item.bearing_deg, " deg")}</td>
          <td>${formatMaybeNumber(item.height_m, " m")}</td>
          <td>${sourceLabel(item.height_source)}</td>
        </tr>
      `).join("")}</tbody></table>`
    : "<p>No rejected in-sector obstructions were recorded.</p>";
  msExplanation.innerHTML = `
    <p>${sector.direction} uses azimuth ${sector.wind_direction_deg.toFixed(1)} deg, upwind sector ${sector.sector_start_deg.toFixed(1)}-${sector.sector_end_deg.toFixed(1)} deg, radius ${sector.sector_radius_m.toFixed(1)} m, z ${sector.subject_height_m.toFixed(2)} m.</p>
    <p>${sector.total_obstructions_in_sector || 0} obstructions are in sector; ${sector.usable_height_count || 0} have usable height; ${sector.included_as_shielding_count || sector.ns || 0} are included as shielding.</p>
    <h4>Top rejection reasons</h4>
    ${reasonRows ? `<ul>${reasonRows}</ul>` : "<p>No rejection reasons were recorded.</p>"}
    <h4>First rejected obstructions</h4>
    ${rejectedRows}
  `;
}

function reasonLabel(reason) {
  return {
    height_missing: "height missing",
    height_below_subject: "height below z",
    excluded_or_manual_review: "excluded/manual review",
  }[reason] || reason;
}

function obstructionRow(item) {
  const heightValue = item.height_m === null ? "" : item.height_m.toFixed(2);
  const dsmHeightValue = item.obstruction_height_m == null ? "-" : item.obstruction_height_m.toFixed(2);
  const levelsValue = item.building_levels === null ? "" : item.building_levels;
  const reviewRequired = item.review_required ?? item.manual_review_required;
  return `
    <tr>
      <td>${item.obstruction_id}</td>
      <td>${item.classification || "unknown"}</td>
      <td>${item.distance_m.toFixed(1)} m</td>
      <td>${item.bearing_deg.toFixed(0)} deg</td>
      <td><input data-id="${item.obstruction_id}" data-field="height_m" type="number" step="0.1" value="${heightValue}" placeholder="missing" /></td>
      <td>${dsmHeightValue}</td>
      <td><input data-id="${item.obstruction_id}" data-field="building_levels" type="number" step="0.1" value="${levelsValue}" /></td>
      <td>${badge(item.height_source, sourceLabel(item.height_source))}</td>
      <td>${badge(item.confidence || "unknown", item.confidence || "unknown")}</td>
      <td>${reviewRequired ? badge("review", "review required") : badge("ok", "reviewed")}</td>
    </tr>
  `;
}

function filterObstructions(obstructions) {
  const selected = obstructionFilter?.value || "all";
  if (selected === "all") return obstructions;
  if (selected === "review_required") {
    return obstructions.filter((item) => item.review_required ?? item.manual_review_required);
  }
  return obstructions.filter((item) => (item.confidence || "unknown") === selected);
}

function badge(kind, text) {
  return `<span class="badge badge-${badgeClass(kind)}">${text}</span>`;
}

function badgeClass(kind) {
  if (["high", "manual_verified", "DSM_DTM", "IMPORTED", "ok"].includes(kind)) return "pass";
  if (["medium", "OSM_HEIGHT", "OSM_LEVELS"].includes(kind)) return "warn";
  if (["low", "ESTIMATED", "review"].includes(kind)) return "fail";
  return "neutral";
}

function sourceLabel(source) {
  return {
    manual_verified: "Manual Verified",
    DSM_DTM: "DSM-DTM",
    OSM_HEIGHT: "OSM Height",
    OSM_LEVELS: "OSM Levels",
    IMPORTED: "Imported",
    ESTIMATED: "Estimated",
    missing: "Unknown",
  }[source] || source || "Unknown";
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
  item.height_source = "manual_verified";
  item.selected_height_m = item.height_m;
  item.raw_source_height_m = item.height_m;
  item.raw_source_height_source = item.height_m === null ? null : "manual_verified";
  item.confidence = item.height_m === null ? "unknown" : "high";
  item.manual_review_required = item.height_m === null;
  item.review_required = item.height_m === null;
  currentObstructionInventory = {
    ...(currentObstructionInventory || {}),
    obstructions: reviewedObstructions,
  };
  refreshShieldingSectors();
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
      item.footprint_source = "manual_reviewed";
      reviewedObstructions.push(item);
    }
    if (!item) continue;
    item.height_m = parseOptionalNumber(override.height_m);
    item.building_levels = parseOptionalNumber(override.building_levels);
    if (item.height_m === null && item.building_levels !== null) {
      item.height_m = item.building_levels * Number(document.getElementById("default_storey_height_m").value || 3);
    }
    item.height_source = "manual_verified";
    item.selected_height_m = item.height_m;
    item.raw_source_height_m = item.height_m;
    item.raw_source_height_source = item.height_m === null ? null : "manual_verified";
    item.confidence = item.height_m === null ? "unknown" : "high";
    item.manual_review_required = item.height_m === null;
    item.review_required = item.height_m === null;
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
  refreshShieldingSectors();
  renderObstructionInventory(inventory);
}

function parseOptionalNumber(value) {
  if (value === undefined || value === null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function refreshShieldingSectors() {
  if (!currentObstructionInventory?.input?.building_height_m) return;
  const sectors = calculateShieldingSectors(
    currentObstructionInventory.site,
    reviewedObstructions,
    currentObstructionInventory.input.building_height_m,
  );
  currentObstructionInventory.shielding_sectors = sectors;
}

function calculateShieldingSectors(site, obstructions, subjectHeight) {
  const directions = [
    ["N", 0],
    ["NE", 45],
    ["E", 90],
    ["SE", 135],
    ["S", 180],
    ["SW", 225],
    ["W", 270],
    ["NW", 315],
  ];
  return directions.map(([direction, azimuth]) => shieldingSector(site, obstructions, subjectHeight, direction, azimuth));
}

function shieldingSector(site, obstructions, subjectHeight, direction, azimuth) {
  const radius = 20 * subjectHeight;
  const sectorCandidates = obstructions.filter((item) =>
    item.distance_m <= radius &&
    angleDelta(item.bearing_deg, azimuth) <= 22.5
  );
  const rejected = [];
  const rejectionReasonCounts = {};
  const included = [];
  let usableHeightCount = 0;
  sectorCandidates.forEach((item) => {
    const height = shieldingHeight(item);
    if (height === null) {
      recordRejection(rejected, rejectionReasonCounts, item, "height_missing");
      return;
    }
    usableHeightCount += 1;
    if (height < subjectHeight) {
      recordRejection(rejected, rejectionReasonCounts, item, "height_below_subject", height);
      return;
    }
    included.push(item);
  });
  const ns = included.length;
  const unknownHeightCount = rejectionReasonCounts.height_missing || 0;
  if (!ns) {
    const emptySector = baseShieldingSector(direction, azimuth, radius, subjectHeight, 0, 1);
    addShieldingDebug(emptySector, sectorCandidates, usableHeightCount, rejectionReasonCounts, rejected);
    emptySector.unknown_height_count = unknownHeightCount;
    emptySector.overall_confidence = unknownHeightCount ? "unknown" : "low";
    emptySector.warnings = sectorConfidenceWarnings([], unknownHeightCount);
    return emptySector;
  }
  const averageHs = mean(included.map((item) => shieldingHeight(item)));
  const averageBs = mean(included.map((item) => footprintBreadthNormalToWind(item.footprint_geometry, site, azimuth)));
  const ls = subjectHeight * ((10 / ns) + 5);
  const s = averageHs > 0 && averageBs > 0 ? ls / Math.sqrt(averageHs * averageBs) : null;
  const sector = baseShieldingSector(direction, azimuth, radius, subjectHeight, ns, s === null ? 1 : msFromS(s));
  const dsmIds = included.filter((item) => item.height_source === "DSM_DTM").map((item) => item.obstruction_id);
  const warningIds = included
    .filter((item) => ["low", "unknown"].includes(item.confidence) || (item.warnings || []).length)
    .map((item) => item.obstruction_id);
  const reviewRequired = included.filter((item) => item.review_required ?? item.manual_review_required);
  const vegetation = included.filter((item) => item.classification === "vegetation");
  const estimatedCount = included.filter((item) => item.height_source === "ESTIMATED").length;
  addShieldingDebug(sector, sectorCandidates, usableHeightCount, rejectionReasonCounts, rejected);
  sector.average_hs_m = averageHs;
  sector.average_bs_m = averageBs;
  sector.ls_m = ls;
  sector.s = s;
  sector.high_confidence_count = included.filter((item) => item.confidence === "high").length;
  sector.estimated_height_count = estimatedCount;
  sector.unknown_height_count = unknownHeightCount;
  sector.overall_confidence = overallShieldingConfidence(included, unknownHeightCount);
  sector.included_obstruction_ids = included.map((item) => item.obstruction_id);
  sector.warnings = [
    ...(dsmIds.length ? [`Sector uses DSM-DTM estimated obstruction heights for: ${dsmIds.join(", ")}`] : []),
    ...(estimatedCount ? ["Shielding assessment contains estimated obstruction heights."] : []),
    ...(dsmIds.length || estimatedCount ? ["Estimated or DSM-DTM heights are included for preliminary shielding only."] : []),
    ...(warningIds.length ? [`Sector includes low-confidence or warning-flagged obstructions: ${warningIds.join(", ")}`] : []),
    ...(reviewRequired.length > 1 ? ["Multiple shielding structures require manual review."] : []),
    ...(vegetation.length ? [`Vegetation appears as potential shielding and requires engineer review: ${vegetation.map((item) => item.obstruction_id).join(", ")}`] : []),
    ...sectorConfidenceWarnings(included, unknownHeightCount),
  ];
  return sector;
}

function shieldingHeight(item) {
  const height = item.selected_height_m ?? item.height_m;
  return height === null || height === undefined ? null : height;
}

function addShieldingDebug(sector, sectorCandidates, usableHeightCount, rejectionReasonCounts, rejected) {
  sector.total_obstructions_in_sector = sectorCandidates.length;
  sector.usable_height_count = usableHeightCount;
  sector.rejected_height_below_z_count = rejectionReasonCounts.height_below_subject || 0;
  sector.rejected_height_missing_count = rejectionReasonCounts.height_missing || 0;
  sector.rejected_excluded_manual_review_count = rejectionReasonCounts.excluded_or_manual_review || 0;
  sector.included_as_shielding_count = sector.ns;
  sector.rejection_reason_counts = rejectionReasonCounts;
  sector.rejected_obstructions = rejected.slice(0, 10);
}

function recordRejection(rejected, reasonCounts, item, reason, height = null) {
  reasonCounts[reason] = (reasonCounts[reason] || 0) + 1;
  if (rejected.length >= 10) return;
  rejected.push({
    obstruction_id: item.obstruction_id,
    reason,
    distance_m: item.distance_m,
    bearing_deg: item.bearing_deg,
    height_m: height,
    height_source: item.height_source,
    classification: item.classification,
    confidence: item.confidence,
    review_required: item.review_required ?? item.manual_review_required,
  });
}

function baseShieldingSector(direction, azimuth, radius, subjectHeight, ns, indicativeMs) {
  return {
    direction,
    wind_direction_deg: azimuth,
    sector_start_deg: normaliseBearing(azimuth - 22.5),
    sector_end_deg: normaliseBearing(azimuth + 22.5),
    sector_radius_m: radius,
    subject_height_m: subjectHeight,
    total_obstructions_in_sector: 0,
    usable_height_count: 0,
    rejected_height_below_z_count: 0,
    rejected_height_missing_count: 0,
    rejected_excluded_manual_review_count: 0,
    included_as_shielding_count: 0,
    ns,
    average_hs_m: null,
    average_bs_m: null,
    ls_m: null,
    s: null,
    indicative_ms: indicativeMs,
    high_confidence_count: 0,
    estimated_height_count: 0,
    unknown_height_count: 0,
    overall_confidence: "unknown",
    included_obstruction_ids: [],
    rejection_reason_counts: {},
    rejected_obstructions: [],
    notes: [],
    warnings: [],
  };
}

function overallShieldingConfidence(included, unknownHeightCount) {
  if (!included.length) return unknownHeightCount ? "unknown" : "low";
  if (unknownHeightCount || included.some((item) => ["low", "unknown"].includes(item.confidence))) {
    return "low";
  }
  if (included.some((item) => ["ESTIMATED", "DSM_DTM"].includes(item.height_source) || (item.review_required ?? item.manual_review_required))) {
    return "low";
  }
  if (included.every((item) => item.confidence === "high")) return "high";
  return "medium";
}

function sectorConfidenceWarnings(included, unknownHeightCount) {
  const warnings = [];
  if (unknownHeightCount) warnings.push(`${unknownHeightCount} in-sector obstructions have unknown heights.`);
  if (overallShieldingConfidence(included, unknownHeightCount) === "low") {
    warnings.push("Shielding confidence is low.");
  }
  return warnings;
}

function footprintBreadthNormalToWind(geometry, site, azimuth) {
  const coordinates = footprintProjectionCoordinates(geometry);
  if (coordinates.length < 2) return 0;
  const theta = azimuth * Math.PI / 180;
  const normalEast = Math.cos(theta);
  const normalNorth = -Math.sin(theta);
  const projections = coordinates.map(([lon, lat]) => {
    const [east, north] = localOffsetsMeters(lat, lon, site.latitude, site.longitude);
    return east * normalEast + north * normalNorth;
  });
  return Math.max(...projections) - Math.min(...projections);
}

function footprintProjectionCoordinates(geometry) {
  if (geometry?.type === "Polygon") return geometry.coordinates?.[0] || [];
  if (geometry?.type === "MultiPolygon") {
    return (geometry.coordinates || []).flatMap((polygon) => polygon?.[0] || []);
  }
  return [];
}

function localOffsetsMeters(lat, lon, originLat, originLon) {
  const earthRadius = 6371008.8;
  const east = toRadians(lon - originLon) * earthRadius * Math.cos(toRadians(originLat));
  const north = toRadians(lat - originLat) * earthRadius;
  return [east, north];
}

function msFromS(s) {
  if (s <= 1.5) return 0.7;
  if (s >= 12) return 1.0;
  const points = [[1.5, 0.7], [3, 0.8], [6, 0.9], [12, 1.0]];
  for (let i = 0; i < points.length - 1; i += 1) {
    const [s0, ms0] = points[i];
    const [s1, ms1] = points[i + 1];
    if (s <= s1) {
      return ms0 + ((s - s0) / (s1 - s0)) * (ms1 - ms0);
    }
  }
  return 1.0;
}

function angleDelta(a, b) {
  return Math.abs(((a - b + 180) % 360) - 180);
}

function normaliseBearing(value) {
  return ((value % 360) + 360) % 360;
}

function toRadians(value) {
  return value * Math.PI / 180;
}

function mean(values) {
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function formatMaybeNumber(value, suffix) {
  return value === null || value === undefined ? "-" : `${value.toFixed(2)}${suffix}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#039;");
}

obstructionFilter?.addEventListener("change", () => {
  if (currentObstructionInventory) renderObstructionInventory(currentObstructionInventory);
});

msExplanationSector?.addEventListener("change", () => {
  renderMsExplanation(currentObstructionInventory?.shielding_sectors || []);
});

mapDisplayMode?.addEventListener("change", async () => {
  if (!currentObstructionInventory?.site) return;
  mapFrame.removeAttribute("srcdoc");
  const mapResponse = await postJson("/api/map/combined", combinedMapPayload());
  mapFrame.srcdoc = await mapResponse.text();
});
