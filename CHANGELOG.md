# Changelog

All notable project milestones are documented here.

## v0.3.0 - Validation Framework

- Added qualitative validation cases for representative Australian terrain settings.
- Added validation runner with pass, warning, and fail outcomes.
- Added JSON and HTML validation reports.
- Added validation UI page and validation documentation.
- Added GitHub issue template for proposing validation examples.

This milestone does not add AS/NZS 1170.2 multipliers or design-compliance claims.

## v0.2.0 - Preliminary Topographic Screening

- Added conservative rule-based screening for ridge, hill, escarpment, valley, and no significant
  feature outcomes.
- Added one topographic screening result for each 8-direction terrain profile.
- Added Plotly overlays for site, candidate base, candidate crest, `H`, and `Lu`.
- Added topographic screening outputs to JSON, HTML, and PDF reports.
- Added synthetic terrain tests for flat terrain, ridge, hill, escarpment, and valley behaviour.

This milestone provides preliminary screening only and requires competent engineering review.

## v0.1.0 - Terrain Profile Foundation

- Added 8-direction terrain profile generation for N, NE, E, SE, S, SW, W, and NW.
- Added configurable analysis radii of 500 m, 1000 m, 2000 m, and 4000 m.
- Added terrain profile summary UI, Plotly profile output, and Folium map output.
- Added JSON, HTML, and PDF report exports.
- Added tests for terrain profile generation and report helpers.

This milestone does not calculate wind design values.
