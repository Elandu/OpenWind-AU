# Consumer Readiness

OpenWind-AU is not consumer-ready as a certified wind-design product yet. The current project is a
useful engineering review aid, with reproducible validation checks and a clear audit trail, but it
still needs authoritative data packaging, certified multiplier workflows, and broader project
validation before non-expert users should rely on the output.

## Current Position

- `VR` has packaged AS/NZS 1170.2:2021 lookup data with review metadata.
- The packaged `Md` data has reviewed rows for the Australian 2021 production regions `A0-A5`,
  `B1`, `B2`, `C`, and `D`. Readiness checks the labels actually exposed by the configured GIS
  dataset, so a custom generic or unknown region remains blocked unless it has a reviewed row.
- `Mz,cat`, `Ms`, and `Mt` are still review workflows, not certified design outputs.
- Reference calculation 7989 can be reproduced through `/api/reference-validation/7989`.
- Applying reviewed class overrides for reference calculation 7989 matches all directional
  `Mz,cat`, `Ms`, and `Mt` comparison points, which confirms the workflow can carry reviewed
  classes through the calculation.
- The default public-data run still differs from the reference classes, which means the automated
  evidence-to-class logic is not ready to stand alone.

## Licensed Standards Verification

Verification against licensed standards must happen in an access-controlled standards library
outside the repository. Do not publish workstation paths, licensed standard PDFs, copied clauses,
or bulk table excerpts. Derived lookup data should record the source standard, clause/table
reference, reviewer, review date, and test coverage without exposing the licensed source material.

## Rebuildable Data Sources

The production data bundle should be rebuilt from public or licensed sources rather than from any
third-party binary format.

| Need | Current / Candidate Source | Consumer-Ready Requirement |
| --- | --- | --- |
| Terrain DEM | Geoscience Australia 1-second SRTM-derived DEM, NASA SRTM, or configured DEM rasters | Local cache with versioned metadata, datum notes, and fallback behaviour |
| Wind lookup data | AS/NZS 1170.2:2021 and AS 4055:2021 verified tables | Structured JSON/SQLite tables with reviewer sign-off and deterministic tests |
| Point elevation | Configured DEM first; Open-Meteo opt-in fallback/comparison provider | Source provenance in every report and clear warnings for external API data |
| Map context | OSM, MapTiler/Stadia, ESRI imagery, or project-configured tiles | Attribution, key management, and offline/error behaviour |
| Address search | Photon autocomplete plus deliberate Nominatim single-address resolution | Self-hosted or contracted provider capacity, caching, attribution, and outage handling |
| Building footprints | Microsoft Building Footprints, reviewed project data, OSM/Overpass fallback | Coverage diagnostics, attribution, cache controls, and manual review workflow |

## Must-Fix Before Consumer Release

1. Create authoritative lookup assets for `Mz,cat`, `Ms`, `Mt`, AS 4055 classes, pressure
   coefficients, and any height/terrain interpolation rules that are intended to be automated.
2. Add a standard-table verification workflow that checks every derived lookup table against a
   reviewer-approved source snapshot without exposing licensed source text.
3. Expand reference validation beyond job 7989 to cover multiple regions, terrain categories,
   shielding states, heights, and topographic classes.
4. Promote `Mz,cat`, `Ms`, and `Mt` from indicative to reviewed/certified only after the lookup
   tables, class selection logic, and edge cases have independent engineering sign-off.
5. Add consumer-facing guardrails: project setup wizard, explicit standard/version selection,
   required engineer review states, report watermarking, and blocked export when critical inputs
   are missing.
6. Replace live-network assumptions with cache-first data services and visible data-source health
   checks.
7. Add licensing and attribution checks for all bundled and live data sources.

## Release Gate

A consumer-ready release should not be tagged until:

- `GET /health` returns HTTP 200 with `status: "ready"` under the production configuration;
- full test suite and lint pass;
- reference validations pass for a representative project set;
- all bundled lookup assets have source metadata and reviewer approval;
- reports clearly identify which values are automated, reviewed, overridden, or unavailable;
- the UI prevents final design language unless the required reviewed inputs are present.
