# Changelog

All notable project milestones are documented here.

## v0.8.0 - Standards Provenance And Preliminary-Issue Guardrails

- Moved Table 4.1 `Mz,cat` and Table 4.2 `Ms` values into structured, digest-protected packaged
  lookup assets with deployment overrides, explicit pending-review status, and readiness checks.
- Centralised `Vsit,b` multiplication across the web workflow and MCP tools, preserving full
  multiplier and product precision for governing-direction selection while formatting reports
  to three decimal places.
- Corrected Clause 4.4 screening to use `H >= min(0.4h, 5 m)`, applied one reference height to
  `Mz,cat` and `Mt`, rejected out-of-scope heights above 200 m, and blocked unresolved qualifying
  topographic geometry instead of returning a complete site wind speed.
- Corrected steep-slope shielding to retain the Clause 4.3.1/Figure 4.2 common-datum exception
  when the upwind building top exceeds the subject building, with an explicit review warning.
- Rejected unknown wind regions in direct `Mz,cat` and `Mt` calculations instead of silently
  applying the ordinary Australian-region path.
- Restricted workflow issue states to draft or reviewed preliminary output. Reviewed output now
  requires a reviewer and notes; final/certified status is rejected on calculation and report
  routes.
- Added prominent preliminary/not-for-certification markings to HTML and PDF reports and removed
  duplicated status, notes, and override collections from workflow result payloads.
- Added browser reviewer/notes controls and server-issued integrity tokens for completed-result
  report routes, preventing modified workflow payloads from being rendered as authentic results.
- Removed the unused legacy workflow report renderer and documented the breaking completed-result
  payload transition from `0.7.x`; clients must rerun workflows before using `0.8.0` report routes.

## v0.7.0 - Interactive Wind Workflow, MCP API, And AS/NZS Calculation Audit

- Replaced sparse packaged-table interpolation for Australian `VR` with the Table 3.1(A)
  regional equations and prescribed nearest-1-m/s rounding.
- Expanded regional wind-speed regression data across all published recurrence rows from 1 to
  10,000 years.
- Added current Table 4.1 `Mz,cat` interpolation, A0 handling, and Clause 4.4 `Mt` calculations
  with traceable intermediate values.
- Enforced the Clause 4.3 shielding exclusions for vegetation, structures higher than 25 m, and
  qualifying steep-slope cases.
- Added stable-v1 MCP tools for `VR`, `Md`, `Mz,cat`, `Ms`, `Mt`, and `Vsit,b`, available over
  stdio or Streamable HTTP.
- Added deterministic calculation, MCP registration, and end-to-end variable-product tests.
- Replaced the repetitive site-wind report with a compact project/outcome, directional-results,
  review-items, and basis/limitations structure.
- Added a Documents-tab PDF preview backed by completed-result report endpoints, avoiding a
  second terrain and obstruction workflow run when a report is generated.
- Removed repeated Raw Data summaries and consolidated calculation provenance and warnings.
- Made the design building directly draggable and persisted its updated coordinates for reruns.
- Replaced the browser-dependent address datalist with an accessible autocomplete list, added a
  lightweight address resolver, and made a newly entered address clear stale saved coordinates.
- Filtered geocoder results to the same Australian coordinate bounds enforced by API requests.
- Scoped saved map coordinates by project, cancelled stale autocomplete/workflow/report requests,
  and replayed coordinates and orientation safely into sandboxed map frames after reload.
- Added liveness/readiness separation and now validate `Md` coverage against the Australian region
  labels actually present in the configured production GIS dataset.
- Removed legacy New Zealand `A6/A7` labels from the AU region contract, corrected the Clause 4.3
  steep-gradient exclusion, and stopped project class labels from inventing implicit `Ms`/`Mt`.
- Added a public obstruction response schema that omits repeated imported footprints, raw provider
  geometry/debug logs, and local cache paths from runtime responses and OpenAPI.
- Hardened Microsoft footprint index/tile downloads with HTTPS, size/hash/structure validation,
  atomic concurrent caching, and a bounded thread-safe query cache.
- Batched Open-Meteo elevation requests to the documented 100-coordinate limit while preserving
  support for custom single-point DEM providers.
- Escaped report/map content, sandboxed generated HTML frames, and gated raw debug diagnostics
  behind an explicit environment switch.

These calculations remain engineering-review outputs. Automated GIS classification, public DEM
geometry, obstruction data, jurisdictional variations, and final compliance are not certified.

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
