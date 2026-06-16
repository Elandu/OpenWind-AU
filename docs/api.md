# API Usage

The API exposes preliminary terrain and topographic screening workflows. It does not calculate
AS/NZS 1170.2 multipliers or design wind pressures.

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

The obstruction inventory queries nearby OpenStreetMap building footprints for shielding input
review. Heights are taken only from explicit height tags, `building:levels` converted with the
configured storey height, or manual reviewed data. Missing heights are not inferred from footprint
size. `Ms` is not calculated.

The obstruction inventory radius is independent from the terrain analysis radius. In the browser UI
it defaults to 500 m so dense urban building-footprint queries do not inherit a 2 km or 4 km
terrain radius. If public Overpass data is unavailable, the inventory response remains HTTP 200
with `data_source_status: "unavailable"`, an empty obstruction list, and warning text for the
reviewer.

## Validation

```text
GET /api/validation/cases
GET /api/validation
GET /api/validation/report/html
```

Validation responses are qualitative audit outputs. They are not proof of engineering accuracy or
code compliance.
