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
