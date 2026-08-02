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
matching lookup digests, a durable `OPENWIND_RESULT_SIGNING_KEY`, and the configured DEM
provider/cache are usable. `VR` and `Md` hash canonical `tables`; `Mz,cat` and `Ms` hash canonical
`values`. Otherwise the endpoint returns HTTP 503 with `status: "not_ready"` and a consumer-safe
`checks` object. Use `/health/live` for restart decisions and `/health` for routing assessment
traffic.

Assessment endpoints distinguish request failures from deployment and provider failures: malformed
or unsupported request data returns HTTP 4xx, an unavailable required local dataset or invalid
server configuration returns HTTP 503, and a required upstream provider failure returns HTTP 502.
HTTP 502 responses use a generic consumer-safe detail; full provider, cache, URL, and low-level
exception diagnostics are retained only in server logs.
The NDJSON workflow stream always starts with HTTP 200, so clients must also inspect a terminal
`error` event's `data.status_code` for the equivalent 400, 502, 503, or 500 classification.

All JSON request models are strict. Unknown fields, booleans used as numbers, and numeric strings
such as `"10"` are rejected with HTTP 422 instead of being ignored or coerced. Request bodies are
capped at 1 MiB before route parsing, except the completed-result HTML/PDF routes, which use a
separate 4 MiB cap so a valid signed workflow result can be rendered. JSON duplicate members,
`NaN`, and infinite/overflowing numbers are rejected. Validation responses omit submitted values
and cap the number of errors.

Set `OPENWIND_ENVIRONMENT=production` and an explicit comma-separated
`OPENWIND_TRUSTED_HOSTS` allowlist for production. In that mode, OpenAPI documentation is disabled
and assessment/completed-report routes return HTTP 503 until `/health` is ready. Dynamic responses
use `Cache-Control: no-store` and baseline browser security headers.

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

`POST /api/full-analysis` runs the combined site, obstruction, terrain-category, wind-input, and
map workflow used by the legacy dashboard. New integrations should prefer the explicit
`/api/wind-workflow` contract when they need the signed directional site-wind result.

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
terrain radius. When the common reference height is 25 m or less, the request must still provide
`obstruction_radius_m >= 20h`; shorter requests are rejected because they cannot contain the full
Clause 4.3.1 shielding sector. If the Microsoft cache is unavailable, the response reports
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

This terrain-category evidence endpoint does not assign a final AS/NZS 1170.2 terrain category or
by itself calculate design wind speeds. It reports indicative `Mz,cat` ranges from the suggested
terrain category range for competent engineering review. Suggested ranges such as `TC2-TC2.5` or
`TC2.5-TC3` are prompts for review, not confirmed categories.

For the human review workflow, see [`workflow.md`](workflow.md) and
[`reviewer-checklist.md`](reviewer-checklist.md).

## Site Wind Workflow Overrides

```text
POST /api/wind-workflow
POST /api/wind-workflow/stream
POST /api/wind-workflow/map
POST /api/wind-workflow/report/html
POST /api/wind-workflow/report/pdf
POST /api/wind-workflow/result/report/html
POST /api/wind-workflow/result/report/pdf
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
- `workflow_overrides` accepts at most one entry for each variable/direction pair. `VR`
  overrides are non-directional and must omit `direction`; `Md`, `Mzcat`, `Ms`, `Mt`, and `Vsitb` overrides
  require one of `N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, or `NW`. Every entry requires a positive
  `override_value` and a non-empty `reason`.

`wind_direction_multiplier_case` records whether `Md` is being applied to the main structure,
cladding/immediate supports, or a circular/polygonal chimney, tank or pole. The workflow enforces
the mandatory Clause 3.3 value `Md = 1.0` for the latter case in every region and for the cladding
case in B2, C and D. `Mc` is selected once from Clause 3.4/Table 3.3 and included in the Clause 2.2
product `Vsit,b = VR x Mc x Md x Mz,cat x Ms x Mt`. Generic Region `B` is rejected until B1/B2 is
confirmed.

Generic Region A is also rejected by the combined workflow until A0, A1, A2, A3, A4, or A5 is
confirmed. This is required because A0 has special terrain-height and topographic rules, A4 has a
high-elevation topographic rule, and the direction multiplier requires a specific regional row.

### Clause 4.2.3 Mixed Terrain Profiles

Supply `mixed_terrain_profiles` when reviewed source material identifies the ordered terrain
transitions for a wind direction. Distances are absolute upwind distances measured from the site.
For a non-A0 assessment height `z`, the profile must continuously cover the complete averaging
window `[xi, xi + xa)`, where `xi = 20z` and `xa = max(500 m, 40z)`. Segments must be ordered and
contiguous, and every segment requires a non-empty `source_reference`. The workflow rejects gaps,
overlaps, incomplete non-A0 coverage, duplicate profile directions, and a terrain-category or
`Mz,cat` class override for the same direction.

For non-A0 workflow requests, `average_roof_height_m` is required and may be used as Clause 4.2.3
height `z` only when `h <= 25 m`. Higher buildings require a separate height-specific assessment;
the workflow does not substitute `building_height_m`. Region A0 instead uses its mandatory
terrain-independent Table 4.1 value at the workflow reference height
(`average_roof_height_m`, falling back to `building_height_m`). Supplied A0 profiles are
evidence-only, may be incomplete, and are not distance-weighted, although their supplied segments
must remain ordered, contiguous, and source-referenced. Aggregate built-up, vegetation, and
open-terrain sector percentages do not locate transitions and are never converted into a
transition schedule.

At `h = 10 m`, `xi = 200 m`, `xa = 500 m`, and the required averaging window is 200-700 m. This
REST example supplies complete coverage for the north direction:

```bash
curl -X POST http://127.0.0.1:8000/api/wind-workflow \
  -H "Content-Type: application/json" \
  -d '{
    "latitude": -33.86,
    "longitude": 151.21,
    "building_height_m": 10,
    "average_roof_height_m": 10,
    "radius_m": 500,
    "sample_interval_m": 100,
    "obstruction_radius_m": 500,
    "default_storey_height_m": 3.0,
    "annual_exceedance_probability": "1/500",
    "mixed_terrain_profiles": [{
      "direction": "N",
      "source_reference": "Reviewed transition schedule W-04 rev C",
      "segments": [
        {
          "start_distance_m": 200,
          "end_distance_m": 450,
          "terrain_category": "TC2",
          "source_reference": "W-04 rev C, N segment 1"
        },
        {
          "start_distance_m": 450,
          "end_distance_m": 700,
          "terrain_category": "TC3",
          "source_reference": "W-04 rev C, N segment 2"
        }
      ]
    }]
  }'
```

Supply one complete profile for each direction that needs mixed-terrain weighting. Directions
without a profile continue to use one reviewed or recommended terrain category and return an
explicit warning. The response exposes the traceable calculations in
`mixed_terrain_assessments`.

Mandatory standard values cannot be replaced through either override collection. In Region A0,
the mandatory Table 4.1 A0 rule is retained independently of terrain-category class, while still
using the common reference height. When average roof height h exceeds 25 m, Clause 4.3.1 requires
Ms = 1.0. Numeric overrides for either case are rejected.

Use `average_roof_height_m` for the common AS/NZS reference height `h` used by
`Mz,cat`, the Clause 4.3 shielding-height checks, and Clause 4.4 topographic calculations.
When it is omitted, the workflow uses `building_height_m` as a continuity fallback. That fallback
is an assumption, is not uniformly conservative across all multipliers, and requires confirmation
of the actual average roof height. The request-only `average_height_m` alias remains accepted for
migration, but responses and OpenAPI use the unambiguous `average_roof_height_m` name.

`annual_exceedance_probability` is the AEP/ARI input used to select `VR`.
`importance_level` and `design_life_years` are optional report metadata only; they do not derive,
select, or alter the AEP/ARI. The deprecated `building_dimensions` field remains available as
legacy free-text request metadata only; it does not define the footprint or drive calculations.
It cannot be combined with the structured `building_width_m` and `building_length_m` fields.

`Mc` is a deterministic Table 3.3 mapping and is not overrideable. Other overrides are reviewed
engineering inputs. They preserve their reasons in result provenance and do not certify the
automated GIS evidence or final design outcome.

`assessment_status`, `reviewed_by`, and `engineer_notes` are optional public request fields retained
for legacy/backward compatibility and preserved in the normalized signed `input`. The browser does
not expose review or issue-status controls and omits all three fields; the server defaults
`assessment_status` to `draft`. API clients may still send `reviewed`, which requires both
`reviewed_by` and non-empty `engineer_notes`; `final` is rejected by request validation. These
fields do not create an HTML/PDF issue status, reviewer label, certification claim, or banner.
When supplied, `engineer_notes` may appear only as a review note in the report.

`structure_orientation_deg` is the engineering azimuth of the building's front, measured clockwise
from North. It accepts `0 <= beta < 360`; `0`, `90`, `180`, and `270` therefore correspond to
the front pointing North, East, South, and West respectively. The right, back, and left building
axes are offset from that front azimuth by 90, 180, and 270 degrees. The browser map uses the same
convention. `building_width_m` is the left-to-right breadth across the front and
`building_length_m` is the front-to-back depth; supply both together when defining the editable
footprint. When all eight final cardinal-direction `Vsit,b` rows are available, the workflow
linearly interpolates between the 45-degree direction points and reports the maximum value within
each plan face's plus-or-minus 45-degree sector as Clause 2.3 ultimate `Vdes,theta`. The Front,
Right, Back, and Left result rows use relative `theta` values of 0, 90, 180, and 270 degrees and
absolute `beta` bearings derived from the front orientation. The Clause 2.3 ultimate minimum of
30 m/s is enforced. Design pressures remain outside this workflow.

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
GET /api/reference-validation/anonymized
GET /api/wind-region/validation
```

Validation responses are qualitative audit outputs. They are not proof of engineering accuracy or
code compliance. The anonymized-reference endpoint compares the current OpenWind workflow against
stored class-level expectations: `TC3` terrain, `FS` shielding, and `T0`/`T1` topography. Its
published coordinates and OSM-derived footprint geometry are deliberately translated, with source
feature IDs and tags removed. Use
`GET /api/reference-validation/anonymized?apply_reference_overrides=true` to rerun the comparison
with the encoded reference classes applied through `class_multiplier_overrides`.
