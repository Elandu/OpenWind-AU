# AS/NZS 1170.2:2021 Base-Edition Verification

Audit date: 2026-07-29

This record documents the calculation evidence checked against an access-controlled copy of the
base AS/NZS 1170.2:2021 publication. It records clause and page references without reproducing
licensed text or tables. No standards PDF or workstation path is stored in the repository.

The available standards folder did not contain Amendments 1 or 2. This audit therefore verifies
the base 2021 edition only and does not claim compliance with an amended or jurisdictionally
adopted edition. Production readiness still requires a named independent engineer, review date,
and confirmation of the edition applicable to the project.

## Evidence Matrix

| Runtime item | Base-edition evidence checked | Repository coverage | Audit result |
| --- | --- | --- | --- |
| Eight-direction site wind-speed product | Clause 2.2, printed page 16 (PDF page 24) | `site_wind_speed`, directional workflow rows, REST/MCP parity tests | Product and full-precision multiplication match |
| Engineering azimuth and design wind speed | Clause 2.3 and Figures 2.2-2.3, printed pages 16-17 (PDF pages 24-25) | `0 <= beta < 360`, clockwise from true North; front/right/back/left axes; linear interpolation and maximum within each plus-or-minus 45-degree sector; 30 m/s ULS minimum | Convention and deterministic `Vdes,theta` calculation match the base-edition method |
| Regional wind speed, `VR` | Clause 3.2 and Table 3.1(A), printed pages 24-26 (PDF pages 32-34) | `R=1` nodes, `R>=5` equations, nearest-1 m/s rounding, packaged rows | Equations and packaged rows match |
| Direction multiplier, `Md` | Clause 3.3 and Table 3.2(A), printed pages 26-27 (PDF pages 34-35) | Eight regional rows plus mandatory `Md=1.0` cases | Packaged rows and mandatory cases match |
| Climate-change multiplier, `Mc` | Clause 3.4 and Table 3.3, printed page 27 (PDF page 35) | A0-A5/B1 `1.0`; B2/C/D `1.05`; ambiguous B rejected | Mapping matches |
| Terrain-height multiplier, `Mz,cat` | Clause 4.2.2 and Table 4.1, printed pages 30-31 (PDF pages 38-39) | Table nodes, height/category interpolation, A0 rule | Nodes and interpolation match; TC3.5 now interpolates instead of snapping to TC4 |
| Mixed-terrain fetch | Clause 4.2.3, printed page 31 (PDF page 39) | Explicit warning and reviewed override path | Not automated; no runtime coverage claim |
| Shielding multiplier, `Ms` | Clauses 4.3.1-4.3.2 and Table 4.2, printed pages 32-33 (PDF pages 40-41) | 45-degree sectors, `20h` radius, height/breadth/spacing equations, table interpolation, `h>25 m` rule | Implemented equations/nodes match; request validation now prevents a truncated `20h` fetch |
| Topographic multiplier, `Mt` | Clauses 4.4.1-4.4.2 and Figures 4.3-4.5, printed pages 33-35 (PDF pages 41-43) | A0/A4 rules, `H/(2Lu)`, `L1`, `L2`, Equations 4.4(3)-4.4(4), local-zone checks | Implemented equations match; the base-edition `H<10 m => Mh=1.0` rule is enforced |
| Australian lee multiplier | Clause 4.4 and Table 4.3, printed pages 33 and 36 (PDF pages 41 and 44) | `Mlee=1.0` for the Australian workflow | Matches the base-edition evidence |

## Corrections Made From This Audit

- Replaced the unsupported dynamic topographic feature cutoff with the base-edition 10 m cutoff.
- Required obstruction inventory coverage of the complete Clause 4.3.1 `20h` shielding sector
  whenever `h <= 25 m`.
- Added correct linear Table 4.1 support for TC3.5.
- Removed the false claim that a single-category Table 4.1 lookup implements Clause 4.2.3.
- Blocked wind-region calculation when the configured GIS has no polygon covering the site,
  instead of silently selecting the nearest polygon.
- Made wind-region source attribution reflect the configured dataset.
- Added schema and out-of-band digest protection to the packaged `VR` and `Md` tables, matching the
  existing `Mz,cat` and `Ms` controls.
- Added building orientation, breadth/depth semantics, and roof geometry to issued report context.
- Added the Clause 2.3 four-face `Vdes,theta` calculation, including circular linear
  interpolation, the closed plus-or-minus 45-degree sector, and the 30 m/s ultimate minimum.

## Deliberate Limits

The following paths are not claimed as implemented:

- automatic derivation of AEP/ARI from `importance_level` or `design_life_years`; those fields
  are report metadata only;
- design pressures, pressure coefficients, structural response, or certification;
- Region C/D distance-based coastal interpolation;
- Clause 4.2.3 mixed-terrain weighted averaging;
- automatic selection of the most adverse Clause 4.4.2 section within plus or minus 22.5 degrees;
- automatic confirmation of escarpment downwind-slope eligibility;
- amendment-specific or NCC jurisdictional changes not present in the supplied base edition.

Terrain-category scoring and DEM feature selection remain software evidence heuristics. They are
not normative classification formulas. Issued results remain preliminary, expose confidence and
warnings, and allow explicit reviewed class/value overrides.

## Reverification Procedure

1. Confirm the project edition, amendments, NCC adoption, and jurisdictional variations.
2. Compare every supported row/equation above against a licensed copy of that edition.
3. Update calculation code, snapshots, this matrix, and the immutable report-lineage commit.
4. For any approved replacement lookup, calculate its canonical payload digest and configure the
   matching `OPENWIND_*_EXPECTED_SHA256` value.
5. Record the independent reviewer and ISO review date in each lookup source block.
6. Run the complete Python/JavaScript suite, package install smoke test, REST/MCP parity checks,
   report generation/render checks, and `openwind-au check --json`.

Passing automated tests verifies the implemented paths and regression evidence. It is not a
substitute for project-specific engineering review.
