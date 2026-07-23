# Changelog

All notable project milestones are documented here.

## v0.8.0 (unreleased) - Standards Provenance And Preliminary-Issue Guardrails

- Corrected the mandatory Clause 2.2 site-wind product to include the Clause 3.4/Table 3.3
  climate-change multiplier `Mc`. B2, C and D now receive the required 1.05 multiplier, generic
  Region B fails closed pending B1/B2 confirmation, and signed workflow, report, API and MCP
  contracts carry the factor explicitly. The deterministic mapping is not overrideable.
- Added an explicit Clause 3.3 direction-multiplier design case and enforce `Md = 1.0` for
  circular/polygonal chimneys, tanks and poles and for cladding/immediate supports in B2, C and D.
  Signed variables and top-level source data now expose the same effective Clause 3.3 values. The
  combined MCP tool now distinguishes average roof height from overall building height.
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
- Hid all wind-region and obstruction diagnostic routes by default, removed local GIS paths and
  full region polygons from normal JSON responses, and sanitised PDF failures while retaining
  detailed server-side incident logs.
- Added CI construction, required-file inspection, isolated installation smoke tests, and retained
  distribution artifacts for the consumer wheel and source package, using current Node 24-based
  GitHub Actions and least-privilege repository permissions.
- Classified invalid deployment settings and required local datasets as HTTP 503 readiness
  failures, retained 4xx responses for consumer input errors and 502 for required upstream
  failures, sanitised low-level 502 details, and applied the same status contract to terminal
  workflow-stream events.
- Added an operator preflight command (`openwind-au check` and `--json`) backed by the same readiness
  report as `/health`, plus validated host/port options for the server command while retaining the
  safe loopback default.
- Synchronised package, citation, and locked-environment versions; added CI lock, locked-graph, and
  vulnerability checks; corrected the effective Pydantic floor; and migrated FastAPI test clients
  to Starlette's maintained `httpx2` backend.
- Removed source-only `openwind` compatibility shims that were never included in consumer wheels
  but leaked into source distributions.
- Added browser-state regression tests and corrected saved-location invalidation so editing an
  address immediately clears the previous map, autocomplete can adopt the replacement site, and
  fallback workflow reports bind to the resolved coordinates.
- Removed repeated calculated values from Raw Data override cells while retaining one calculated
  column and the complete optional override controls.
- Verified Python 3.13 and 3.14 support and normalised Windows extended-path aliases so concurrent
  Microsoft footprint requests share one download lock on current Python releases.
- Made every public request location unambiguous: clients now send either an address to geocode or
  a complete coordinate pair, with optional `site_label` for coordinate display. Updated both
  browser workflows so autocomplete, restored sites, and dragged buildings use that contract.
- Made public request and completed-result validation strict, rejecting unknown nested fields,
  booleans/numeric strings in engineering-number fields, unsigned internal GIS geometry, and other
  representation changes that could previously be discarded before integrity verification.
- Corrected OpenAPI media types and schemas for NDJSON streams, all PDF routes, raw obstruction
  imports, health/error responses, geocoding, combined analysis, and validation outputs. PDF and
  completed-result errors now document the JSON bodies actually returned at runtime.
- Made CSV/JSON obstruction imports fail closed on unknown or duplicate fields, missing reviewed
  heights, surplus CSV values, invalid identifiers, unsupported media, and bodies over 1 MB while
  streaming the size check instead of buffering an unbounded request.
- Unified configured `VR` selection between FastAPI and MCP, added MCP source provenance and
  application-version handshakes, published bounded enum/result schemas, and validated all MCP
  engineering types without coercion. Streamable HTTP now retains DNS-rebinding protection and
  requires explicit Host allowlists for wildcard binds.
- Added bounded and ambiguity-safe HTTP request parsing, finite/bounded public models, trusted Host
  enforcement, production readiness gating, sanitized validation errors, browser security headers,
  conservative dynamic caching, and a shared versioned outbound User-Agent.
- Corrected bounded-body replay for streaming responses so workflow progress no longer stalls or
  spins a server core after the request body is consumed. Compact PDF output now keeps the
  calculation-lineage reference with the issued one-page summary. A broader concise warning set
  remains in HTML, while complete diagnostics remain in the workflow result.
- Unified the REST, browser, and MCP reference-height contract as `average_roof_height_m`,
  with documented fallback to `building_height_m` and a request-only legacy alias for
  `average_height_m`.
- Anonymized the bundled class-level reference fixture and endpoint by translating its coordinates,
  removing original project and OSM feature identifiers/tags, and adding explicit OpenStreetMap
  attribution and ODbL 1.0 licensing metadata.

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
