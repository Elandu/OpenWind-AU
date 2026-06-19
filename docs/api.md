# API Usage

The API exposes preliminary terrain, topographic screening, obstruction inventory, and
shielding-sector workflows. It does not calculate certified AS/NZS 1170.2 multipliers or design
wind pressures.

## Analyse A Site

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
`microsoft_source_status`, `microsoft_cache_status`, `microsoft_cache_path`, and
`osm_fallback_used`. If Microsoft and OSM sources are both unavailable, the inventory response
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

## Validation

```text
GET /api/validation/cases
GET /api/validation
GET /api/validation/report/html
```

Validation responses are qualitative audit outputs. They are not proof of engineering accuracy or
code compliance.
