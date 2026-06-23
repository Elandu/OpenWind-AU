# Calculation Basis and Data Lineage

OpenWind-AU is an engineering review aid. Outputs are evidence and workflow support tools.
Final design decisions remain the responsibility of the engineer.

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

Dataset metadata is reported with the assessment, including dataset name, polygon count,
available region labels, configured path, and whether the active dataset is a test fixture.

### Output Fields

- Wind region label: `A0`, `A1`, `A2`, `A3`, `A4`, `A5`, `B1`, `B2`, `C`, or `D`.
- Region subclassification where available.
- Dataset name and path.
- Polygon count and available region names.
- Distance to boundary.
- Boundary warning flag.
- Confidence.
- Warnings.

### Review Requirements

The engineer must confirm the wind region against the project standard and source GIS dataset.
Sites close to region boundaries need particular review because small changes in coordinates,
dataset interpretation, or boundary geometry can change the selected region.

## Regional Wind Speed (VR)

### Input Data

- Packaged AS/NZS 1170.2:2021 Table 3.1(A) lookup data.
- Source file: `src/openwind_au/data/regional_wind_speeds.json`.
- Assessed wind region.
- Annual recurrence interval parsed from the selected annual exceedance probability.
- Optional override table supplied with `OPENWIND_VR_TABLE_PATH`.

### Processing Method

OpenWind-AU maps subregions to their base table where required, then selects `VR,ult` from the
ultimate table for the requested ARI. If the ARI is tabulated, the exact value is returned. If the
ARI sits between two available table rows, OpenWind-AU uses logarithmic interpolation between
those tabulated ARIs. Values outside the supported table range return a warning and require manual
input.

The serviceability value currently reported by the app is the 25-year serviceability row where
available. Lookup metadata is checked so packaged or override JSON must include
`source.review_status == "verified_against_standard"` to avoid a warning.

### Output Fields

- `VR,ult`.
- `VR,serv`.
- Selected source table reference.
- Lookup values used in the calculation.
- Interpolation note where applicable.
- Warnings.

### Review Requirements

The engineer must confirm the ARI, importance level, table applicability, and any interpolation or
override source before using the value in design decisions.

## Direction Multiplier (Md)

### Input Data

- Packaged AS/NZS 1170.2:2021 Table 3.2(A) lookup data.
- Source file: `src/openwind_au/data/direction_multipliers.json`.
- Assessed wind region.
- Optional override table supplied with `OPENWIND_MD_TABLE_PATH`.

### Processing Method

OpenWind-AU selects the region-specific direction multiplier row and returns values for N, NE, E,
SE, S, SW, W, and NW. It identifies the highest value in the row and marks all matching directions
as governing directions. Lookup metadata is checked so packaged or override JSON must include
`source.review_status == "verified_against_standard"` to avoid a warning.

### Output Fields

- Md values by direction.
- Highest Md.
- Governing direction list.
- Selected source table reference.
- Lookup values.
- Warnings.

### Review Requirements

The engineer must confirm direction multiplier applicability for the structure and project case,
including any cases where the standard requires a different value or all directions are taken as
1.0.

## Terrain Evidence

### Input Data

- Public DEM sampling from SRTM through the configured DEM workflow.
- Site location, building height, radius, and sample interval.
- Obstruction inventory evidence for built-up and vegetation coverage.

### Processing Method

OpenWind-AU generates radial terrain profiles for the standard eight directions. It samples DEM
elevations along each profile, calculates slope evidence, and combines terrain-profile context with
directional obstruction evidence. Built-up density, vegetation evidence, open-terrain percentage,
obstruction density, height coverage, and confidence scoring are reported by direction.

OpenWind-AU does not assign final terrain categories. It provides evidence only.

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

### Processing Method

OpenWind-AU generates 45-degree upwind shielding sectors for the standard wind directions. It
selects candidate obstructions by sector position and distance, then filters by selected height
against the subject building height threshold. For included obstructions, it calculates sector
counts, average shielding height, footprint breadth normal to wind, spacing evidence, and an
indicative shielding multiplier workflow.

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
- Building height and analysis radius.

### Processing Method

OpenWind-AU extracts terrain profiles, screens each direction for candidate ridge, hill,
escarpment, valley, or no significant feature behaviour, and reports evidence such as site RL,
crest RL, base RL, `H`, `Lu`, `x`, average upwind slope, confidence, and notes.

OpenWind-AU does not currently produce certified `Mt` values.

### Review Requirements

The engineer must confirm topographic feature selection, terrain data adequacy, and any final
topographic multiplier independently.

## Site Wind Workflow

The intended evidence chain is:

Wind Region -> VR -> Md -> Terrain Evidence -> Shielding Evidence -> Topographic Evidence ->
Engineer Review -> Final design calculations

OpenWind-AU organises the workflow through `Vsit,b` as review support. It does not currently
produce certified design wind pressures.

## Data Provenance

| Output | Primary Dataset | Fallback Dataset | Review Status |
| --- | --- | --- | --- |
| Wind Region | Geoscience Australia AS1170 wind region polygons | Configured test fixture or alternate user-supplied GIS dataset | Requires engineer confirmation, especially near boundaries |
| VR | Packaged `regional_wind_speeds.json` for AS/NZS 1170.2:2021 Table 3.1(A) | `OPENWIND_VR_TABLE_PATH` override JSON | Packaged table has verified metadata; overrides warn if not verified |
| Md | Packaged `direction_multipliers.json` for AS/NZS 1170.2:2021 Table 3.2(A) | `OPENWIND_MD_TABLE_PATH` override JSON | Packaged table has verified metadata; overrides warn if not verified |
| Obstruction Inventory | Reviewed footprint data, then Microsoft Building Footprints | OpenStreetMap building footprints | Review required for coverage, duplicates, and height sources |
| Shielding Evidence | Obstruction inventory records with selected heights and footprints | None for certified design; incomplete data produces warnings | Indicative only, not certified `Ms` |
| Terrain Evidence | DEM terrain profiles and obstruction evidence | Public DEM and public footprint fallbacks where configured | Evidence only, final terrain category not assigned |
| Topographic Evidence | DEM terrain profiles | None for certified design; project survey should be reviewed | Screening only, certified `Mt` not assigned |

## Important Limitations

- OpenWind-AU is not a design tool.
- OpenWind-AU is not a certification tool.
- It does not assign final terrain category.
- It does not assign certified `Ms`.
- It does not assign certified `Mt`.
- It does not produce final design pressures.
- It requires competent engineering review.
