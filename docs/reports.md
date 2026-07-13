# Report Exports

OpenWind-AU can export preliminary analysis results as JSON, HTML, and PDF.

## JSON

```text
POST /api/export/json
```

Use JSON for audit trails, downstream review tooling, or repeatable regression checks.

## HTML Report

```text
POST /api/report/html
```

The HTML report includes:

- site coordinates and ground elevation;
- preliminary topographic screening table;
- terrain profile summary;
- assumptions, limitations, and disclaimer text.

## PDF Report

```text
POST /api/report/pdf
```

The PDF report is a compact summary for engineering review. It is not a certified design report.

## Validation Report

```text
GET /api/validation/report/html
```

The validation report lists representative validation cases, detected broad behaviour, and
pass/warn/fail outcomes.

## Obstruction Inventory Report

```text
POST /api/obstructions/report/html
POST /api/obstructions/map
```

The obstruction report includes a footprint map endpoint, obstruction table, missing-height
summary, height-source summary, public-footprint-source warnings, classification, selected height,
raw source height, DSM-DTM estimate fields, confidence, review-required flags, preliminary
shielding sector table, sector confidence diagnostics, and indicative `Ms` values where enough
reviewed obstruction height data is available.

## Terrain Category Evidence Report

```text
POST /api/terrain-category/report/html
POST /api/terrain-category/map
```

The terrain category evidence report includes a directional evidence summary for all eight wind
directions, including built-up coverage, vegetation coverage, open terrain, obstruction height
statistics, obstruction density, vegetation density, fetch distance, shielding confidence,
suggested category range, confidence, warnings, indicative Mz,cat ranges, and separate evidence
score components.

The report does not assign a final terrain category and does not calculate final `Mz,cat` design
values.

## Site Wind Assessment Report

```text
POST /api/wind-workflow/report/html
POST /api/wind-workflow/report/pdf
POST /api/wind-workflow/result/report/html
POST /api/wind-workflow/result/report/pdf
```

The `/result/report/*` routes accept an already completed `WindWorkflowResult` only when its
server-issued `integrity_token` verifies. The browser uses these routes so opening a report does
not repeat elevation, terrain, or obstruction data calls. Editing any signed input, variable,
directional result, status, note, or override invalidates the token and returns HTTP 422.

`0.7.x` completed-result payloads are not compatible with the `0.8.0` report routes. Rerun the
workflow to obtain the current payload shape and integrity token; do not copy the old top-level
status, engineer-note, or override fields into the new result.

The HTML and PDF outputs use the same compact report structure:

- project, site, building, region, AEP/ARI, `VR,ult`, and governing result;
- one eight-direction table for `Md`, `Mz,cat`, `Ms`, `Mt`, and `Vsit,b`;
- deduplicated decision-relevant warnings, overrides, and engineer notes when present; and
- a short calculation-basis and limitations statement.

Raw calculation inputs, repeated per-variable summaries, map/profile placeholders, verbose source
metadata, and duplicated disclaimers are intentionally omitted. Those diagnostics remain available
in the application raw-data and diagnostics views.

The site wind assessment report does not include pressure calculations, `Cpe`, `Cpi`, or final
design pressures.
