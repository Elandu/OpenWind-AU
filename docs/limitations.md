# Limitations And Engineering Review

OpenWind-AU is an early-stage, preliminary terrain analysis tool.

It does not:

- calculate AS/NZS 1170.2 topographic multipliers;
- calculate terrain category;
- calculate shielding;
- calculate design wind pressures;
- produce AS 4055 wind classifications;
- certify compliance for any project.

## Data Limitations

The current workflow uses public DEM data. Public DEMs may not reflect:

- local survey levels;
- retaining walls;
- batters and earthworks;
- vegetation;
- recent development;
- small ridges, cuttings, or drainage channels;
- local obstructions.

## Review Expectations

Outputs should be treated as screening information only. A competent engineer should review:

- input coordinates or geocoded address;
- DEM suitability and resolution;
- terrain profile directions and radius;
- candidate topographic screening results;
- project-specific survey, imagery, and site context.

Validation examples are broad regression checks. They do not prove accuracy for a specific site.
