# Limitations And Engineering Review

OpenWind-AU is an early-stage, preliminary terrain analysis tool.

It does not:

- calculate AS/NZS 1170.2 topographic multipliers;
- assign a final terrain category;
- calculate final `Mz,cat` design values;
- calculate certified shielding multipliers;
- calculate design wind pressures;
- produce AS 4055 wind classifications;
- certify compliance for any project.

## Data Limitations

The current workflow uses public SRTM DEM data and public building footprint sources. SRTM is a
coarse public terrain source, not the Google Elevation API, project lidar, or site survey. Public
DEMs and building datasets may not reflect:

- local survey levels;
- retaining walls;
- batters and earthworks;
- vegetation;
- recent development;
- small ridges, cuttings, or drainage channels;
- local obstructions.
- recently constructed, demolished, or altered buildings.

DSM-DTM obstruction height enrichment depends on the quality, currency, resolution, alignment, and
vertical datum consistency of the supplied DSM and DTM datasets. Assumption-based obstruction
heights are low-confidence screening values only and are not inferred from footprint area.

Microsoft Australia Building Footprints is the preferred building geometry source when a local
cache is configured, but it should still be reviewed against current imagery, site survey, and
project knowledge. OSM/Overpass remains a fallback and attribute source; it should not be treated
as complete footprint coverage.

## Review Expectations

Outputs should be treated as screening information only. A competent engineer should review:

- input coordinates or geocoded address;
- DEM suitability and resolution;
- terrain profile directions and radius;
- candidate topographic screening results;
- preliminary shielding sectors and any obstruction heights used for indicative `Ms`;
- terrain category evidence ranges, scoring components, and confidence warnings;
- height-source summaries, confidence flags, and review-required obstruction records;
- DSM-DTM warnings such as missing datasets, negative estimates, extreme estimates, or low
  confidence estimates;
- project-specific survey, imagery, and site context.

Validation examples are broad regression checks. They do not prove accuracy for a specific site.
