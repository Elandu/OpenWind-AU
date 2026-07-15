"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const scriptPath = path.resolve(__dirname, "../../src/openwind_au/static/app.js");
const source = fs.readFileSync(scriptPath, "utf8");
const helperStart = source.indexOf("function normalizeLocationPayload");
const helperEnd = source.indexOf("function formPayload", helperStart);
assert.ok(helperStart >= 0 && helperEnd > helperStart);

const context = vm.createContext({ Number });
vm.runInContext(source.slice(helperStart, helperEnd), context);

function normalize(payload) {
  context.payload = structuredClone(payload);
  return JSON.parse(
    vm.runInContext("JSON.stringify(normalizeLocationPayload(payload))", context),
  );
}

test("legacy analysis payload uses address only when no coordinate pair exists", () => {
  assert.deepEqual(
    normalize({ address: "Sydney NSW", latitude: null, longitude: null }),
    { address: "Sydney NSW" },
  );
});

test("legacy analysis payload moves a coordinate label out of the geocoded address field", () => {
  assert.deepEqual(
    normalize({ address: "Sydney NSW", latitude: -33.86, longitude: 151.21 }),
    {
      site_label: "Sydney NSW",
      latitude: -33.86,
      longitude: 151.21,
    },
  );
  assert.equal(
    source.match(/return normalizeLocationPayload\(payload\);/g)?.length,
    2,
    "both legacy site and obstruction payload builders must use the location contract",
  );
});

test("legacy analysis payload preserves partial coordinates for server validation", () => {
  assert.deepEqual(
    normalize({ address: "Sydney NSW", latitude: -33.86, longitude: null }),
    { address: "Sydney NSW", latitude: -33.86 },
  );
});
