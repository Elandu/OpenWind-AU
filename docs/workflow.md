# OpenWind-AU Workflow

OpenWind-AU is an engineering support workflow. It helps gather terrain, obstruction, shielding,
and terrain category evidence for review. It does not produce certified design values.

## 1. Address Input

Enter either:

- an Australian street address; or
- latitude and longitude coordinates.

Review the resolved location before relying on any output. Geocoding can place a point at a parcel,
street segment, suburb, or other public-map reference.

OpenWind-AU also accepts structured building inputs for review workflows:

- structure class: `building`, `house`, `monopole`, `tower`, or `other`;
- front-face orientation as an engineering azimuth in the range `0 <= beta < 360` degrees,
  measured clockwise from North (`0`, `90`, `180`, and `270` point the front North, East, South,
  and West respectively);
- roof shape: `gable`, `hip`, or `monoslope`;
- breadth/width measured left-to-right across the front, depth/length measured front-to-back,
  roof pitch, average roof height, and base RL.

The Design building on the map uses the same coordinate, orientation, and dimension values as the
assessment request. Drag the footprint to move it, drag the orientation handle to set any
full-circle azimuth at 0.1-degree precision, or drag a corner handle to resize it. Map edits
update the visible form controls, invalidate any earlier signed result, and are saved with the
selected project number.
Projects without a project number remain session-only. Entering a new address clears the saved
coordinate override so autocomplete can resolve the replacement site.

Orientation identifies the front/right/back/left building axes and drives the Clause 2.3
building-orthogonal ultimate `Vdes,theta` calculation. For each face, the workflow linearly
interpolates between the eight cardinal/intercardinal `Vsit,b` points, takes the maximum within
the face bearing plus or minus 45 degrees, and applies the 30 m/s ultimate minimum. It does not
calculate design pressures.
For a front azimuth `beta`, the right, back, and left axes are `beta + 90`, `beta + 180`, and
`beta + 270` degrees, normalized back into the same full-circle range.

Both building dimensions are optional, but when one is entered the other is required. Average roof
height must not exceed overall building height. The browser validates these relationships and the
published numeric bounds before sending the request; server validation remains authoritative and
returns the affected field when a request is rejected.

The deprecated `building_dimensions` field is retained as legacy free-text request metadata only.
It does not define the editable footprint or drive calculations. Use it only when the structured
`building_width_m` and `building_length_m` fields are absent; requests that combine the legacy and
structured representations are rejected.

`annual_exceedance_probability` is the AEP/ARI input that selects the regional wind speed.
`importance_level` and `design_life_years` are optional report metadata only; they do not derive,
select, or alter the AEP/ARI.

## 2. Terrain Profiles

OpenWind-AU samples 8-direction terrain profiles for:

- N, NE, E, SE, S, SW, W, and NW.

Profiles use the configured public DEM provider and the selected analysis radius. The default
provider is cached SRTM data from AWS terrain tiles. Open-Meteo point elevations can be enabled for
source comparison. Review profile endpoints, sample spacing, and ground elevations before using the
profile as evidence. Public DEMs are useful for broad preliminary screening, but they are not a
substitute for local survey, lidar, or project-specific terrain review where local relief,
retaining walls, cuts, fills, or drainage features matter.

## 3. Topographic Screening

The topographic screening table flags broad candidate terrain forms such as ridge, hill,
escarpment, valley, or no significant feature. These are rule-based indicators derived from the
directional DEM profiles.
Broad low-gradient DEM undulations are screened out unless they show substantial relief or a
meaningful average upwind slope.

The site wind workflow uses the candidate geometry to calculate preliminary directional `Mt`
values with the Clause 4.4 equations. Expand the calculation provenance to review `H`, `Lu`, `x`,
`z`, `L1`, `L2`, `Mh`, and the regional adjustment. Do not treat the result as certified until the
feature geometry and DEM suitability have been reviewed.
If the upwind half-height point defining `Lu` is outside or unresolved by the sampled profile, the
workflow leaves `Mt` unavailable instead of assuming `1.0`; extend/review the terrain profile or
provide a reasoned engineer override.

## 4. Obstruction Inventory

The obstruction inventory uses Microsoft Australia Building Footprints as the preferred building
geometry source when a local cache is configured. OSM/Overpass is used as fallback and as a source
of useful height, levels, and building-type attributes where matching footprints overlap. The
inventory records footprint class, distance, bearing, height source, confidence, and review status.

If Microsoft cache data and OSM fallback data are unavailable, OpenWind-AU reports warnings and
leaves the obstruction inventory empty rather than fabricating shielding evidence.

## 5. Height Confidence

Obstruction heights can come from:

1. manual verified heights;
2. DSM-DTM estimates;
3. OSM explicit height tags;
4. OSM building levels;
5. low-confidence class assumptions;
6. unknown sources.

Review the height source and confidence badges. Low-confidence and unknown heights should be
checked before relying on shielding or terrain category evidence.

## 6. Shielding Sector Review

Preliminary shielding sectors are generated for the 8 wind directions when a subject building
height is provided. The output reports obstruction counts, height-confidence counts, estimated or
unknown heights, warnings, and indicative shielding evidence.

This is not a certified shielding multiplier calculation. Confirm shielding applicability
independently.

## 7. Terrain Category Evidence

The terrain category evidence engine summarises directional built-up coverage, vegetation
coverage, open terrain, obstruction height statistics, density, spacing, fetch, shielding
confidence, evidence scores, and suggested category ranges.

Suggested ranges are prompts for review only. The aggregate terrain-evidence engine does not assign
a final terrain category by itself; it provides indicative Mz,cat ranges as supporting evidence.
The explicit single-category and Clause 4.2.3 paths described below do calculate the directional
`Mz,cat` values used by the workflow.

## 8. Clause 4.2.3 Mixed-Terrain Calculation

When reviewed survey, mapping, or other source material identifies terrain transition distances,
add an ordered profile for each affected wind direction. Distances are measured upwind from the
site. Every segment needs its own source reference. For non-A0 weighting, the segments must
continuously cover the complete Clause 4.2.3 averaging window: from `xi = 20z` to `xi + xa`, where
`xa = max(500 m, 40z)`.

For non-A0 wind-workflow requests, average roof height supplies `z` only when `h <= 25 m`. Missing
average roof height, heights above 25 m, gapped or overlapping segments, and incomplete coverage
are blocked. Region A0 instead retains the mandatory terrain-independent Table 4.1 value at the
workflow reference height (`average_roof_height_m`, falling back to `building_height_m`). Supplied
A0 profiles may be incomplete and are retained as unweighted evidence only; their supplied
segments must still be ordered, contiguous, and source-referenced. Aggregate sector percentages
are useful classification evidence, but they do not establish transition locations and are not
used to fabricate a profile.

For non-A0 profiles, the calculated result records the averaging geometry, the clipped length and
weight of every segment, its Table 4.1 value, weighted contribution, source reference, and final
directional weighted `Mz,cat`. For A0, it records the mandatory terrain-independent value and keeps
any supplied segment data as unweighted evidence. Non-A0 directions without supplied profiles
continue to use one reviewed or recommended category and are identified in the warnings.

## 9. Engineer Review

Before using any output in project work, a competent engineer should confirm:

- site coordinates and building height;
- public data suitability;
- obstruction heights and shielding relevance;
- topographic effects;
- terrain category;
- supplied Clause 4.2.3 transition distances, categories, coverage, and source references;
- all code calculations independently.

The wind workflow API also accepts reviewed directional class inputs via
`class_multiplier_overrides`. These are useful when a prior calculation, such as a reference
calculation, gives the controlling classes rather than raw public-data evidence. Each entry must
have a unique direction, a reason, and at least one reviewed class, and can include:

- `direction`;
- `terrain_category` such as `TC3`;
- `shielding_class` such as `FS`, `PS`, or `NS`;
- `topographic_class` such as `T0` or `T1`;
- optional exact `mzcat`, `ms`, or `mt` values;
- `reason` and `source_reference`.

An exact `mzcat`, `ms`, or `mt` value is valid only when the corresponding terrain, shielding, or
topographic class is present. Terrain categories map to the reviewed Table 4.1 values. Shielding
and topographic classes are project/reference provenance rather than AS/NZS 1170.2 lookup keys, so
a class alone does not invent an `Ms` or `Mt`; provide the reviewed numeric value when it should
replace the Clause 4.3 or 4.4 calculation. Only one class override entry is accepted per direction.

Direct reviewed variable values use `workflow_overrides`. `VR` is non-directional and
must omit `direction`; `Md`, `Mzcat`, `Ms`, `Mt`, and `Vsitb` require a direction. Duplicate
variable/direction pairs are rejected. `Mc` is deterministic and cannot be overridden. Each entry requires `variable`, `override_value`, and
`reason`, with an optional display `label`.

The visible `wind_direction_multiplier_case` input distinguishes main-structure calculations from
cladding/immediate-support and circular/polygonal chimney, tank or pole cases. The workflow
enforces the mandatory Clause 3.3 `Md = 1.0` cases, selects one non-directional `Mc` from Clause
3.4/Table 3.3, calculates `Vsit,b = VR x Mc x Md x Mz,cat x Ms x Mt`, and then derives the four
Clause 2.3 ultimate `Vdes,theta` rows when a front orientation is supplied.

`average_roof_height_m` is the common AS/NZS reference height used for `Mz,cat`,
shielding-height checks, and `Mt`. It defaults to `building_height_m` when omitted.
That fallback is a continuity assumption, is not uniformly conservative across all multipliers,
and requires confirmation of the actual average roof height.
The legacy request alias `average_height_m` is accepted only for migration; normalized
workflow inputs use `average_roof_height_m`.

Mandatory standard values remain fail-closed. Region A0 uses the mandatory Table 4.1 A0 rule,
independent of the selected terrain-category class but still dependent on reference height, even
when a terrain class is recorded for provenance; numeric Mz,cat overrides are rejected. When
average roof height h exceeds 25 m, Clause 4.3.1 requires Ms = 1.0 and numeric Ms overrides are
rejected. Calculated values remain separate from reviewed override values in the result audit
trail.

The wind workflow request rejects unknown fields. Legacy fields that previously appeared to
override a result but were ignored (`wind_region`, `regional_wind_speed_mps`,
`wind_direction_multipliers`, and `workflow_reviews`) are no longer accepted.
