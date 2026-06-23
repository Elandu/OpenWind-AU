# Vegetation Obstruction Sources

OpenWind-AU does not yet calculate shielding from vegetation or other non-building obstruction
sources. This note records the preferred source hierarchy for a future, reviewable pipeline.

## Recommended Source Hierarchy

### Tier 1: DSM-DTM Height Surface

Use a DSM-DTM height surface as the primary source for elevated non-building obstruction masses.
Known building footprints should be excluded first so the remaining height signal can be reviewed
as possible vegetation, canopy, mounds, plant, signs, screens, or other non-building obstructions.

This is the preferred future pathway because shielding depends on physical obstruction height as
well as plan position and breadth.

### Tier 2: Canopy Or Vegetation Polygons With Height Evidence

Use state, local, project, or council canopy and vegetation polygons when they can be intersected
with DSM-DTM height estimates. Polygon labels alone should be treated as classification context,
not as calculated shielding input.

### Tier 3: OSM Context

Use OpenStreetMap tags such as `natural=tree`, `natural=wood`, `landuse=forest`, `leisure=park`,
orchard, scrub, and similar features as low-confidence context. OSM can help flag where review is
needed, but it is not a reliable height or breadth source by itself.

### Tier 4: Coarse Global Tree-Cover Context

Use coarse global tree-cover datasets as context only. They should not be used for calculated `Ms`
because they generally do not provide project-scale obstruction geometry, spacing, or reliable
height data.

## Why Vegetation Polygons Alone Are Not Enough

Vegetation and canopy datasets can indicate possible obstruction locations, but shielding
calculation depends on obstruction height, breadth normal to wind, spacing, distance from the
subject building, and confidence in the source data. A future vegetation shielding workflow should
therefore combine geometry classification with DSM-DTM height evidence and explicit review flags.
