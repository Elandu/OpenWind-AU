"""Rule-based preliminary topographic feature screening."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from openwind_au.models import TerrainProfile, TopographicFeature

MIN_FEATURE_RELIEF_M = 5.0
MIN_RIDGE_VALLEY_SUBSTANTIAL_RELIEF_M = 50.0
MIN_RIDGE_VALLEY_SLOPE = 0.10
MIN_RISING_HILL_SLOPE = 0.03
ESCARPMENT_SLOPE = 0.15

REVIEW_NOTE = (
    "Candidate only; detected features require review by a competent engineer "
    "against survey data, imagery, and site context."
)


@dataclass(frozen=True)
class _Candidate:
    feature_type: str
    base_index: int
    crest_index: int
    x_index: int
    h_m: float
    lu_m: float
    slope: float
    score: float
    notes: tuple[str, ...]


@dataclass(frozen=True)
class _ClauseGeometry:
    base_index: int
    h_m: float
    lu_m: float
    slope_parameter: float


def analyse_topography(
    profiles: list[TerrainProfile],
    site_rl_m: float,
) -> list[TopographicFeature]:
    """Return one conservative topographic screening result for each profile."""

    return [analyse_profile_topography(profile, site_rl_m) for profile in profiles]


def analyse_profile_topography(
    profile: TerrainProfile,
    site_rl_m: float,
) -> TopographicFeature:
    """Classify one radial profile using transparent geometric rules."""

    distances = np.array([point.distance_m for point in profile.points], dtype=float)
    elevations = np.array([point.elevation_m for point in profile.points], dtype=float)
    if len(distances) < 3:
        return _no_significant_feature(profile, site_rl_m)

    candidates = [
        *_ridge_candidates(distances, elevations),
        *_valley_candidates(distances, elevations),
        *_escarpment_candidates(distances, elevations),
    ]
    hill = _hill_candidate(distances, elevations)
    if hill:
        candidates.append(hill)

    if not candidates:
        return _no_significant_feature(profile, site_rl_m)

    screened_candidates = [
        candidate for candidate in candidates if _candidate_meets_review_thresholds(candidate)
    ]
    if not screened_candidates:
        return _no_significant_feature(profile, site_rl_m)

    candidate = max(screened_candidates, key=lambda item: item.score)
    clause_geometry = _clause_4_4_geometry(distances, elevations, candidate)
    if clause_geometry is None:
        base_index = candidate.base_index
        h_m = candidate.h_m
        lu_m = candidate.lu_m
        slope = candidate.slope
        geometry_notes = (
            "The upwind half-height point required for Clause 4.4 Lu was not resolved "
            "within this profile; automatic Mt is unavailable.",
        )
    else:
        base_index = clause_geometry.base_index
        h_m = clause_geometry.h_m
        lu_m = clause_geometry.lu_m
        slope = clause_geometry.slope_parameter
        geometry_notes = (
            "H and Lu resolve the upwind half-height geometry required by Clause 4.4.",
        )
    confidence = _confidence(h_m, slope)
    return TopographicFeature(
        direction=profile.direction,
        azimuth_deg=profile.azimuth_deg,
        feature_type=candidate.feature_type,
        site_rl_m=site_rl_m,
        crest_rl_m=float(elevations[candidate.crest_index]),
        base_rl_m=float(elevations[base_index]),
        h_m=h_m,
        lu_m=lu_m,
        x_m=float(distances[candidate.x_index]),
        base_x_m=float(distances[base_index]),
        crest_x_m=float(distances[candidate.crest_index]),
        average_upwind_slope=slope,
        mt_geometry_resolved=clause_geometry is not None,
        confidence=confidence,
        notes=[*candidate.notes, *geometry_notes, REVIEW_NOTE],
    )


def _clause_4_4_geometry(
    distances: np.ndarray,
    elevations: np.ndarray,
    candidate: _Candidate,
) -> _ClauseGeometry | None:
    """Resolve H and Lu on the upwind side of a candidate crest.

    Profile distance increases away from the site into the named wind direction,
    so increasing distance is upwind. Clause 4.4 Lu terminates where the upwind
    terrain first reaches half the feature height below the crest.
    """

    if candidate.feature_type not in {"ridge", "hill", "escarpment"}:
        return None
    crest_index = candidate.crest_index
    if crest_index >= len(elevations) - 1:
        return None
    upwind_elevations = elevations[crest_index:]
    relative_base_index = int(np.argmin(upwind_elevations))
    base_index = crest_index + relative_base_index
    if base_index <= crest_index:
        return None
    crest_elevation = float(elevations[crest_index])
    h_m = crest_elevation - float(elevations[base_index])
    if h_m <= 0:
        return None
    half_height_elevation = crest_elevation - h_m / 2.0
    half_height_x_m = _first_upwind_crossing(
        distances,
        elevations,
        crest_index,
        base_index,
        half_height_elevation,
    )
    if half_height_x_m is None:
        return None
    lu_m = half_height_x_m - float(distances[crest_index])
    if lu_m <= 0:
        return None
    return _ClauseGeometry(
        base_index=base_index,
        h_m=h_m,
        lu_m=lu_m,
        slope_parameter=h_m / (2.0 * lu_m),
    )


def _first_upwind_crossing(
    distances: np.ndarray,
    elevations: np.ndarray,
    crest_index: int,
    base_index: int,
    target_elevation: float,
) -> float | None:
    for lower_index in range(crest_index, base_index):
        upper_index = lower_index + 1
        elevation_0 = float(elevations[lower_index])
        elevation_1 = float(elevations[upper_index])
        if elevation_0 >= target_elevation >= elevation_1:
            if elevation_0 == elevation_1:
                return float(distances[upper_index])
            ratio = (elevation_0 - target_elevation) / (elevation_0 - elevation_1)
            distance_0 = float(distances[lower_index])
            distance_1 = float(distances[upper_index])
            return distance_0 + ratio * (distance_1 - distance_0)
    return None


def _ridge_candidates(distances: np.ndarray, elevations: np.ndarray) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for index in range(1, len(elevations) - 1):
        if elevations[index] < elevations[index - 1] or elevations[index] < elevations[index + 1]:
            continue

        left_min_index = int(np.argmin(elevations[: index + 1]))
        right_min_index = index + int(np.argmin(elevations[index:]))
        left_prominence = elevations[index] - elevations[left_min_index]
        right_prominence = elevations[index] - elevations[right_min_index]
        prominence = float(min(left_prominence, right_prominence))
        if prominence < MIN_FEATURE_RELIEF_M:
            continue

        base_index = (
            left_min_index
            if elevations[left_min_index] <= elevations[right_min_index]
            else right_min_index
        )
        h_m = float(elevations[index] - elevations[base_index])
        lu_m = abs(float(distances[index] - distances[base_index]))
        if lu_m <= 0:
            continue
        slope = h_m / lu_m
        candidates.append(
            _Candidate(
                feature_type="ridge",
                base_index=base_index,
                crest_index=index,
                x_index=index,
                h_m=h_m,
                lu_m=lu_m,
                slope=slope,
                score=h_m + prominence,
                notes=(
                    "Local crest rises at least 5 m above lower terrain on both sides.",
                    "Classified as a ridge candidate from profile geometry only.",
                ),
            )
        )
    return candidates


def _valley_candidates(distances: np.ndarray, elevations: np.ndarray) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for index in range(1, len(elevations) - 1):
        if elevations[index] > elevations[index - 1] or elevations[index] > elevations[index + 1]:
            continue

        left_max_index = int(np.argmax(elevations[: index + 1]))
        right_max_index = index + int(np.argmax(elevations[index:]))
        left_depth = elevations[left_max_index] - elevations[index]
        right_depth = elevations[right_max_index] - elevations[index]
        depth = float(min(left_depth, right_depth))
        if depth < MIN_FEATURE_RELIEF_M:
            continue

        crest_index = (
            left_max_index
            if elevations[left_max_index] >= elevations[right_max_index]
            else right_max_index
        )
        h_m = float(elevations[crest_index] - elevations[index])
        lu_m = abs(float(distances[crest_index] - distances[index]))
        if lu_m <= 0:
            continue
        slope = h_m / lu_m
        candidates.append(
            _Candidate(
                feature_type="valley",
                base_index=index,
                crest_index=crest_index,
                x_index=index,
                h_m=h_m,
                lu_m=lu_m,
                slope=slope,
                score=h_m + depth,
                notes=(
                    "Local low point sits at least 5 m below higher terrain on both sides.",
                    "Classified as a valley candidate from profile geometry only.",
                ),
            )
        )
    return candidates


def _escarpment_candidates(distances: np.ndarray, elevations: np.ndarray) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for index, gradient in enumerate(np.diff(elevations) / np.diff(distances)):
        slope = abs(float(gradient))
        if slope < ESCARPMENT_SLOPE:
            continue

        start = index
        end = index + 1
        base_index = start if elevations[start] <= elevations[end] else end
        crest_index = end if base_index == start else start
        h_m = abs(float(elevations[end] - elevations[start]))
        lu_m = abs(float(distances[end] - distances[start]))
        if h_m < MIN_FEATURE_RELIEF_M or lu_m <= 0:
            continue
        candidates.append(
            _Candidate(
                feature_type="escarpment",
                base_index=base_index,
                crest_index=crest_index,
                x_index=crest_index,
                h_m=h_m,
                lu_m=lu_m,
                slope=slope,
                score=h_m + slope * 100,
                notes=(
                    "Adjacent samples show a steep local rise or fall.",
                    "Classified as an escarpment candidate using the maximum local gradient.",
                ),
            )
        )
    return candidates


def _hill_candidate(distances: np.ndarray, elevations: np.ndarray) -> _Candidate | None:
    endpoint_indices = (0, len(elevations) - 1)
    crest_index = max(endpoint_indices, key=lambda item: elevations[item])
    base_index = int(np.argmin(elevations))
    h_m = float(elevations[crest_index] - elevations[base_index])
    lu_m = abs(float(distances[crest_index] - distances[base_index]))
    if h_m < MIN_FEATURE_RELIEF_M or lu_m <= 0:
        return None
    slope = h_m / lu_m
    if slope < MIN_RISING_HILL_SLOPE:
        return None
    return _Candidate(
        feature_type="hill",
        base_index=base_index,
        crest_index=crest_index,
        x_index=crest_index,
        h_m=h_m,
        lu_m=lu_m,
        slope=slope,
        score=h_m + slope * 50,
        notes=(
            "Profile rises toward the analysis radius endpoint.",
            "Classified as a hill candidate; consider extending radius before relying on it.",
        ),
    )


def _candidate_meets_review_thresholds(candidate: _Candidate) -> bool:
    if candidate.h_m < MIN_FEATURE_RELIEF_M or candidate.lu_m <= 0:
        return False
    if candidate.feature_type not in {"ridge", "valley"}:
        return True
    return (
        candidate.h_m >= MIN_RIDGE_VALLEY_SUBSTANTIAL_RELIEF_M
        or candidate.slope >= MIN_RIDGE_VALLEY_SLOPE
    )


def _no_significant_feature(profile: TerrainProfile, site_rl_m: float) -> TopographicFeature:
    return TopographicFeature(
        direction=profile.direction,
        azimuth_deg=profile.azimuth_deg,
        feature_type="no significant feature",
        site_rl_m=site_rl_m,
        crest_rl_m=site_rl_m,
        base_rl_m=site_rl_m,
        h_m=0.0,
        lu_m=0.0,
        x_m=0.0,
        base_x_m=0.0,
        crest_x_m=0.0,
        average_upwind_slope=0.0,
        mt_geometry_resolved=False,
        confidence="none",
        notes=[
            "No ridge, hill, escarpment, or valley candidate met the conservative "
            "screening thresholds.",
            REVIEW_NOTE,
        ],
    )


def _confidence(h_m: float, slope: float) -> str:
    if h_m >= 25 and slope >= 0.15:
        return "medium"
    return "low"
