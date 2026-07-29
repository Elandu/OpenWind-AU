# Calculation Basis and Data Lineage

OpenWind-AU is an engineering review aid. Outputs are evidence and workflow support tools.
Final design decisions remain the responsibility of the engineer.

## Standards Verification Status

The implemented Clause 2.2 product, the Clause 2.3/Figure 2.2 clockwise-from-true-North cardinal
direction convention, base Table 3.1(A) regional-speed equations and rows, Table 3.2(A) direction
multipliers, Clause 3.4/Table 3.3 climate-change factors, Table 4.1 terrain/height values, Table 4.2
shielding values, and the implemented Clause 4.4 equations have been cross-checked against an
access-controlled copy of the base AS/NZS 1170.2:2021 publication. That source does not establish
incorporation of Amendments 1 and 2. It therefore does not satisfy the production release
requirement for independent named reviewer/date sign-off against the applicable amended edition.

No licensed PDF, workstation path, copied clause, or bulk standards table is committed to the
repository. Derived data, source references, tests, and review status are recorded without
publishing the licensed source material.

The detailed clause/page matrix and reverification procedure are recorded in
[`base-standard-verification.md`](base-standard-verification.md).

## Wind Region

### Input Data

- Geoscience Australia AS1170 wind region polygons supplied as a local GIS dataset.
- Site latitude and longitude from user coordinates or geocoding.
- Optional environment configuration for dataset path, layer, and region field.

### Processing Method

OpenWind-AU loads the configured wind-region GIS dataset and performs a point-in-polygon
selection for the site coordinate. When more than one polygon intersects the site, it applies the
configured selection logic and reports neighbouring polygons for review. Boundary warning logic
checks the site distance to the selected region boundary and downgrades confidence near a
configured warning distance.

If no configured polygon covers the site, calculation is blocked. The nearest polygon remains
available only in internal diagnostics and is not promoted to a wind-region assessment.

Internal dataset diagnostics include the configured path. Public assessments report the dataset
identity, polygon count, available region labels, and whether the active dataset is a test
fixture, but omit local paths and full region geometry.

### Output Fields

- Wind region label: `A0`, `A1`, `A2`, `A3`, `A4`, `A5`, `B1`, `B2`, `C`, or `D`.
- Region subclassification where available.
- Dataset name and non-sensitive metadata; the local path remains internal/diagnostic.
- Polygon count and available region names.
- Distance to boundary.
- Boundary warning flag.
- Confidence.
- Warnings.

### Review Requirements

The engineer must confirm the wind region against the project standard and source GIS dataset.
Sites close to region boundaries need particular review because small changes in coordinates,
dataset interpretation, or boundary geometry can change the selected region.

`OPENWIND_WIND_REGION_BOUNDARY_WARNING_M` must be a finite number greater than zero. A non-numeric,
non-finite, zero, or negative value is a deployment-readiness failure rather than a silently
accepted threshold.

## Regional Wind Speed (VR)

### Input Data

- Packaged AS/NZS 1170.2:2021 Table 3.1(A) lookup data.
- Source file: `src/openwind_au/data/regional_wind_speeds.json`.
- Assessed wind region.
- Annual recurrence interval parsed from the selected annual exceedance probability.
- Optional override table supplied with `OPENWIND_VR_TABLE_PATH`.

### Processing Method

OpenWind-AU maps Australian subregions to their base regional equation and calculates `VR,ult`
from AS/NZS 1170.2:2021 Table 3.1(A). The explicit `V1` table value is used for `R = 1`; for
`R >= 5`, the regional equation is evaluated and rounded to the nearest 1 m/s. Recurrence
intervals between 1 and 5 are rejected because they are not covered by the regional equation.
Project-supplied override tables may provide an independently reviewed exact ARI row. Missing
rows are not interpolated. If an override row is unchanged from the packaged standard snapshot,
non-tabulated `R >= 5` values retain the regional-equation calculation rather than interpolating
between already rounded rows.

Each configured regional table must contain exactly non-empty `ultimate` and `serviceability`
objects. ARI keys must be canonical positive integer years, limited to `1` or `R >= 5`, without
duplicate normalized years. Speeds must be finite numbers greater than zero and no greater than
200 m/s. Unexpected members or invalid rows fail readiness and the calculation rather than being
coerced or partially used.

For Regions C and D, the default equation result is explicitly labelled as the regional maximum.
Distance-based interpolation from the smoothed coastline is not implemented; an exact configured
row may be treated as site-specific only after independent review of that interpolation.

The serviceability value currently reported by the app is the 25-year serviceability row where
available. Lookup metadata is checked so packaged or override JSON must include
`source.review_status == "verified_against_standard"`, a named `source.reviewed_by`, and a valid
ISO `source.reviewed_on` date to avoid a warning.

### Output Fields

- `VR,ult`.
- `VR,serv`.
- Selected source table reference.
- Lookup values used in the calculation.
- Interpolation note where applicable.
- Warnings.

### Review Requirements

The engineer must confirm the selected AEP/ARI, table applicability, jurisdictional NCC
variations, and any override source before using the value in design decisions. `importance_level`
and `design_life_years` are retained as report metadata only; they do not derive or select the
AEP/ARI.

## Direction Multiplier (Md)

### Input Data

- Packaged AS/NZS 1170.2:2021 Table 3.2(A) lookup data.
- Source file: `src/openwind_au/data/direction_multipliers.json`.
- Assessed wind region.
- Optional override table supplied with `OPENWIND_MD_TABLE_PATH`.

### Processing Method

OpenWind-AU selects the region-specific direction multiplier row and returns values for N, NE, E,
SE, S, SW, W, and NW. The request also identifies the Clause 3.3 design case. `Md = 1.0` is
enforced for circular or polygonal chimneys, tanks and poles, and for cladding and its immediate
supporting structure in Regions B2, C and D. A `monopole` structure class automatically takes the
pole case. It identifies the highest value in the row and marks all matching directions as
governing directions. Lookup metadata is checked so packaged or override JSON must include
`source.review_status == "verified_against_standard"`, a named `source.reviewed_by`, and a valid
ISO `source.reviewed_on` date to avoid a warning.

Each selected lookup row must contain exactly the eight named directions with no extras. Every
value must be a finite numeric value greater than zero and no greater than 2.0. An invalid row
fails readiness and calculation instead of returning a partial direction set.

### Output Fields

- Md values by direction.
- Highest Md.
- Governing direction list.
- Selected source table reference.
- Lookup values.
- Warnings.

### Review Requirements

The engineer must confirm the selected direction-multiplier design case. An `Md` override is
rejected where Clause 3.3 mandates `Md = 1.0`.

## Climate Change Multiplier (Mc)

### Processing Method

OpenWind-AU selects the non-directional `Mc` from AS/NZS 1170.2:2021 Clause 3.4 and Table 3.3.
Regions A0-A5 and B1 use `1.0`; Regions B2, C and D use `1.05`. Generic legacy Region `A` is safe
because every A subclass has the same value. Generic Region `B` is rejected because it does not
distinguish B1 from B2.

### Output Fields

- One non-directional `Mc` assessment with its source reference.
- `Mc` in every signed directional factor snapshot used to verify `Vsit,b`.

### Review Requirements

The engineer must confirm the wind-region subclassification, particularly B1 versus B2.

## Terrain Evidence

### Input Data

- Public DEM sampling from SRTM through the configured DEM workflow.
- Site location, overall building height, average roof height, radius, and sample interval.
- Obstruction inventory evidence for built-up and vegetation coverage.
- Packaged `src/openwind_au/data/terrain_height_multipliers.json` Table 4.1 values.
- Optional reviewed override supplied with `OPENWIND_MZCAT_TABLE_PATH`.

### Processing Method

OpenWind-AU generates radial terrain profiles for the standard eight directions. It samples DEM
elevations along each profile, calculates slope evidence, and combines terrain-profile context with
directional obstruction evidence. Built-up density, vegetation evidence, open-terrain percentage,
obstruction density, height coverage, and confidence scoring are reported by direction.

OpenWind-AU does not assign final terrain categories. It provides evidence only.

For each reviewed or recommended category, the wind workflow evaluates `Mz,cat` at the request's
single common reference height (`average_roof_height_m`, falling back to `building_height_m`). The
lookup supports the AS/NZS 1170.2:2021 Table 4.1 height nodes from `z <= 3 m` through `z = 200 m`;
intermediate heights and terrain categories use linear interpolation. Intermediate categories
such as TC1.5 and TC3.5 are derived between adjacent standard table columns rather than stored as
separate table columns. The Region A0 rule uses TC2 for `z <= 100 m` and `Mz,cat = 1.24` above
100 m to 200 m.

The Clause 4.2.3 mixed-terrain weighted-average workflow is not automated. A mixed directional
fetch still requires an engineer-reviewed category/value rather than an inferred final design
multiplier.

### Output Fields

- Directional terrain profiles.
- Built-up, vegetation, and open-terrain percentages.
- Obstruction density and spacing evidence.
- Obstruction height statistics.
- Suggested terrain category range.
- Confidence and warnings.

### Review Requirements

The engineer must confirm terrain category independently using project-specific site knowledge,
survey information, aerial review, and the applicable standard.

## Obstruction Inventory

### Input Data

Current hierarchy:

1. Reviewed footprint data.
2. Microsoft Building Footprints.
3. OpenStreetMap building footprints.

Additional inputs can include manual obstruction height overrides, DSM and DTM rasters, and
configuration for storey-height assumptions.

### Processing Method

OpenWind-AU normalises footprint records, preserves source provenance, and merges duplicate
footprints where preferred sources substantially overlap lower-priority sources. Reviewed
footprints have priority over Microsoft footprints, and Microsoft footprints have priority over OSM
fallback geometry.

Height source selection follows the current hierarchy:

1. Manual verified height.
2. DSM-DTM height where configured and usable.
3. OSM explicit height.
4. OSM levels converted with configured storey assumptions.
5. Low-confidence class assumptions.
6. Unknown.

Manual overrides can replace selected heights and mark records as manually reviewed. Confidence is
assigned from the selected height source, available warnings, and whether engineering review is
required.

Untrusted provider/import fields are bounded before they enter height selection. Explicit heights
greater than 500 m, building-level counts greater than 200, negative or non-finite values, and
level/storey-height products greater than 500 m are ignored. The footprint remains available as
geometry evidence, while the rejected height value is quarantined and an explicit review note is
retained; no extreme provider value is silently promoted into shielding evidence.

### Current Height Methods

- `manual`
- `dsm_dtm`
- `osm_height`
- `osm_levels`
- `assumption`
- `unknown`

### Output Fields

- Obstruction records with geometry, centroid, distance, bearing, classification, height, height
  source, height method, source dataset, source provenance, confidence, and warnings.
- Data quality metrics.
- Excluded object reasons.
- Duplicate overlap counts.
- Missing height counts.

### Review Requirements

The engineer must confirm obstruction coverage, height reliability, duplicate handling, and any
manual assumptions before relying on obstruction evidence.

## Shielding Evidence

### Input Data

- Subject building height.
- Obstruction inventory records.
- Obstruction footprint geometry and selected obstruction heights.
- Packaged `src/openwind_au/data/shielding_multipliers.json` Table 4.2 values.
- Optional reviewed override supplied with `OPENWIND_MS_TABLE_PATH`.

### Processing Method

OpenWind-AU generates 45-degree upwind shielding sectors for the standard wind directions. It
selects candidate obstructions by sector position and distance, then filters by selected height
against the subject building height threshold. For included obstructions, it calculates sector
counts, average shielding height, footprint breadth normal to wind, spacing evidence, and an
indicative shielding multiplier workflow.

For `h <= 25 m`, request validation requires the obstruction inventory radius to cover at least
`20h`; a shorter provider query is rejected rather than presented as a complete shielding sector.

Vegetation is excluded because Clause 4.3 does not permit trees or vegetation to provide
shielding. For structures higher than 25 m, `Ms` is fixed at 1.0. Where ground levels are
available, an upwind building on an average ground gradient greater than 0.2 is rejected unless
its overall height above the common datum exceeds the subject building, as shown by Clause 4.3.1
and Figure 4.2. Candidates retained through that steep-slope exception are explicitly warned for
competent review because Clause 4.3.2 also requires careful interpretation. Missing ground levels
are reported for review.

Indicative `Ms` values are not certified design values.

### Output Fields

- Sector polygons.
- Included and rejected obstruction IDs.
- Rejection reason counts.
- Average `hs`, average `bs`, `ls`, shielding parameter, and indicative `Ms`.
- Confidence and warnings.

### Review Requirements

The engineer must confirm whether shielding applies, whether obstruction heights and breadths are
valid, and whether the sector assumptions match the standard and project conditions.

## Vegetation Obstruction Roadmap

OpenWind-AU does not currently calculate vegetation shielding.

The planned source hierarchy is documented in `docs/vegetation-obstruction-sources.md`:

- Tier 1: DSM-DTM height surface, excluding known building footprints.
- Tier 2: Canopy or vegetation polygons intersected with DSM-DTM height evidence.
- Tier 3: OSM context such as `natural=tree`, `natural=wood`, `landuse=forest`, and similar tags.
- Tier 4: Coarse global tree-cover datasets as context only.

Vegetation and canopy datasets alone are not enough for shielding calculation because `Ms`
depends on obstruction height, breadth, spacing, distance, and confidence.

## Topographic Assessment

### Input Data

- DEM terrain profiles around the site.
- Site elevation and directional profile samples.
- Common reference height and analysis radius. `average_roof_height_m` is used when supplied;
  otherwise `building_height_m` is the explicit fallback.

### Processing Method

OpenWind-AU extracts terrain profiles, screens each direction for candidate ridge, hill,
escarpment, valley, or no significant feature behaviour, and reports evidence such as site RL,
crest RL, base RL, `H`, `Lu`, `x`, average upwind slope, confidence, and notes.

Ridge and valley candidates must exceed the minimum relief threshold and also show either
substantial relief or meaningful average upwind slope. This suppresses broad low-gradient public
DEM undulations on flat validation sites while preserving stronger topographic evidence for
engineering review.

The site wind workflow calculates a preliminary directional hill-shape multiplier using
AS/NZS 1170.2:2021 Clause 4.4. It uses the DEM-derived `H`, `Lu`, and `x`, together with the
common reference height `z` / average roof height `h`. The workflow uses
`average_roof_height_m` when supplied and falls back to `building_height_m`. The implementation
applies:

- the `H < 10 m` and `H/(2Lu) < 0.05` exclusions;
- Equation 4.4(3) in the local topographic zone;
- Equation 4.4(4) in the steep-slope rectangular peak zone;
- the different downwind length scale for escarpments;
- the Region A0 adjustment in Equation 4.4(2); and
- the elevation factor in Equation 4.4(1) for Region A4 sites above 500 m.

No Australian lee zones are identified by the Standard, so `Mlee = 1.0` in the Australian
workflow. OpenWind-AU calculates `Mt`, but does not certify it: public DEM resolution and automatic
feature geometry remain inputs requiring engineering review.

If the sampled profile does not extend far enough upwind to resolve the half-height point that
defines `Lu`, OpenWind-AU leaves directional `Mt` unavailable and blocks the corresponding
`Vsit,b` calculation until the profile geometry or an engineer-reviewed override is supplied.

Automatic selection of the most adverse cross-section within the Clause 4.4.2 directional range,
including the corresponding escarpment interpretation, is not implemented. Those cases require
reviewed geometry and independent calculation before the result can be treated as complete.

### Review Requirements

The engineer must confirm topographic feature selection, terrain data adequacy, `H`, `Lu`, `x`,
the building reference height, and the resulting topographic multiplier.

## Site Wind Workflow

The intended evidence chain is:

Wind Region -> VR -> Mc -> Md -> Terrain Evidence -> Shielding Evidence -> Topographic Evidence ->
Engineer Review -> Final design calculations

OpenWind-AU organises the workflow through cardinal `Vsit,b` and building-orthogonal ultimate
`Vdes,theta` as review support. The stored front orientation uses the Figure 2.2 engineering
azimuth convention (clockwise from true North over `0 <= beta < 360`). Right, Back, and Left are
offset by 90, 180, and 270 degrees. For each face, the Clause 2.3 calculation linearly interpolates
`Vsit,b` between the eight 45-degree direction points, takes the maximum over the closed sector
from `beta - 45` to `beta + 45`, and enforces the 30 m/s ultimate minimum. It does not produce
certified design wind pressures.

The Clause 2.2 product used by the workflow is:

`Vsit,b = VR x Mc x Md x Mz,cat x Ms x Mt`

## Data Provenance

| Output | Primary Dataset | Fallback Dataset | Review Status |
| --- | --- | --- | --- |
| Wind Region | Geoscience Australia AS1170 wind region polygons | Configured test fixture or alternate user-supplied GIS dataset | Requires engineer confirmation, especially near boundaries |
| VR | Packaged `regional_wind_speeds.json` for AS/NZS 1170.2:2021 Table 3.1(A) | `OPENWIND_VR_TABLE_PATH` override JSON | Exact structure, independently pinned canonical `tables` digest, coverage, and named reviewer/date metadata are checked; packaged named sign-off is pending |
| Mc | Deterministic AS/NZS 1170.2:2021 Clause 3.4/Table 3.3 mapping | No override table; generic Region B is rejected | Wind-region subclassification requires engineer confirmation |
| Md | Packaged `direction_multipliers.json` for AS/NZS 1170.2:2021 Table 3.2(A) | `OPENWIND_MD_TABLE_PATH` override JSON | Exact structure, independently pinned canonical `tables` digest, region coverage, and named reviewer/date metadata are checked; packaged named sign-off is pending |
| Mz,cat | Packaged `terrain_height_multipliers.json` for Table 4.1 and A0 rules | `OPENWIND_MZCAT_TABLE_PATH` override JSON | Exact structure, independently pinned values digest, and named reviewer/date metadata are checked; packaged named sign-off is pending |
| Ms | Packaged `shielding_multipliers.json` for Table 4.2 and the 25 m rule | `OPENWIND_MS_TABLE_PATH` override JSON | Exact normative points, independently pinned values digest, and named reviewer/date metadata are checked; packaged named sign-off is pending |
| Obstruction Inventory | Reviewed footprint data, then Microsoft Building Footprints | OpenStreetMap building footprints | Review required for coverage, duplicates, and height sources |
| Shielding Evidence | Obstruction inventory records with selected heights and footprints | None for certified design; incomplete data produces warnings | Indicative only, not certified `Ms` |
| Terrain Evidence | DEM terrain profiles and obstruction evidence | Public DEM and public footprint fallbacks where configured | Evidence only, final terrain category not assigned |
| Topographic Evidence | DEM terrain profiles and Clause 4.4 equations | None for certified design; project survey should be reviewed | Preliminary `Mt` calculated; geometry and result require review |

## Important Limitations

- OpenWind-AU is not a design tool.
- OpenWind-AU is not a certification tool.
- It does not assign final terrain category.
- It does not assign certified `Ms`.
- It does not certify calculated `Mt` without competent engineering review.
- It does not produce final design pressures.
- It requires competent engineering review.
