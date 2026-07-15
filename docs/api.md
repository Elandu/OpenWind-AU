# API Usage

The API exposes preliminary terrain, topographic screening, obstruction inventory, and
shielding-sector workflows. It does not calculate certified AS/NZS 1170.2 multipliers or design
wind pressures.

For MCP clients, use the separate stdio or Streamable HTTP server documented in
[`mcp.md`](mcp.md).

## Service Health

```text
GET /health/live
GET /health
```

`/health/live` is a process-liveness probe. It returns HTTP 200 with `{"status": "ok"}` when the
API process can answer requests.

`/health` is a deployment-readiness probe. It returns HTTP 200 with `status: "ready"` only when a
non-test wind-region dataset, reviewed and complete `VR`, `Md`, `Mz,cat`, and `Ms` lookup data,
matching `Mz,cat`/`Ms` lookup digests, a durable `OPENWIND_RESULT_SIGNING_KEY`, and the configured DEM
provider/cache are usable. Otherwise it returns HTTP 503 with `status: "not_ready"` and a
consumer-safe `checks` object. Use `/health/live` for restart decisions and `/health` for routing
assessment traffic.

Assessment endpoints distinguish request failures from deployment and provider failures: malformed
or unsupported request data returns HTTP 4xx, an unavailable required local dataset or invalid
server configuration returns HTTP 503, and a required upstream provider failure returns HTTP 502.
HTTP 502 responses use a generic consumer-safe detail; full provider, cache, URL, and low-level
exception diagnostics are retained only in server logs.
The NDJSON workflow stream always starts with HTTP 200, so clients must also inspect a terminal
`error` event's `data.status_code` for the equivalent 400, 502, 503, or 500 classification.

All JSON request models are strict. Unknown fields, booleans used as numbers, and numeric strings
such as `"10"` are rejected with HTTP 422 instead of being ignored or coerced.

Raw obstruction-provider and wind-region diagnostics are intentionally absent from OpenAPI and
disabled by default. For a trusted local troubleshooting session only, set
`OPENWIND_ENABLE_DEBUG_ENDPOINTS=1` before starting the API to enable `/api/debug/*` and
`GET /api/obstructions/debug`. Do not expose those routes on a public deployment because they can
include local dataset paths, polygon attributes, provider queries, cache diagnostics, and pipeline
details. Normal assessment responses omit the local wind-region dataset path and full GIS polygon;
use the dedicated map endpoint for rendered geometry.

## Analyse A Site

Every assessment request must use exactly one location mode:

- `address` alone asks the server to geocode that address; or
- `latitude` and `longitude` supply the calculation coordinates directly. An optional `site_label`
  may describe those coordinates without being geocoded.

Do not send `address` together with coordinates. For example, a map-selected or dragged site uses:

```json
{
  "site_label": "1 Macquarie Street, Sydney NSW",
  "latitude": -33.8568,
  "longitude": 151.2153,
  "building_height_m": 12
}
```

```bash
curl -X POST http://127.0.0.1:8000/api/analyse \
  -H "Content-Type: application/json" \
  -d '{
    "latitude": -33.8568,
    "longitude": 151.2153,
    "building_height_m": 12,
    "radius_m": 2000,
    "sample_interval_m": 100
  }'
```

The response includes:

- resolved site location and ground elevation;
- 8 terrain profiles for N, NE, E, SE, S, SW, W, and NW;
- preliminary topographic screening results for each direction;
- assumptions, limitations, and disclaimer text.

## Export JSON

```text
POST /api/export/json
```

The payload is the same as `/api/analyse`.

## Interactive Outputs

```text
POST /api/plots/profile
POST /api/maps/site
```

The terrain profile plot includes site, candidate base, candidate crest, `H`, and `Lu` overlays
where a candidate feature is detected.

## Obstruction Inventory

```text
POST /api/obstructions/inventory
POST /api/obstructions/map
POST /api/obstructions/report/html
POST /api/obstructions/import/csv
POST /api/obstructions/import/json
```

CSV and JSON imports are limited to 1 MB and must use `text/csv`, `application/csv`, or
`application/json` as documented in OpenAPI. CSV accepts only `obstruction_id`, `height_m`,
`building_levels`, `height_source`, and `notes`; duplicate/unknown headers and surplus values are
rejected. Each JSON/CSV item requires a nonblank `obstruction_id` and at least one of `height_m` or
`building_levels`. Unknown or duplicate JSON member names and numeric strings are rejected.

The obstruction inventory uses Microsoft Australia Building Footprints as the preferred building
geometry source when a local cache is configured. OSM/Overpass is used as fallback and to merge
useful attributes such as `height`, `building:levels`, and building type onto matching Microsoft
footprints. Heights follow this priority order:

1. manual verified height;
2. DSM-DTM estimate when configured DSM and DTM data are available;
3. OSM explicit height;
4. OSM `building:levels` converted with the configured storey height;
5. low-confidence estimate from configured class assumptions;
6. unknown.

Missing heights are not inferred from footprint size. Default class assumptions are 3.0 m for a
single-storey residential obstruction, 6.0 m for a two-storey residential obstruction, and 4.0 m
per commercial storey. These assumptions are configurable in the request payload.

DSM-DTM enrichment records `ground_rl_m`, `surface_rl_m`, `obstruction_height_m`,
`height_source`, `confidence`, `enrichment_method`, classification, source-height summary fields,
and warnings.

When `building_height_m` is supplied, the response includes eight preliminary shielding sectors:
N, NE, E, SE, S, SW, W, and NW. Each sector is 45 degrees wide and uses radius `20 *
building_height_m`. Obstructions are included only where available `hs >= building_height_m`. For each
sector, the response reports `ns`, average `hs`, average `bs` normal to wind, `ls`, shielding
parameter `s`, an indicative `Ms`, high-confidence height count, estimated-height count,
unknown-height count, and overall shielding confidence. These values are screening outputs only
and require competent engineering review.

The obstruction inventory radius is independent from the terrain analysis radius. In the browser UI
it defaults to 500 m so dense urban building-footprint queries do not inherit a 2 km or 4 km
terrain radius. If the Microsoft cache is unavailable, the response reports
`microsoft_source_status`, `microsoft_cache_status`, `osm_fallback_used`, source totals, and
consumer-safe warnings. Server cache paths and filenames, raw source geometry, provider queries,
sample source IDs, excluded source objects, and pipeline logs are not included in the public
inventory response. If Microsoft and OSM sources are both unavailable, the inventory response
remains HTTP 200 with `data_source_status: "unavailable"`, an empty obstruction list, and warning
text for the reviewer.

Microsoft cache setup uses GeoJSON or GeoJSONL tiles in EPSG:4326. Set
`OPENWIND_MICROSOFT_FOOTPRINT_CACHE` to a directory containing files such as
`tiles/-34_151.geojsonl`. OpenWind-AU does not automatically download the full country-wide
Microsoft ZIP during a site query because it is large; use a prepared clipped or tiled cache for
routine local analysis.

DSM/DTM rasters can be configured with `OPENWIND_DSM_PATH` and `OPENWIND_DTM_PATH`. If either
dataset is missing, the API returns `DSM unavailable` or `DTM unavailable` warnings and continues
with manual/OSM height sources.

## Terrain Category Evidence

```text
GET  /terrain-category
POST /api/terrain-category/evidence
POST /api/mzcat/assessment
POST /api/terrain-category/map
POST /api/terrain-category/report/html
GET  /api/terrain-category/validation/cases
GET  /api/terrain-category/validation
```

The terrain category evidence workflow analyses N, NE, E, SE, S, SW, W, and NW independently. It
uses terrain profiles plus the obstruction inventory to report built-up coverage, vegetation
coverage, open-terrain percentage, obstruction heights, obstruction density, spacing, vegetation
density, directional fetch, shielding confidence, separate evidence scores, warnings, and a
qualified suggested terrain category range.

The API does not assign a final AS/NZS 1170.2 terrain category and does not calculate final
design wind speeds. It reports indicative `Mz,cat` ranges from the suggested terrain category
range for competent engineering review. Suggested ranges such as `TC2-TC2.5` or `TC2.5-TC3`
are prompts for review, not confirmed categories.

For the human review workflow, see [`workflow.md`](workflow.md) and
[`reviewer-checklist.md`](reviewer-checklist.md).

## Site Wind Workflow Overrides

```text
POST /api/wind-workflow
POST /api/wind-workflow/stream
POST /api/wind-workflow/map
POST /api/wind-workflow/report/html
POST /api/wind-workflow/report/pdf
```

Wind-workflow requests use the same strict location and type contract. In particular, legacy
request fields such as `wind_region`,
`regional_wind_speed_mps`, `wind_direction_multipliers`, and `workflow_reviews` are not accepted.
Use the two explicit override collections instead:

- `class_multiplier_overrides` accepts at most one entry per direction. Every entry requires a
  non-empty `reason` and at least one reviewed `terrain_category`, `shielding_class`, or
  `topographic_class`. An exact `mzcat`, `ms`, or `mt` value is accepted only when its corresponding
  class is also supplied.
- A terrain category selects `Mz,cat` from Table 4.1. Project-specific shielding (`FS/PS/NS`) and
  topographic (`T0-T5`) class labels are provenance only; they do not imply a standard multiplier.
  Supply an explicit reviewed `ms` or `mt` to replace the calculated Clause 4.3 or 4.4 value.
- `workflow_overrides` accepts at most one entry for each variable/direction pair. A `VR` override
  is non-directional and must omit `direction`; `Md`, `Mzcat`, `Ms`, `Mt`, and `Vsitb` overrides
  require one of `N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, or `NW`. Every entry requires a positive
  `override_value` and a non-empty `reason`.

These overrides are reviewed engineering inputs. They preserve their reasons in result provenance
and do not certify the automated GIS evidence or final design outcome.

`assessment_status` accepts only `draft` or `reviewed`. A reviewed preliminary assessment requires
both `reviewed_by` and non-empty `engineer_notes`. `final` is rejected because this service does
not issue certified assessments. HTML and PDF reports remain marked `PRELIMINARY - NOT FOR
CERTIFICATION` in either state.

The response fields named `final_value` and `final_vsitb` are retained for API compatibility. They
mean the selected calculated or explicitly overridden value used in the current preliminary
workflow; they are not a certification state. Review metadata and override collections have one
source of truth under `input` and are not repeated at the result top level.

`/api/wind-workflow/stream` is documented and returned as `application/x-ndjson`. PDF routes return
binary `application/pdf` with `Content-Disposition`; completed-result routes require an authentic
server integrity token and reject unknown, excluded, or coercible nested representations.

## Validation

```text
GET /api/validation/cases
GET /api/validation
GET /api/validation/report/html
GET /api/calculation-validation
GET /api/reference-validation/7989
```

Validation responses are qualitative audit outputs. They are not proof of engineering accuracy or
code compliance. The reference calculation 7989 endpoint compares the current OpenWind workflow against the
stored Byambee Street reference classes: `TC3` terrain, `FS` shielding, and `T0`/`T1` topography.
Use `GET /api/reference-validation/7989?apply_reference_overrides=true` to rerun the comparison
with the encoded reference calculation classes applied through `class_multiplier_overrides`.
