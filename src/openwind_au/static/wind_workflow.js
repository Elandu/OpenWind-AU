const workflowForm = document.getElementById("workflow-form");
const workflowSummary = document.getElementById("workflow-summary");
const siteInputSummary = document.getElementById("site-input-summary");
const vsitbTable = document.getElementById("vsitb-table");
const evidenceLinks = document.getElementById("evidence-links");
const workflowReport = document.getElementById("workflow-report");

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

let currentWorkflow = null;
let workflowReviews = [];

workflowForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  workflowReviews = [];
  await runWorkflow();
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
  workflowSummary.textContent = "Running AS/NZS site wind workflow...";
  resetWorkflowSections();
  try {
    const response = await postJson("/api/wind-workflow", workflowPayload());
    currentWorkflow = await response.json();
    renderWorkflow(currentWorkflow);
  } catch (error) {
    workflowSummary.textContent = `Workflow failed: ${error.message}`;
    vsitbTable.innerHTML = "<tr><td colspan=\"8\">Workflow failed.</td></tr>";
  }
}

function workflowPayload() {
  const data = new FormData(workflowForm);
  const payload = {
    address: data.get("address") || null,
    latitude: data.get("latitude") ? Number(data.get("latitude")) : null,
    longitude: data.get("longitude") ? Number(data.get("longitude")) : null,
    building_height_m: Number(data.get("building_height_m")),
    radius_m: Number(data.get("radius_m")),
    sample_interval_m: Number(data.get("sample_interval_m")),
    obstruction_radius_m: Number(data.get("obstruction_radius_m") || 500),
    default_storey_height_m: Number(data.get("default_storey_height_m") || 3),
    wind_region: data.get("wind_region") || "A2",
    annual_exceedance_probability: data.get("annual_exceedance_probability") || "1/500",
    importance_level: data.get("importance_level") || null,
    user_assumptions: data.get("user_assumptions") || null,
    regional_wind_speed_mps: data.get("regional_wind_speed_mps")
      ? Number(data.get("regional_wind_speed_mps"))
      : null,
    mzcat_recommendation_mode: data.get("mzcat_recommendation_mode") || "conservative",
    workflow_reviews: workflowReviews,
  };
  if (!payload.address) delete payload.address;
  if (payload.latitude === null) delete payload.latitude;
  if (payload.longitude === null) delete payload.longitude;
  if (payload.regional_wind_speed_mps === null) delete payload.regional_wind_speed_mps;
  if (payload.importance_level === null) delete payload.importance_level;
  if (payload.user_assumptions === null) delete payload.user_assumptions;
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
    warnings: workflow.warnings,
    vsitb_status: workflow.directional_vsitb.map((row) => ({
      direction: row.direction,
      status: row.status,
      vsitb: row.final_vsitb,
    })),
    disclaimer: workflow.disclaimer,
  }, null, 2);

  const grouped = groupVariables(workflow.variables || []);
  renderSiteInputs(workflow);
  variableOrder.forEach((variable) => {
    if (variable === "Vsitb") return;
    renderVariableSection(variable, grouped[variable] || []);
  });
  renderVsitbCards(grouped.Vsitb || []);
  renderVsitbTable(workflow.directional_vsitb || []);
  renderEvidenceLinks(workflow.evidence_references || []);
}

function renderSiteInputs(workflow) {
  const input = workflow.input || {};
  siteInputSummary.innerHTML = `
    <div class="table-wrap">
      <table>
        <tbody>
          <tr><th>Address</th><td>${escapeHtml(input.address || workflow.site?.display_name || "not supplied")}</td></tr>
          <tr><th>Coordinates</th><td>${Number(workflow.site.latitude).toFixed(6)}, ${Number(workflow.site.longitude).toFixed(6)}</td></tr>
          <tr><th>Building height</th><td>${Number(input.building_height_m).toFixed(2)} m</td></tr>
          <tr><th>Return period / importance level</th><td>${escapeHtml(input.importance_level || input.annual_exceedance_probability || "user input")}</td></tr>
          <tr><th>User assumptions</th><td>${escapeHtml(input.user_assumptions || "No additional assumptions supplied.")}</td></tr>
        </tbody>
      </table>
    </div>
  `;
}

function resetWorkflowSections() {
  variableOrder.forEach((variable) => {
    const section = document.getElementById(variableAnchors[variable]);
    if (section && variable !== "Vsitb") {
      section.querySelectorAll(".workflow-card").forEach((card) => card.remove());
      section.insertAdjacentHTML("beforeend", "<p class=\"note workflow-card\">Running workflow evidence...</p>");
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
  section.insertAdjacentHTML("beforeend", `
    <article class="workflow-card">
      ${workflowTable(rows)}
    </article>
  `);
  attachReviewHandlers(section);
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
  attachReviewHandlers(section);
}

function workflowTable(rows) {
  if (!rows.length) return "<p class=\"note\">No workflow evidence generated.</p>";
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Direction</th>
            <th>Recommended</th>
            <th>Confidence</th>
            <th>Engineer-selected Final</th>
            <th>Review Status</th>
            <th>Source Reference</th>
            <th>Warnings</th>
            <th>Evidence</th>
            <th>Review</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => variableRow(row)).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function variableRow(row) {
  const key = reviewKey(row.variable, row.direction);
  return `
    <tr>
      <td>${escapeHtml(row.direction || "all")}</td>
      <td>${recommendedCell(row)}</td>
      <td>${badge(row.confidence, row.confidence)}</td>
      <td>${reviewedFinalCell(row)}</td>
      <td>${badge(row.review_status, row.review_status)}</td>
      <td>${escapeHtml(row.source_reference || "Engineer review required.")}</td>
      <td>${(row.warnings || []).map(escapeHtml).join(" ")}</td>
      <td><a href="${escapeHtml(row.evidence_link)}">Evidence</a></td>
      <td>${reviewControls(row, key)}</td>
    </tr>
    <tr>
      <td></td>
      <td colspan="8">
        <details>
          <summary>${escapeHtml(row.detail_label || "Show calculation")}</summary>
          <div class="calc-panel">
            <p><strong>Formula / basis:</strong> ${escapeHtml(row.formula_basis)}</p>
            <p><strong>Inputs:</strong></p>
            <ul>${(row.calculation_inputs || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
            ${detailItems(row)}
            <p><strong>Result:</strong> ${escapeHtml(row.calculation_result)}</p>
          </div>
        </details>
      </td>
    </tr>
  `;
}

function reviewControls(row, key) {
  const canAccept = row.recommended_value !== null && row.recommended_value !== undefined;
  const canReviewVsitb = row.variable !== "Vsitb" || canAccept;
  return `
    <div class="workflow-review">
      <button type="button" data-action="accept" data-key="${key}" ${canAccept && canReviewVsitb ? "" : "disabled"}>Accept</button>
      <label>
        Override
        <input data-field="final_value" data-key="${key}" type="number" step="0.001" value="${row.final_value ?? ""}" />
      </label>
      ${row.variable === "Mzcat" ? terrainCategoryOverrideControl(row, key) : ""}
      <label>
        Reviewed by
        <input data-field="reviewed_by" data-key="${key}" value="${escapeHtml(row.reviewed_by || "")}" />
      </label>
      <label>
        Notes
        <textarea data-field="review_notes" data-key="${key}">${escapeHtml(row.review_notes || "")}</textarea>
      </label>
      <button type="button" data-action="override" data-key="${key}" ${canReviewVsitb ? "" : "disabled"}>Override</button>
    </div>
  `;
}

function attachReviewHandlers(scope) {
  scope.querySelectorAll("button[data-action]").forEach((button) => {
    button.addEventListener("click", () => updateWorkflowReview(button));
  });
  scope.querySelectorAll("input[data-field], textarea[data-field]").forEach((input) => {
    input.addEventListener("change", () => updateReviewDraft(input));
  });
}

function updateReviewDraft(input) {
  const item = reviewForKey(input.dataset.key, true);
  if (!item) return;
  if (input.dataset.field === "final_value") {
    item.final_value = input.value === "" ? null : Number(input.value);
  } else {
    item[input.dataset.field] = input.value || null;
  }
}

async function updateWorkflowReview(button) {
  const key = button.dataset.key;
  const source = variableForKey(key);
  if (!source) return;
  const review = reviewForKey(key, true);
  if (button.dataset.action === "accept") {
    if (source.recommended_value === null || source.recommended_value === undefined) return;
    review.final_value = source.recommended_value;
    review.final_label = source.recommended_label || null;
    review.review_status = "accepted";
    review.review_notes = review.review_notes || "Engineer accepted the workflow recommendation.";
  }
  if (button.dataset.action === "override") {
    const container = button.closest(".workflow-review");
    const valueInput = container.querySelector("[data-field='final_value']");
    const reviewerInput = container.querySelector("[data-field='reviewed_by']");
    const notesInput = container.querySelector("[data-field='review_notes']");
    const labelInput = container.querySelector("[data-field='final_label']");
    review.final_value = valueInput.value === "" ? null : Number(valueInput.value);
    review.final_label = labelInput?.value || null;
    review.reviewed_by = reviewerInput.value || null;
    review.review_notes = notesInput.value || null;
    review.review_status = review.final_value === null ? "unreviewed" : "overridden";
  }
  await runWorkflow();
}

function reviewForKey(key, create = false) {
  const [variable, directionValue] = key.split(":");
  const direction = directionValue || null;
  let review = workflowReviews.find((item) => item.variable === variable && (item.direction || null) === direction);
  if (!review && create) {
    review = {
      variable,
      direction,
      final_value: null,
      final_label: null,
      reviewed_by: null,
      review_notes: null,
      review_status: "unreviewed",
    };
    workflowReviews.push(review);
  }
  return review;
}

function variableForKey(key) {
  return (currentWorkflow?.variables || []).find((item) =>
    reviewKey(item.variable, item.direction) === key
  );
}

function reviewKey(variable, direction) {
  return `${variable}:${direction || ""}`;
}

function renderVsitbTable(rows) {
  if (!rows.length) {
    vsitbTable.innerHTML = "<tr><td colspan=\"8\">No Vsit,b rows generated.</td></tr>";
    return;
  }
  vsitbTable.innerHTML = rows.map((row) => `
    <tr>
      <td>${row.direction}</td>
      <td>${formatWorkflowValue(row.vr, "m/s")}</td>
      <td>${formatWorkflowValue(row.md, "")}</td>
      <td>${formatWorkflowValue(row.mzcat, "")}</td>
      <td>${formatWorkflowValue(row.ms, "")}</td>
      <td>${formatWorkflowValue(row.mt, "")}</td>
      <td>${row.final_vsitb === null || row.final_vsitb === undefined ? "blocked" : `${row.final_vsitb.toFixed(3)} m/s`}</td>
      <td>${badge(row.status, row.status)} <span class="muted">${(row.warnings || []).map(escapeHtml).join(" ")}</span></td>
    </tr>
  `).join("");
}

function renderEvidenceLinks(references) {
  evidenceLinks.innerHTML = references.length
    ? references.map((reference) => `<li>${escapeHtml(reference)}</li>`).join("")
    : "<li>No evidence references generated.</li>";
}

function reviewedFinalCell(row) {
  if (!["accepted", "overridden"].includes(row.review_status) || row.final_value === null || row.final_value === undefined) {
    return "hidden until engineer review";
  }
  const value = formatWorkflowValue(row.final_value, row.unit);
  return row.final_label ? `${escapeHtml(row.final_label)}<span class="muted">${value}</span>` : value;
}

function recommendedCell(row) {
  const value = formatWorkflowValue(row.recommended_value, row.unit);
  return row.recommended_label
    ? `${escapeHtml(row.recommended_label)}<span class="muted">${value}</span>`
    : value;
}

function terrainCategoryOverrideControl(row, key) {
  return `
    <label>
      Final TC
      <select data-field="final_label" data-key="${key}">
        ${terrainCategoryOptions(row.final_label || "")}
      </select>
    </label>
  `;
}

function terrainCategoryOptions(selected) {
  const options = ["", "TC1", "TC1.5", "TC2", "TC2.5", "TC3", "TC4"];
  return options.map((option) => {
    const label = option || "Select final TC";
    return `<option value="${option}" ${option === selected ? "selected" : ""}>${label}</option>`;
  }).join("");
}

function detailItems(row) {
  if (!row.detail_items?.length) return "";
  return `
    <p><strong>Evidence / source details:</strong></p>
    <ul>${row.detail_items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
  `;
}

function formatWorkflowValue(value, unit) {
  if (value === null || value === undefined) return "review required";
  return `${Number(value).toFixed(3)}${unit ? ` ${unit}` : ""}`;
}

function badge(status, text) {
  const classes = {
    high: "badge-pass",
    medium: "badge-warn",
    low: "badge-fail",
    accepted: "badge-pass",
    overridden: "badge-warn",
    unreviewed: "badge-neutral",
    calculated: "badge-pass",
    blocked: "badge-fail",
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
