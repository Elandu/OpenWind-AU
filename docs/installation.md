# Installation

OpenWind-AU is a Python/FastAPI project with geospatial dependencies. It is intended for
preliminary terrain and topographic screening, not certified wind design.

## Requirements

- Python 3.11 or newer.
- `pip` and `venv`.
- `curl` on `PATH` for robust public DEM tile downloads.
- A platform capable of installing geospatial Python packages such as Rasterio, GeoPandas,
  Shapely, and PyProj.

## Install From Source

```bash
git clone https://github.com/Elandu/OpenWind-AU.git
cd OpenWind-AU
python -m venv .venv
```

Activate the virtual environment on Windows:

```powershell
.\.venv\Scripts\activate
```

Activate the virtual environment on macOS or Linux:

```bash
source .venv/bin/activate
```

Install the package and development tools:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Verify The Install

```bash
pytest
ruff check .
ruff format --check .
```

The first real terrain analysis may download public SRTM tiles into `data/cache/srtm`.

## Optional Elevation Provider

OpenWind-AU uses cached public SRTM terrain tiles by default:

```powershell
$env:OPENWIND_DEM_PROVIDER="srtm"
```

For source comparison against a free point-elevation API, use Open-Meteo:

```powershell
$env:OPENWIND_DEM_PROVIDER="open-meteo"
```

Open-Meteo's elevation endpoint is based on Copernicus DEM GLO-90 public terrain data. This is an
opt-in provider for comparison and review workflows; all public DEM outputs still require
engineering review before project use. To use a proxy or test endpoint, set:

```powershell
$env:OPENWIND_OPEN_METEO_ELEVATION_URL="https://api.open-meteo.com/v1/elevation"
```

The provider deduplicates and caches coordinate pairs in the application process. Uncached points
are sent in batches of no more than 100 coordinate pairs per Open-Meteo request, matching the
provider's multi-coordinate request limit. Large terrain runs may therefore make several bounded
requests.

## Address Search Provider

Search-as-you-type address suggestions use Photon with an Australian bounding box. Public
Nominatim is used only when the user deliberately resolves one complete address; it is not used
for autocomplete. Teams can point suggestions at a self-hosted Photon-compatible service:

```powershell
$env:OPENWIND_PHOTON_URL="https://photon.example.com/api/"
```

Repeated suggestion queries are cached in the application process. Production deployments should
use a provider capacity appropriate to their traffic or operate their own Photon instance.
Address text is sent to the configured Photon service for suggestions and to OpenStreetMap
Nominatim when resolving a complete free-text address. Use self-hosted services when project
addresses are confidential. Browser-to-server lookups use POST so addresses are not placed in
normal HTTP access-log query strings.

## Optional Microsoft Building Footprint Cache

The obstruction inventory prefers
[Microsoft Australia Building Footprints](https://github.com/microsoft/AustraliaBuildingFootprints)
when local cache data is available. The upstream Microsoft dataset is a large country-wide GeoJSON
ZIP, so OpenWind-AU does not download it automatically during a site query.

Prepare clipped or tiled GeoJSON/GeoJSONL files in EPSG:4326, then set:

```powershell
$env:OPENWIND_MICROSOFT_FOOTPRINT_CACHE="C:\data\openwind-au\microsoft_building_footprints"
```

Tile filenames use integer-degree latitude/longitude keys, for example:

```text
C:\data\openwind-au\microsoft_building_footprints\tiles\-34_151.geojsonl
```

If no Microsoft cache tile is available for a site, OpenWind-AU falls back to OSM/Overpass where
available and reports the fallback in the obstruction data quality fields.

Successful OSM/Overpass building queries are cached locally so repeat analyses can survive
temporary Overpass outages. Override the cache location with:

```powershell
$env:OPENWIND_OSM_FOOTPRINT_CACHE="C:\data\openwind-au\osm_building_footprints"
```

Teams that maintain tiled footprint hosting can also provide an index:

```powershell
$env:OPENWIND_MICROSOFT_FOOTPRINT_INDEX="C:\data\openwind-au\microsoft_building_footprints\index.json"
```

The index maps tile keys to downloadable files:

```json
{
  "tiles": {
    "-34_151": {
      "url": "https://example.com/openwind-au/tiles/-34_151.geojsonl",
      "file": "tiles/-34_151.geojsonl",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  }
}
```

With an index configured, OpenWind-AU downloads only the tile keys touched by the site radius and
stores them in the local cache. Replace the example `sha256` with the tile's actual lowercase
SHA-256 digest. The digest is optional for compatibility, but strongly recommended; when supplied,
it is checked for both an existing cached tile and a new download.

Remote index URLs, tile URLs, and their redirects must remain on HTTPS. A remote index is limited
to 2 MiB and each tile to 50 MiB. Indexed filenames must remain inside the configured cache and use
`.geojson`, `.json`, `.geojsonl`, or `.ndjson`. Downloads are streamed to a temporary file, checked
for size, optional SHA-256, and a supported GeoJSON structure, then installed atomically. Invalid
or empty downloads are rejected rather than retained as cache entries.

## Optional Wind Region GIS Dataset

Wind-region lookup prefers Geoscience Australia's
[1170.2 Wind Regions for Australia](https://ecat.ga.gov.au/geonetwork/srv/api/records/74dfa021-95cd-4090-9e25-a7a8efde5454)
GIS dataset. The catalogue describes the dataset as Geoscience Australia's interpretation of the
AS/NZS 1170.2 wind-region definitions and notes that professional designers should refer to the
Standard for design purposes.

Download and extract the GA data ZIP from the catalogue, then configure the local GeoJSON or GPKG
path:

```powershell
$env:OPENWIND_WIND_REGION_DATASET="C:\data\openwind-au\1170_2_wind_regions.gpkg"
```

Optional settings:

```powershell
$env:OPENWIND_WIND_REGION_LAYER="wind_regions"
$env:OPENWIND_WIND_REGION_FIELD="wind_region"
$env:OPENWIND_WIND_REGION_BOUNDARY_WARNING_M="25000"
```

OpenWind-AU does not generate wind regions from a copied image. Test-only sample polygons live under
`tests/fixtures` and must not be used for project assessments.

Regional wind speed, direction, terrain/height, and shielding multiplier lookup data are editable
JSON files packaged under `src/openwind_au/data`. To use project-reviewed tables, set:

```powershell
$env:OPENWIND_VR_TABLE_PATH="C:\data\openwind-au\regional_wind_speeds.json"
$env:OPENWIND_MD_TABLE_PATH="C:\data\openwind-au\direction_multipliers.json"
$env:OPENWIND_MZCAT_TABLE_PATH="C:\data\openwind-au\terrain_height_multipliers.json"
$env:OPENWIND_MS_TABLE_PATH="C:\data\openwind-au\shielding_multipliers.json"
$env:OPENWIND_MZCAT_EXPECTED_SHA256="<approved canonical values digest>"
$env:OPENWIND_MS_EXPECTED_SHA256="<approved canonical values digest>"
$env:OPENWIND_RESULT_SIGNING_KEY="<deployment secret containing at least 32 UTF-8 bytes>"
```

Replacement Table 4.1 and Table 4.2 files must retain schema version 1, source/table metadata, a
review status, valid interpolation rules, and a `values_sha256` matching the canonical `values`
object. An override retains the trusted packaged digest unless the deployment separately pins an
approved replacement with `OPENWIND_MZCAT_EXPECTED_SHA256` or `OPENWIND_MS_EXPECTED_SHA256`.
Changing only the digest inside the JSON is therefore insufficient to make changed values ready.

Readiness requires `source.reviewed_by` and an ISO `source.reviewed_on` date alongside
`review_status: "verified_against_standard"` for all four wind-variable lookup assets. Do not
invent these fields: they record an actual independent standards review. The packaged assets do
not yet contain that named sign-off. `/health` reports `not_ready` for an unreviewed, malformed, oversized,
digest-mismatched, or externally unapproved lookup.

`OPENWIND_RESULT_SIGNING_KEY` seals completed workflow responses before the browser or an API
client sends them to `/api/wind-workflow/result/report/*`. Use the same private value on every
API worker and keep it stable across restarts. When it is absent, a process-local development key
is used, but `/health` remains `not_ready` because results cannot be verified across workers or
after restart.

After configuring the deployment inputs, verify them without starting the web server:

```bash
openwind-au check
openwind-au check --json
```

The preflight command and `GET /health` use the same readiness implementation. Exit status 0 means
all required checks are ready; exit status 1 means the JSON or human-readable output identifies at
least one remaining production input.

## Optional DSM/DTM Height Enrichment

Obstruction height enrichment can use local DSM and DTM rasters when they are available. Set:

```bash
OPENWIND_DSM_PATH=/path/to/dsm.tif
OPENWIND_DTM_PATH=/path/to/dtm.tif
```

The current raster provider expects WGS84 raster coordinates. If either dataset is unavailable,
OpenWind-AU keeps the obstruction inventory usable and returns warnings instead of fabricating
heights.
