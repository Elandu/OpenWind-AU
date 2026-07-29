"""Tests for AS/NZS 1170.2 Clause 4.2.3 mixed-terrain averaging."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from openwind_au.mixed_terrain import (
    calculate_mixed_terrain_assessment,
    clause_423_distances,
)
from openwind_au.models import MixedTerrainProfile
from openwind_au.mzcat import indicative_mzcat
from openwind_au.standard_lookup_tables import MZCAT_DATA_FILE, load_packaged_lookup_data


def profile(*segments: tuple[float, float, str], direction: str = "N") -> MixedTerrainProfile:
    return MixedTerrainProfile.model_validate(
        {
            "direction": direction,
            "source_reference": "Reviewed transition schedule",
            "segments": [
                {
                    "start_distance_m": start,
                    "end_distance_m": end,
                    "terrain_category": category,
                    "source_reference": f"Survey segment {index + 1}",
                }
                for index, (start, end, category) in enumerate(segments)
            ],
        }
    )


@pytest.fixture
def lookup() -> dict:
    return load_packaged_lookup_data(MZCAT_DATA_FILE)


def test_clause_423_distances_use_lag_and_larger_averaging_distance() -> None:
    assert clause_423_distances(10) == (200.0, 500.0)
    assert clause_423_distances(20) == (400.0, 800.0)


def test_equal_mixed_fetch_weights_table_values_after_ignoring_lag(lookup: dict) -> None:
    result = calculate_mixed_terrain_assessment(
        profile=profile((0, 200, "TC4"), (200, 450, "TC2"), (450, 700, "TC3")),
        assessment_height_z_m=10,
        reference_height_h_m=10,
        assessment_height_basis="average_roof_height_h",
        wind_region="A2",
        lookup_data=lookup,
    )

    expected = 0.5 * indicative_mzcat("TC2", 10, wind_region="A2", lookup_data=lookup)
    expected += 0.5 * indicative_mzcat("TC3", 10, wind_region="A2", lookup_data=lookup)
    assert result.mode == "mixed_weighted"
    assert result.lag_distance_xi_m == 200
    assert result.averaging_distance_xa_m == 500
    assert result.window_start_distance_m == 200
    assert result.window_end_distance_m == 700
    assert result.covered_distance_m == 500
    assert result.weighted_mzcat == pytest.approx(expected)
    assert [item.terrain_category for item in result.contributions] == ["TC2", "TC3"]
    assert [item.weight_fraction for item in result.contributions] == [0.5, 0.5]


def test_larger_40z_window_and_clipping_are_applied_without_rounding(lookup: dict) -> None:
    result = calculate_mixed_terrain_assessment(
        profile=profile((300, 600, "TC2"), (600, 1300, "TC3")),
        assessment_height_z_m=20,
        reference_height_h_m=20,
        assessment_height_basis="average_roof_height_h",
        wind_region="A2",
        lookup_data=lookup,
    )

    expected = 0.25 * indicative_mzcat("TC2", 20, wind_region="A2", lookup_data=lookup)
    expected += 0.75 * indicative_mzcat("TC3", 20, wind_region="A2", lookup_data=lookup)
    assert result.window_start_distance_m == 400
    assert result.window_end_distance_m == 1200
    assert [item.included_length_m for item in result.contributions] == [200, 600]
    assert result.weighted_mzcat == pytest.approx(expected)


def test_height_interpolation_precedes_distance_weighting(lookup: dict) -> None:
    result = calculate_mixed_terrain_assessment(
        profile=profile((250, 500, "TC2"), (500, 750, "TC3")),
        assessment_height_z_m=12.5,
        reference_height_h_m=12.5,
        assessment_height_basis="average_roof_height_h",
        wind_region="A2",
        lookup_data=lookup,
    )

    expected = 0.5 * indicative_mzcat("TC2", 12.5, wind_region="A2", lookup_data=lookup)
    expected += 0.5 * indicative_mzcat("TC3", 12.5, wind_region="A2", lookup_data=lookup)
    assert result.weighted_mzcat == pytest.approx(expected)


def test_homogeneous_profile_equals_single_category_lookup(lookup: dict) -> None:
    result = calculate_mixed_terrain_assessment(
        profile=profile((0, 1000, "TC2.5")),
        assessment_height_z_m=10,
        wind_region="A2",
        lookup_data=lookup,
    )
    assert result.mode == "homogeneous"
    assert result.weighted_mzcat == indicative_mzcat(
        "TC2.5", 10, wind_region="A2", lookup_data=lookup
    )


@pytest.mark.parametrize(
    "segments",
    [
        ((200, 400, "TC2"), (401, 700, "TC3")),
        ((200, 451, "TC2"), (450, 700, "TC3")),
        ((201, 700, "TC2"),),
        ((200, 699, "TC2"),),
    ],
)
def test_gaps_overlaps_and_incomplete_window_coverage_are_rejected(
    lookup: dict,
    segments: tuple[tuple[float, float, str], ...],
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        calculate_mixed_terrain_assessment(
            profile=profile(*segments),
            assessment_height_z_m=10,
            wind_region="A2",
            lookup_data=lookup,
        )


def test_region_a0_value_is_terrain_independent_and_does_not_require_full_coverage(
    lookup: dict,
) -> None:
    first = calculate_mixed_terrain_assessment(
        profile=profile((0, 100, "TC1")),
        assessment_height_z_m=10,
        wind_region="A0",
        lookup_data=lookup,
    )
    second = calculate_mixed_terrain_assessment(
        profile=profile((0, 1000, "TC4")),
        assessment_height_z_m=10,
        wind_region="A0",
        lookup_data=lookup,
    )
    assert first.mode == second.mode == "a0_mandatory"
    assert first.contributions == second.contributions == []
    assert first.covered_distance_m == second.covered_distance_m == 0.0
    assert (
        first.weighted_mzcat
        == second.weighted_mzcat
        == indicative_mzcat("TC2", 10, wind_region="A0", lookup_data=lookup)
    )


def test_segment_source_reference_is_required() -> None:
    with pytest.raises(ValidationError, match="source_reference"):
        MixedTerrainProfile.model_validate(
            {
                "direction": "N",
                "segments": [
                    {
                        "start_distance_m": 200,
                        "end_distance_m": 700,
                        "terrain_category": "TC2",
                    }
                ],
            }
        )
