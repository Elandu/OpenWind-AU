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
const HTML_SOURCE = fs.readFileSync(
  path.resolve(__dirname, "../../src/openwind_au/static/wind_workflow.html"),
  "utf8",
);
const STYLES_SOURCE = fs.readFileSync(
  path.resolve(__dirname, "../../src/openwind_au/static/styles.css"),
  "utf8",
);
const DESIGN_LOCATION_KEY = "openwindDesignBuildingLocation";
const PROJECT_NUMBER_KEY = "openwindProjectNumber";
const WIND_DIRECTION_MULTIPLIER_CASE_KEY = "openwindWindDirectionMultiplierCase";

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
    return Promise.all(
      (this.listeners.get(type) || []).map((listener) => listener(event)),
    );
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

  click() {
    this.clicked = true;
  }

  remove() {
    this.removed = true;
  }

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
  const scheduledDelays = [];
  const createdElements = [];
  const createdObjectUrls = [];
  const revokedObjectUrls = [];
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
    wind_direction_multiplier_case: "main_structure",
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
      if (name === "wind_direction_multiplier_case") {
        return element("wind_direction_multiplier_case").value || null;
      }
      return Object.hasOwn(formValues, name) ? formValues[name] : null;
    }
  }

  element("wind_direction_multiplier_case").options = [
    { value: "main_structure" },
    { value: "cladding_or_immediate_support" },
    { value: "circular_or_polygonal_chimney_tank_or_pole" },
  ];

  const mapNudgeButtons = [
    ["north", "0", "1"],
    ["west", "-1", "0"],
    ["east", "1", "0"],
    ["south", "0", "-1"],
  ].map(([direction, east, north]) => {
    const button = new FakeElement(`map-nudge-${direction}`);
    button.dataset.mapNudge = "";
    button.dataset.mapNudgeEast = east;
    button.dataset.mapNudgeNorth = north;
    return button;
  });

  const queryElements = new Map();
  const document = {
    activeElement: null,
    body: new FakeElement("body"),
    createElement(tagName) {
      const created = new FakeElement(tagName);
      createdElements.push(created);
      return created;
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
    querySelectorAll(selector) {
      if (selector === "[data-map-nudge]") return mapNudgeButtons;
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
    open(...args) {
      return options.windowOpen?.(...args) || null;
    },
  };

  const urlApi = {
    createObjectURL(value) {
      const url = `blob:openwind-test-${createdObjectUrls.length + 1}`;
      createdObjectUrls.push({ url, value });
      return url;
    },
    revokeObjectURL(url) {
      revokedObjectUrls.push(url);
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
    mapNudgeButtons,
    setTimeout(callback, delay = 0) {
      const timerId = nextTimerId;
      nextTimerId += 1;
      timers.set(timerId, callback);
      scheduledDelays.push(delay);
      return timerId;
    },
    TextDecoder,
    Uint8Array,
    URL: urlApi,
    window,
  };
  window.localStorage = localStorage;

  vm.createContext(context);
  vm.runInContext(SCRIPT_SOURCE, context, { filename: SCRIPT_PATH });

  return {
    context,
    createdElements,
    createdObjectUrls,
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
    mapNudgeButtons,
    revokedObjectUrls,
    scheduledDelays,
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
  harness.evaluate(`workflowOverrides = [{
    variable: "Mzcat",
    direction: "N",
    override_value: 1.08,
    reason: "Prior site review",
  }]`);

  assert.match(mapFrame.srcdoc, /Old saved site/);
  address.value = "200 New Road, Melbourne VIC";
  address.dispatch("input");

  const state = locationState(harness);
  assert.equal(state.locationMode, "address");
  assert.equal(state.coordinateOverride, null);
  assert.equal(harness.evaluate("workflowOverrides.length"), 0);
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
  harness.evaluate(`workflowOverrides = [{
    variable: "Ms",
    direction: "N",
    override_value: 0.9,
    reason: "Prior site review",
  }]`);
  address.value = "200 New Road";
  address.dispatch("input");

  assert.match(suggestions.innerHTML, /Searching Australian addresses/);
  assert.equal(harness.localStorage.getItem(DESIGN_LOCATION_KEY), null);
  assert.equal(harness.evaluate("workflowOverrides.length"), 0);

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
  harness.evaluate(`workflowOverrides = [{
    variable: "Mt",
    direction: "N",
    override_value: 1.1,
    reason: "Must not follow a new suggestion",
  }]`);
  address.dispatch("keydown", { key: "Enter" });

  const state = locationState(harness);
  const persisted = JSON.parse(
    harness.localStorage.getItem(DESIGN_LOCATION_KEY),
  );
  assert.equal(address.value, newSite.display_name);
  assert.equal(state.locationMode, "coordinates");
  assert.equal(harness.evaluate("workflowOverrides.length"), 0);
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
  harness.evaluate(`workflowOverrides = [{
    variable: "Md",
    direction: "N",
    override_value: 0.95,
    reason: "Prior position",
  }]`);

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
  assert.equal(harness.evaluate("workflowOverrides.length"), 0);
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

test("changing project identity clears coordinates and workflow overrides", () => {
  const harness = createHarness({
    storage: {
      [DESIGN_LOCATION_KEY]: savedLocation(),
      [PROJECT_NUMBER_KEY]: "OW-101",
    },
  });
  harness.evaluate(`workflowOverrides = [{
    variable: "Mzcat",
    direction: "S",
    override_value: 1.12,
    reason: "Previous project",
  }]`);

  const project = harness.element("dashboard-project-number");
  project.value = "OW-202";
  project.dispatch("input");

  assert.equal(harness.evaluate("workflowOverrides.length"), 0);
  assert.equal(locationState(harness).locationMode, "address");
  assert.equal(locationState(harness).coordinateOverride, null);
  assert.equal(harness.localStorage.getItem(DESIGN_LOCATION_KEY), null);
  assert.equal(harness.localStorage.getItem(PROJECT_NUMBER_KEY), "OW-202");
});

test("keyboard-focusable nudge controls send one-metre map commands only for a positioned site", () => {
  const positioned = createHarness({
    storage: {
      [DESIGN_LOCATION_KEY]: savedLocation(),
      [PROJECT_NUMBER_KEY]: "OW-101",
    },
  });
  const posted = [];
  positioned.element("workflow-map-frame").contentWindow.postMessage = (message) => {
    posted.push(JSON.parse(JSON.stringify(message)));
  };

  assert.equal(positioned.mapNudgeButtons[0].disabled, false);
  positioned.mapNudgeButtons[0].dispatch("click");
  assert.deepEqual(posted, [{
    type: "openwind-map-command",
    action: "nudge",
    payload: { east_m: 0, north_m: 1 },
  }]);

  const unpositioned = createHarness();
  const unexpected = [];
  unpositioned.element("workflow-map-frame").contentWindow.postMessage = (message) => {
    unexpected.push(message);
  };
  assert.equal(unpositioned.mapNudgeButtons[0].disabled, true);
  unpositioned.mapNudgeButtons[0].dispatch("click");
  assert.deepEqual(unexpected, []);

  assert.match(HTML_SOURCE, /data-map-nudge[^>]+aria-label="Move building north one metre"/);
  assert.match(HTML_SOURCE, /data-map-nudge[^>]+aria-label="Move building south one metre"/);
});

test("wind direction multiplier case defaults, serializes, and restores", () => {
  const harness = createHarness();
  assert.equal(
    harness.evaluate("workflowPayload().wind_direction_multiplier_case"),
    "main_structure",
  );

  const control = harness.element("wind_direction_multiplier_case");
  control.value = "cladding_or_immediate_support";
  control.dispatch("change");
  assert.equal(
    harness.evaluate("workflowPayload().wind_direction_multiplier_case"),
    "cladding_or_immediate_support",
  );
  assert.equal(
    harness.localStorage.getItem(WIND_DIRECTION_MULTIPLIER_CASE_KEY),
    "cladding_or_immediate_support",
  );
  harness.evaluate(`
    activeWorkflowController = new AbortController();
    globalThis.__caseSignal = activeWorkflowController.signal;
    globalThis.__runIdBeforeCaseChange = workflowRunId;
    workflowOverrides = [{
      variable: "Mzcat",
      direction: "N",
      override_value: 1.05,
      reason: "Same site engineering review",
    }];
  `);
  harness.element("workflow-form").dispatch("change", { target: control });
  assert.equal(harness.evaluate("__caseSignal.aborted"), true);
  assert.equal(
    harness.evaluate("workflowRunId"),
    harness.evaluate("__runIdBeforeCaseChange + 1"),
  );
  assert.equal(harness.evaluate("workflowOverrides.length"), 1);

  const restored = createHarness({
    storage: {
      [WIND_DIRECTION_MULTIPLIER_CASE_KEY]: "circular_or_polygonal_chimney_tank_or_pole",
    },
  });
  assert.equal(
    restored.evaluate("workflowPayload().wind_direction_multiplier_case"),
    "circular_or_polygonal_chimney_tank_or_pole",
  );
  assert.match(
    HTML_SOURCE,
    /name="wind_direction_multiplier_case" required>[\s\S]*value="main_structure" selected/,
  );
});

test("PDF generation falls back to a download when popups are blocked and surfaces errors", async () => {
  const pdfBytes = new Uint8Array(160);
  pdfBytes.set([0x25, 0x50, 0x44, 0x46, 0x2d]);
  const pdf = new Blob([pdfBytes], { type: "application/pdf" });
  const harness = createHarness();
  harness.evaluate(`
    currentWorkflow = { input: {}, variables: [], directional_vsitb: [], warnings: [] };
    currentWorkflowFingerprint = assessmentFingerprint();
    updateReportAvailability();
  `);
  harness.setFetch(async (url, request) => {
    assert.equal(url, "/api/wind-workflow/result/report/pdf");
    assert.equal(request.signal.aborted, false);
    return {
      ok: true,
      async blob() { return pdf; },
    };
  });

  await harness.element("workflow-pdf").dispatch("click");

  const link = harness.createdElements.find((element) => element.id === "a");
  assert.ok(link);
  assert.equal(link.href, "blob:openwind-test-1");
  assert.equal(link.download, "openwind-au-site-wind-assessment.pdf");
  assert.equal(link.clicked, true);
  assert.equal(link.removed, true);
  assert.equal(harness.createdObjectUrls.length, 1);
  assert.equal(harness.revokedObjectUrls.length, 0);
  assert.ok(harness.scheduledDelays.includes(300000));
  assert.equal(
    harness.element("report-status").textContent,
    "PDF generated. Use the PDF viewer to save or print it.",
  );

  await harness.flushTimers();
  assert.deepEqual(harness.revokedObjectUrls, ["blob:openwind-test-1"]);

  const invalidHarness = createHarness();
  invalidHarness.evaluate(`
    currentWorkflow = { input: {}, variables: [], directional_vsitb: [], warnings: [] };
    currentWorkflowFingerprint = assessmentFingerprint();
    updateReportAvailability();
  `);
  invalidHarness.setFetch(async () => ({
    ok: true,
    async blob() { return new Blob(["not pdf"], { type: "text/plain" }); },
  }));

  await invalidHarness.element("workflow-pdf").dispatch("click");
  assert.match(invalidHarness.element("report-status").textContent, /PDF report failed/);
  assert.match(invalidHarness.element("workflow-summary").textContent, /valid PDF file/);
  assert.equal(invalidHarness.createdObjectUrls.length, 0);
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
  assert.match(initialHtml, /min="0\.001" max="10"/);
  assert.match(initialHtml, /maxlength="2000"/);
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

test("override values enforce backend maxima and mandatory Md/Ms rules before mutation", async () => {
  const harness = createHarness({
    values: {
      wind_direction_multiplier_case: "circular_or_polygonal_chimney_tank_or_pole",
    },
    formValues: {
      average_roof_height_m: "30",
      building_height_m: "30",
    },
  });
  harness.evaluate(`
    workflowOverrides = [{
      variable: "Mzcat",
      direction: "N",
      override_value: 1.04,
      reason: "Existing reviewed value",
    }];
    globalThis.__valueInput = { value: "11" };
    globalThis.__reasonInput = { value: "Too high" };
    globalThis.__panel = {
      querySelector(selector) {
        return selector.includes("override_value") ? __valueInput : __reasonInput;
      },
    };
    globalThis.__button = {
      dataset: { key: "Mzcat:N", overrideAction: "apply" },
      closest() { return __panel; },
    };
  `);

  await harness.evaluate("updateOverride(__button)");
  assert.equal(harness.evaluate("workflowOverrides[0].override_value"), 1.04);
  assert.match(harness.element("workflow-summary").textContent, /no greater than 10/);

  harness.evaluate(`
    __valueInput.value = "1.05";
    __reasonInput.value = "x".repeat(2001);
  `);
  await harness.evaluate("updateOverride(__button)");
  assert.equal(harness.evaluate("workflowOverrides[0].override_value"), 1.04);
  assert.match(harness.element("workflow-summary").textContent, /2000 characters or fewer/);

  harness.evaluate(`
    __valueInput.value = "0.95";
    __reasonInput.value = "Attempted Md edit";
    __button.dataset.key = "Md:N";
  `);
  await harness.evaluate("updateOverride(__button)");
  assert.equal(harness.evaluate("workflowOverrides.length"), 1);
  assert.match(harness.element("workflow-summary").textContent, /Clause 3\.3.*Md = 1\.0/);

  harness.element("wind_direction_multiplier_case").value = "main_structure";
  harness.evaluate(
    '__valueInput.value = "0.9"; __reasonInput.value = "Attempted high-rise Ms edit"; __button.dataset.key = "Ms:N";',
  );
  await harness.evaluate("updateOverride(__button)");
  assert.equal(harness.evaluate("workflowOverrides.length"), 1);
  assert.match(harness.element("workflow-summary").textContent, /Clause 4\.3\.1.*Ms = 1\.0/);

  harness.evaluate(
    'currentWorkflow = { wind_region_assessment: { wind_region: "A0" } }; __valueInput.value = "0.5"; __reasonInput.value = "Attempted A0 Mzcat edit"; __button.dataset.key = "Mzcat:N";',
  );
  await harness.evaluate("updateOverride(__button)");
  assert.equal(harness.evaluate("workflowOverrides[0].override_value"), 1.04);
  assert.match(harness.element("workflow-summary").textContent, /Region A0 Table 4\.1.*mandatory/);
});

test("a rejected override restores the previous completed workflow and controls", async () => {
  const harness = createHarness();
  harness.evaluate(`
    workflowOverrides = [{
      variable: "Mzcat",
      direction: "N",
      override_value: 1.04,
      reason: "Existing reviewed value",
    }];
    currentWorkflow = { marker: "valid completed workflow" };
    currentWorkflowFingerprint = assessmentFingerprint();
    activeWorkflowPayload = { marker: "valid payload" };
    document.getElementById("workflow-map-frame").srcdoc = "<p>valid map</p>";
    document.getElementById("terrain-profile-frame").srcdoc = "<p>valid terrain</p>";
    renderWorkflow = function (workflow) {
      globalThis.__restoredWorkflow = workflow;
      document.getElementById("terrain-category-mzcat").innerHTML = "restored override controls";
    };
    runWorkflow = async function () {
      workflowRunId += 1;
      currentWorkflow = null;
      currentWorkflowFingerprint = null;
      document.getElementById("workflow-map-frame").srcdoc = "";
      document.getElementById("terrain-profile-frame").srcdoc = "";
      document.getElementById("workflow-summary").textContent = "Workflow failed: backend rejected override";
      return false;
    };
    globalThis.__valueInput = { value: "1.08" };
    globalThis.__reasonInput = { value: "Attempted replacement" };
    globalThis.__panel = {
      querySelector(selector) {
        return selector.includes("override_value") ? __valueInput : __reasonInput;
      },
    };
    globalThis.__button = {
      dataset: { key: "Mzcat:N", overrideAction: "apply" },
      closest() { return __panel; },
    };
  `);

  await harness.evaluate("updateOverride(__button)");

  assert.equal(harness.evaluate("workflowOverrides[0].override_value"), 1.04);
  assert.equal(harness.evaluate("currentWorkflow.marker"), "valid completed workflow");
  assert.equal(harness.evaluate("activeWorkflowPayload.marker"), "valid payload");
  assert.equal(harness.evaluate("__restoredWorkflow.marker"), "valid completed workflow");
  assert.match(harness.element("terrain-category-mzcat").innerHTML, /restored override controls/);
  assert.match(harness.element("workflow-map-frame").srcdoc, /valid map/);
  assert.match(harness.element("terrain-profile-frame").srcdoc, /valid terrain/);
  assert.match(harness.element("workflow-summary").textContent, /previous completed assessment was restored/i);
  assert.equal(harness.element("workflow-pdf").disabled, false);
  assert.equal(harness.element("workflow-report").disabled, false);
});

test("raw provenance includes and deduplicates workflow-level standards warnings", () => {
  const harness = createHarness();
  harness.context.__variables = [{
    variable: "VR",
    source_reference: "Table 3.1(A)",
    formula_basis: "Regional wind speed lookup",
    warnings: ["Variable-specific review warning."],
  }];
  harness.context.__workflowWarnings = [
    "Clause 4.2.3 mixed-terrain weighted averaging is not automated.",
    "Clause 4.4.2 most-adverse topographic cross-section is not automated.",
    "Clause 4.2.3 mixed-terrain weighted averaging is not automated.",
  ];

  harness.evaluate("renderRawProvenance(__variables, __workflowWarnings)");

  const html = harness.element("raw-provenance").innerHTML;
  assert.match(html, /Clause 4\.2\.3 mixed-terrain weighted averaging is not automated/);
  assert.match(html, /Clause 4\.4\.2 most-adverse topographic cross-section is not automated/);
  assert.match(html, /Variable-specific review warning/);
  assert.equal((html.match(/Clause 4\.2\.3/g) || []).length, 1);
});

test("directional Vsit,b rows omit constants and show VR and Mc once in Assessment Basis", () => {
  const harness = createHarness();
  harness.context.__rows = [{
    direction: "N",
    vr: 47.125,
    md: 0.95,
    mzcat: 1.04,
    ms: 0.9,
    mt: 1.1,
    mc: 0.876,
    final_vsitb: 41.02,
    is_governing: false,
  }];
  harness.evaluate("renderVsitbTable(__rows)");
  const rowHtml = harness.element("vsitb-table").innerHTML;

  harness.context.__vrRow = {
    variable: "VR",
    direction: null,
    unit: "m/s",
    recommended_value: 47.125,
    confidence: "high",
    calculated_value: 47.125,
    final_value: 47.125,
    override_value: null,
    override_reason: null,
  };
  harness.context.__mcRow = {
    variable: "Mc",
    direction: null,
    unit: "",
    recommended_value: 0.876,
    confidence: "high",
    calculated_value: 0.876,
    final_value: 0.876,
    override_value: null,
    override_reason: null,
  };
  harness.evaluate("renderVariableSection('VR', [__vrRow]); renderVariableSection('Mc', [__mcRow]);");
  const vrHtml = harness.element("wind-region-vr").innerHTML;
  const mcHtml = harness.element("climate-change-mc").innerHTML;

  assert.doesNotMatch(rowHtml, /47\.125/);
  assert.doesNotMatch(rowHtml, /0\.876/);
  assert.equal((rowHtml.match(/<td>/g) || []).length, 6);
  assert.equal(((vrHtml + mcHtml + rowHtml).match(/47\.125/g) || []).length, 1);
  assert.equal(((vrHtml + mcHtml + rowHtml).match(/0\.876/g) || []).length, 1);
  assert.match(vrHtml, /Override \(optional\)/);
  assert.doesNotMatch(mcHtml, /Override \(optional\)|data-override-action/);
  assert.deepEqual(
    JSON.parse(harness.evaluate("JSON.stringify(variableOrder)")),
    ["VR", "Mc", "Md", "Mzcat", "Ms", "Mt", "Vsitb"],
  );
  assert.equal(harness.evaluate("variableAnchors.Mc"), "climate-change-mc");

  const summarySection = HTML_SOURCE.match(
    /<section id="vsitb-summary"[\s\S]*?<\/section>/,
  )[0];
  assert.doesNotMatch(summarySection, /<th>VR<\/th>/);
  assert.match(summarySection, /VR x Mc x Md x Mz,cat x Ms x Mt/);
  const basisStart = HTML_SOURCE.indexOf('id="resolved-wind-inputs"');
  const directionalStart = HTML_SOURCE.indexOf('id="vsitb-summary"');
  assert.ok(HTML_SOURCE.indexOf('id="wind-region-vr"') > basisStart);
  assert.ok(HTML_SOURCE.indexOf('id="wind-region-vr"') < directionalStart);
  assert.ok(HTML_SOURCE.indexOf('id="climate-change-mc"') > basisStart);
  assert.ok(HTML_SOURCE.indexOf('id="climate-change-mc"') < directionalStart);
  assert.doesNotMatch(SCRIPT_SOURCE, /non_directional_inputs/);
});

test("mobile dashboard styles let address and KPI cells shrink to 320px", () => {
  const mobileStyles = STYLES_SOURCE.slice(STYLES_SOURCE.indexOf("@media (max-width: 900px)"));
  assert.match(mobileStyles, /\.dashboard-project \{[\s\S]*?display: grid;/);
  assert.match(mobileStyles, /\.address-autocomplete \{[\s\S]*?width: 100%;[\s\S]*?max-width: none;/);
  assert.match(mobileStyles, /\.dashboard-kpis \{[\s\S]*?repeat\(3, minmax\(0, 1fr\)\)/);
  assert.match(mobileStyles, /\.dashboard-kpis > div \{[\s\S]*?min-width: 0;/);
});
