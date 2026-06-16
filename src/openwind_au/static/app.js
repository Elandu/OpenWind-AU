const form = document.getElementById("analysis-form");
const summary = document.getElementById("summary");
const profileFrame = document.getElementById("profile-frame");
const mapFrame = document.getElementById("map-frame");

function formPayload() {
  const data = new FormData(form);
  const payload = {
    address: data.get("address") || null,
    latitude: data.get("latitude") ? Number(data.get("latitude")) : null,
    longitude: data.get("longitude") ? Number(data.get("longitude")) : null,
    building_height_m: Number(data.get("building_height_m")),
    radius_m: Number(data.get("radius_m")),
    radial_count: Number(data.get("radial_count")),
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

  try {
    const resultResponse = await postJson("/api/analyse", payload);
    const result = await resultResponse.json();
    summary.textContent = JSON.stringify({
      site: result.site,
      feature_count: result.features.length,
      features: result.features.slice(0, 10),
      disclaimer: result.disclaimer,
    }, null, 2);

    const profileResponse = await postJson("/api/plots/profile", payload);
    profileFrame.srcdoc = await profileResponse.text();

    const mapResponse = await postJson("/api/maps/site", payload);
    mapFrame.srcdoc = await mapResponse.text();
  } catch (error) {
    summary.textContent = `Analysis failed: ${error.message}`;
  }
});
