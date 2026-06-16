# OpenWind-AU

[![CI](https://github.com/Elandu/OpenWind-AU/actions/workflows/ci.yml/badge.svg)](https://github.com/Elandu/OpenWind-AU/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

OpenWind-AU is an open-source Python/FastAPI application for preliminary terrain-profile and
topographic screening of Australian building sites. It helps engineers and reviewers inspect public
terrain data before deciding whether more detailed project-specific wind engineering review is
needed.

Current maturity: early-stage pre-alpha. The project is suitable for exploration, review,
contribution, and regression testing. It is not a certified design tool.

## Who It Is For

- Structural and facade engineers reviewing terrain context.
- Wind engineering researchers and tool builders.
- Building consultants preparing early site-screening information.
- Open-source contributors interested in geospatial engineering workflows.

## What It Does

- Accepts an Australian street address or latitude/longitude.
- Samples public SRTM DEM terrain data.
- Generates 8 terrain profiles: N, NE, E, SE, S, SW, W, and NW.
- Supports analysis radii of 500 m, 1000 m, 2000 m, and 4000 m.
- Performs conservative rule-based screening for candidate ridge, hill, escarpment, valley, or no
  significant feature outcomes.
- Exports JSON, HTML, and PDF reports.
- Provides qualitative validation checks against representative Australian terrain examples.

## What It Does Not Do

OpenWind-AU does not calculate:

- AS/NZS 1170.2 topographic multipliers;
- terrain category;
- shielding;
- design wind pressures;
- AS 4055 wind classifications;
- certified design compliance.

Outputs are preliminary and must be reviewed by a competent engineer. Public DEM data may not
reflect local survey levels, recent earthworks, retaining structures, vegetation, or built
obstructions.

## Screenshots

Screenshots are planned. Placeholder coverage is tracked in [`docs/screenshots.md`](docs/screenshots.md):

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

## Documentation

- [Installation](docs/installation.md)
- [Running locally](docs/running-locally.md)
- [API usage](docs/api.md)
- [Report exports](docs/reports.md)
- [Validation framework](docs/validation.md)
- [Limitations and engineering review](docs/limitations.md)
- [Release checklist](docs/release.md)

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
`gis`, `terrain-analysis`, `topography`, `python`, `fastapi`

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
