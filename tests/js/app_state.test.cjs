"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const SCRIPT_PATH = path.resolve(__dirname, "../../src/openwind_au/static/app.js");
const SCRIPT_SOURCE = fs.readFileSync(SCRIPT_PATH, "utf8");

class FakeElement {
  constructor(id = "") {
    this.id = id;
    this.value = "";
    this.name = id;
    this.textContent = "";
    this.innerHTML = "";
    this.disabled = false;
    this.files = [];
    this.src = "";
    this.srcdoc = "";
    this.listeners = new Map();
    this.attributes = new Map();
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  async dispatch(type, overrides = {}) {
    const event = {
      target: this,
      preventDefault() {},
      ...overrides,
    };
    await Promise.all((this.listeners.get(type) || []).map((listener) => listener(event)));
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  removeAttribute(name) {
    this.attributes.delete(name);
    if (name === "src" || name === "srcdoc") this[name] = "";
  }

  querySelectorAll() {
    return [];
  }

  click() {}
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function fullAnalysisResult(label) {
  return {
    site_analysis: {
      site: { display_name: label, latitude: -33.86, longitude: 151.21 },
      profiles: [],
      features: [],
      disclaimer: "Preliminary",
    },
    obstruction_inventory: {
      site: { display_name: label, latitude: -33.86, longitude: 151.21 },
      input: { radius_m: 500, building_height_m: 10 },
      obstructions: [],
      data_quality: null,
      shielding_sectors: [],
      warnings: [],
      data_source_status: "ok",
    },
    terrain_category_evidence: {
      site: { display_name: label },
      directions: [],
      mzcat_assessment: [],
    },
    profile_plot_html: `<p>${label} profile</p>`,
    terrain_category_map_html: `<p>${label} terrain</p>`,
    combined_map_html: `<p>${label} map</p>`,
  };
}

function okJson(value) {
  return {
    ok: true,
    statusText: "OK",
    async json() {
      return value;
    },
  };
}

function createHarness(fetchImplementation) {
  const elements = new Map();
  const formValues = {
    address: "Site A",
    latitude: "",
    longitude: "",
    building_height_m: "10",
    radius_m: "1000",
    sample_interval_m: "20",
    mzcat_recommendation_mode: "conservative",
    obstruction_radius_m: "500",
    default_storey_height_m: "3",
    residential_storey_height_m: "3",
    residential_two_storey_height_m: "6",
    commercial_storey_height_m: "4",
    map_display_mode: "nearest_500",
  };
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, new FakeElement(id));
    return elements.get(id);
  };
  element("obstruction-filter").value = "all";
  element("ms-explanation-sector").value = "N";

  class FakeFormData {
    get(name) {
      return Object.hasOwn(formValues, name) ? formValues[name] : null;
    }
  }

  const document = {
    createElement(tagName) {
      return new FakeElement(tagName);
    },
    getElementById(id) {
      return element(id);
    },
  };
  const context = {
    AbortController,
    Blob,
    console,
    document,
    fetch: fetchImplementation,
    FormData: FakeFormData,
    setTimeout,
    URL,
    window: {
      location: { origin: "https://openwind.test" },
      open() {
        return null;
      },
    },
  };
  vm.createContext(context);
  vm.runInContext(SCRIPT_SOURCE, context, { filename: SCRIPT_PATH });

  return {
    context,
    element,
    evaluate(source) {
      return vm.runInContext(source, context);
    },
    formValues,
  };
}

test("newer legacy analysis wins even when an aborted older response arrives last", async () => {
  const pending = [];
  const harness = createHarness((url, options) => {
    assert.equal(url, "/api/full-analysis");
    const request = deferred();
    pending.push({ ...request, options });
    return request.promise;
  });
  const form = harness.element("analysis-form");

  const firstRun = form.dispatch("submit");
  assert.equal(pending.length, 1);

  harness.formValues.address = "Site B";
  await form.dispatch("input", { target: { name: "address" } });
  assert.equal(pending[0].options.signal.aborted, true);
  const secondRun = form.dispatch("submit");
  assert.equal(pending.length, 2);

  pending[1].resolve(okJson(fullAnalysisResult("Site B")));
  await secondRun;
  assert.equal(harness.evaluate("currentObstructionInventory.site.display_name"), "Site B");
  assert.equal(harness.evaluate("currentTerrainCategoryEvidence.site.display_name"), "Site B");
  assert.equal(harness.element("terrain-report").disabled, false);
  assert.match(harness.element("map-frame").srcdoc, /Site B map/);

  pending[0].resolve(okJson(fullAnalysisResult("Site A")));
  await firstRun;
  assert.equal(harness.evaluate("currentObstructionInventory.site.display_name"), "Site B");
  assert.equal(harness.evaluate("currentTerrainCategoryEvidence.site.display_name"), "Site B");
  assert.match(harness.element("map-frame").srcdoc, /Site B map/);
  assert.doesNotMatch(harness.element("map-frame").srcdoc, /Site A map/);
});

test("legacy form changes and failed reruns clear obstruction, terrain, and review state", async () => {
  let response = okJson(fullAnalysisResult("Site A"));
  const harness = createHarness(async () => response);
  const form = harness.element("analysis-form");

  await form.dispatch("submit");
  harness.evaluate(`reviewedObstructions = [{
    obstruction_id: "reviewed-a",
    height_source: "manual_verified",
    height_m: 12,
  }]`);
  assert.equal(harness.evaluate("legacyAnalysisIsCurrent()"), true);

  harness.formValues.building_height_m = "12";
  await form.dispatch("input", { target: { name: "building_height_m" } });
  assert.equal(harness.evaluate("currentObstructionInventory"), null);
  assert.equal(harness.evaluate("currentTerrainCategoryEvidence"), null);
  assert.equal(harness.evaluate("reviewedObstructions.length"), 0);
  assert.equal(harness.element("obstruction-export").disabled, true);
  assert.equal(harness.element("terrain-report").disabled, true);
  assert.equal(harness.evaluate("terrainCategoryReportPayload().mzcat_reviews.length"), 0);

  response = Promise.reject(new Error("upstream unavailable"));
  await form.dispatch("submit");
  assert.equal(harness.evaluate("currentObstructionInventory"), null);
  assert.equal(harness.evaluate("currentTerrainCategoryEvidence"), null);
  assert.equal(harness.evaluate("reviewedObstructions.length"), 0);
  assert.match(harness.element("summary").textContent, /Analysis failed: upstream unavailable/);
});

test("an obstruction import started for old inputs cannot repopulate cleared review state", async () => {
  const request = deferred();
  let requestOptions;
  const harness = createHarness((_url, options) => {
    requestOptions = options;
    return request.promise;
  });

  const importPromise = harness.evaluate(
    "importObstructionCsvText('obstruction_id,height_m\\nold-site,12\\n')",
  );
  harness.formValues.address = "Different site";
  await harness.element("analysis-form").dispatch("input", {
    target: { name: "address" },
  });
  assert.equal(requestOptions.signal.aborted, true);

  request.resolve(okJson([{
    obstruction_id: "old-site",
    height_m: 12,
    building_levels: null,
    height_source: "manual_review",
    notes: null,
  }]));
  await importPromise;

  assert.equal(harness.evaluate("reviewedObstructions.length"), 0);
  assert.equal(harness.evaluate("currentObstructionInventory"), null);
  assert.equal(harness.element("obstruction-export").disabled, true);
});
