"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const scriptPath = path.resolve(__dirname, "../../src/openwind_au/static/app.js");
const indexPath = path.resolve(__dirname, "../../src/openwind_au/static/index.html");
const source = fs.readFileSync(scriptPath, "utf8");
const indexSource = fs.readFileSync(indexPath, "utf8");

function importContext(fetchImpl) {
  const helperStart = source.indexOf("async function requestManualOverrideImport");
  const helperEnd = source.indexOf('obstructionCsv.addEventListener("change"', helperStart);
  assert.ok(helperStart >= 0 && helperEnd > helperStart);
  const applications = [];
  const context = vm.createContext({
    AbortController,
    fetch: fetchImpl,
    applyBrowserOverrides(overrides, options) {
      applications.push({ overrides: structuredClone(overrides), options });
    },
    finishImportRequest() {},
    importRequestIsCurrent() {
      return true;
    },
    startImportRequest() {
      return {
        requestId: 1,
        controller: new AbortController(),
        fingerprint: "test-inputs",
      };
    },
  });
  vm.runInContext(source.slice(helperStart, helperEnd), context);
  return { context, applications };
}

async function runImport(context, functionName, content) {
  context.importContent = content;
  return vm.runInContext(`${functionName}(importContent)`, context);
}

function okJson(value) {
  return {
    ok: true,
    statusText: "OK",
    async json() {
      return structuredClone(value);
    },
  };
}

test("legacy CSV import posts the untouched file body to the strict CSV endpoint", async () => {
  const requests = [];
  const csv = 'obstruction_id,height_m,notes\r\nbuilding-1,12.5,"verified, onsite"\r\n';
  const { context, applications } = importContext(async (url, options) => {
    requests.push({ url, options });
    return okJson([{
      obstruction_id: "building-1",
      height_m: 12.5,
      building_levels: null,
      height_source: "manual_review",
      notes: "verified, onsite",
    }]);
  });

  await runImport(context, "importObstructionCsvText", csv);

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/api/obstructions/import/csv");
  assert.equal(requests[0].options.method, "POST");
  assert.equal(requests[0].options.headers["Content-Type"], "text/csv");
  assert.equal(requests[0].options.body, csv);
  assert.equal(applications.length, 1);
  assert.equal(applications[0].overrides[0].height_m, 12.5);
});

test("legacy manual JSON import posts the untouched body to the strict JSON endpoint", async () => {
  const requests = [];
  const json = '[{"obstruction_id":"building-1","height_m":8,"height_m":9}]';
  const { context, applications } = importContext(async (url, options) => {
    requests.push({ url, options });
    return okJson([{
      obstruction_id: "building-1",
      height_m: 9,
      building_levels: null,
      height_source: "manual_review",
      notes: null,
    }]);
  });

  await runImport(context, "importObstructionJsonText", json);

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/api/obstructions/import/json");
  assert.equal(requests[0].options.headers["Content-Type"], "application/json");
  assert.equal(requests[0].options.body, json);
  assert.equal(applications.length, 1);
});

test("legacy import rejects an empty manual override response before applying it", async () => {
  const { context, applications } = importContext(async () => okJson([{
    obstruction_id: "building-1",
    height_m: null,
    building_levels: null,
    height_source: "manual_review",
    notes: null,
  }]));

  await assert.rejects(
    runImport(
      context,
      "importObstructionJsonText",
      '[{"obstruction_id":"building-1","height_m":12}]',
    ),
    /invalid manual override response/,
  );
  assert.equal(applications.length, 0);
});

test("reviewed-footprint inventory stays on the local geometry import path", async () => {
  let fetchCount = 0;
  const { context, applications } = importContext(async () => {
    fetchCount += 1;
    throw new Error("reviewed footprints must not use the manual override API");
  });
  const reviewed = JSON.stringify({
    export_format: "openwind-au-reviewed-obstructions-v1",
    input: { radius_m: 500 },
    site: { latitude: -33.86, longitude: 151.21 },
    obstructions: [{
      obstruction_id: "reviewed-building",
      height_m: null,
      building_levels: null,
      footprint_geometry: {
        type: "Polygon",
        coordinates: [[[151.21, -33.86], [151.22, -33.86], [151.21, -33.86]]],
      },
    }],
  });

  await runImport(context, "importObstructionJsonText", reviewed);

  assert.equal(fetchCount, 0);
  assert.equal(applications.length, 1);
  assert.equal(applications[0].options.reviewedFootprints, true);
});

test("local reviewed-footprint import rejects duplicate object members", async () => {
  let fetchCount = 0;
  const { context, applications } = importContext(async () => {
    fetchCount += 1;
    throw new Error("duplicate reviewed JSON must not reach the manual override API");
  });
  const reviewed = `{
    "export_format": "openwind-au-reviewed-obstructions-v1",
    "obstructions": [{
      "obstruction_id": "reviewed-building",
      "height_m": 8,
      "height_m": 9,
      "footprint_geometry": {
        "type": "Polygon",
        "coordinates": [[[151.21, -33.86], [151.22, -33.86], [151.21, -33.86]]]
      }
    }]
  }`;

  await assert.rejects(
    runImport(context, "importObstructionJsonText", reviewed),
    /JSON contains duplicate key: height_m/,
  );
  assert.equal(fetchCount, 0);
  assert.equal(applications.length, 0);
});

test("geometry-only reviewed records remain missing instead of becoming manual overrides", () => {
  const applyStart = source.indexOf("function applyBrowserOverrides");
  const applyEnd = source.indexOf("function refreshShieldingSectors", applyStart);
  assert.ok(applyStart >= 0 && applyEnd > applyStart);
  const context = vm.createContext({
    reviewedObstructions: [],
    currentObstructionInventory: null,
    cancelMapRequest() {},
    cancelTerrainReportRequest() {},
    document: { getElementById: () => ({ value: "3" }) },
    refreshShieldingSectors() {},
    renderObstructionInventory() {},
  });
  vm.runInContext(source.slice(applyStart, applyEnd), context);
  context.records = [{
    obstruction_id: "reviewed-building",
    height_m: null,
    building_levels: null,
    footprint_geometry: {
      type: "Polygon",
      coordinates: [[[151.21, -33.86], [151.22, -33.86], [151.21, -33.86]]],
    },
  }];

  vm.runInContext(
    "applyBrowserOverrides(records, { reviewedFootprints: true })",
    context,
  );
  const imported = JSON.parse(vm.runInContext("JSON.stringify(reviewedObstructions[0])", context));

  assert.equal(imported.height_source, "missing");
  assert.equal(imported.height_m, null);
  assert.equal(imported.building_levels, null);
  assert.equal(imported.footprint_source, "manual_reviewed");
});

test("legacy app cache revision includes the state-safe obstruction review flow", () => {
  assert.match(indexSource, /app\.js\?v=20260715-state-safety-1/);
});
