# Roadmap

OpenWind-AU is early-stage. This roadmap separates MVP terrain analysis from future wind-code workflows.

## MVP

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
- JSON export.
- HTML report.
- PDF report.
- Unit tests and GitHub Actions CI.

## Near-Term Improvements

- Better DEM cache management.
- Clearer confidence scoring for preliminary topographic screening.
- Profile filtering and directional sector summaries.
- More robust feature grouping across adjacent radials.
- Better report layout with embedded maps and plots.
- More tests with synthetic terrain fixtures.
- Documented validation examples against known terrain cases.

## Roadmap Only

These are not MVP features and should not be described as implemented until they exist:

- Terrain category assessment.
- Shielding assessment.
- Topographic multiplier calculations.
- AS 4055 wind classification support.
- LiDAR integration.
- MCP server integration.

## Future Data Sources

- Copernicus DEM.
- Australian LiDAR where publicly available.
- State and territory elevation services.
- Survey data import for project-specific review.
