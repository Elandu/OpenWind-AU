# Changelog

All notable project milestones are documented here.

## v0.6.0 - Terrain Category Evidence Engine

- Added directional terrain category evidence for N, NE, E, SE, S, SW, W, and NW.
- Added built-up, vegetation, open-terrain, obstruction density, spacing, height statistic,
  directional fetch, and shielding-confidence evidence metrics.
- Added separate evidence score components for open exposure, vegetation, urban density, and
  obstruction height.
- Added qualified suggested terrain category ranges for engineering review.
- Added terrain category evidence API endpoints, report output, map layers, validation examples,
  and UI section.

This milestone does not assign a final terrain category, does not calculate `Mz,cat`, and does not
claim AS/NZS 1170.2 compliance.

## v0.5.0 - Height Provenance And Shielding Confidence

- Added height provenance fields for raw source height and selected operational height.
- Added source priority across manual verified, DSM-DTM, OSM explicit height, OSM levels,
  assumption-based estimates, and unknown heights.
- Added configurable low-confidence height assumptions for residential and commercial
  obstruction records.
- Added confidence and review-required indicators for obstruction heights.
- Added shielding sector diagnostics for high-confidence, estimated, and unknown heights.

This milestone improves transparency for shielding review only. It does not certify obstruction
heights or shielding outcomes.

## v0.4.0 - Preliminary Shielding Sector Analysis

- Added nearby obstruction inventory from public building and vegetation footprints.
- Added reviewed obstruction height import/export support.
- Added preliminary 45 degree shielding sectors for N, NE, E, SE, S, SW, W, and NW.
- Added indicative shielding-sector outputs including `ns`, average `hs`, average `bs`, `ls`,
  shielding parameter `s`, and indicative `Ms`.
- Added obstruction maps and obstruction inventory reports.

This milestone provides preliminary screening only. Indicative shielding values require competent
engineering review and are not certified design values.

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
