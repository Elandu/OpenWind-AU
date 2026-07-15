# OpenWind-AU

[![CI](https://github.com/Elandu/OpenWind-AU/actions/workflows/ci.yml/badge.svg)](https://github.com/Elandu/OpenWind-AU/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)

OpenWind-AU is an open-source Python/FastAPI application for interactive preliminary wind
assessment of Australian building sites. It combines terrain-category evidence, directional
AS/NZS 1170.2 wind-speed calculations, obstruction inventory, and topographic analysis into a
reviewable engineer-facing workflow with HTML/PDF reporting and an MCP API.

> **Maturity warning:** OpenWind-AU is a pre-alpha engineering support tool. It does not
> produce certified design values.

Current maturity: pre-alpha. The project provides an interactive wind assessment workflow with
directional AS/NZS 1170.2 calculations, terrain-category evidence, and MCP API tools, but is not a
certified design tool. Suitable for exploration, review, contribution, and regression testing.

## Who It Is For

- Structural and facade engineers reviewing terrain context.
- Wind engineering researchers and tool builders.
- Building consultants preparing early site-screening information.
- Open-source contributors interested in geospatial engineering workflows.

## What It Does

- Accepts either an Australian street address or latitude/longitude, with an optional non-geocoded
  `site_label` for map-selected coordinates.
- Generates 8-direction terrain profiles: N, NE, E, SE, S, SW, W, and NW.
- Supports analysis radii of 500 m, 1000 m, 2000 m, and 4000 m.
- Performs conservative rule-based screening for candidate ridge, hill, escarpment, valley, or no
  significant feature outcomes.
- Provides a qualitative validation framework for representative Australian terrain examples.
- Builds a nearby obstruction inventory for shielding input review, including footprint,
  distance, bearing, height source, confidence, and missing-height flags.
- Uses Microsoft Australia Building Footprints as the preferred building footprint source when a
  local cache is configured, with OSM/Overpass used as fallback and for height/levels attributes.
- Enriches obstruction heights from DSM-DTM elevation differences when configured DSM and DTM
  datasets are available.
- Tracks height provenance and confidence from manual verified, DSM-DTM, OSM explicit height,
  OSM levels, low-confidence class assumptions, or unknown sources.
- Includes vegetation polygons as context, but excludes them from calculated shielding in
  accordance with AS/NZS 1170.2:2021 Clause 4.3.
- Uses a separate obstruction inventory radius so terrain/profile sampling can extend farther than
  the building footprint dataset used for shielding review.
- Provides preliminary shielding sector analysis from reviewed obstruction data.
- Calculates preliminary directional `Mt` values from DEM-derived topographic geometry using
  AS/NZS 1170.2:2021 Clause 4.4 equations, including Australian A0 and A4 adjustments.
- Generates directional terrain category evidence for engineer review, including built-up,
  vegetation, open-terrain, obstruction density, height, confidence, and suggested range evidence.
- Exports JSON, HTML, and PDF reports.
- Provides qualitative validation checks against representative Australian terrain examples.
- Exposes traceable `VR`, `Md`, `Mz,cat`, `Ms`, `Mt`, and `Vsit,b` tools through an MCP server.

## What It Does Not Do

OpenWind-AU does not produce:

- certified topographic multipliers without review of the DEM-derived feature geometry;
- final terrain category assignments;
- final `Mz,cat` design values;
- design wind pressures;
- AS 4055 wind classifications;
- certified shielding multiplier `Ms`;
- certified design compliance.

Outputs are preliminary and must be reviewed by a competent engineer. Public DEM data may not
reflect local survey levels, recent earthworks, retaining structures, vegetation, or built
obstructions.

The obstruction inventory uses Microsoft Australia Building Footprints as the preferred source when
cached regional data is available. OSM/Overpass is used as a fallback and to preserve useful
attributes such as `height`, `building:levels`, and building type. If Microsoft and OSM footprint
sources are both unavailable, OpenWind-AU returns warnings rather than calculating indicative
shielding from incomplete data.

DSM-DTM height enrichment is optional and depends on configured elevation datasets. Without a DSM
and DTM, obstruction heights fall back to manual, OSM-derived, or low-confidence assumption-based
sources and the response includes warnings.

## Screenshots

Screenshot coverage is tracked in [`docs/screenshots.md`](docs/screenshots.md):

- Terrain category evidence: `docs/screenshots/terrain-category-evidence.png`

- Site analysis page: `docs/screenshots/site-analysis.placeholder.md`
- Terrain profiles: `docs/screenshots/terrain-profiles.placeholder.md`
- Topographic screening: `docs/screenshots/topographic-screening.placeholder.md`
- Validation report: `docs/screenshots/validation-report.placeholder.md`

## Quick Start

```bash
git clone https://github.com/Elandu/OpenWind-AU.git
cd OpenWind-AU
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
openwind-au
```

On macOS or Linux, activate with:

```bash
source .venv/bin/activate
```

Open the interactive wind assessment workflow:

```text
http://127.0.0.1:8000
```

The terrain category evidence and legacy site-analysis pages are also available at:

```text
http://127.0.0.1:8000/site-analysis
http://127.0.0.1:8000/terrain-category
```

Before routing production assessment traffic, run the same readiness checks used by `/health`
without starting a server:

```bash
openwind-au check
openwind-au check --json
```

The command exits with status 0 only when the deployment is ready and status 1 when any required
dataset, reviewed lookup, digest, signing key, or DEM check fails. A source checkout without the
project-specific production inputs is expected to report `NOT_READY`. Invalid command-line usage
exits with status 2.

## Microsoft Building Footprint Cache

Microsoft publishes [Australia Building Footprints](https://github.com/microsoft/AustraliaBuildingFootprints)
as a large country-wide GeoJSON ZIP. OpenWind-AU does not silently download the full dataset during
an analysis. For local footprint coverage, prepare a clipped or tiled GeoJSON/GeoJSONL cache and
set:

```powershell
$env:OPENWIND_MICROSOFT_FOOTPRINT_CACHE="C:\data\openwind-au\microsoft_building_footprints"
```

Tile files can be placed at `tiles/<lat_floor>_<lon_floor>.geojsonl` or
`tiles/<lat_floor>_<lon_floor>.geojson`, for example `tiles/-34_151.geojsonl` for central Sydney.
Each record should be a GeoJSON Feature or Polygon in EPSG:4326. If no Microsoft cache is found,
the app uses OSM/Overpass fallback where available and reports that fallback in the obstruction
source diagnostics.

If a project maintains its own tile index, set `OPENWIND_MICROSOFT_FOOTPRINT_INDEX` or
`OPENWIND_MICROSOFT_FOOTPRINT_INDEX_URL`. The index maps tile keys to downloadable GeoJSON or
GeoJSONL URLs, allowing OpenWind-AU to fetch only the tile required for the current site. Remote
index and tile URLs (including redirects) must use HTTPS. Remote indexes are limited to 2 MiB,
tiles are limited to 50 MiB, and an optional per-tile `sha256` is verified before a supported
GeoJSON file is installed atomically in the cache.

## Wind Region GIS Dataset

OpenWind-AU uses a local GIS file for wind-region lookup. The preferred source is Geoscience
Australia's [1170.2 Wind Regions for Australia](https://ecat.ga.gov.au/geonetwork/srv/api/records/74dfa021-95cd-4090-9e25-a7a8efde5454)
dataset. The catalogue data download is currently published at
`https://d28rz98at9flks.cloudfront.net/146359/146359_01_0.zip`.

OpenWind-AU does not hard-code the map from an image and does not silently download this dataset
during an assessment. Download and extract the GA data locally, then set the local GeoJSON or GPKG
path:

```powershell
$env:OPENWIND_WIND_REGION_DATASET="C:\data\openwind-au\1170_2_wind_regions.gpkg"
```

For a GeoPackage with multiple layers, set `OPENWIND_WIND_REGION_LAYER`. If the region attribute is
not auto-detected, set `OPENWIND_WIND_REGION_FIELD` to the field containing labels such as `A0`,
`A1`, `B1`, `B2`, `C`, or `D`. Sample polygons in this repository are test fixtures only and are not
a production wind-region map.

## Documentation

- [Installation](docs/installation.md)
- [Running locally](docs/running-locally.md)
- [Workflow guide](docs/workflow.md)
- [Calculation basis and data lineage](docs/calculation-basis.md)
- [Reviewer checklist](docs/reviewer-checklist.md)
- [API usage](docs/api.md)
- [MCP server](docs/mcp.md)
- [Report exports](docs/reports.md)
- [Validation framework](docs/validation.md)
- [Limitations and engineering review](docs/limitations.md)
- [Release checklist](docs/release.md)
- [v0.8.0 milestone changes](CHANGELOG.md#v080---standards-provenance-and-preliminary-issue-guardrails)
- [v0.6.0 release notes](docs/releases/v0.6.0.md)

## API Overview

Run an analysis:

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

Main endpoints:

```text
GET  /health/live
GET  /health
POST /api/geocode/suggest
POST /api/geocode/resolve
POST /api/analyse
POST /api/export/json
POST /api/report/html
POST /api/report/pdf
POST /api/wind-workflow/report/html
POST /api/wind-workflow/report/pdf
POST /api/wind-workflow/result/report/html
POST /api/wind-workflow/result/report/pdf
POST /api/plots/profile
POST /api/maps/site
POST /api/map/combined
POST /api/obstructions/inventory
POST /api/obstructions/map
POST /api/obstructions/report/html
POST /api/terrain-category/evidence
POST /api/terrain-category/map
POST /api/terrain-category/report/html
POST /api/wind-region
POST /api/wind-region/map
GET  /api/terrain-category/validation
GET  /terrain-category
GET  /validation
GET  /api/validation
GET  /api/validation/report/html
```

`/health/live` is the process-liveness probe. `/health` is the stricter assessment-readiness probe
and returns HTTP 503 with component checks until required production datasets, reviewed lookup
tables (`VR`, `Md`, `Mz,cat`, and `Ms`), matching lookup digests, and the configured DEM
provider/cache are usable. Digest pinning currently covers `Mz,cat` and `Ms`; `VR` and `Md` use
review metadata and coverage checks. Completed-result report endpoints also require the unmodified
`integrity_token` returned by the workflow. Production deployments must configure the same
32-byte-or-longer `OPENWIND_RESULT_SIGNING_KEY` on every API worker.

## Example Outputs

- [Sample request](examples/sample_request.json)
- [Sample JSON analysis](examples/sample_analysis.json)
- [Sample HTML report](examples/sample_report.html)
- [Sample validation report](examples/sample_validation_report.html)
- [Example workflow](examples/workflow.md)
- [Demo project folder](examples/demo-project/README.md)

## Validation

The validation framework runs the normal terrain/topographic workflow against broad Australian
examples: flat suburban, coastal escarpment, hilltop, valley, and inland-flat settings. Results are
reported as pass, warning, or fail against broad expected behaviour.

Validation is an audit and regression tool. It does not prove design accuracy, code compliance, or
fitness for a specific project.

## Development

```bash
pytest
ruff check .
ruff format --check .
```

CI runs these checks through GitHub Actions.

## Suggested GitHub Topics

`open-source`, `wind-engineering`, `structural-engineering`, `as-nzs-1170-2`, `geospatial`,
`gis`, `terrain-analysis`, `topography`, `python`, `fastapi`, `microsoft-building-footprints`,
`openstreetmap`

## Roadmap

See [`ROADMAP.md`](ROADMAP.md). Near-term work focuses on better validation examples, clearer
confidence reporting, improved public documentation, and design-certification readiness.

## Contributing

Contributions are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md), keep claims
preliminary, and do not include private project data in public issues or examples.

## Security

See [`SECURITY.md`](SECURITY.md) for vulnerability reporting and sensitive-data guidance.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md).

## Licence

GNU Affero General Public License v3. See [`LICENSE`](LICENSE).
