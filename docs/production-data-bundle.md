# Production Data Bundle

A production OpenWind-AU deployment should use a versioned, reviewable data bundle rather than an
unrecorded collection of local files.

The manifest contract is defined in `data/production/manifest.schema.json`. A deliberately
unapproved example is provided in `data/production/manifest.example.json`.

## Required properties

Each bundle should identify:

- the exact wind-region GIS dataset and content digest;
- the DEM source/version and any project cache snapshot needed for reproducibility;
- building-footprint source/version where a local cache or tile index is used;
- reviewed `VR`, `Md`, `Mz,cat`, and `Ms` lookup assets and their canonical digests;
- source attribution and licence/terms for each dataset;
- actual reviewer/date metadata where an engineering review is required.

A bundle remains `draft` until those checks have genuinely been completed. The example manifest
must never be treated as an approved production bundle.

## Deployment behavior

Issue #16 tracks integration of this manifest into `openwind-au check` and result provenance. The
intended end state is:

1. the deployment selects one approved bundle;
2. readiness verifies every required asset and digest;
3. each completed assessment records the bundle identifier and calculation-affecting digests;
4. an updated dataset requires a new manifest/review rather than silently changing an existing
   assessment environment.

The manifest must contain derived metadata only. Do not distribute licensed standards text or
private project data in a production bundle.
