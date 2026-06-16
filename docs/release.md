# Release Checklist

Use this checklist before tagging a public release.

## Code Quality

- Run `pytest`.
- Run `ruff check .`.
- Run `ruff format --check .`.
- Confirm CI passes on the release branch.

## Documentation

- Confirm README describes current capabilities and maturity.
- Confirm README does not claim certified design compliance.
- Update `CHANGELOG.md`.
- Confirm `docs/installation.md`, `docs/api.md`, `docs/reports.md`, `docs/validation.md`,
  and `docs/limitations.md` still match current behaviour.

## Example Outputs

- Refresh `examples/sample_analysis.json` if API fields changed.
- Refresh `examples/sample_report.html` if report layout changed.
- Refresh `examples/sample_validation_report.html` if validation output changed.

## Validation

- Run the validation page locally.
- Run `GET /api/validation`.
- Confirm validation output clearly separates pass, warning, and fail outcomes.

## Safety

- Check that no private addresses, client details, claim numbers, API keys, or credentials are
  included.
- Confirm public wording remains preliminary and review-focused.

## Release

- Tag the release.
- Publish release notes with known limitations.
- Include screenshots or screenshot placeholders.
