# Running Locally

Start the OpenWind-AU web app and API:

```bash
openwind-au
```

The no-argument command remains a loopback development server. Use explicit serving options or
their environment equivalents when deploying behind a trusted proxy:

```bash
openwind-au serve --host 0.0.0.0 --port 8080
```

```powershell
$env:OPENWIND_HOST="0.0.0.0"
$env:OPENWIND_PORT="8080"
openwind-au
```

Ports must be integers from 1 through 65535. The default remains `127.0.0.1:8000` so a fresh local
installation is not exposed to the network unintentionally.

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
`Mz,cat`/`Ms` digests, configured DEM provider/cache, and durable result-signing key are ready;
otherwise it returns HTTP 503 with per-component checks. A development instance can be live while
correctly reporting `not_ready` for project assessments.

Run the identical readiness report before starting or routing traffic:

```bash
openwind-au check
openwind-au check --json
```

Human-readable mode lists each readiness component. JSON mode emits the same consumer-safe object
as `/health`. Both return exit status 0 for `ready` and 1 for `not_ready`, making the command usable
in container entrypoints and deployment scripts without first opening a listening socket. Invalid
command-line usage returns exit status 2.

Assessment requests return HTTP 503 when a required deployment input is missing or invalid (for
example, the wind-region dataset, DEM selection, or durable result-signing key). Treat this as a
server readiness problem and check `/health`; request validation errors remain HTTP 4xx, while
required external-provider failures return HTTP 502.

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
