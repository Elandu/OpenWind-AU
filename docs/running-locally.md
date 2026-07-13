# Running Locally

Start the OpenWind-AU web app and API:

```bash
openwind-au
```

Or run Uvicorn directly:

```bash
uvicorn openwind_au.api:app --reload
```

Open the main analysis page:

```text
http://127.0.0.1:8000
```

Open the validation page:

```text
http://127.0.0.1:8000/validation
```

Check process liveness separately from assessment readiness:

```text
GET http://127.0.0.1:8000/health/live
GET http://127.0.0.1:8000/health
```

`/health/live` returns HTTP 200 when the API process is responsive. `/health` returns HTTP 200 only
when the production wind-region dataset, reviewed `VR`/`Md`/`Mz,cat`/`Ms` lookup data, matching
`Mz,cat`/`Ms` digests,
and configured DEM provider/cache are ready; otherwise it returns HTTP 503 with per-component
checks. A development instance can be live while correctly reporting `not_ready` for project
assessments.

## Local Data

SRTM terrain tiles are cached under:

```text
data/cache/srtm
```

To compare with Open-Meteo point elevations instead of cached SRTM tiles, start the app with:

```powershell
$env:OPENWIND_DEM_PROVIDER="open-meteo"
openwind-au
```

Leave `OPENWIND_DEM_PROVIDER` unset, or set it to `srtm`, for the default local-cache DEM workflow.

Generated local reports are written under:

```text
reports
```

These directories are local runtime artifacts and should not be committed.

## Development Checks

```bash
pytest
ruff check .
ruff format --check .
```
