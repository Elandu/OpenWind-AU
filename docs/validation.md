# Validation Framework

OpenWind-AU validation is a qualitative audit framework for representative Australian terrain
settings. It runs the normal 8-direction terrain-profile and preliminary topographic screening
workflow against known example sites, then compares the results with broad expected behaviour.

Validation helps contributors see whether changes preserve sensible behaviour across flat,
coastal escarpment, hilltop, valley, and inland-flat terrain examples.

## What Validation Means

Validation means:

- the analysis pipeline can run consistently across representative Australian locations;
- outputs can be compared with broad terrain expectations;
- changes can be reviewed against pass, warning, and fail outcomes;
- validation reports can be exported as JSON and HTML for audit trails.

## What Validation Does Not Mean

Validation does not mean:

- AS/NZS 1170.2 compliance;
- verified design wind pressures;
- verified topographic multipliers;
- certification for any project site;
- proof that public DEM data is accurate enough for final engineering design.

All outputs remain preliminary and require review by a competent engineer.

## Why Broad Qualitative Validation Is Used

The project currently uses public DEM terrain data and conservative rule-based screening. At this
stage, broad qualitative checks are more appropriate than exact engineering targets because:

- public DEM resolution can miss local earthworks, retaining structures, and abrupt terrain changes;
- the Clause 4.4 equations are unit tested, but representative locations are not surveyed
  topographic benchmark cases;
- representative locations are useful for regression testing but are not calibrated benchmark sites;
- engineering review is still required before any project use.

## Adding Validation Sites

When adding a validation case, include:

- `case_id`;
- site name;
- latitude and longitude;
- building height used for the test request;
- expected general terrain description;
- expected broad topographic behaviour;
- notes explaining why the site is useful;
- source/reference field;
- broad expected feature type set.

Use only representative behaviour. Do not add exact design outcomes, code multipliers, or claims
that the validation case proves compliance.

Good validation cases should be:

- public and easy to understand from general terrain context;
- broad enough to avoid false precision;
- useful for catching regressions in terrain-profile or topographic-screening behaviour;
- free of private client, claim, or project information.

Validation examples can be proposed with the GitHub issue template:
`.github/ISSUE_TEMPLATE/validation_example.yml`.

## Deterministic Calculation Validation

The qualitative site validation above depends on public terrain data and broad expected behaviour.
OpenWind-AU also includes deterministic calculation validation for wind inputs, shielding, and
topographic screening formulas using synthetic inputs and anonymized class-level checks with
known expected outputs.

Use:

```text
GET /api/calculation-validation
```

These checks are designed to be stable without external DEM, geocoding, Microsoft footprint, or
Overpass data. They validate covered implementation details such as:

- indicative `Ms` interpolation thresholds;
- Table 4.1 nodes, combined height/category interpolation, and Region A0 rules;
- a synthetic Region A2 serviceability regional wind speed check of 37 m/s;
- Clause 4.4 `Mt` calculations including Region A0 and high-elevation Region A4 adjustments;
- the Table 3.3 `Mc` mapping and a full-precision
  `VR x Mc x Md x Mz,cat x Ms x Mt` product that rounds only the reported `Vsit,b`;
- shielding-sector inclusion, rejection counts, `hs`, `bs`, `ls`, `s`, and indicative `Ms`;
- topographic feature screening for flat, ridge, hill, escarpment, and valley synthetic profiles;
- threshold behaviour where sub-5 m relief is screened out.

Passing deterministic calculation validation confirms that the covered formulas and screening
rules are internally consistent. It does not certify AS/NZS 1170.2 compliance, public dataset
accuracy, or suitability for a project site.

## Terrain Category Evidence Examples

Terrain category evidence scoring includes synthetic representative examples for:

- coastal open terrain;
- suburban housing;
- dense suburban terrain;
- industrial estate terrain;
- CBD-like terrain;
- rural vegetation.

Use:

```text
GET /api/terrain-category/validation/cases
GET /api/terrain-category/validation
```

These examples validate that suggested ranges and indicative Mz,cat ranges are broadly reasonable
prompts for review. They do not assign final terrain categories or final `Mz,cat` design values.

## Reference Calculation Comparisons

OpenWind-AU includes a fixed, anonymized class-level comparison at deliberately translated
synthetic coordinates in Region `B1`. The encoded reference reports:

- Region `B1`;
- `Vh,ult = 40 m/s`, `Vh,serv = 26 m/s`;
- `TC3` terrain in all eight directions;
- `FS` shielding in all eight directions;
- topography class `T1` for `NE` and `E`, and `T0` elsewhere.

Use:

```text
GET /api/reference-validation/anonymized
```

This endpoint runs the current terrain, obstruction, and terrain-category evidence pipelines for
the anonymized fixture and compares directional terrain, shielding, and topographic class labels.
It does not execute the numeric site-wind multiplier workflow. The bundled footprint geometry is translated by one
fixed offset so relative geometry is preserved while the original location, OSM feature IDs, and
all source tags are omitted. It remains intentionally a class-level gap check: mismatches usually
mean the public obstruction/topographic evidence or class mapping needs review before final
multipliers are trusted.

The fixture contains information derived from OpenStreetMap data. Attribution is
`© OpenStreetMap contributors`, available under the Open Data Commons Open Database License
([ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)); see the
[OpenStreetMap copyright page](https://www.openstreetmap.org/copyright).

Use:

```text
GET /api/reference-validation/anonymized?apply_reference_overrides=true
```

to apply the encoded reference classes during the comparison. A 24/24 match verifies override
transport and class-label mapping while preserving the raw evidence mismatch in the default
endpoint; it is not a numeric multiplier validation.
