# Release Checklist

Use this checklist before tagging a public release.

## Code Quality

- Run `pytest`.
- Run `ruff check .`.
- Run `ruff format --check .`.
- Run `node --check src/openwind_au/static/wind_workflow.js` and
  `node --test tests/js/*.test.cjs`.
- Run `uv lock --check` and `uv audit --locked --preview-features audit-command`.
- Confirm CI passes on the release branch.

## Documentation

- Confirm README describes current capabilities and maturity.
- Confirm README does not claim certified design compliance.
- Update `CHANGELOG.md`.
- Confirm `pyproject.toml`, `openwind_au.__version__`, `CITATION.cff`, and `uv.lock` identify the
  same release version.
- Update the current changelog section and add dedicated release notes only when extra migration
  detail is required.
- Confirm `docs/workflow.md` and `docs/reviewer-checklist.md` match the current workflow.
- Confirm `docs/installation.md`, `docs/api.md`, `docs/reports.md`, `docs/validation.md`,
  and `docs/limitations.md` still match current behaviour.
- Confirm `CITATION.cff` has the release version.

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
- If sensitive material ever entered public Git history, coordinate an explicit history rewrite
  and host-side cleanup; deleting it in a later commit does not retract prior objects or diffs.

## Release

- Build wheel and sdist into a clean output directory from the final commit, then inspect their
  file lists and installed-package smoke tests. Never reuse an older `dist/` artifact.
- Tag the release.
- Publish release notes with known limitations.
- Attach the verified wheel and sdist to the GitHub release.
- Include screenshots or screenshot placeholders.
- Confirm GitHub issue templates and pull request template are present.
