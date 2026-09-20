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
In the browser workflow, a generated PDF is downloaded when the viewer window cannot be opened;
the API response remains the authoritative report payload.

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

This aggregate terrain-evidence report does not assign a final terrain category or by itself select
the workflow `Mz,cat`; reviewed single-category or mixed-terrain inputs drive that calculation.

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

- project, site, building, common reference height, reviewed base RL, region, AEP/ARI, effective
  `VR,ult`, `Mc`, and every tied governing direction;
- one eight-direction table for `Md`, `Mz,cat`, `Ms`, `Mt`, calculated `Vsit,b`, and final
  `Vsit,b` when a reviewed direct override applies;
- one four-face Clause 2.3 table for the relative `theta`, absolute `beta`, design sector, raw
  maximum and ultimate `Vdes,theta`;
- Clause 4.2.3 averaging geometry and per-segment Table 4.1 weighted contributions for supplied
  non-A0 `mixed_terrain_profiles`, or the signed input intervals as unweighted evidence for A0;
- deduplicated decision-relevant warnings, overrides, and engineer notes when present; and
- a short calculation-basis and limitations statement.

Raw calculation inputs, repeated per-variable summaries, map/profile placeholders, verbose source
metadata, and duplicated disclaimers are intentionally omitted. Those diagnostics remain available
in the application raw-data and diagnostics views.

The report states the complete Clause 2.2 product
`Vsit,b = VR x Mc x Md x Mz,cat x Ms x Mt`. Non-directional `VR` and `Mc` are each shown once
rather than repeated across all eight directional rows. Numeric class-multiplier overrides are
disclosed alongside their calculated values, while a direct `Vsit,b` override is labelled as the
final reviewed value instead of being presented as the multiplier product.

The site wind assessment report includes cardinal `Vsit,b` and building-orthogonal ultimate
`Vdes,theta`. It does not include pressure calculations, `Cpe`, `Cpi`, or final design pressures.
The workflow reports intentionally omit certification/compliance wording, issue-status banners,
and reviewer labels. The legacy/API-compatibility `assessment_status` and `reviewed_by` fields do
not control report presentation; API-supplied `engineer_notes` may appear only as a review note.
For A0, any supplied mixed-terrain profile is reported as evidence against the workflow reference
height; it may be incomplete and does not weight or replace the mandatory terrain-independent
`Mz,cat`.

The browser-generated PDF also includes a screenshot of the current interactive map, captured
against the signed workflow location immediately before report generation. Direct API clients may
send an optional PNG or JPEG data URI as `map_screenshot` with `result` to
`POST /api/wind-workflow/result/report/pdf`; remote image URLs and file paths are not accepted.
The screenshot is context only. The signed coordinates and numeric assessment remain the source
of truth.
