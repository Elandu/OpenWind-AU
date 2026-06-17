# OpenWind-AU

[![CI](https://github.com/Elandu/OpenWind-AU/actions/workflows/ci.yml/badge.svg)](https://github.com/Elandu/OpenWind-AU/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

OpenWind-AU is an open-source Python/FastAPI application for preliminary terrain-profile and
topographic screening of Australian building sites. It helps engineers and reviewers inspect public
terrain data before deciding whether more detailed project-specific wind engineering review is
needed.

> **Maturity warning:** OpenWind-AU is an early-stage engineering support tool. It does not
> produce certified design values.

Current maturity: early-stage pre-alpha. The project is suitable for exploration, review,
contribution, and regression testing. It is not a certified design tool.

## Who It Is For

- Structural and facade engineers reviewing terrain context.
- Wind engineering researchers and tool builders.
- Building consultants preparing early site-screening information.
- Open-source contributors interested in geospatial engineering workflows.

## What It Does

- Accepts an Australian street address or latitude/longitude.
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
- Includes building and vegetation polygons as potential shielding obstructions.
- Uses a separate obstruction inventory radius so terrain/profile sampling can extend farther than
  the building footprint dataset used for shielding review.
- Provides preliminary shielding sector analysis from reviewed obstruction data.
- Generates directional terrain category evidence for engineer review, including built-up,
  vegetation, open-terrain, obstruction density, height, confidence, and suggested range evidence.
- Exports JSON, HTML, and PDF reports.
- Provides qualitative validation checks against representative Australian terrain examples.

## What It Does Not Do

OpenWind-AU does not calculate:

- AS/NZS 1170.2 topographic multipliers;
- final terrain category assignments;
- `Mz,cat` values;
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

Open:

```text
http://127.0.0.1:8000
```

The terrain category evidence page is also available at:

```text
http://127.0.0.1:8000/terrain-category
```

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
GeoJSONL URLs, allowing OpenWind-AU to fetch only the tile required for the current site.

## Documentation

- [Installation](docs/installation.md)
- [Running locally](docs/running-locally.md)
- [Workflow guide](docs/workflow.md)
- [Reviewer checklist](docs/reviewer-checklist.md)
- [API usage](docs/api.md)
- [Report exports](docs/reports.md)
- [Validation framework](docs/validation.md)
- [Limitations and engineering review](docs/limitations.md)
- [Release checklist](docs/release.md)
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
POST /api/analyse
POST /api/export/json
POST /api/report/html
POST /api/report/pdf
POST /api/plots/profile
POST /api/maps/site
POST /api/map/combined
POST /api/obstructions/inventory
POST /api/obstructions/map
POST /api/obstructions/report/html
POST /api/terrain-category/evidence
POST /api/terrain-category/map
POST /api/terrain-category/report/html
GET  /api/terrain-category/validation
GET  /terrain-category
GET  /validation
GET  /api/validation
GET  /api/validation/report/html
```

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
confidence reporting, and improved public documentation. Wind-code calculations remain roadmap
items only.

## Contributing

Contributions are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md), keep claims
preliminary, and do not include private project data in public issues or examples.

## Security

See [`SECURITY.md`](SECURITY.md) for vulnerability reporting and sensitive-data guidance.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md).

## Licence

MIT. See [`LICENSE`](LICENSE).
