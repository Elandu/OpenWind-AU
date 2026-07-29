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

  getBoundingClientRect() {
    return { x: 0, y: 0, width: 800, height: 600 };
  }
}

function createHarness(options = {}) {
  const elements = new Map();
  const storageValues = new Map();
  const timers = new Map();
  const timerDelays = new Map();
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
      if (options.failStorageWrites) {
        throw new Error("Browser storage unavailable");
      }
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
  for (const [name, value] of Object.entries(formValues)) {
    if (!Object.hasOwn(options.values || {}, name)) {
      element(name).value = value === null || value === undefined ? "" : String(value);
    }
  }

  class FakeFormData {
    get(name) {
      if (name === "address") return element("dashboard-address").value || null;
      if (name === "wind_direction_multiplier_case") {
        return element("wind_direction_multiplier_case").value || null;
      }
      return Object.hasOwn(formValues, name) ? element(name).value : null;
    }
  }

  element("wind_direction_multiplier_case").options = [
    { value: "main_structure" },
    { value: "cladding_or_immediate_support" },
    { value: "circular_or_polygonal_chimney_tank_or_pole" },
  ];

  const activeWorkspaceTab = options.activeWorkspaceTab || "map";
  const workspaceTabs = ["map", "profile"].map((name) => {
    const button = new FakeElement(`workspace-tab-${name}`);
    button.dataset.workspaceTab = name;
    if (name === activeWorkspaceTab) button.classList.add("is-active");
    return button;
  });
  const workspacePanels = ["map", "profile"].map((name) => {
    const panel = new FakeElement(`workspace-panel-${name}`);
    panel.dataset.workspacePanel = name;
    panel.hidden = name !== activeWorkspaceTab;
    if (name === activeWorkspaceTab) panel.classList.add("is-active");
    return panel;
  });
  element("workflow-map-frame").hidden = activeWorkspaceTab !== "map";
  element("terrain-profile-frame").hidden = activeWorkspaceTab !== "profile";

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
      if (selector === "[data-workspace-tab]") {
        return options.activeWorkspaceTab ? workspaceTabs : [];
      }
      if (selector === "[data-workspace-panel]") {
        return options.activeWorkspaceTab ? workspacePanels : [];
      }
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
      timerDelays.delete(timerId);
    },
    console,
    document,
    Element: FakeElement,
    fetch(...args) {
      return fetchImplementation(...args);
    },
    FormData: FakeFormData,
    localStorage,
    setTimeout(callback, delay = 0) {
      const timerId = nextTimerId;
      nextTimerId += 1;
      timers.set(timerId, callback);
      timerDelays.set(timerId, delay);
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
        timerDelays.clear();
        for (const [, callback] of pending) {
          await callback();
        }
      }
    },
    async flushTimersAtDelay(delay) {
      const pending = [...timers.entries()]
        .filter(([timerId]) => timerDelays.get(timerId) === delay);
      for (const [timerId, callback] of pending) {
        timers.delete(timerId);
        timerDelays.delete(timerId);
        await callback();
      }
    },
    localStorage,
    revokedObjectUrls,
    scheduledDelays,
    workspaceTabs,
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

test("saved orientation and optional dimensions restore using full-circle engineering azimuths", () => {
  const harness = createHarness({
    storage: {
      [DESIGN_LOCATION_KEY]: savedLocation({
        orientation_deg: -45,
        width_m: 24.6,
        length_m: 51.2,
      }),
      [PROJECT_NUMBER_KEY]: "OW-101",
    },
  });

  assert.equal(harness.element("structure_orientation_deg").value, "315");
  assert.equal(harness.element("building_width_m").value, "24.6");
  assert.equal(harness.element("building_length_m").value, "51.2");
  assert.equal(harness.evaluate("normalizeOrientation(360)"), 0);
  assert.equal(harness.evaluate("normalizeOrientation(-1)"), 359);
  assert.equal(harness.evaluate("normalizeOrientation(271)"), 271);
  assert.deepEqual(
    JSON.parse(harness.evaluate("JSON.stringify(orientationOptions)")),
    [0, 45, 90, 135, 180, 225, 270, 315],
  );
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
  }];
  currentWorkflow = {
    site: {
      latitude: -33.8688,
      longitude: 151.2093,
      display_name: "Old saved site",
    },
  };
  currentWorkflowFingerprint = assessmentFingerprint();`);

  assert.match(mapFrame.srcdoc, /Old saved site/);
  address.value = "200 New Road, Melbourne VIC";
  address.dispatch("input");

  const state = locationState(harness);
  assert.equal(state.locationMode, "address");
  assert.equal(state.coordinateOverride, null);
  assert.equal(harness.evaluate("workflowOverrides.length"), 0);
  assert.equal(harness.localStorage.getItem(DESIGN_LOCATION_KEY), null);
  assert.equal(harness.element("map-coordinate-readout").textContent, "Not positioned");
  const payload = JSON.parse(harness.evaluate("JSON.stringify(workflowPayload())"));
  assert.equal(payload.address, "200 New Road, Melbourne VIC");
  assert.equal(Object.hasOwn(payload, "latitude"), false);
  assert.equal(Object.hasOwn(payload, "longitude"), false);
  const secondaryPayload = JSON.parse(
    harness.evaluate("JSON.stringify(resolvedSiteRequestPayload(workflowPayload()))"),
  );
  assert.equal(secondaryPayload.address, "200 New Road, Melbourne VIC");
  assert.equal(Object.hasOwn(secondaryPayload, "latitude"), false);
  assert.equal(Object.hasOwn(secondaryPayload, "longitude"), false);
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

test("manual address resolution replaces saved coordinates instead of staying pinned", async () => {
  const requested = [];
  const resolvedSite = {
    display_name: "New Road, Oak Park, Melbourne VIC",
    latitude: -37.7134988,
    longitude: 144.9080534,
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
          return resolvedSite;
        },
      };
    },
    storage: {
      [DESIGN_LOCATION_KEY]: savedLocation(),
      [PROJECT_NUMBER_KEY]: "OW-101",
    },
  });
  const address = harness.element("dashboard-address");
  address.value = "200 New Road Melbourne VIC";
  address.dispatch("input");

  const pendingPayload = JSON.parse(
    harness.evaluate("JSON.stringify(workflowPayload())"),
  );
  assert.equal(pendingPayload.address, "200 New Road Melbourne VIC");
  assert.equal(Object.hasOwn(pendingPayload, "latitude"), false);
  assert.equal(Object.hasOwn(pendingPayload, "longitude"), false);
  assert.equal(harness.localStorage.getItem(DESIGN_LOCATION_KEY), null);

  await harness.evaluate("zoomMapToAddress()");

  const state = locationState(harness);
  const payload = JSON.parse(
    harness.evaluate("JSON.stringify(workflowPayload())"),
  );
  const persisted = JSON.parse(
    harness.localStorage.getItem(DESIGN_LOCATION_KEY),
  );
  assert.deepEqual(requested, [{
    body: { query: "200 New Road Melbourne VIC" },
    url: "/api/geocode/resolve",
  }]);
  assert.equal(state.locationMode, "coordinates");
  assert.deepEqual(state.coordinateOverride, resolvedSite);
  assert.equal(payload.latitude, resolvedSite.latitude);
  assert.equal(payload.longitude, resolvedSite.longitude);
  assert.equal(Object.hasOwn(payload, "address"), false);
  assert.equal(persisted.latitude, resolvedSite.latitude);
  assert.equal(persisted.longitude, resolvedSite.longitude);
  assert.notEqual(persisted.latitude, savedLocation().latitude);
  assert.notEqual(persisted.longitude, savedLocation().longitude);
});

test("a map drag persists adjusted coordinates and reuses them for map/profile payloads", async () => {
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
  assert.match(
    harness.element("workflow-progress-label").textContent,
    /Map adjusted and saved/,
  );

  harness.evaluate(`
    globalThis.__secondaryLocationRequests = [];
    postJson = async function (url, requestPayload) {
      __secondaryLocationRequests.push({
        url,
        payload: JSON.parse(JSON.stringify(requestPayload)),
      });
      return { text: async function () { return "<p>rendered</p>"; } };
    };
  `);
  await harness.evaluate("Promise.all([renderWorkflowMap(), renderTerrainProfileGraph()])");
  const secondaryRequests = JSON.parse(
    harness.evaluate("JSON.stringify(__secondaryLocationRequests)"),
  );
  assert.deepEqual(
    secondaryRequests.map((item) => item.url),
    ["/api/wind-workflow/map", "/api/plots/profile"],
  );
  for (const item of secondaryRequests) {
    assert.ok(
      Math.abs(item.payload.latitude - state.coordinateOverride.latitude) < 1e-12,
    );
    assert.ok(
      Math.abs(item.payload.longitude - state.coordinateOverride.longitude) < 1e-12,
    );
    assert.equal(Object.hasOwn(item.payload, "address"), false);
  }
});

test("map corner resizing updates, persists, and invalidates building dimensions", () => {
  const harness = createHarness({
    storage: {
      [DESIGN_LOCATION_KEY]: savedLocation(),
      [PROJECT_NUMBER_KEY]: "OW-101",
    },
  });
  const mapFrame = harness.element("workflow-map-frame");
  harness.evaluate(`
    currentWorkflow = { marker: "completed-before-resize" };
    currentWorkflowFingerprint = assessmentFingerprint();
    updateReportAvailability();
  `);
  assert.equal(harness.element("workflow-pdf").disabled, false);

  harness.dispatchWindow("message", {
    data: {
      type: "openwind-design-building-change",
      state: {
        latitude: -33.8688,
        longitude: 151.2093,
        offset_east_m: 0,
        offset_north_m: 0,
        orientation_deg: 271,
        orientation_modified: false,
        position_modified: false,
        dimensions_modified: true,
        width_m: 24.6,
        length_m: 51.2,
      },
    },
    source: mapFrame.contentWindow,
  });

  const persisted = JSON.parse(harness.localStorage.getItem(DESIGN_LOCATION_KEY));
  const payload = JSON.parse(harness.evaluate("JSON.stringify(workflowPayload())"));
  assert.equal(harness.element("building_width_m").value, "24.6");
  assert.equal(harness.element("building_length_m").value, "51.2");
  assert.equal(payload.building_width_m, 24.6);
  assert.equal(payload.building_length_m, 51.2);
  assert.equal(persisted.width_m, 24.6);
  assert.equal(persisted.length_m, 51.2);
  assert.equal(harness.element("workflow-pdf").disabled, true);
  assert.equal(harness.element("workflow-report").disabled, true);
  assert.match(
    harness.element("workflow-progress-label").textContent,
    /Map adjusted and saved/,
  );
});

test("map rotation persists a continuous front beta across the full engineering circle", () => {
  const harness = createHarness({
    storage: {
      [DESIGN_LOCATION_KEY]: savedLocation(),
      [PROJECT_NUMBER_KEY]: "OW-101",
    },
  });
  const mapFrame = harness.element("workflow-map-frame");

  harness.dispatchWindow("message", {
    data: {
      type: "openwind-design-building-change",
      state: {
        latitude: -33.8688,
        longitude: 151.2093,
        offset_east_m: 0,
        offset_north_m: 0,
        orientation_deg: 359.9,
        orientation_modified: true,
        position_modified: false,
        dimensions_modified: false,
      },
    },
    source: mapFrame.contentWindow,
  });

  const payload = JSON.parse(harness.evaluate("JSON.stringify(workflowPayload())"));
  const persisted = JSON.parse(harness.localStorage.getItem(DESIGN_LOCATION_KEY));
  assert.equal(harness.element("structure_orientation_deg").value, "359.9");
  assert.equal(harness.element("orientation-readout").textContent, "359.9 deg");
  assert.equal(payload.structure_orientation_deg, 359.9);
  assert.equal(persisted.orientation_deg, 359.9);
  assert.match(
    harness.element("workflow-progress-label").textContent,
    /Map adjusted and saved/,
  );
});

test("terrain profile requests exclude strict workflow-only fields", () => {
  const harness = createHarness();
  harness.context.__workflowPayload = {
    latitude: -33.8688,
    longitude: 151.2093,
    site_label: "Mapped project site",
    building_height_m: 14,
    radius_m: 2000,
    sample_interval_m: 25,
    mzcat_recommendation_mode: "conservative",
    project_number: "OW-STRICT",
    annual_exceedance_probability: "1/500",
    building_width_m: 24,
    building_length_m: 40,
    structure_orientation_deg: 127.5,
    assessment_status: "draft",
    workflow_overrides: [{ variable: "Mt", direction: "N", override_value: 1.1 }],
  };

  const profilePayload = JSON.parse(
    harness.evaluate("JSON.stringify(terrainProfileRequestPayload(__workflowPayload))"),
  );
  assert.deepEqual(profilePayload, {
    building_height_m: 14,
    latitude: -33.8688,
    longitude: 151.2093,
    mzcat_recommendation_mode: "conservative",
    radius_m: 2000,
    sample_interval_m: 25,
    site_label: "Mapped project site",
  });
  assert.equal(Object.hasOwn(profilePayload, "project_number"), false);
  assert.equal(Object.hasOwn(profilePayload, "structure_orientation_deg"), false);
  assert.equal(Object.hasOwn(profilePayload, "workflow_overrides"), false);
});

test("map location feedback distinguishes saved and session-only coordinates", async (t) => {
  const selectedSite = {
    display_name: "10 Example Street, Brisbane QLD",
    latitude: -27.4698,
    longitude: 153.0251,
  };

  await t.test("a blank project number is explicitly session-only", () => {
    const harness = createHarness();
    harness.context.__selectedSite = selectedSite;
    harness.evaluate("applyAddressSuggestion(__selectedSite)");

    assert.equal(locationState(harness).locationMode, "coordinates");
    assert.equal(harness.localStorage.getItem(DESIGN_LOCATION_KEY), null);
    assert.match(
      harness.element("workflow-progress-label").textContent,
      /session only.*enter a project number to save the current location/i,
    );

    const project = harness.element("dashboard-project-number");
    project.value = "OW-NEW";
    project.dispatch("input");
    project.dispatch("change");

    const persisted = JSON.parse(harness.localStorage.getItem(DESIGN_LOCATION_KEY));
    assert.equal(locationState(harness).locationMode, "coordinates");
    assert.equal(persisted.project_number, "OW-NEW");
    assert.equal(persisted.latitude, selectedSite.latitude);
    assert.equal(persisted.longitude, selectedSite.longitude);
    assert.match(
      harness.element("workflow-progress-label").textContent,
      /Current building location saved to the new project number/i,
    );
  });

  await t.test("a browser storage failure is explicitly session-only", () => {
    const harness = createHarness({
      failStorageWrites: true,
      storage: { [PROJECT_NUMBER_KEY]: "OW-FAIL-STORAGE" },
    });
    harness.context.__selectedSite = selectedSite;
    harness.evaluate("applyAddressSuggestion(__selectedSite)");

    assert.equal(locationState(harness).locationMode, "coordinates");
    assert.equal(harness.localStorage.getItem(DESIGN_LOCATION_KEY), null);
    assert.match(
      harness.element("workflow-progress-label").textContent,
      /session only.*browser storage is unavailable/i,
    );
  });
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

test("workflow stays draft without review controls or directional nudge UI", () => {
  const harness = createHarness();
  const payload = JSON.parse(harness.evaluate("JSON.stringify(workflowPayload())"));
  const mapHtml = harness.evaluate('initialMapHtml("Drag QA")');

  assert.equal(payload.assessment_status, "draft");
  assert.equal(Object.hasOwn(payload, "reviewed_by"), false);
  assert.equal(Object.hasOwn(payload, "engineer_notes"), false);
  assert.doesNotMatch(
    HTML_SOURCE,
    /Review and issue status|id="assessment_status"|id="reviewed_by"|id="engineer_notes"/,
  );
  assert.doesNotMatch(HTML_SOURCE, /data-map-nudge|map-nudge-control|Move building 1 m/);
  assert.doesNotMatch(SCRIPT_SOURCE, /mapNudge|nudgeDesignBuilding|action === "nudge"/);
  assert.doesNotMatch(STYLES_SOURCE, /\.map-nudge-control|\.map-nudge-buttons|\.workflow-review/);
  assert.match(mapHtml, /enableBuildingDrag\(footprint\)/);
  assert.match(mapHtml, /applyResizeFromLatLng/);
  assert.match(mapHtml, /applyOrientationFromLatLng/);
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

test("monopole Md display follows the effective mandatory Clause 3.3 case", () => {
  const harness = createHarness();
  harness.context.__monopoleWorkflow = {
    input: {
      structure_class: "monopole",
      wind_direction_multiplier_case: "main_structure",
    },
    direction_multiplier_assessment: {
      source_table: "AS/NZS 1170.2:2021 Clause 3.3 mandatory application",
    },
  };
  assert.equal(
    harness.evaluate("effectiveWindDirectionMultiplierCaseLabel(__monopoleWorkflow)"),
    "Circular/polygonal chimney, tank or pole (monopole)",
  );
});

test("HTML generation falls back to a download when popups are blocked and surfaces errors", async () => {
  const harness = createHarness();
  harness.evaluate(`
    currentWorkflow = { input: {}, variables: [], directional_vsitb: [], warnings: [] };
    currentWorkflowFingerprint = assessmentFingerprint();
    updateReportAvailability();
  `);
  harness.setFetch(async (url, request) => {
    assert.equal(url, "/api/wind-workflow/result/report/html");
    assert.equal(request.signal.aborted, false);
    return {
      ok: true,
      async text() { return "<!doctype html><title>Assessment</title>"; },
    };
  });

  await harness.element("workflow-report").dispatch("click");

  const link = harness.createdElements.find((element) => element.id === "a");
  assert.ok(link);
  assert.equal(link.href, "blob:openwind-test-1");
  assert.equal(link.download, "openwind-au-site-wind-assessment.html");
  assert.equal(link.clicked, true);
  assert.equal(link.removed, true);
  assert.equal(harness.createdObjectUrls.length, 1);
  assert.ok(harness.scheduledDelays.includes(300000));
  assert.equal(
    harness.element("report-status").textContent,
    "HTML report generated. Use the report window or download to save it.",
  );
  assert.equal(harness.element("workflow-report").disabled, false);

  const failedHarness = createHarness();
  failedHarness.evaluate(`
    currentWorkflow = { input: {}, variables: [], directional_vsitb: [], warnings: [] };
    currentWorkflowFingerprint = assessmentFingerprint();
    updateReportAvailability();
  `);
  failedHarness.setFetch(async () => {
    throw new Error("HTML renderer unavailable");
  });

  await failedHarness.element("workflow-report").dispatch("click");

  assert.match(failedHarness.element("report-status").textContent, /HTML report failed/);
  assert.match(failedHarness.element("workflow-summary").textContent, /HTML renderer unavailable/);
  assert.equal(failedHarness.createdObjectUrls.length, 0);
});

test("PDF generation falls back to a download when popups are blocked and surfaces errors", async () => {
  const pdfBytes = new Uint8Array(160);
  pdfBytes.set([0x25, 0x50, 0x44, 0x46, 0x2d]);
  const pdf = new Blob([pdfBytes], { type: "application/pdf" });
  const harness = createHarness();
  harness.evaluate(`
    currentWorkflow = {
      input: {},
      variables: [],
      directional_vsitb: [],
      warnings: [],
      integrity_token: "signed-pdf-result",
    };
    currentWorkflowFingerprint = assessmentFingerprint();
    updateReportAvailability();
  `);
  const mapFrame = harness.element("workflow-map-frame");
  let mapCaptureCommand;
  mapFrame.contentWindow.postMessage = (message) => {
    mapCaptureCommand = JSON.parse(JSON.stringify(message));
    harness.dispatchWindow("message", {
      source: mapFrame.contentWindow,
      data: {
        type: "openwind-map-screenshot",
        request_id: message.payload.request_id,
        result_integrity_token: message.payload.result_integrity_token,
        data_url: "data:image/jpeg;base64,/9j/AA==",
      },
    });
  };
  harness.setFetch(async (url, request) => {
    assert.equal(url, "/api/wind-workflow/result/report/pdf");
    assert.equal(request.signal.aborted, false);
    const body = JSON.parse(request.body);
    assert.equal(body.result.integrity_token, "signed-pdf-result");
    assert.equal(body.map_screenshot, "data:image/jpeg;base64,/9j/AA==");
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
  assert.equal(mapCaptureCommand.action, "capture-screenshot");
  assert.equal(
    mapCaptureCommand.payload.result_integrity_token,
    "signed-pdf-result",
  );
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
    currentWorkflow = {
      input: {},
      variables: [],
      directional_vsitb: [],
      warnings: [],
      integrity_token: "signed-invalid-pdf-result",
    };
    currentWorkflowFingerprint = assessmentFingerprint();
    updateReportAvailability();
  `);
  const invalidMapFrame = invalidHarness.element("workflow-map-frame");
  invalidMapFrame.contentWindow.postMessage = (message) => {
    invalidHarness.dispatchWindow("message", {
      source: invalidMapFrame.contentWindow,
      data: {
        type: "openwind-map-screenshot",
        request_id: message.payload.request_id,
        result_integrity_token: message.payload.result_integrity_token,
        data_url: "data:image/png;base64,iVBORw0KGgo=",
      },
    });
  };
  invalidHarness.setFetch(async () => ({
    ok: true,
    async blob() { return new Blob(["not pdf"], { type: "text/plain" }); },
  }));

  await invalidHarness.element("workflow-pdf").dispatch("click");
  assert.match(invalidHarness.element("report-status").textContent, /PDF report failed/);
  assert.match(invalidHarness.element("workflow-summary").textContent, /valid PDF file/);
  assert.equal(invalidHarness.createdObjectUrls.length, 0);
});

test("map screenshot capture rejects mismatched responses and times out cleanly", async () => {
  const mismatched = createHarness();
  const mapFrame = mismatched.element("workflow-map-frame");
  let captureCommand;
  mapFrame.contentWindow.postMessage = (message) => {
    captureCommand = JSON.parse(JSON.stringify(message));
  };
  const rejectedCapture = mismatched.evaluate(
    "captureWorkflowMapScreenshot({ integrity_token: 'signed-map-result' }, new AbortController().signal)",
  );
  const rejectedAssertion = assert.rejects(rejectedCapture, /did not match/);
  mismatched.dispatchWindow("message", {
    source: {},
    data: {
      type: "openwind-map-screenshot",
      request_id: captureCommand.payload.request_id,
      result_integrity_token: "signed-map-result",
      data_url: "data:image/jpeg;base64,/9j/AA==",
    },
  });
  assert.equal(
    mismatched.evaluate("pendingMapScreenshotRequests.size"),
    1,
  );
  mismatched.dispatchWindow("message", {
    source: mapFrame.contentWindow,
    data: {
      type: "openwind-map-screenshot",
      request_id: captureCommand.payload.request_id,
      result_integrity_token: "different-result",
      data_url: "data:image/jpeg;base64,/9j/AA==",
    },
  });
  await rejectedAssertion;
  assert.equal(
    mismatched.evaluate("pendingMapScreenshotRequests.size"),
    0,
  );

  const timedOut = createHarness();
  const timeoutPromise = timedOut.evaluate(
    "captureWorkflowMapScreenshot({ integrity_token: 'signed-timeout-result' }, new AbortController().signal)",
  );
  const timeoutAssertion = assert.rejects(timeoutPromise, /timed out/);
  await timedOut.flushTimers();
  await timeoutAssertion;
  assert.equal(timedOut.evaluate("pendingMapScreenshotRequests.size"), 0);

  const profileView = createHarness({ activeWorkspaceTab: "profile" });
  const profileMapFrame = profileView.element("workflow-map-frame");
  profileMapFrame.contentWindow.postMessage = (message) => {
    profileView.dispatchWindow("message", {
      source: profileMapFrame.contentWindow,
      data: {
        type: "openwind-map-screenshot",
        request_id: message.payload.request_id,
        result_integrity_token: message.payload.result_integrity_token,
        data_url: "data:image/jpeg;base64,/9j/AA==",
      },
    });
  };
  const profileCapture = profileView.evaluate(
    "captureWorkflowMapScreenshot({ integrity_token: 'signed-profile-result' })",
  );
  assert.equal(
    profileView.workspaceTabs.find((tab) => tab.classList.contains("is-active"))
      .dataset.workspaceTab,
    "map",
  );
  assert.equal(profileMapFrame.hidden, false);
  await profileView.flushTimersAtDelay(100);
  assert.equal(await profileCapture, "data:image/jpeg;base64,/9j/AA==");
  assert.equal(
    profileView.workspaceTabs.find((tab) => tab.classList.contains("is-active"))
      .dataset.workspaceTab,
    "profile",
  );
  assert.equal(profileMapFrame.hidden, true);
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
      "globalThis.__presentationPayloads = [];",
      "renderWorkflowMap = async function (payload) {",
      "  __presentationPayloads.push({ kind: 'map', payload: JSON.parse(JSON.stringify(payload)) });",
      "  return true;",
      "};",
      "renderTerrainProfileGraph = async function (payload) {",
      "  __presentationPayloads.push({ kind: 'profile', payload: JSON.parse(JSON.stringify(payload)) });",
      "};",
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
  const presentationPayloads = JSON.parse(
    harness.evaluate("JSON.stringify(__presentationPayloads)"),
  );
  assert.deepEqual(presentationPayloads.map((item) => item.kind), ["map", "profile"]);
  for (const item of presentationPayloads) {
    assert.equal(item.payload.latitude, -27.4698);
    assert.equal(item.payload.longitude, 153.0251);
    assert.equal(item.payload.site_label, address);
    assert.equal(Object.hasOwn(item.payload, "address"), false);
  }
});

test("fallback map failure preserves the completed assessment and resolved profile payload", async () => {
  const address = "22 Example Parade, Hobart TAS";
  const harness = createHarness({
    values: { "dashboard-address": address },
  });
  harness.context.__workflowResponse = {
    marker: "signed-result",
    input: { address, building_height_m: 10 },
    site: {
      latitude: -42.8826,
      longitude: 147.3257,
      display_name: address,
      ground_elevation_m: 12,
    },
  };
  harness.evaluate(`
    globalThis.__presentationRequests = [];
    postJson = async function (url, payload) {
      __presentationRequests.push({
        url,
        payload: JSON.parse(JSON.stringify(payload)),
      });
      if (url === "/api/wind-workflow") {
        return { json: async function () { return __workflowResponse; } };
      }
      if (url === "/api/wind-workflow/map") {
        throw new Error("Map renderer unavailable");
      }
      if (url === "/api/plots/profile") {
        return { text: async function () { return "<p>profile rendered</p>"; } };
      }
      throw new Error("Unexpected URL " + url);
    };
    renderWorkflow = function () {};
    globalThis.__requestPayload = workflowPayload();
  `);

  const succeeded = await harness.evaluate(
    "runWorkflowFallback(new Error('stream unavailable'), __requestPayload, workflowRunId, new AbortController().signal)",
  );

  assert.equal(succeeded, true);
  assert.equal(harness.evaluate("currentWorkflow.marker"), "signed-result");
  assert.equal(harness.evaluate("assessmentIsCurrent()"), true);
  assert.equal(harness.element("workflow-pdf").disabled, false);
  assert.equal(harness.element("workflow-report").disabled, false);
  assert.match(harness.element("workflow-map-frame").srcdoc, /Combined map failed/);
  assert.match(
    harness.element("workflow-progress-label").textContent,
    /Assessment complete; combined map unavailable/,
  );
  const requests = JSON.parse(harness.evaluate("JSON.stringify(__presentationRequests)"));
  const profileRequest = requests.find((item) => item.url === "/api/plots/profile");
  assert.ok(profileRequest);
  assert.equal(profileRequest.payload.latitude, -42.8826);
  assert.equal(profileRequest.payload.longitude, 147.3257);
  assert.equal(Object.hasOwn(profileRequest.payload, "address"), false);
});

test("stream map failure preserves a completed assessment and report controls", () => {
  const address = "33 Example Avenue, Adelaide SA";
  const harness = createHarness({
    values: { "dashboard-address": address },
  });
  harness.context.__requestPayload = JSON.parse(
    harness.evaluate("JSON.stringify(workflowPayload())"),
  );
  harness.context.__workflowResponse = {
    marker: "stream-signed-result",
    input: { address, building_height_m: 10 },
    site: {
      latitude: -34.9285,
      longitude: 138.6007,
      display_name: address,
      ground_elevation_m: 24,
    },
  };
  harness.evaluate(`
    renderWorkflow = function () {};
    renderTerrainProfileGraph = async function () {};
    globalThis.__streamSignal = new AbortController().signal;
    handleWorkflowStreamEvent({
      stage: "site",
      percent: 12,
      label: "Site located",
      data: {
        site_analysis: {
          input: __workflowResponse.input,
          site: __workflowResponse.site,
        },
      },
    }, workflowRunId, __requestPayload, __streamSignal);
    handleWorkflowStreamEvent({
      stage: "workflow",
      percent: 84,
      label: "Calculation complete",
      data: { workflow: __workflowResponse },
    }, workflowRunId, __requestPayload, __streamSignal);
  `);
  assert.equal(harness.evaluate("assessmentIsCurrent()"), true);

  harness.evaluate(`
    handleWorkflowStreamEvent({
      stage: "error",
      percent: 100,
      label: "Unexpected workflow failure. Check the server logs for the incident details.",
      data: { status_code: 500 },
    }, workflowRunId, __requestPayload, __streamSignal);
  `);

  assert.equal(harness.evaluate("currentWorkflow.marker"), "stream-signed-result");
  assert.equal(harness.evaluate("assessmentIsCurrent()"), true);
  assert.equal(harness.element("workflow-pdf").disabled, false);
  assert.equal(harness.element("workflow-report").disabled, false);
  assert.match(harness.element("workflow-map-frame").srcdoc, /Combined map failed/);
  assert.match(
    harness.element("workflow-progress-label").textContent,
    /Assessment complete; combined map unavailable/,
  );
});

test("Raw Data renders one canonical inline Value input with no per-row override controls", () => {
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
  assert.match(initialHtml, /data-raw-value/);
  assert.match(initialHtml, /value="1\.04"/);
  assert.match(initialHtml, /data-calculated-value="1\.04"/);
  assert.match(initialHtml, /min="0\.001"[\s\S]*max="10"/);
  assert.doesNotMatch(initialHtml, /data-override-field|data-override-action/);
  assert.doesNotMatch(initialHtml, /placeholder="reason|>Save<|>Reset</);

  harness.context.__roundedValueRow = {
    ...harness.context.__row,
    recommended_value: 1.0396,
    calculated_value: 1.0396,
    final_value: 1.0396,
    recommended_label: "Recommended Mz,cat 1.040",
  };
  const roundedValueHtml = harness.evaluate("variableRow(__roundedValueRow)");
  assert.match(roundedValueHtml, /value="1\.0396"/);
  assert.match(roundedValueHtml, /data-initial-value="1\.0396"/);

  harness.context.__longPrecisionRow = {
    ...harness.context.__row,
    variable: "Ms",
    recommended_value: 0.7019200058768141,
    calculated_value: 0.7019200058768141,
    final_value: 0.7019200058768141,
  };
  const longPrecisionHtml = harness.evaluate("variableRow(__longPrecisionRow)");
  assert.match(longPrecisionHtml, /value="0\.70192"/);
  assert.match(
    longPrecisionHtml,
    /data-initial-value="0\.7019200058768141"/,
  );
  assert.equal(
    harness.evaluate("rawDataValuesEqual(0.70192, 0.7019200058768141)"),
    true,
  );
  assert.equal(harness.evaluate("rawDataValuesEqual(1.039601, 1.0396)"), false);

  harness.evaluate(`
    workflowOverrides = [{
      variable: "Mzcat",
      direction: "N",
      override_value: 1.08,
      reason: "Reviewed terrain category",
    }];
  `);
  const overrideHtml = harness.evaluate("variableRow(__row)");
  assert.match(overrideHtml, /value="1\.08"/);
  assert.match(overrideHtml, /title="Reviewed terrain category">edited/);
  assert.doesNotMatch(overrideHtml, /data-override-field|data-override-action|>Reset</);

  const toolbar = HTML_SOURCE.match(/<div class="raw-data-toolbar">[\s\S]*?<\/div>\s*<div class="workflow-column/)[0];
  assert.equal((toolbar.match(/id="raw-data-save"/g) || []).length, 1);
  assert.equal((toolbar.match(/id="raw-data-edit-reason"/g) || []).length, 1);
  assert.match(toolbar, />Save all changes</);
  assert.match(toolbar, />Reset to calculated values</);
  assert.match(
    toolbar,
    /title="Replace every editable value with the latest calculation\. Click Save all changes to apply\."/,
  );
  assert.match(toolbar, />Undo unsaved edits</);
  assert.match(
    toolbar,
    /title="Return to the last saved values without recalculating or saving\."/,
  );
  assert.doesNotMatch(HTML_SOURCE, /<th>Override \(optional\)<\/th>|data-override-field/);
});

test("draft typing pauses reports without mutating accepted overrides, fingerprint, or request token", () => {
  const harness = createHarness();
  harness.evaluate(`
    workflowOverrides = [{
      variable: "Mzcat",
      direction: "N",
      override_value: 1.04,
      reason: "Accepted review",
    }];
    currentWorkflow = { marker: "accepted" };
    currentWorkflowFingerprint = assessmentFingerprint();
    reportRequestId = 17;
    globalThis.__draftInput = {
      value: "1.08",
      disabled: false,
      dataset: {
        rawValue: "",
        key: "Mzcat:N",
        variable: "Mzcat",
        direction: "N",
        calculatedValue: "1.0396",
        initialValue: "1.04",
      },
    };
    rawDataPanel.querySelectorAll = () => [__draftInput];
    refreshRawDataEditorState();
  `);

  assert.equal(harness.evaluate("rawDataEditorDirty"), true);
  assert.equal(harness.element("workflow-pdf").disabled, true);
  assert.equal(harness.element("workflow-report").disabled, true);
  assert.equal(harness.evaluate("workflowOverrides[0].override_value"), 1.04);
  assert.equal(harness.evaluate("currentWorkflowFingerprint"), harness.evaluate("assessmentFingerprint()"));
  assert.equal(harness.evaluate("reportRequestId"), 17);

  const runIdBeforeDiscard = harness.evaluate("workflowRunId");
  harness.evaluate("discardRawDataEdits()");
  assert.equal(harness.evaluate("__draftInput.value"), "1.04");
  assert.equal(harness.evaluate("rawDataEditorDirty"), false);
  assert.equal(harness.evaluate("workflowRunId"), runIdBeforeDiscard);
  assert.equal(harness.element("workflow-pdf").disabled, false);
  assert.equal(harness.element("workflow-report").disabled, false);
});

test("global validation enforces maxima and mandatory Md, Ms, and Mzcat rules before mutation", () => {
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
    globalThis.__input = {
      value: "11",
      disabled: false,
      dataset: {
        key: "Mzcat:N",
        variable: "Mzcat",
        direction: "N",
        calculatedValue: "1.0396",
        initialValue: "1.04",
      },
    };
  `);

  assert.throws(
    () => harness.evaluate("validateAndBuildRawDataOverrides([__input], 'Too high')"),
    /no greater than 10/,
  );
  assert.equal(harness.evaluate("workflowOverrides[0].override_value"), 1.04);

  harness.evaluate("__input.value = '1.05'");
  assert.throws(
    () => harness.evaluate("validateAndBuildRawDataOverrides([__input], 'x'.repeat(2001))"),
    /2000 characters or fewer/,
  );

  harness.evaluate(`
    __input.value = "0.95";
    __input.dataset.key = "Md:N";
    __input.dataset.variable = "Md";
  `);
  assert.throws(
    () => harness.evaluate("validateAndBuildRawDataOverrides([__input], 'Attempted Md edit')"),
    /Clause 3\.3.*Md = 1\.0/,
  );

  harness.element("wind_direction_multiplier_case").value = "main_structure";
  harness.evaluate(
    '__input.value = "0.9"; __input.dataset.key = "Ms:N"; __input.dataset.variable = "Ms";',
  );
  assert.throws(
    () => harness.evaluate("validateAndBuildRawDataOverrides([__input], 'Attempted high-rise Ms edit')"),
    /Clause 4\.3\.1.*Ms = 1\.0/,
  );

  harness.evaluate(
    'currentWorkflow = { wind_region_assessment: { wind_region: "A0" } }; __input.value = "0.5"; __input.dataset.key = "Mzcat:N"; __input.dataset.variable = "Mzcat";',
  );
  assert.throws(
    () => harness.evaluate("validateAndBuildRawDataOverrides([__input], 'Attempted A0 Mzcat edit')"),
    /Region A0 Table 4\.1.*mandatory/,
  );
  assert.equal(harness.evaluate("workflowOverrides[0].override_value"), 1.04);
});

test("mandatory directional values use one clause note and compact cell locks", () => {
  const harness = createHarness({
    values: {
      wind_direction_multiplier_case: "circular_or_polygonal_chimney_tank_or_pole",
    },
  });
  harness.context.__rows = [
    {
      direction: "N",
      md: 1,
      mzcat: 0.83,
      ms: 1,
      mt: 1,
      recommended_vsitb: 37.35,
      final_vsitb: 37.35,
      is_governing: true,
    },
    {
      direction: "S",
      md: 1,
      mzcat: 0.83,
      ms: 1,
      mt: 1,
      recommended_vsitb: 37.35,
      final_vsitb: 37.35,
      is_governing: true,
    },
  ];

  harness.evaluate("renderVsitbTable(__rows)");

  const restriction = harness.element("directional-edit-restrictions");
  const rowsHtml = harness.element("vsitb-table").innerHTML;
  assert.equal(restriction.hidden, false);
  assert.match(restriction.textContent, /Clause 3\.3.*Md = 1\.0/);
  assert.equal((restriction.textContent.match(/Clause 3\.3/g) || []).length, 1);
  assert.doesNotMatch(rowsHtml.replaceAll(/ title="[^"]*"/g, ""), /Clause 3\.3/);
  assert.equal((rowsHtml.match(/>locked<\/span>/g) || []).length, 2);
});

test("one global save builds an audited override and performs exactly one rerun", async () => {
  const harness = createHarness();
  harness.evaluate(`
    workflowOverrides = [];
    currentWorkflow = { marker: "accepted" };
    currentWorkflowFingerprint = assessmentFingerprint();
    globalThis.__saveInput = {
      value: "1.08",
      disabled: false,
      dataset: {
        rawValue: "",
        key: "Mzcat:N",
        variable: "Mzcat",
        direction: "N",
        calculatedValue: "1.0396",
        initialValue: "1.0396",
      },
    };
    rawDataPanel.querySelectorAll = () => [__saveInput];
    globalThis.__runCalls = 0;
    globalThis.__submittedOverrides = null;
    globalThis.__acceptedOverrideCountDuringRun = null;
    runWorkflow = async function (options) {
      __runCalls += 1;
      __submittedOverrides = options.workflowOverrides;
      __acceptedOverrideCountDuringRun = workflowOverrides.length;
      workflowRunId += 1;
      __saveInput.dataset.initialValue = __saveInput.value;
      currentWorkflow = { marker: "recalculated" };
      currentWorkflowFingerprint = assessmentFingerprint();
      return true;
    };
    refreshRawDataEditorState();
  `);

  const saved = await harness.evaluate("saveRawDataEdits()");

  assert.equal(saved, true);
  assert.equal(harness.evaluate("__runCalls"), 1);
  assert.equal(harness.evaluate("__acceptedOverrideCountDuringRun"), 0);
  assert.equal(harness.evaluate("__submittedOverrides[0].override_value"), 1.08);
  assert.equal(harness.evaluate("workflowOverrides.length"), 1);
  assert.equal(harness.evaluate("workflowOverrides[0].override_value"), 1.08);
  assert.match(
    harness.evaluate("workflowOverrides[0].reason"),
    /no user change reason was provided/,
  );
  assert.equal(harness.evaluate("rawDataEditorDirty"), false);
});

test("a rejected global save restores accepted state but preserves the unsaved draft", async () => {
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
    };
    globalThis.__runCalls = 0;
    runWorkflow = async function () {
      __runCalls += 1;
      workflowRunId += 1;
      currentWorkflow = null;
      currentWorkflowFingerprint = null;
      document.getElementById("workflow-map-frame").srcdoc = "";
      document.getElementById("terrain-profile-frame").srcdoc = "";
      document.getElementById("workflow-summary").textContent = "Workflow failed: backend rejected override";
      return false;
    };
    globalThis.__draftInput = {
      value: "1.08",
      disabled: false,
      dataset: {
        rawValue: "",
        key: "Mzcat:N",
        variable: "Mzcat",
        direction: "N",
        calculatedValue: "1.0396",
        initialValue: "1.04",
      },
    };
    rawDataPanel.querySelectorAll = () => [__draftInput];
    rawDataEditReason.value = "Attempted replacement";
    refreshRawDataEditorState();
  `);

  const saved = await harness.evaluate("saveRawDataEdits()");

  assert.equal(saved, false);
  assert.equal(harness.evaluate("__runCalls"), 1);
  assert.equal(harness.evaluate("workflowOverrides[0].override_value"), 1.04);
  assert.equal(harness.evaluate("currentWorkflow.marker"), "valid completed workflow");
  assert.equal(harness.evaluate("activeWorkflowPayload.marker"), "valid payload");
  assert.equal(harness.evaluate("__restoredWorkflow.marker"), "valid completed workflow");
  assert.match(harness.element("workflow-map-frame").srcdoc, /valid map/);
  assert.match(harness.element("terrain-profile-frame").srcdoc, /valid terrain/);
  assert.match(harness.element("workflow-summary").textContent, /previous completed assessment was restored/i);
  assert.equal(harness.evaluate("__draftInput.value"), "1.08");
  assert.equal(harness.element("raw-data-edit-reason").value, "Attempted replacement");
  assert.equal(harness.evaluate("rawDataEditorDirty"), true);
  assert.equal(harness.element("workflow-pdf").disabled, true);
  assert.equal(harness.element("workflow-report").disabled, true);
});

test("a form change that cancels a save cannot leak candidate overrides", async () => {
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
    globalThis.__draftInput = {
      value: "1.08",
      disabled: false,
      dataset: {
        rawValue: "",
        key: "Mzcat:N",
        variable: "Mzcat",
        direction: "N",
        calculatedValue: "1.0396",
        initialValue: "1.04",
      },
    };
    rawDataPanel.querySelectorAll = () => [__draftInput];
    runWorkflow = async function (options) {
      globalThis.__cancelledCandidate = options.workflowOverrides;
      workflowRunId += 2;
      currentWorkflow = null;
      currentWorkflowFingerprint = null;
      activeWorkflowController = null;
      document.getElementById("workflow-map-frame").srcdoc = "";
      return false;
    };
    renderWorkflow = function (workflow) {
      globalThis.__restoredWorkflow = workflow;
    };
    refreshRawDataEditorState();
  `);

  const saved = await harness.evaluate("saveRawDataEdits()");

  assert.equal(saved, false);
  assert.equal(harness.evaluate("__cancelledCandidate[0].override_value"), 1.08);
  assert.equal(harness.evaluate("workflowOverrides.length"), 1);
  assert.equal(harness.evaluate("workflowOverrides[0].override_value"), 1.04);
  assert.equal(harness.evaluate("currentWorkflow.marker"), "valid completed workflow");
  assert.equal(harness.evaluate("__restoredWorkflow.marker"), "valid completed workflow");
  assert.match(harness.element("workflow-map-frame").srcdoc, /valid map/);
  assert.equal(harness.evaluate("__draftInput.value"), "1.08");
  assert.equal(harness.evaluate("rawDataEditorDirty"), true);
});

test("a newly mandatory clause removes an incompatible saved edit before rerun", () => {
  const harness = createHarness({
    values: {
      wind_direction_multiplier_case: "circular_or_polygonal_chimney_tank_or_pole",
    },
  });
  harness.evaluate(`
    workflowOverrides = [
      {
        variable: "Md",
        direction: "N",
        override_value: 0.9,
        reason: "Prior main-structure review",
      },
      {
        variable: "Mt",
        direction: "N",
        override_value: 1.1,
        reason: "Still applicable",
      },
    ];
  `);

  assert.equal(harness.evaluate("removeNowRestrictedWorkflowOverrides()"), 1);
  assert.deepEqual(
    JSON.parse(harness.evaluate("JSON.stringify(workflowOverrides)")),
    [{
      variable: "Mt",
      direction: "N",
      override_value: 1.1,
      reason: "Still applicable",
    }],
  );
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
  for (const variable of ["Md", "Mzcat", "Ms", "Mt", "Vsitb"]) {
    assert.equal((rowHtml.match(new RegExp(`data-variable="${variable}"`, "g")) || []).length, 1);
  }
  assert.match(vrHtml, /data-variable="VR"/);
  assert.match(vrHtml, /value="47\.125"/);
  assert.doesNotMatch(vrHtml, /Override \(optional\)|data-override-action/);
  assert.match(mcHtml, /0\.876/);
  assert.doesNotMatch(mcHtml, /data-raw-value|Override \(optional\)|data-override-action/);
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
  assert.doesNotMatch(
    HTML_SOURCE,
    /id="wind-direction-md"|id="terrain-category-mzcat"|id="shielding-ms"|id="topographic-mt"/,
  );
  assert.doesNotMatch(SCRIPT_SOURCE, /non_directional_inputs/);
});

test("Clause 2.3 design rows render four plan faces without repeating cardinal inputs", () => {
  const harness = createHarness();
  harness.context.__designRows = [
    {
      face: "Front",
      theta_deg: 0,
      beta_deg: 337.5,
      sector_start_beta_deg: 292.5,
      sector_end_beta_deg: 22.5,
      raw_vdes_theta_mps: 42.125,
      vdes_theta_mps: 42.125,
      minimum_uls_applied: false,
      is_governing: true,
    },
    {
      face: "Right",
      theta_deg: 90,
      beta_deg: 67.5,
      sector_start_beta_deg: 22.5,
      sector_end_beta_deg: 112.5,
      raw_vdes_theta_mps: 38,
      vdes_theta_mps: 38,
      minimum_uls_applied: false,
      is_governing: false,
    },
    {
      face: "Back",
      theta_deg: 180,
      beta_deg: 157.5,
      sector_start_beta_deg: 112.5,
      sector_end_beta_deg: 202.5,
      raw_vdes_theta_mps: 29,
      vdes_theta_mps: 30,
      minimum_uls_applied: true,
      is_governing: false,
    },
    {
      face: "Left",
      theta_deg: 270,
      beta_deg: 247.5,
      sector_start_beta_deg: 202.5,
      sector_end_beta_deg: 292.5,
      raw_vdes_theta_mps: 40,
      vdes_theta_mps: 40,
      minimum_uls_applied: false,
      is_governing: false,
    },
  ];

  harness.evaluate("renderVdesTable(__designRows)");

  const html = harness.element("vdes-table").innerHTML;
  assert.equal((html.match(/<tr/g) || []).length, 4);
  assert.match(html, /Front/);
  assert.match(html, /337\.5 deg/);
  assert.match(html, /292\.5 to 22\.5 deg/);
  assert.match(html, /42\.125 m\/s/);
  assert.match(html, /30 m\/s ULS minimum applied/);
  assert.doesNotMatch(html, />N<|>NE<|>E<|>SE<|>S<|>SW<|>W<|>NW</);
  assert.match(HTML_SOURCE, /id="vdes-summary"/);
  assert.ok(HTML_SOURCE.indexOf('id="vdes-summary"') > HTML_SOURCE.indexOf('id="vsitb-summary"'));
});

test("required AEP and sample interval inputs keep blank values invalid instead of defaulting", () => {
  const aepInput = HTML_SOURCE.match(
    /<input\s+id="annual_exceedance_probability"[\s\S]*?\/>/,
  )[0];
  const sampleInput = HTML_SOURCE.match(
    /<input\s+id="sample_interval_m"[\s\S]*?\/>/,
  )[0];
  assert.match(aepInput, /\srequired(?:\s|\/?>)/);
  assert.match(aepInput, /minlength="1"/);
  assert.match(aepInput, /maxlength="50"/);
  assert.match(sampleInput, /\srequired(?:\s|\/?>)/);
  assert.match(sampleInput, /min="5"/);
  assert.match(sampleInput, /max="500"/);
  assert.match(sampleInput, /step="any"/);

  const harness = createHarness({
    formValues: {
      annual_exceedance_probability: "",
      sample_interval_m: "",
    },
  });
  const payload = JSON.parse(harness.evaluate("JSON.stringify(workflowPayload())"));
  assert.equal(payload.annual_exceedance_probability, "");
  assert.equal(payload.sample_interval_m, null);
  assert.notEqual(payload.annual_exceedance_probability, "1/500");
  assert.notEqual(payload.sample_interval_m, 0);
});

test("orientation input and initial map use a continuous engineering azimuth editor", () => {
  const orientationInput = HTML_SOURCE.match(
    /<input\s+id="structure_orientation_deg"[\s\S]*?\/>/,
  )[0];
  assert.match(orientationInput, /type="number"/);
  assert.match(orientationInput, /min="0"/);
  assert.match(orientationInput, /max="359\.9"/);
  assert.match(orientationInput, /step="0\.1"/);
  assert.match(orientationInput, /\srequired(?:\s|\/?>)/);
  assert.match(orientationInput, /aria-describedby="orientation-convention"/);
  assert.doesNotMatch(HTML_SOURCE, /<select id="structure_orientation_deg"/);
  assert.match(HTML_SOURCE, /class="help-tooltip-trigger"/);
  assert.match(HTML_SOURCE, /type="button"\s+aria-label="Show orientation convention"/);
  assert.match(HTML_SOURCE, /id="orientation-convention" class="help-tooltip-content" role="tooltip"/);
  assert.match(HTML_SOURCE, /Front &beta; is clockwise from true North/);
  assert.match(HTML_SOURCE, /Right, Back, and Left add/);
  assert.match(HTML_SOURCE, /drives the Clause 2\.3 V<sub>des,&theta;<\/sub> calculation/);
  assert.doesNotMatch(HTML_SOURCE, /id="orientation-convention" class="note"/);
  assert.match(STYLES_SOURCE, /\.help-tooltip:focus-within \.help-tooltip-content/);

  const harness = createHarness({
    values: { structure_orientation_deg: "127.5" },
  });
  const payload = JSON.parse(harness.evaluate("JSON.stringify(workflowPayload())"));
  const mapHtml = harness.evaluate('initialMapHtml("Orientation QA")');
  const embeddedMapScript = mapHtml.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
  assert.equal(payload.structure_orientation_deg, 127.5);
  assert.equal(harness.evaluate("normalizeOrientation(359.96)"), 0);
  assert.equal(harness.evaluate("normalizeOrientation(271.24)"), 271.2);
  assert.match(mapHtml, /orientation_deg: 127\.5/);
  assert.match(mapHtml, /orientation_options: \[0,45,90,135,180,225,270,315\]/);
  assert.match(mapHtml, /Front theta=0 at beta=/);
  assert.match(mapHtml, /\["Right", 90/);
  assert.match(mapHtml, /\["Back", 180/);
  assert.match(mapHtml, /\["Left", 270/);
  assert.match(mapHtml, /applyResizeFromLatLng/);
  assert.match(mapHtml, /Drag corner to resize breadth and depth/);
  assert.match(mapHtml, /dimensions_modified/);
  assert.doesNotThrow(() => new vm.Script(embeddedMapScript));
});

test("Raw Data and Documents are persistent below-map outputs, not map-view tabs", () => {
  const tabList = HTML_SOURCE.match(
    /<nav class="workspace-tabs"[\s\S]*?<\/nav>/,
  )[0];
  const rawDataSection = HTML_SOURCE.match(
    /<section id="workspace-panel-raw-data"[^>]*>/,
  )[0];
  const documentsSection = HTML_SOURCE.match(
    /<section id="workspace-panel-documents"[^>]*>/,
  )[0];

  assert.equal((tabList.match(/data-workspace-tab=/g) || []).length, 2);
  assert.match(tabList, />Map<\/button>/);
  assert.match(tabList, />Profile<\/button>/);
  assert.doesNotMatch(tabList, /Raw Data|Documents/);
  assert.match(rawDataSection, /class="below-map-output"/);
  assert.match(documentsSection, /class="below-map-output"/);
  assert.doesNotMatch(rawDataSection + documentsSection, /\shidden|role="tabpanel"|data-workspace-panel/);
  assert.ok(
    HTML_SOURCE.indexOf('id="workspace-panel-raw-data"')
      > HTML_SOURCE.indexOf('id="workflow-map-frame"'),
  );
  assert.ok(
    HTML_SOURCE.indexOf('id="workspace-panel-documents"')
      > HTML_SOURCE.indexOf('id="workspace-panel-raw-data"'),
  );
  assert.match(STYLES_SOURCE, /\.below-map-output\s*\{/);
  assert.match(STYLES_SOURCE, /body\.dashboard-page\s*\{\s*overflow-y: auto;/);
  assert.doesNotMatch(
    HTML_SOURCE,
    /does not certify the result|does not certify AS\/NZS 1170\.2 compliance/i,
  );
});

test("client validation explains paired dimensions, roof height, and field bounds", async (t) => {
  await t.test("breadth and depth must be supplied together", async () => {
    const harness = createHarness({
      values: {
        building_width_m: "12",
        building_length_m: "",
      },
    });
    const messages = JSON.parse(
      harness.evaluate("JSON.stringify(validateWorkflowInputs())"),
    );
    assert.deepEqual(messages, [
      "Enter both building breadth and building depth, or leave both blank.",
    ]);
    assert.match(
      harness.element("building_length_m").validationMessage,
      /both building breadth and building depth/,
    );
    assert.equal(await harness.evaluate("runWorkflow()"), false);
    assert.match(
      harness.element("workflow-summary").textContent,
      /Assessment inputs need attention.*both building breadth and building depth/,
    );
  });

  await t.test("average roof height cannot exceed overall height", () => {
    const harness = createHarness({
      values: {
        building_height_m: "10",
        building_width_m: "",
        building_length_m: "",
        average_roof_height_m: "10.1",
      },
    });
    const messages = JSON.parse(
      harness.evaluate("JSON.stringify(validateWorkflowInputs())"),
    );
    assert.deepEqual(messages, [
      "Average roof height must not exceed the overall building height.",
    ]);
    assert.match(
      harness.element("average_roof_height_m").validationMessage,
      /must not exceed the overall building height/,
    );
  });

  await t.test("obstruction radius must cover the complete 20h shielding sector", () => {
    const harness = createHarness({
      formValues: {
        building_height_m: "20",
        obstruction_radius_m: "200",
      },
    });
    const messages = JSON.parse(
      harness.evaluate("JSON.stringify(validateWorkflowInputs())"),
    );
    assert.deepEqual(messages, [
      "Obstruction radius must be at least 400 m to cover the full 20h shielding sector.",
    ]);
    assert.match(
      harness.element("obstruction_radius_m").validationMessage,
      /at least 400 m.*20h shielding sector/,
    );
  });

  await t.test("backend numeric bounds are checked before submission", () => {
    const harness = createHarness({
      values: {
        building_height_m: "201",
        building_width_m: "",
        building_length_m: "",
        structure_orientation_deg: "360",
        sample_interval_m: "4",
      },
    });
    const messages = JSON.parse(
      harness.evaluate("JSON.stringify(validateWorkflowInputs())"),
    );
    assert.deepEqual(messages, [
      "Building height must not exceed 200.",
      "Orientation must be less than 360.",
      "Sample interval must be at least 5.",
    ]);
  });

  await t.test("422 details identify the rejected request field", () => {
    const harness = createHarness();
    harness.evaluate(`
      const validationError = new Error("body.building_width_m: Input should be less than or equal to 5000");
      validationError.status = 422;
      renderWorkflowFailure(validationError);
    `);
    assert.equal(
      harness.element("workflow-progress-label").textContent,
      "Assessment inputs need attention",
    );
    assert.match(
      harness.element("workflow-summary").textContent,
      /body\.building_width_m: Input should be less than or equal to 5000/,
    );
  });
});

test("dashboard shows every tied governing direction and serves the current UI asset revision", () => {
  const harness = createHarness();
  harness.context.__workflow = {
    governing_direction: "N",
    governing_directions: ["N", "NE", "E"],
    governing_vsitb: 52.125,
    wind_region_assessment: { wind_region: "B" },
  };
  harness.evaluate("renderDashboardHeader(__workflow)");
  assert.equal(
    harness.element("dashboard-governing-direction").textContent,
    "N, NE, E",
  );
  assert.match(
    HTML_SOURCE,
    /wind_workflow\.js\?v=20260729-simplified-controls-1/,
  );
  assert.match(
    HTML_SOURCE,
    /styles\.css\?v=20260729-simplified-controls-1/,
  );
});

test("mobile dashboard styles let address and KPI cells shrink to 320px", () => {
  const mobileStyles = STYLES_SOURCE.slice(STYLES_SOURCE.indexOf("@media (max-width: 900px)"));
  assert.match(mobileStyles, /\.dashboard-project \{[\s\S]*?display: grid;/);
  assert.match(mobileStyles, /\.address-autocomplete \{[\s\S]*?width: 100%;[\s\S]*?max-width: none;/);
  assert.match(mobileStyles, /\.dashboard-kpis \{[\s\S]*?repeat\(3, minmax\(0, 1fr\)\)/);
  assert.match(mobileStyles, /\.dashboard-kpis > div \{[\s\S]*?min-width: 0;/);
});
