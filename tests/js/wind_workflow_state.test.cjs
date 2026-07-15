"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const SCRIPT_PATH = path.resolve(
  __dirname,
  "../../src/openwind_au/static/wind_workflow.js",
);
const SCRIPT_SOURCE = fs.readFileSync(SCRIPT_PATH, "utf8");
const DESIGN_LOCATION_KEY = "openwindDesignBuildingLocation";
const PROJECT_NUMBER_KEY = "openwindProjectNumber";

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  add(...names) {
    names.forEach((name) => this.values.add(name));
  }

  remove(...names) {
    names.forEach((name) => this.values.delete(name));
  }

  toggle(name, force) {
    const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
    if (enabled) this.values.add(name);
    else this.values.delete(name);
    return enabled;
  }

  contains(name) {
    return this.values.has(name);
  }
}

class FakeElement {
  constructor(id = "") {
    this.id = id;
    this.value = "";
    this.textContent = "";
    this.innerHTML = "";
    this.hidden = false;
    this.disabled = false;
    this.required = false;
    this.src = "";
    this.srcdoc = "";
    this.tabIndex = 0;
    this.dataset = {};
    this.style = {};
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.classList = new FakeClassList();
    this.contentWindow = { postMessage() {} };
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    this.listeners.set(
      type,
      listeners.filter((candidate) => candidate !== listener),
    );
  }

  dispatch(type, overrides = {}) {
    const event = {
      target: this,
      preventDefault() {},
      stopPropagation() {},
      ...overrides,
    };
    for (const listener of this.listeners.get(type) || []) {
      listener(event);
    }
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "src" || name === "srcdoc") this[name] = String(value);
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
    if (name === "src" || name === "srcdoc") this[name] = "";
  }

  querySelector() {
    return null;
  }

  querySelectorAll() {
    return [];
  }

  insertAdjacentHTML(_position, html) {
    this.innerHTML += html;
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  removeChild(child) {
    this.children = this.children.filter((candidate) => candidate !== child);
    return child;
  }

  closest() {
    return null;
  }

  focus() {}

  click() {}

  remove() {}

  reportValidity() {
    return true;
  }

  setCustomValidity(message) {
    this.validationMessage = message;
  }
}

function createHarness(options = {}) {
  const elements = new Map();
  const storageValues = new Map();
  const timers = new Map();
  let nextTimerId = 1;
  let fetchImplementation = options.fetch || (async () => {
    throw new Error("Unexpected fetch in workflow state test");
  });
  const initialStorage = options.storage || {};

  for (const [key, value] of Object.entries(initialStorage)) {
    storageValues.set(
      key,
      typeof value === "string" ? value : JSON.stringify(value),
    );
  }

  const element = (id) => {
    if (!elements.has(id)) elements.set(id, new FakeElement(id));
    return elements.get(id);
  };

  const defaultElementValues = {
    assessment_status: "draft",
    building_length_m: "18",
    building_width_m: "12",
    structure_orientation_deg: "0",
  };
  for (const [id, value] of Object.entries({
    ...defaultElementValues,
    ...(options.values || {}),
  })) {
    element(id).value = String(value);
  }

  const localStorage = {
    getItem(key) {
      return storageValues.has(key) ? storageValues.get(key) : null;
    },
    setItem(key, value) {
      storageValues.set(key, String(value));
    },
    removeItem(key) {
      storageValues.delete(key);
    },
    clear() {
      storageValues.clear();
    },
  };

  const defaultFormValues = {
    address: "",
    annual_exceedance_probability: "1/500",
    assessment_status: "draft",
    building_height_m: "10",
    building_length_m: "18",
    building_width_m: "12",
    default_storey_height_m: "3",
    obstruction_radius_m: "500",
    radius_m: "1000",
    sample_interval_m: "20",
    structure_orientation_deg: "0",
  };
  const formValues = {
    ...defaultFormValues,
    ...(options.formValues || {}),
  };

  class FakeFormData {
    get(name) {
      if (name === "address") return element("dashboard-address").value || null;
      return Object.hasOwn(formValues, name) ? formValues[name] : null;
    }
  }

  const queryElements = new Map();
  const document = {
    activeElement: null,
    body: new FakeElement("body"),
    createElement(tagName) {
      return new FakeElement(tagName);
    },
    getElementById(id) {
      return element(id);
    },
    querySelector(selector) {
      if (!queryElements.has(selector)) {
        queryElements.set(selector, new FakeElement(selector));
      }
      return queryElements.get(selector);
    },
    querySelectorAll() {
      return [];
    },
  };

  const windowListeners = new Map();
  const window = {
    addEventListener(type, listener) {
      const listeners = windowListeners.get(type) || [];
      listeners.push(listener);
      windowListeners.set(type, listeners);
    },
    document,
    location: { origin: "https://openwind.test" },
    open() {
      return null;
    },
  };

  const context = {
    AbortController,
    Blob,
    clearTimeout(timerId) {
      timers.delete(timerId);
    },
    console,
    document,
    Element: FakeElement,
    fetch(...args) {
      return fetchImplementation(...args);
    },
    FormData: FakeFormData,
    localStorage,
    setTimeout(callback) {
      const timerId = nextTimerId;
      nextTimerId += 1;
      timers.set(timerId, callback);
      return timerId;
    },
    TextDecoder,
    Uint8Array,
    URL,
    window,
  };
  window.localStorage = localStorage;

  vm.createContext(context);
  vm.runInContext(SCRIPT_SOURCE, context, { filename: SCRIPT_PATH });

  return {
    context,
    element,
    evaluate(source) {
      return vm.runInContext(source, context);
    },
    dispatchWindow(type, overrides = {}) {
      const event = { ...overrides };
      for (const listener of windowListeners.get(type) || []) {
        listener(event);
      }
    },
    async flushTimers() {
      while (timers.size) {
        const pending = [...timers.entries()];
        timers.clear();
        for (const [, callback] of pending) {
          await callback();
        }
      }
    },
    localStorage,
    setFetch(implementation) {
      fetchImplementation = implementation;
    },
  };
}

function savedLocation(overrides = {}) {
  return {
    version: 1,
    latitude: -33.8688,
    longitude: 151.2093,
    display_name: "Old saved site",
    address: "1 Old Street, Sydney NSW",
    project_number: "OW-101",
    orientation_deg: 0,
    ...overrides,
  };
}

function locationState(harness) {
  return JSON.parse(
    harness.evaluate(
      "JSON.stringify({ locationMode, coordinateOverride, currentMapSite })",
    ),
  );
}

test("saved coordinates restore only for an exact, nonblank project number", async (t) => {
  await t.test("blank project coordinates are discarded", () => {
    const harness = createHarness({
      storage: {
        [DESIGN_LOCATION_KEY]: savedLocation({ project_number: "" }),
        [PROJECT_NUMBER_KEY]: "",
      },
    });

    assert.equal(locationState(harness).locationMode, "address");
    assert.equal(locationState(harness).coordinateOverride, null);
    assert.equal(harness.localStorage.getItem(DESIGN_LOCATION_KEY), null);
  });

  await t.test("an exact nonblank project restores its coordinates", () => {
    const harness = createHarness({
      storage: {
        [DESIGN_LOCATION_KEY]: savedLocation(),
        [PROJECT_NUMBER_KEY]: "OW-101",
      },
    });
    const state = locationState(harness);

    assert.equal(state.locationMode, "coordinates");
    assert.deepEqual(state.coordinateOverride, {
      latitude: -33.8688,
      longitude: 151.2093,
      display_name: "Old saved site",
    });
    assert.equal(
      harness.element("dashboard-address").value,
      "1 Old Street, Sydney NSW",
    );
  });

  await t.test("a different project cannot restore the saved site", () => {
    const harness = createHarness({
      storage: {
        [DESIGN_LOCATION_KEY]: savedLocation(),
        [PROJECT_NUMBER_KEY]: "OW-101-REV-A",
      },
    });

    assert.equal(locationState(harness).locationMode, "address");
    assert.equal(locationState(harness).coordinateOverride, null);
    assert.equal(harness.localStorage.getItem(DESIGN_LOCATION_KEY), null);
  });
});

test("malformed, null, and out-of-bounds saved coordinates are rejected", async (t) => {
  const invalidLocations = [
    ["null latitude", { latitude: null }],
    ["string latitude", { latitude: "-33.8688" }],
    ["latitude outside Australia", { latitude: -70 }],
    ["longitude outside Australia", { longitude: 20 }],
  ];

  for (const [name, coordinates] of invalidLocations) {
    await t.test(name, () => {
      const harness = createHarness({
        storage: {
          [DESIGN_LOCATION_KEY]: savedLocation(coordinates),
          [PROJECT_NUMBER_KEY]: "OW-101",
        },
      });

      assert.equal(locationState(harness).locationMode, "address");
      assert.equal(locationState(harness).coordinateOverride, null);
      assert.equal(harness.localStorage.getItem(DESIGN_LOCATION_KEY), null);
    });
  }
});

test("editing a restored address clears its override and stale map", () => {
  const harness = createHarness({
    storage: {
      [DESIGN_LOCATION_KEY]: savedLocation(),
      [PROJECT_NUMBER_KEY]: "OW-101",
    },
  });
  const address = harness.element("dashboard-address");
  const mapFrame = harness.element("workflow-map-frame");

  assert.match(mapFrame.srcdoc, /Old saved site/);
  address.value = "200 New Road, Melbourne VIC";
  address.dispatch("input");

  const state = locationState(harness);
  assert.equal(state.locationMode, "address");
  assert.equal(state.coordinateOverride, null);
  assert.equal(harness.localStorage.getItem(DESIGN_LOCATION_KEY), null);
  assert.equal(harness.element("map-coordinate-readout").textContent, "Not positioned");
  assert.match(
    mapFrame.srcdoc,
    /Address changed\. Select a suggestion or run the assessment to locate it\./,
  );
  assert.doesNotMatch(mapFrame.srcdoc, /Old saved site/);
  assert.doesNotMatch(mapFrame.srcdoc, /-33\.8688/);
  assert.doesNotMatch(mapFrame.srcdoc, /151\.2093/);
});

test("address autocomplete replaces a restored site with the selected suggestion", async () => {
  const requested = [];
  const newSite = {
    display_name: "200 New Road, Melbourne VIC",
    latitude: -37.8136,
    longitude: 144.9631,
  };
  const harness = createHarness({
    fetch: async (url, request) => {
      requested.push({
        body: JSON.parse(request.body),
        url,
      });
      return {
        ok: true,
        async json() {
          return { suggestions: [newSite] };
        },
      };
    },
    storage: {
      [DESIGN_LOCATION_KEY]: savedLocation(),
      [PROJECT_NUMBER_KEY]: "OW-101",
    },
  });
  const address = harness.element("dashboard-address");
  const suggestions = harness.element("dashboard-address-suggestions");
  const mapFrame = harness.element("workflow-map-frame");

  assert.match(mapFrame.srcdoc, /Old saved site/);
  address.value = "200 New Road";
  address.dispatch("input");

  assert.match(suggestions.innerHTML, /Searching Australian addresses/);
  assert.equal(harness.localStorage.getItem(DESIGN_LOCATION_KEY), null);

  await harness.flushTimers();

  assert.deepEqual(requested, [
    {
      body: { query: "200 New Road", limit: 6 },
      url: "/api/geocode/suggest",
    },
  ]);
  assert.match(suggestions.innerHTML, /200 New Road, Melbourne VIC/);
  assert.match(
    suggestions.innerHTML,
    /data-address-suggestion-index="0"/,
  );

  address.dispatch("keydown", { key: "ArrowDown" });
  address.dispatch("keydown", { key: "Enter" });

  const state = locationState(harness);
  const persisted = JSON.parse(
    harness.localStorage.getItem(DESIGN_LOCATION_KEY),
  );
  assert.equal(address.value, newSite.display_name);
  assert.equal(state.locationMode, "coordinates");
  assert.deepEqual(state.coordinateOverride, newSite);
  assert.equal(persisted.project_number, "OW-101");
  assert.equal(persisted.address, newSite.display_name);
  assert.equal(persisted.latitude, newSite.latitude);
  assert.equal(persisted.longitude, newSite.longitude);
  const payload = JSON.parse(
    harness.evaluate("JSON.stringify(workflowPayload())"),
  );
  assert.equal(payload.site_label, newSite.display_name);
  assert.equal(Object.hasOwn(payload, "address"), false);
  assert.equal(suggestions.hidden, true);
  assert.equal(suggestions.innerHTML, "");
  assert.match(mapFrame.srcdoc, /200 New Road, Melbourne VIC/);
  assert.match(mapFrame.srcdoc, /-37\.8136/);
  assert.match(mapFrame.srcdoc, /144\.9631/);
  assert.doesNotMatch(mapFrame.srcdoc, /Old saved site/);
});

test("a map drag persists adjusted coordinates and includes them in workflow payload", () => {
  const harness = createHarness({
    storage: {
      [DESIGN_LOCATION_KEY]: savedLocation(),
      [PROJECT_NUMBER_KEY]: "OW-101",
    },
  });
  const mapFrame = harness.element("workflow-map-frame");
  const originalLatitude = -33.8688;
  const originalLongitude = 151.2093;

  harness.dispatchWindow("message", {
    data: {
      type: "openwind-design-building-change",
      state: {
        latitude: originalLatitude,
        longitude: originalLongitude,
        offset_east_m: 125,
        offset_north_m: 80,
        orientation_deg: 0,
        orientation_modified: false,
        position_modified: true,
      },
    },
    source: mapFrame.contentWindow,
  });

  const state = locationState(harness);
  const payload = JSON.parse(
    harness.evaluate("JSON.stringify(workflowPayload())"),
  );
  const persisted = JSON.parse(
    harness.localStorage.getItem(DESIGN_LOCATION_KEY),
  );

  assert.equal(state.locationMode, "coordinates");
  assert.notEqual(state.coordinateOverride.latitude, originalLatitude);
  assert.notEqual(state.coordinateOverride.longitude, originalLongitude);
  assert.ok(
    Math.abs(payload.latitude - state.coordinateOverride.latitude) < 1e-12,
  );
  assert.ok(
    Math.abs(payload.longitude - state.coordinateOverride.longitude) < 1e-12,
  );
  assert.ok(
    Math.abs(persisted.latitude - state.coordinateOverride.latitude) < 1e-12,
  );
  assert.ok(
    Math.abs(persisted.longitude - state.coordinateOverride.longitude) < 1e-12,
  );
  assert.equal(persisted.project_number, "OW-101");
  assert.equal(payload.project_number, "OW-101");
  assert.equal(payload.site_label, "1 Old Street, Sydney NSW");
  assert.equal(Object.hasOwn(payload, "address"), false);
  assert.equal(
    harness.element("map-coordinate-readout").textContent,
    state.coordinateOverride.latitude.toFixed(6)
      + ", "
      + state.coordinateOverride.longitude.toFixed(6),
  );
});

test("address-only fallback adopts resolved coordinates before report fingerprinting", async () => {
  const address = "10 Example Street, Brisbane QLD";
  const harness = createHarness({
    storage: { [PROJECT_NUMBER_KEY]: "OW-202" },
    values: { "dashboard-address": address },
  });
  harness.context.__workflowResponse = {
    input: {
      address,
      building_height_m: 10,
    },
    site: {
      latitude: -27.4698,
      longitude: 153.0251,
      display_name: address,
      ground_elevation_m: 18,
    },
  };
  harness.evaluate(
    [
      "postJson = async function () {",
      "  return { json: async function () { return __workflowResponse; } };",
      "};",
      "renderWorkflow = function () {};",
      "renderWorkflowMap = async function () {};",
      "renderTerrainProfileGraph = async function () {};",
      "globalThis.__requestPayload = workflowPayload();",
    ].join("\n"),
  );

  assert.equal(harness.evaluate("__requestPayload.latitude"), undefined);
  assert.equal(harness.evaluate("__requestPayload.longitude"), undefined);

  await harness.evaluate(
    "runWorkflowFallback(new Error('stream unavailable'), __requestPayload, workflowRunId, new AbortController().signal)",
  );

  const state = locationState(harness);
  assert.equal(state.locationMode, "coordinates");
  assert.equal(state.coordinateOverride.latitude, -27.4698);
  assert.equal(state.coordinateOverride.longitude, 153.0251);
  assert.equal(harness.evaluate("assessmentIsCurrent()"), true);
  assert.equal(harness.element("workflow-pdf").disabled, false);
  assert.equal(harness.element("workflow-report").disabled, false);
  assert.equal(
    harness.element("report-status").textContent,
    "Reports are ready for the current assessment.",
  );
});

test("raw-data override rows render the calculated value once and preserve overrides", () => {
  const harness = createHarness();
  harness.context.__row = {
    variable: "Mzcat",
    direction: "N",
    unit: "",
    recommended_value: 1.04,
    recommended_label: "Recommended multiplier",
    confidence: "medium",
    calculated_value: 1.04,
    final_value: 1.04,
    override_value: null,
    override_reason: null,
    is_overridden: false,
  };

  const initialHtml = harness.evaluate("variableRow(__row)");
  assert.equal((initialHtml.match(/1\.040/g) || []).length, 1);
  assert.match(initialHtml, /placeholder="optional override"/);
  assert.doesNotMatch(initialHtml, /muted">calculated/);

  harness.evaluate(`
    workflowOverrides = [{
      variable: "Mzcat",
      direction: "N",
      override_value: 1.08,
      reason: "Reviewed terrain category",
    }];
  `);
  const overrideHtml = harness.evaluate("variableRow(__row)");
  assert.equal((overrideHtml.match(/1\.040/g) || []).length, 1);
  assert.match(overrideHtml, /value="1\.08"/);
  assert.match(overrideHtml, /value="Reviewed terrain category"/);
  assert.match(overrideHtml, />Reset<\/button>/);
});
