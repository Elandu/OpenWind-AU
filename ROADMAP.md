# Roadmap

OpenWind-AU is early-stage. This roadmap separates MVP terrain analysis from future wind-code workflows.

## MVP

- Address and coordinate input.
- Nominatim geocoding.
- Public DEM querying using SRTM.
- 360 degree terrain profile generation.
- Topographic feature detection for ridges, hills, escarpments, and valleys.
- Crest RL, base RL, H, Lu, x, and average upwind slope outputs.
- Interactive map display.
- Interactive terrain profile plots.
- JSON export.
- HTML report.
- PDF report.
- Unit tests and GitHub Actions CI.

## Near-Term Improvements

- Better DEM cache management.
- Clearer confidence scoring for detected features.
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
