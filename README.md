# OpenWind-AU

OpenWind-AU is an open-source web application and Python backend for preliminary wind site terrain and topographic analysis for Australian buildings.

The purpose is to automate collection and interpretation of public geospatial terrain information relevant to early AS/NZS 1170.2 wind assessment workflows.

OpenWind-AU is not a certified design tool. It does not claim AS/NZS 1170.2 compliance and must not replace engineering judgement.

## What It Does

Users provide:

- Street address or latitude/longitude.
- Building height in metres.

The application can:

- Geocode Australian street addresses with OpenStreetMap/Nominatim.
- Resolve site coordinates and ground elevation.
- Download/query public SRTM DEM terrain tiles.
- Generate 8-direction terrain profiles around the site: N, NE, E, SE, S, SW, W, and NW.
- Support configurable analysis radii of 500 m, 1000 m, 2000 m, and 4000 m.
- Screen each terrain profile for preliminary candidate topographic features: ridge, hill,
  escarpment, valley, or no significant feature.
- Report site RL, crest RL, base RL, `H`, `Lu`, `x`, average upwind slope, confidence, and
  review notes for each directional screening result.
- Display interactive terrain profile plots with Plotly, including candidate site, base, crest,
  `H`, and `Lu` overlays.
- Display an interactive site map with Folium/Leaflet.
- Export results as JSON.
- Generate HTML and PDF summary reports.

## Safety Disclaimer

OpenWind-AU provides preliminary terrain and topographic analysis only. Outputs must be reviewed by a competent engineer before use. DEM data may not reflect survey levels, local earthworks, retaining structures, vegetation, or built obstructions.

The project does not calculate terrain category, shielding, topographic multipliers, design wind pressures, or wind classifications in the MVP. AS/NZS 1170.2, AS 4055, and related code checks are roadmap items only.

## Tech Stack

- FastAPI
- NumPy
- SciPy
- Rasterio
- GeoPandas
- Shapely
- PyProj
- Plotly
- Folium
- ReportLab
- Pytest
- Ruff

## Data Sources

Current MVP integrations:

- OpenStreetMap/Nominatim for geocoding.
- AWS public SRTM HGT tiles from `elevation-tiles-prod/skadi` for DEM elevation data.

Future work may add Copernicus DEM, Australian LiDAR datasets, and state/territory elevation services.

## Installation

Prerequisites:

- Python 3.11 or newer.
- A Python environment capable of installing geospatial Python packages.
- `curl` available on `PATH` for robust public DEM tile downloads.

Install from source:

```bash
git clone https://github.com/Elandu/OpenWind-AU.git
cd OpenWind-AU
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

On macOS or Linux:

```bash
source .venv/bin/activate
```

## Local Development

Run the API and web UI:

```bash
openwind-au
```

Or:

```bash
uvicorn openwind_au.api:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

Run tests:

```bash
pytest
```

Run linting and formatting checks:

```bash
ruff check .
ruff format --check .
```

## API Example

Run an analysis using coordinates:

```bash
curl -X POST http://127.0.0.1:8000/api/analyse \
  -H "Content-Type: application/json" \
  -d '{
    "latitude": -33.8568,
    "longitude": 151.2153,
    "building_height_m": 12,
    "radius_m": 2000,
    "sample_interval_m": 50
  }'
```

Run an analysis using an address:

```json
{
  "address": "1 Macquarie Street, Sydney NSW",
  "building_height_m": 12,
  "radius_m": 2000,
  "sample_interval_m": 50
}
```

Export JSON:

```text
POST /api/export/json
```

Generate reports:

```text
POST /api/report/html
POST /api/report/pdf
```

Generate interactive views:

```text
POST /api/plots/profile
POST /api/maps/site
```

## Example Files

- [`examples/sample_request.json`](examples/sample_request.json)
- [`examples/workflow.md`](examples/workflow.md)

## Output Metrics

For preliminary topographic screening, OpenWind-AU reports one result for each of the 8 profile
directions:

- `direction`
- `azimuth_deg`
- `feature_type`
- `site_rl_m`
- `crest_rl_m`
- `base_rl_m`
- `h_m`
- `lu_m`
- `x_m`
- `average_upwind_slope`
- `confidence`
- `notes`

Feature types are limited to `ridge`, `hill`, `escarpment`, `valley`, and
`no significant feature`. These are preliminary geometric indicators from public DEM profiles.
They are not AS/NZS 1170.2 topographic multipliers, certified design values, or final wind
assessment conclusions.

Terrain profiles are exported with:

- `direction`
- `azimuth_deg`
- `radius_m`
- `endpoint_latitude`
- `endpoint_longitude`
- sampled profile points with distance, latitude, longitude, and elevation
- minimum RL
- maximum RL
- average slope

## Roadmap

MVP priorities:

- Robust 8-direction terrain profile generation.
- Conservative topographic feature screening for engineer review.
- Interactive maps and profile plots.
- JSON, HTML, and PDF outputs.
- Deterministic tests and CI.

Roadmap-only items:

- Terrain category assessment.
- Shielding assessment.
- Topographic multiplier calculations.
- AS 4055 wind classification support.
- LiDAR integration.
- MCP server integration.

See [`ROADMAP.md`](ROADMAP.md) for more detail.

## Contributing

Contributions are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request.

## Licence

MIT. See [`LICENSE`](LICENSE).
