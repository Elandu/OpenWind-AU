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

## Validation

```text
GET /api/validation/cases
GET /api/validation
GET /api/validation/report/html
```

Validation responses are qualitative audit outputs. They are not proof of engineering accuracy or
code compliance.
