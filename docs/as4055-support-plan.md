# AS 4055:2021 Support Plan

## Implementation update — 2026-09-29

A first, preliminary implementation now exists in `src/openwind_au/as4055.py`, the OpenCalcs
registry, and the AS 4055 API routes. It includes geometry guards, a Table 2.2 class lookup
from supplied categories, Table 2.1 speeds, roof/wall suffixes, Section 3 surface pressures
and forces, simple flat/gable automatic zones, Table 4 anchoring, and Tables 5.2(A-M)
racking selection/interpolation. A combined housing assessment assembles both limit states
and every supplied storey's side/end racking demand into one run. It still requires reviewed
site categories and elevation areas, and excludes complex roofs, overhangs and subfloors
from the combined automatic path. No independent review has been completed. Use the review
matrix and sign-off record in `docs/review-packages/as4055-2021/README.md` as the current
engineering review package. The remaining items below describe the intended full workflow.

## Goal and Boundary

Add a separate AS 4055:2021 housing assessment for eligible NCC Class 1 and Class 10a
buildings. AS 4055 is a prescriptive classification and housing-load path. It must not be
presented as a conversion of the existing AS/NZS 1170.2 workflow, and results outside its
scope must route to an engineer using the applicable AS/NZS 1170.2 edition.

Keep all derived values traceable to the selected edition, clause/table, reviewer, review
date, and immutable lookup digest. Do not store licensed standards pages or copied tables in
the repository.

## Standard Workflow to Implement

1. **Edition and scope gate**
   - Make AS 4055:2021 an explicit standard selection; do not infer it from house geometry.
   - Confirm building class and the standard's house geometry limits before calculating:
     eaves height, total roof height, width, length-to-width ratio, and roof pitch.
   - Reject unsupported building classes or out-of-scope geometry with a clear AS/NZS
     1170.2 referral state. Require a human decision where the NCC class or geometry is
     ambiguous.

2. **Site inputs and classifications**
   - Resolve the geographic wind region using the applicable AS 4055 map and retain the map
     version and location evidence.
   - For Regions C and D, collect distance to the coast or applicable wind-region boundary
     and implement the standard's coastal interpolation. Do not substitute OpenWind's
     current AS/NZS 1170.2 maximum-region fallback.
   - Determine terrain category using AS 4055's housing definitions and anticipated
     development horizon. Restrict this path to the categories AS 4055 permits; do not feed
     an AS/NZS TC4 result into the housing classification.
   - Determine topographic class T0-T5 from reviewed cross-section geometry and the
     standard's top/middle/bottom zone rules.
   - Determine shielding class FS/PS/NS using permanent obstruction coverage and the
     region-specific vegetation rules. Keep terrain and shielding evidence separate.
   - Map region, terrain, topographic class, shielding class, and coastal distance to the
     AS 4055 site class N1-N6 or C1-C4. Return the serviceability and ultimate design
     speeds required by the selected class and applicable source table.

3. **Housing component outputs**
   - Map the site class to the roof and wall classifications, retaining the `r` and `w`
     designations.
   - Calculate pressure zones for roof general, roof edge, roof corner, wall general, and
     wall corner areas using the geometric inputs.
   - Add the applicable non-cyclonic or cyclonic pressure coefficients, internal pressure
     cases, design pressures, and component forces. Keep cladding, fasteners, immediate
     supports, and primary structure outputs distinct where the standard does.
   - Implement uplift and racking forces as separate outputs with explicit tributary areas
     and load paths. Do not describe a wind class alone as a complete structural design.

4. **Evidence and reporting**
   - Add a separately versioned AS 4055 request/result schema and calculation registry
     entries; do not overload AS/NZS 1170.2 `Vdes,theta`, `Mt`, or `Ms` fields.
   - Show the exact inputs, classification decisions, table references, source digest,
     warnings, and unresolved review items in JSON, UI, and reports.
   - Preserve the existing preliminary/reviewed status controls and block certification or
     final-design language until the independent release gate is met.

## Delivery Sequence

1. **Standards matrix and decision record** — confirm current amendments, NCC adoption,
   exclusions, definitions, units, table sources, and independent reviewer with a licensed
   structural engineer.
2. **Reviewed source assets** — transcribe only the required classification and coefficient
   data into schema-validated lookup assets. Add canonical digests, provenance metadata,
   named independent review, and date before enabling calculations.
3. **Classification engine** — implement scope validation, region/distance resolution,
   terrain, topographic and shielding classes, and N/C site class selection. Add traceable
   decision paths and unresolved-input blockers.
4. **Housing load engine** — implement roof/wall class mapping, pressure zones and
   coefficients, pressure/force calculations, uplift, and racking in separable modules.
5. **User workflow** — add an explicit AS 4055 entry point and standard selector, input
   collection, explainable review screens, reports, and export guardrails.
6. **Validation and release** — verify each table and equation against the licensed 2021
   source, reproduce the standard's applicable worked examples, add boundary and regression
   cases, and complete independent engineer sign-off. Repeat for each adopted amendment or
   jurisdictional variation.

## Acceptance Gates

- Every in-scope classification, pressure, and force result has a traceable source and
  deterministic regression case.
- Out-of-scope buildings, missing classification inputs, and unsupported region cases block
  final outputs instead of silently falling back to AS/NZS 1170.2 values.
- Non-cyclonic and cyclonic paths are independently checked, including serviceability and
  ultimate cases, wall/roof component classes, internal pressure, and pressure-zone edges.
- Standards tables, worked examples, and edge conditions pass review by a named independent
  engineer for the exact edition and jurisdiction.
- Product copy clearly separates screening evidence, engineer-reviewed results, and
  certification, which remains outside the software's claim unless separately authorized.

## Current Reuse and Gaps

OpenWind can provide site coordinates, base mapping, terrain profiles, obstruction evidence,
and report provenance. Its current terrain scoring is a screening heuristic, its shielding
assessment targets AS/NZS 1170.2, and its topographic calculation targets AS/NZS 1170.2.
Those values may support evidence gathering but cannot be reused as AS 4055 classes without
implementing the separate rules and obtaining engineering review. Cyclonic C/D interpolation,
AS 4055 site classification, component pressure coefficients, uplift, and racking calculations
are not currently implemented.
