# Engineering Reviewer Checklist

Use this checklist before relying on OpenWind-AU outputs.

## Site Inputs

- Confirm site coordinates or geocoded address.
- Confirm subject building height.
- Confirm analysis radius and sample interval suit the review purpose.

## Terrain And Topography

- Confirm terrain profiles align with the site context.
- Confirm topographic effects independently.
- Review any ridge, hill, escarpment, or valley screening flags.

## Obstructions And Shielding

- Confirm obstruction heights.
- Review height source, confidence, and review-required flags.
- Confirm shielding applicability.
- Check whether missing or estimated heights affect shielding conclusions.

## Terrain Category

- Confirm terrain category independently.
- Review built-up, vegetation, and open-terrain evidence by direction.
- Treat suggested category ranges as review prompts only.

## Independent Code Work

- Confirm AS/NZS calculations independently.
- Confirm the packaged `VR`, `Md`, `Mz,cat`, and `Ms` lookup tables remain tested against
  independently defined AS/NZS 1170.2:2021 expected values and that their review metadata and
  digests are current.
- Confirm topographic multipliers independently.
- Confirm terrain category and shielding multipliers independently.
- Treat vegetation and non-building shielding as planned context only; it is not a certified `Ms`
  source in OpenWind-AU.
- Prefer DSM-DTM evidence for any future vegetation obstruction height review.
- Confirm design wind pressures independently.

OpenWind-AU is an early-stage engineering support tool. It does not produce certified design
values.
