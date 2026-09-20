"""AS/NZS 1170.2:2021 Clause 4.2.3 mixed-terrain averaging."""

from __future__ import annotations

import math
from typing import Any, Literal

from openwind_au.models import (
    MixedTerrainAssessment,
    MixedTerrainProfile,
    MixedTerrainSegmentContribution,
)
from openwind_au.mzcat import indicative_mzcat, load_mzcat_table, mzcat_source_reference

CLAUSE_423_REFERENCE = "AS/NZS 1170.2:2021 Clause 4.2.3"
MINIMUM_AVERAGING_DISTANCE_M = 500.0
AVERAGING_HEIGHT_FACTOR = 40.0
LAG_HEIGHT_FACTOR = 20.0
COVERAGE_ABSOLUTE_TOLERANCE_M = 1e-6


def clause_423_distances(assessment_height_z_m: float) -> tuple[float, float]:
    """Return the lag distance xi and averaging distance xa at height z."""

    height = float(assessment_height_z_m)
    if not math.isfinite(height) or height <= 0:
        raise ValueError("Clause 4.2.3 assessment height z must be finite and greater than zero.")
    if height > 200:
        raise ValueError(
            "Clause 4.2.3 assessment height exceeds the supported 200 m Table 4.1 range."
        )
    return LAG_HEIGHT_FACTOR * height, max(
        MINIMUM_AVERAGING_DISTANCE_M,
        AVERAGING_HEIGHT_FACTOR * height,
    )


def calculate_mixed_terrain_assessment(
    *,
    profile: MixedTerrainProfile,
    assessment_height_z_m: float,
    wind_region: str,
    lookup_data: dict[str, Any] | None = None,
    reference_height_h_m: float | None = None,
    assessment_height_basis: Literal[
        "average_roof_height_h",
        "explicit_height_z",
        "a0_workflow_reference_height",
    ] = "explicit_height_z",
) -> MixedTerrainAssessment:
    """Calculate one distance-weighted Mz,cat from ordered upwind segments.

    Segment distances are absolute distances from the site. The interval immediately
    upwind of the site, ``[0, xi)``, is ignored. Non-A0 profiles must continuously cover
    the complete averaging window ``[xi, xi + xa)``; missing fetch is never imputed.
    """

    height = float(assessment_height_z_m)
    lag_distance, averaging_distance = clause_423_distances(height)
    window_start = lag_distance
    window_end = lag_distance + averaging_distance
    lookup = lookup_data if lookup_data is not None else load_mzcat_table()
    lookup_reference = mzcat_source_reference(lookup)

    # Validate the active Table 4.1 height/region policy even if none of the supplied
    # segments intersects the window (permitted only for mandatory Region A0 handling).
    mandatory_a0_mzcat = indicative_mzcat(
        "TC2",
        height,
        wind_region=wind_region,
        lookup_data=lookup,
    )
    if wind_region == "A0":
        return MixedTerrainAssessment(
            direction=profile.direction,
            reference_height_h_m=reference_height_h_m,
            assessment_height_z_m=height,
            assessment_height_basis=assessment_height_basis,
            lag_distance_xi_m=lag_distance,
            averaging_distance_xa_m=averaging_distance,
            window_start_distance_m=window_start,
            window_end_distance_m=window_end,
            covered_distance_m=0.0,
            mode="a0_mandatory",
            contributions=[],
            weighted_mzcat=mandatory_a0_mzcat,
            profile_source_reference=profile.source_reference,
            lookup_source_reference=lookup_reference,
            warnings=[
                "Region A0 uses the mandatory terrain-independent Table 4.1 Mz,cat; "
                "the supplied terrain segments are retained as evidence only."
            ],
        )

    contributions = _segment_contributions(
        profile=profile,
        height=height,
        wind_region=wind_region,
        lookup=lookup,
        window_start=window_start,
        window_end=window_end,
        averaging_distance=averaging_distance,
    )
    covered_distance = math.fsum(item.included_length_m for item in contributions)

    _require_complete_window_coverage(
        direction=profile.direction,
        contributions=contributions,
        window_start=window_start,
        window_end=window_end,
        averaging_distance=averaging_distance,
    )
    numerator = math.fsum(item.table_mzcat * item.included_length_m for item in contributions)
    weighted_mzcat = numerator / covered_distance
    categories = {item.terrain_category for item in contributions}
    mode = "homogeneous" if len(categories) == 1 else "mixed_weighted"
    return MixedTerrainAssessment(
        direction=profile.direction,
        reference_height_h_m=reference_height_h_m,
        assessment_height_z_m=height,
        assessment_height_basis=assessment_height_basis,
        lag_distance_xi_m=lag_distance,
        averaging_distance_xa_m=averaging_distance,
        window_start_distance_m=window_start,
        window_end_distance_m=window_end,
        covered_distance_m=covered_distance,
        mode=mode,
        contributions=contributions,
        weighted_mzcat=weighted_mzcat,
        profile_source_reference=profile.source_reference,
        lookup_source_reference=lookup_reference,
        warnings=[],
    )


def _segment_contributions(
    *,
    profile: MixedTerrainProfile,
    height: float,
    wind_region: str,
    lookup: dict[str, Any],
    window_start: float,
    window_end: float,
    averaging_distance: float,
) -> list[MixedTerrainSegmentContribution]:
    contributions: list[MixedTerrainSegmentContribution] = []
    for segment in profile.segments:
        clipped_start = max(float(segment.start_distance_m), window_start)
        clipped_end = min(float(segment.end_distance_m), window_end)
        included_length = clipped_end - clipped_start
        if included_length <= 0:
            continue
        table_mzcat = indicative_mzcat(
            segment.terrain_category,
            height,
            wind_region=wind_region,
            lookup_data=lookup,
        )
        weight_fraction = included_length / averaging_distance
        contributions.append(
            MixedTerrainSegmentContribution(
                start_distance_m=float(segment.start_distance_m),
                end_distance_m=float(segment.end_distance_m),
                clipped_start_distance_m=clipped_start,
                clipped_end_distance_m=clipped_end,
                included_length_m=included_length,
                weight_fraction=weight_fraction,
                terrain_category=segment.terrain_category,
                table_mzcat=table_mzcat,
                weighted_contribution=table_mzcat * weight_fraction,
                source_reference=segment.source_reference,
            )
        )
    return contributions


def _require_complete_window_coverage(
    *,
    direction: str,
    contributions: list[MixedTerrainSegmentContribution],
    window_start: float,
    window_end: float,
    averaging_distance: float,
) -> None:
    tolerance = max(COVERAGE_ABSOLUTE_TOLERANCE_M, averaging_distance * 1e-12)
    if not contributions:
        raise ValueError(
            f"Mixed-terrain profile {direction} does not cover the Clause 4.2.3 averaging "
            f"window {window_start:g}-{window_end:g} m."
        )
    if not math.isclose(
        contributions[0].clipped_start_distance_m,
        window_start,
        rel_tol=0.0,
        abs_tol=tolerance,
    ):
        raise ValueError(
            f"Mixed-terrain profile {direction} starts after the Clause 4.2.3 averaging "
            f"window begins at {window_start:g} m."
        )
    for previous, current in zip(contributions, contributions[1:], strict=False):
        if not math.isclose(
            previous.clipped_end_distance_m,
            current.clipped_start_distance_m,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise ValueError(
                f"Mixed-terrain profile {direction} has incomplete or overlapping coverage "
                "inside the Clause 4.2.3 averaging window."
            )
    if not math.isclose(
        contributions[-1].clipped_end_distance_m,
        window_end,
        rel_tol=0.0,
        abs_tol=tolerance,
    ):
        raise ValueError(
            f"Mixed-terrain profile {direction} ends before the Clause 4.2.3 averaging "
            f"window finishes at {window_end:g} m."
        )
    covered_distance = math.fsum(item.included_length_m for item in contributions)
    if not math.isclose(
        covered_distance,
        averaging_distance,
        rel_tol=0.0,
        abs_tol=tolerance,
    ):
        raise ValueError(
            f"Mixed-terrain profile {direction} covers {covered_distance:g} m; Clause 4.2.3 "
            f"requires the complete {averaging_distance:g} m averaging distance."
        )
