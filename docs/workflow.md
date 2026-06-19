# OpenWind-AU Workflow

OpenWind-AU is an engineering support workflow. It helps gather terrain, obstruction, shielding,
and terrain category evidence for review. It does not produce certified design values.

## 1. Address Input

Enter either:

- an Australian street address; or
- latitude and longitude coordinates.

Review the resolved location before relying on any output. Geocoding can place a point at a parcel,
street segment, suburb, or other public-map reference.

## 2. Terrain Profiles

OpenWind-AU samples 8-direction terrain profiles for:

- N, NE, E, SE, S, SW, W, and NW.

Profiles use public elevation data and the selected analysis radius. Review profile endpoints,
sample spacing, and ground elevations before using the profile as evidence.

## 3. Topographic Screening

The topographic screening table flags broad candidate terrain forms such as ridge, hill,
escarpment, valley, or no significant feature. These are rule-based indicators only.

Use the output to decide where engineering review should focus. Do not treat it as a final
topographic multiplier calculation.

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
