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
5. Run `pytest`, `ruff check .`, and `ruff format --check .`.
6. Note any data-source, network, or native dependency impact.
