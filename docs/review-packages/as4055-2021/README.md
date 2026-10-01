# AS 4055:2021 Independent Review Package

## Purpose and status

This package is prepared for independent structural-engineer review of the new AS 4055
calculation path. **No independent review or approval has been completed.** The code labels
every result `preliminary_independent_review_required`; it must not be used as certified
design or used to select members or connections without project-specific engineering.

The implementation is separate from the AS/NZS 1170.2 workflow and does not convert or
reuse its `Mt`, `Ms`, or directional design-speed results. Inputs for region, terrain,
topographic class, and shielding class are assessment decisions supplied to this service.
The service checks the combination against Table 2.2 but does not derive those categories
from a map, terrain profile, site photographs, or obstruction inventory.

## Licensed source

- Source: `AS 4055-2021 Wind Loads for Housing.pdf` (licensed copy supplied for this work).
- Edition: AS 4055:2021.
- SHA-256 of the reviewed local copy: `CC2A32879EAA83567240AEC3146B66C4D7B3C501903C22F68A6BE3DE78385F00`.
- Relevant printed pages: 1, 6–15, 16–21, and 24–27.
- Relevant references: Clauses 1.1–1.2, 2.1–2.6, 3.1–3.4, 4, and 5; Tables 2.1(A),
  2.1(B), 2.2, 2.6.1(A), 2.6.1(B), 3.2.1, 3.2.2(A), 3.2.2(B), 4, and 5.2(A)-(M).

The repository contains derived data and clause/table references only. It does not contain
scanned pages, figures, or a reproduction of the standard. The reviewer must have lawful
access to the licensed source above and verify the version and hash before sign-off.

## Code and interfaces under review

- `src/openwind_au/as4055.py`: scope checks, Table 2.2 lookup, Table 2.1 class speeds,
  roof/wall class suffixes, Clause 3.2 coefficient values, pressure/force equations, a
  single-load-path net-suction resultant helper, and racking-force arithmetic.
- `src/openwind_au/calculations/registry.py`: OpenCalcs definitions under
  `au.wind.as4055.*`.
- `src/openwind_au/calculations/as4055_extensions.py`: automatic simple zones, roof
  anchoring, racking pressure selection/interpolation and combined housing assessment.
- `src/openwind_au/as4055_racking_data.py`: Table 5.2 source data and lookup digest input.
- `src/openwind_au/api.py`: `/api/as4055/classification` and
  `/api/as4055/housing-loads`, `/api/as4055/pressure-zones`, `/api/as4055/roof-anchoring`,
  `/api/as4055/racking-pressure`, and `/api/as4055/housing-assessment` endpoints.
- `tests/test_as4055.py`: scope, class lookup, distance bands, pressure, force, and
  unsupported-class regressions.
- `tests/test_as4055_extensions.py`: zones, anchoring, racking, combined assessment and
  API/registry parity checks.

The current canonical AS 4055 lookup digest is exposed in each classification result as
`lookup_digest`: `75cf88c7bb94d2ab5ac7034322100724206db0869986187a3ee3dc671154d749`.
It is generated from the site-class matrix, class speeds, pressure coefficients, anchoring and racking data so
a reviewer can bind test evidence to the exact configured data.

## Clause-to-code review matrix

| Standard reference | Implemented behavior | Evidence to inspect | Review status |
| --- | --- | --- | --- |
| 1.1–1.2 | Class 1/10a and height, plan, and pitch scope guards | `validate_geometry`; scope boundary tests | Pending independent review |
| 2.1 / Table 2.1(A), (B) | N1–N6 and C1–C4 serviceability and ultimate class speeds | `_WIND_SPEEDS`; class speed tests | Pending independent review |
| 2.2 / Table 2.2 | Lookup by supplied region, terrain category, topographic class, shielding class, and C/D distance; `NA` produces an AS/NZS 1170.2 referral | `_SITE_COLUMNS`, `_NON_CYCLONIC`, `_CYCLONIC`; band boundary tests | Pending independent review; source transcription not signed off |
| 2.3–2.5 | Requires the resulting category labels as explicit inputs | `SiteConditions` schema | Category derivation and evidence collection are not implemented |
| 2.6 / Table 2.6.1(A), (B) | Adds `r` and `w` to the site class | `classify_site`; suffix tests | Pending independent review |
| 3.1 / Figure 3.1(A), (B) | Requires measured areas tagged G, RE, RC, or SC; rejects incompatible component/zone combinations | `HousingSurface`; area is explicit in API | Simple flat/gable rectangular geometry is implemented; hips, overhangs and individual openings need explicit review |
| 3.2 / Tables 3.2.1, 3.2.2(A), (B) | External, internal, and net coefficients for supported component/zone combinations | `_COEFFICIENTS`; pressure tests | Pending independent review |
| 3.3 | `p = q_u C_p`, with `q_u = 0.5 rho V_h^2 / 1000`, `rho = 1.2 kg/m3` | `calculate_housing_loads`; expected numeric pressure assertions | Pending independent review |
| 3.4 | Resultant surface force equals pressure times supplied area | `calculate_housing_loads`; force regression | Pending independent review |
| Section 4 / Table 4 | Net anchoring pressure by roof class/type and limit state, including tabulated dead load | `calculate_roof_anchoring`; all 40 source cells tested | Implemented; independent review pending. Kept separate from Section 3 suction |
| 5.1–5.2 | Tables 5.2(A)–(M) pressure selection/interpolation; racking force from reviewed elevation area | `calculate_racking_pressure`, `calculate_racking_force`, combined assessment and extension regressions | Implemented for stated table geometry; elevation areas remain reviewed inputs and independent review is pending |
| 3.2.3 | Solar-panel pressures remain outside this path | Refers to AS/NZS 1170.2 | Explicitly unsupported |

## Reproducible software vectors

These vectors are regression evidence for the current code and its transcribed lookup values.
They are not a substitute for independently reproducing the standard's published worked
examples.

| Case | Inputs | Expected result |
| --- | --- | --- |
| Non-cyclonic baseline | Class 1; eaves 3.0 m; ridge 5.0 m; plan 10 m × 20 m; 20°; Region A; TC3; T0; FS | N1, N1w, N1r; serviceability 26 m/s; ultimate 34 m/s |
| Cyclonic boundary | Same geometry; Region C; TC3; T0; PS; distance 0 km from the recorded smoothed-coastline basis | C2, C2w, C2r; serviceability 39 m/s; ultimate 61 m/s |
| C-class distance transition | Region C; TC3; T0; PS | 10 km resolves to C2; 10.01 km resolves to C1 |
| Non-cyclonic roof general pressure | N1 ultimate speed; G roof cladding; 10 m² | `q_u = 0.6936 kPa`; net suction `-0.6936 kPa`; resultant `-6.936 kN` |
| Cyclonic roof corner pressure | C1 ultimate speed; RC roof cladding; 1 m²; pitch 9.9° | `q_u = 1.5 kPa`; net suction coefficient `-3.06`; pressure `-4.59 kPa` |
| Cyclonic roof corner serviceability | Region C; TC3; T0; PS; 0 km; RC roof cladding; 1 m²; pitch 9.9° | C2 serviceability speed 39 m/s; `q_u = 0.9126 kPa`; net suction coefficient `-2.61`; pressure `-2.381886 kPa` |
| Racking arithmetic | 42 m² elevation; 0.8 kPa independently selected lateral pressure | 33.6 kN |

Run `pytest tests/test_as4055.py tests/test_calculation_registry.py` for the focused software
regressions. Record the exact commit, Python/runtime versions, command, and full-suite result
when the independent reviewer reruns them.

### Local software run — 2026-09-26

The current working-tree snapshot was tested from a local-disk copy with Python 3.12.10 and
pytest 9.1.1. The focused AS 4055, calculation-registry, AS/NZS 1170.2 primitive, and lookup
table suites passed **81 tests**; the complete Python suite passed **631 tests**. Ruff passed
for the affected calculation and test files. The run included uncommitted working-tree changes
at repository revision `bc054f23d2645eb9dfe44b1b4b504a94ebec01db`. This is software regression
evidence, not independent engineering review or sign-off.

## Review checklist and release gates

The reviewer should independently verify every Table 2.2 cell and distance interval, class
speed, suffix mapping, pressure coefficient/sign, pressure equation/units, applicability
limit, and expected result. Add at least one applicable worked example for each supported
Region A/B and C/D path and resolve exact distance-boundary conventions before release.

The current implementation must remain preliminary until all of these are complete:

1. Confirm the governing AS 4055 edition and applicable NCC/jurisdictional adoption.
2. Independently inspect every copied/derived lookup value against the licensed source and
   record reviewer initials, date, source hash, and lookup digest.
3. Reproduce relevant published worked examples and add their full input/output vectors.
4. Independently verify the implemented Table 5.2(A)–(M) pressure selection/interpolation
   and supported automatic pressure-zone partitioning. Confirm reviewed elevation areas
   and sufficient source evidence for supplied site-category inputs.
5. Independently verify the separate Table 4 roof-anchoring uplift path before approving
   anchoring results. Keep it distinct from the Clause 3 single-component surface resultant;
   check that cladding, fasteners, immediate supports, framing, and total roof uplift cannot
   be summed twice.
6. Run focused and full test suites; attach logs and commit hash.
7. Complete the sign-off record below. Keep certification claims outside product language.

## Independent reviewer record

- Reviewer name and registration:
- Professional discipline and relevant experience:
- Organization / conflict declaration:
- Standard edition and amendment verified:
- Source PDF SHA-256 verified:
- Lookup digest reviewed:
- Table 2.2 transcription review and boundary convention:
- Tables 2.1, 2.6.1, and 3.2 review:
- Equations / unit / sign review:
- Worked examples reproduced:
- Table 5.2 racking implementation accepted or outstanding:
- Findings and required changes:
- Review disposition: **Not reviewed / Changes required / Accepted for stated scope**
- Signature / date:


## Review continuation - 2026-09-28

New interfaces: `au.wind.as4055.pressure_zone_areas`, `au.wind.as4055.roof_anchoring`,
`au.wind.as4055.racking_pressure`; API routes `/api/as4055/pressure-zones`,
`/api/as4055/roof-anchoring`, `/api/as4055/racking-pressure`.

- Automatic zones use 1.2 m surface distances, distinguish ridge edges from external eave
  corners, conserve area, and use RC only below 10 degrees. They assume a rectangular
  flat or symmetric gable house without overhangs. Individual windows/doors require the
  whole-panel corner check in Table 3.2.1 Note 5.
- Table 4 uses the entire roof surface. Its net pressures already incorporate roof dead
  load. They must not be combined with Section 3 cladding suction or reduced by dead load again.
- Tables 5.2(B-M) require the stated 2.4 m storey and 0.3 m floor, width 4-16 m and pitch
  0-35 degrees. Other heights fail explicitly. Gable-end wind uses Table A. Roof pitch
  and width must agree with the classified building. Check both directions and every storey.
- Saved classifications are recomputed and checked against their source geometry/site,
  class speeds and lookup digest before use. Older lookup digests require deliberate reclassification.
- `tests/test_as4055_extensions.py` adds source anchors, all table-cell addressing,
  interpolation, invalid-scope, area conservation, trust-boundary and API/registry checks.
- Source transcription was visually checked against the licensed pages, with OCR used
  only as an aid. This remains the implementing author's check, not independent sign-off.

Outstanding independent review: original site classification tables and boundaries,
new lookup transcription, interpolation convention, pressure-zone interpretation, worked
examples, amendments and jurisdictional adoption. No engineering approval is claimed.

## Combined housing assessment - 2026-09-29

`au.wind.as4055.housing_assessment` and `/api/as4055/housing-assessment` assemble the
supported methods into one reproducible run. Classification and zone geometry are shared
by the serviceability and ultimate surface/anchoring cases. Racking remains ultimate
demand, with separate reviewed side/end elevation areas for each storey.

The combined path rejects missing/duplicate storeys or directions, inconsistent storey
dimensions, eaves heights inconsistent with the storeys/floor, unsupported roof geometry
and a cladding envelope that does not meet the Table 4 condition. Subfloors and overhangs
are excluded. Section 3, Section 4 and Section 5 results retain their separate load paths.

The combined regression checks N1 anchoring at 0.04/0.33 kPa over the sloping roof area,
side racking at 0.49 kPa over 42 m2 and end racking at 0.66 kPa over 25 m2. API/registry
parity and invalid-scope responses are checked. These are implementing-author regression
fixtures; the independent reviewer must still reproduce and accept the stated scope.
