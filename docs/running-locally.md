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

## Local Data

SRTM terrain tiles are cached under:

```text
data/cache/srtm
```

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
