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
- the tool does not yet implement code-specific terrain or topographic multipliers;
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
topographic screening formulas using synthetic inputs and prior project-reference checks with
known expected outputs.

Use:

```text
GET /api/calculation-validation
```

These checks are designed to be stable without external DEM, geocoding, Microsoft footprint, or
Overpass data. They validate covered implementation details such as:

- indicative `Ms` interpolation thresholds;
- the prior Modos 04625 Region A2 serviceability regional wind speed reference of 37 m/s;
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
