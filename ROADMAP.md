# Roadmap

OpenWind-AU is early-stage engineering support software. This roadmap separates implemented
review aids from experimental workflows and features that are not implemented or certified.

For output derivation, dataset hierarchy, and review boundaries, see
[`docs/calculation-basis.md`](docs/calculation-basis.md).
For the consumer-readiness gap list, see
[`docs/consumer-readiness.md`](docs/consumer-readiness.md).

## Implemented As Review Aid

- Address and coordinate input.
- Nominatim geocoding.
- Public DEM querying using SRTM.
- 8-direction terrain profile generation for N, NE, E, SE, S, SW, W, and NW.
- Configurable analysis radii of 500 m, 1000 m, 2000 m, and 4000 m.
- Conservative topographic screening for ridge, hill, escarpment, valley, or no significant
  feature in each profile direction.
- Site RL, crest RL, base RL, H, Lu, x, average upwind slope, confidence, and review-note
  outputs for engineer review.
- Interactive map display.
- Interactive terrain profile plots.
- Obstruction inventory using Microsoft building footprints where locally cached, with OSM as a
  fallback source.
- Preliminary shielding-sector evidence from reviewed obstruction geometry and heights.
- Directional terrain category evidence, including built-up, vegetation, open-terrain,
  obstruction density, height, confidence, and suggested range evidence.
- Packaged AS/NZS 1170.2:2021 regional wind speed `VR` and direction multiplier `Md` lookup
  tables for review workflow support.
- JSON export.
- HTML report.
- PDF report.
- Qualitative validation runner with representative Australian terrain examples.
- JSON and HTML validation reports.
- Unit tests and GitHub Actions CI.

## Experimental

- Interactive AS/NZS 1170.2 site wind workflow through `Vsit,b` for engineering review.
- Editable review workflow variables and override capture.
- Indicative `Mz,cat` range suggestions from directional terrain evidence.
- Indicative `Ms` calculations from obstruction sectors where reviewed height and footprint data
  are available.
- DSM-DTM obstruction height enrichment when project-supplied rasters are configured.
- Vegetation and non-building obstruction provenance placeholders.
- Combined workflow map overlays for wind regions, terrain evidence, shielding sectors, and
  obstruction footprints.
- MCP tools for traceable `VR`, `Md`, `Mz,cat`, `Ms`, `Mt`, and `Vsit,b` calculations over stdio
  or Streamable HTTP.

## Not Implemented Or Certified

These items should not be described as certified OpenWind-AU outputs:

- Final AS/NZS 1170.2 terrain category assignment.
- Certified shielding multiplier `Ms`.
- Certified topographic multiplier `Mt`.
- Certified site wind speed or pressure design.
- Calculated vegetation/canopy shielding from non-building obstruction sources.
- AS 4055 wind classification support.
- LiDAR acquisition or production-grade LiDAR integration.

## Near-Term Improvements

- Build standard-derived lookup assets for `Mz,cat`, `Ms`, `Mt`, AS 4055 classes, and other
  release-critical wind model coefficients from reviewed source tables.
- Add a reviewer sign-off and regression workflow for derived lookup assets without committing
  licensed standard text.
- Expand reference calculation comparisons beyond job 7989 across regions, heights, terrain
  categories, shielding states, and topographic classes.
- Better DEM cache management.
- Clearer confidence scoring for preliminary topographic screening.
- Profile filtering and directional sector summaries.
- More robust feature grouping across adjacent radials.
- Better report layout with embedded maps and plots.
- More tests with synthetic terrain fixtures.
- More documented validation examples against known public terrain cases.
- Contributor workflow for reviewing proposed validation examples.

## Future Data Sources

- Copernicus DEM.
- Australian LiDAR where publicly available.
- State and territory elevation services.
- DSM-DTM sources for non-building obstruction height and canopy-mass screening.
- State, local, or project canopy datasets for context alongside DSM-DTM height evidence.
- Survey data import for project-specific review.
