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
```

The site wind assessment report includes Wind Region Assessment, Regional Wind Speed Assessment, and
Direction Multiplier Assessment sections. Wind region is derived from the configured local
Geoscience Australia 1170.2 Wind Regions GIS dataset. `VR` and `Md` values are table-derived from
editable JSON lookup files and include source-reference text and warnings when manual input is
required.

The site wind assessment report does not include pressure calculations, `Cpe`, `Cpi`, or final
design pressures.
