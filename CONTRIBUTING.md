# Contributing

Thanks for helping improve OpenWind-AU.

The project is deliberately cautious: it supports preliminary terrain and topographic analysis only. Do not add wording or features that imply certified engineering design compliance unless that work has been implemented, tested, and reviewed.

## Development Setup

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

Run checks:

```bash
pytest
ruff check .
ruff format --check .
node --check src/openwind_au/static/wind_workflow.js
node --test tests/js/*.test.cjs
```

For a reproducible environment from the committed dependency lock, install uv 0.11.x and run:

```bash
uv sync --locked --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

After changing project dependencies or the package version, regenerate and verify the lock before
committing it:

```bash
uv lock
uv lock --check
uv audit --locked --preview-features audit-command
```

## Engineering Scope

- Keep all assumptions visible.
- Include units in inputs and outputs.
- Treat public DEM results as preliminary.
- Do not claim AS/NZS 1170.2, AS 4055, or other code compliance.
- Do not implement terrain category, shielding, or topographic multiplier wording as completed unless the actual feature exists.
- Prefer deterministic calculations and tests.
- Do not require network access in tests.

## Reporting Bugs

Please include:

- Input address or coordinates, unless confidential.
- Building height and analysis radius.
- Expected behaviour.
- Actual behaviour.
- Relevant logs or screenshots.
- Whether the problem appears to be geocoding, DEM download, terrain profiles, feature detection, reports, or UI.

Do not share private project addresses, client names, claim numbers, or confidential assessment material in public issues.

## Reporting Terrain Or Topography Issues

Terrain/topography reports are most useful when they include evidence that can be checked without
private project material. Please include:

- coordinates rounded enough to protect privacy, or a public representative location;
- analysis radius and sample interval;
- screenshots or exported JSON/HTML where possible;
- which direction appears wrong, such as `N`, `NE`, or `W`;
- what public reference suggests a different broad behaviour;
- whether the concern is DEM elevation, profile geometry, candidate feature classification, report
  output, or validation behaviour.

Useful public evidence includes government mapping portals, public contour/topographic maps,
public LiDAR metadata, published terrain descriptions, or reproducible screenshots from the app.

Do not report exact confidential project outcomes, client instructions, claim data, or private
survey extracts in public issues.

## Adding Validation Cases

Validation cases are broad qualitative checks, not engineering benchmarks. When proposing or
adding a case:

- use a public representative site;
- include `case_id`, site name, latitude, longitude, building height, expected general terrain
  description, expected broad topographic behaviour, notes, and source/reference;
- use broad expected behaviour only, such as "generally flat" or "likely escarpment behaviour";
- do not include exact design values, code multipliers, or compliance claims;
- add or update tests when validation logic changes;
- use `.github/ISSUE_TEMPLATE/validation_example.yml` for proposed examples.

## Feature Requests

Please describe:

- The engineering workflow.
- Required input data.
- Expected output fields and units.
- Relevant public data sources.
- Validation examples or references.
- Whether the request is MVP terrain analysis or roadmap wind-code logic.

## Pull Requests

1. Open or link an issue for substantial changes.
2. Keep each pull request focused.
3. Add or update tests.
4. Update documentation when behaviour changes.
5. Run `pytest`, `ruff check .`, `ruff format --check .`, `uv lock --check`, and the Node
   browser-state checks shown above.
6. Run `uv audit --locked --preview-features audit-command` when the dependency lock changes.
7. Note any data-source, network, or native dependency impact.
