# Limitations And Engineering Review

OpenWind-AU is an early-stage, preliminary terrain analysis tool.

It does not:

- automate the Clause 4.2.3 weighted average across mixed-terrain fetches; the workflow evaluates
  one reviewed or recommended terrain category at the common reference height;
- interpolate Region C or D regional wind speed between a smooth coastline and the inland boundary;
  it uses the applicable tabulated-region maximum and emits a review warning;
- automate selection of the most adverse Clause 4.4.2 topographic cross-section within +/-22.5
  degrees or confirm the downwind-slope eligibility criterion for an escarpment;

- certify its preliminary Clause 4.4 `Mt` calculations without engineer review of the
  DEM-derived `H`, `Lu`, `x`, feature type, and reference height;
- assign a final terrain category;
- calculate final `Mz,cat` design values;
- calculate certified shielding multipliers;
- calculate design wind pressures;
- produce AS 4055 wind classifications;
- certify compliance for any project.

## Data Limitations

The default workflow uses public SRTM DEM data and public building footprint sources. Open-Meteo
point elevations can be enabled for comparison, but neither public source is a substitute for
project lidar or site survey. Public DEMs and building datasets may not reflect:

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
- directional Clause 4.4 calculation inputs, local topographic-zone selection, and regional
  adjustment;
- preliminary shielding sectors and any obstruction heights used for indicative `Ms`;
- terrain category evidence ranges, scoring components, and confidence warnings;
- height-source summaries, confidence flags, and review-required obstruction records;
- DSM-DTM warnings such as missing datasets, negative estimates, extreme estimates, or low
  confidence estimates;
- project-specific survey, imagery, and site context.

Validation examples are broad regression checks. They do not prove accuracy for a specific site.
