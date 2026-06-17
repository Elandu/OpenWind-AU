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
      "file": "tiles/-34_151.geojsonl"
    }
  }
}
```

With an index configured, OpenWind-AU downloads only the tile keys touched by the site radius and
stores them in the local cache.

## Optional DSM/DTM Height Enrichment

Obstruction height enrichment can use local DSM and DTM rasters when they are available. Set:

```bash
OPENWIND_DSM_PATH=/path/to/dsm.tif
OPENWIND_DTM_PATH=/path/to/dtm.tif
```

The current raster provider expects WGS84 raster coordinates. If either dataset is unavailable,
OpenWind-AU keeps the obstruction inventory usable and returns warnings instead of fabricating
heights.
