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
- orientation from `-90` to `90` degrees;
- roof shape: `gable`, `hip`, or `monoslope`;
- width, length, roof pitch, average height, and base RL.

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

Suggested ranges are prompts for review only. OpenWind-AU does not assign a final terrain category
and does not calculate final `Mz,cat` design values. It provides indicative Mz,cat ranges as
supporting evidence for engineer review.

## 8. Engineer Review

Before using any output in project work, a competent engineer should confirm:

- site coordinates and building height;
- public data suitability;
- obstruction heights and shielding relevance;
- topographic effects;
- terrain category;
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

Direct reviewed variable values use `workflow_overrides`. `VR` is non-directional and must omit
`direction`; `Md`, `Mzcat`, `Ms`, `Mt`, and `Vsitb` require a direction. Duplicate
variable/direction pairs are rejected. Each entry requires `variable`, `override_value`, and
`reason`, with an optional display `label`.

The wind workflow request rejects unknown fields. Legacy fields that previously appeared to
override a result but were ignored—`wind_region`, `regional_wind_speed_mps`,
`wind_direction_multipliers`, and `workflow_reviews`—are no longer accepted.
