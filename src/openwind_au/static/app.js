const form = document.getElementById("analysis-form");
const summary = document.getElementById("summary");
const profileFrame = document.getElementById("profile-frame");
const mapFrame = document.getElementById("map-frame");
const profileSummary = document.getElementById("profile-summary");
const topographySummary = document.getElementById("topography-summary");

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
  summary.textContent = "Running analysis...";
  profileFrame.removeAttribute("srcdoc");
  mapFrame.removeAttribute("srcdoc");
  profileSummary.innerHTML = "<p>Running terrain profile analysis...</p>";
  topographySummary.innerHTML = "<tr><td colspan=\"10\">Running topographic screening...</td></tr>";

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

    const mapResponse = await postJson("/api/maps/site", payload);
    mapFrame.srcdoc = await mapResponse.text();
  } catch (error) {
    summary.textContent = `Analysis failed: ${error.message}`;
    profileSummary.innerHTML = "<p>Analysis failed.</p>";
    topographySummary.innerHTML = "<tr><td colspan=\"10\">Analysis failed.</td></tr>";
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
