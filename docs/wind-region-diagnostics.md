# Wind Region Diagnostics

OpenWind-AU resolves wind regions from a local GIS dataset. The application should use the
Geoscience Australia `as1170windzones` shapefile in production, either through
`OPENWIND_WIND_REGION_DATASET` or the local cache path:

```text
data/wind-region/ga-1170-2-wind-regions/as1170windzones.shp
```

The sample file at `tests/fixtures/wind_regions_sample.geojson` is a small test fixture only. It
does not contain authoritative A2/A3 boundaries and must not be used for production assessment.

## Current Finding

Wollongong resolved to A3 when the app was configured with the sample fixture. That fixture has:

- an A2 rectangle ending at approximately latitude `-34.25`;
- an A3 rectangle covering Wollongong coordinates near `-34.4278, 150.8931`.

The production Geoscience Australia shapefile resolves Wollongong to A2. The issue is therefore
the wrong dataset/test-fixture geometry, not an overlapping-polygon selection problem.

## Production Validation

Using `Geoscience Australia as1170windzones`:

| Site | Expected | Production Dataset Result | Status |
| --- | --- | --- | --- |
| Wollongong | A2 | A2 | Pass |
| Sydney | A2 | A2 | Pass |
| Newcastle | A2 | A2 | Pass |
| Canberra | A3 | A3 | Pass |
| Bourke | A0 | A0 | Pass |

Bourke is classified as A0 / Interior by the production Geoscience Australia dataset.

## Debug Endpoints

Use these endpoints to inspect the active dataset and point-selection rule:

```text
GET /api/debug/wind-region/dataset
GET /api/debug/wind-region?latitude=-34.4278&longitude=150.8931
POST /api/debug/wind-region
```

The debug response includes dataset metadata, matched polygons, polygon areas, neighbouring
polygons, selected polygon, and the selection rule.
