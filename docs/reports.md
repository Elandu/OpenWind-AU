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
