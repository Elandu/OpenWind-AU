const runValidation = document.getElementById("run-validation");
const validationSummary = document.getElementById("validation-summary");
const validationResults = document.getElementById("validation-results");

runValidation.addEventListener("click", async () => {
  validationSummary.textContent = "Running validation cases...";
  validationResults.innerHTML = "<tr><td colspan=\"7\">Running validation cases...</td></tr>";

  try {
    const response = await fetch("/api/validation");
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.detail || response.statusText);
    }
    const report = await response.json();
    validationSummary.textContent = JSON.stringify({
      generated_at_utc: report.generated_at_utc,
      summary: report.summary,
      disclaimer: report.disclaimer,
    }, null, 2);
    renderValidationRows(report.results);
  } catch (error) {
    validationSummary.textContent = `Validation failed: ${error.message}`;
    validationResults.innerHTML = "<tr><td colspan=\"7\">Validation failed.</td></tr>";
  }
});

function renderValidationRows(results) {
  validationResults.innerHTML = results.map((result) => `
    <tr>
      <td class="status-${result.status}">${result.status}</td>
      <td>
        <strong>${result.case.site_name}</strong><br>
        ${result.case.case_id}<br>
        ${result.case.latitude.toFixed(6)}, ${result.case.longitude.toFixed(6)}
      </td>
      <td>${result.case.expected_general_terrain_description}</td>
      <td>${result.case.expected_topographic_behaviour}</td>
      <td>${result.detected_feature_types.join(", ")}</td>
      <td>${result.max_h_m.toFixed(2)} m</td>
      <td>${result.status_reasons.join(" ")}</td>
    </tr>
  `).join("");
}
