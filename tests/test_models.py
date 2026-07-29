"""Tests for request validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from openwind_au.models import (
    ObstructionInventoryRequest,
    SiteAnalysisRequest,
    WindWorkflowRequest,
)


def test_request_accepts_coordinates() -> None:
    request = SiteAnalysisRequest(
        latitude=-33.86,
        longitude=151.21,
        site_label="Selected Sydney site",
        building_height_m=12,
    )

    assert request.latitude == -33.86
    assert request.longitude == 151.21
    assert request.site_label == "Selected Sydney site"


def test_request_accepts_address() -> None:
    request = SiteAnalysisRequest(
        address="Sydney NSW",
        building_height_m=12,
    )

    assert request.address == "Sydney NSW"


def test_request_rejects_missing_location() -> None:
    with pytest.raises(ValidationError, match="Provide either address or latitude and longitude"):
        SiteAnalysisRequest(building_height_m=12)


def test_request_rejects_address_and_coordinates_together() -> None:
    with pytest.raises(ValidationError, match="not both"):
        SiteAnalysisRequest(
            address="Perth WA",
            latitude=-33.86,
            longitude=151.21,
            building_height_m=12,
        )


def test_request_rejects_site_label_without_coordinates() -> None:
    with pytest.raises(ValidationError, match="site_label"):
        SiteAnalysisRequest(
            address="Sydney NSW",
            site_label="Conflicting label",
            building_height_m=12,
        )


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            SiteAnalysisRequest,
            {
                "latitude": -33.86,
                "longitude": 151.21,
                "building_height_m": 10,
                "buidling_height_m": 99,
            },
        ),
        (
            ObstructionInventoryRequest,
            {
                "latitude": -33.86,
                "longitude": 151.21,
                "radius_m": 500,
                "raduis_m": 4000,
            },
        ),
    ],
)
def test_request_rejects_unknown_fields(model, payload: dict) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate(payload)


@pytest.mark.parametrize("building_height_m", [True, "10"])
def test_request_rejects_coerced_building_height(building_height_m: object) -> None:
    with pytest.raises(ValidationError):
        SiteAnalysisRequest.model_validate(
            {
                "latitude": -33.86,
                "longitude": 151.21,
                "building_height_m": building_height_m,
            }
        )


def test_request_rejects_non_positive_height() -> None:
    with pytest.raises(ValidationError):
        SiteAnalysisRequest(latitude=-33.86, longitude=151.21, building_height_m=0)


def test_request_rejects_unsupported_radius() -> None:
    with pytest.raises(ValidationError, match="radius_m must be one of"):
        SiteAnalysisRequest(
            latitude=-33.86,
            longitude=151.21,
            building_height_m=10,
            radius_m=1200,
        )


def test_wind_workflow_accepts_structured_building_inputs() -> None:
    request = WindWorkflowRequest(
        latitude=-34.550445,
        longitude=150.848728,
        building_height_m=3,
        structure_class="building",
        structure_orientation_deg=0,
        roof_shape="gable",
        building_width_m=4,
        building_length_m=5,
        roof_pitch_deg=15,
        average_roof_height_m=3,
        base_rl_m=0,
    )

    assert request.structure_class == "building"
    assert request.structure_orientation_deg == 0
    assert request.roof_shape == "gable"
    assert request.building_width_m == 4
    assert request.building_length_m == 5
    assert request.average_roof_height_m == 3
    assert request.reference_height_m == 3


def test_wind_workflow_normalizes_legacy_average_height_alias() -> None:
    request = WindWorkflowRequest.model_validate(
        {
            "latitude": -34.550445,
            "longitude": 150.848728,
            "building_height_m": 4,
            "average_height_m": 3,
        }
    )

    assert request.average_roof_height_m == 3
    assert "average_height_m" not in request.model_dump()
    assert request.model_dump()["average_roof_height_m"] == 3


@pytest.mark.parametrize("orientation", [95, 270, 359.9])
def test_wind_workflow_accepts_full_circle_engineering_azimuth(
    orientation: float,
) -> None:
    request = WindWorkflowRequest(
        latitude=-34.550445,
        longitude=150.848728,
        building_height_m=3,
        structure_orientation_deg=orientation,
    )

    assert request.structure_orientation_deg == orientation


@pytest.mark.parametrize("orientation", [-0.1, 360, 361])
def test_wind_workflow_rejects_orientation_outside_engineering_azimuth(
    orientation: float,
) -> None:
    with pytest.raises(ValidationError):
        WindWorkflowRequest(
            latitude=-34.550445,
            longitude=150.848728,
            building_height_m=3,
            structure_orientation_deg=orientation,
        )


def test_wind_workflow_requires_complete_twenty_h_shielding_fetch() -> None:
    with pytest.raises(ValidationError, match="at least 20 times"):
        WindWorkflowRequest(
            latitude=-34.550445,
            longitude=150.848728,
            building_height_m=25,
            obstruction_radius_m=499,
        )

    request = WindWorkflowRequest(
        latitude=-34.550445,
        longitude=150.848728,
        building_height_m=25,
        obstruction_radius_m=500,
    )

    assert request.obstruction_radius_m == 500


def test_wind_workflow_does_not_require_shielding_fetch_above_25_m() -> None:
    request = WindWorkflowRequest(
        latitude=-34.550445,
        longitude=150.848728,
        building_height_m=30,
        obstruction_radius_m=50,
    )

    assert request.reference_height_m == 30


@pytest.mark.parametrize(
    ("building_width_m", "building_length_m"),
    [(4.0, None), (None, 5.0)],
)
def test_wind_workflow_requires_building_dimensions_as_a_pair(
    building_width_m: float | None,
    building_length_m: float | None,
) -> None:
    with pytest.raises(
        ValidationError,
        match="building_width_m and building_length_m must be provided together",
    ):
        WindWorkflowRequest(
            latitude=-34.550445,
            longitude=150.848728,
            building_height_m=3,
            building_width_m=building_width_m,
            building_length_m=building_length_m,
        )


def test_wind_workflow_rejects_legacy_and_structured_building_dimensions() -> None:
    with pytest.raises(
        ValidationError,
        match="Deprecated building_dimensions cannot be combined with structured",
    ):
        WindWorkflowRequest(
            latitude=-34.550445,
            longitude=150.848728,
            building_height_m=3,
            building_dimensions="12 m x 8 m",
            building_width_m=12,
            building_length_m=8,
        )


def test_wind_workflow_retains_legacy_building_dimensions_when_structured_absent() -> None:
    request = WindWorkflowRequest(
        latitude=-34.550445,
        longitude=150.848728,
        building_height_m=3,
        building_dimensions="12 m x 8 m",
    )

    assert request.building_dimensions == "12 m x 8 m"


def test_wind_workflow_accepts_ordered_mixed_terrain_profiles() -> None:
    request = WindWorkflowRequest.model_validate(
        {
            "latitude": -34.550445,
            "longitude": 150.848728,
            "building_height_m": 10.0,
            "average_roof_height_m": 10.0,
            "mixed_terrain_profiles": [
                {
                    "direction": "N",
                    "source_reference": "Reviewed transition schedule",
                    "segments": [
                        {
                            "start_distance_m": 200.0,
                            "end_distance_m": 450.0,
                            "terrain_category": "TC2",
                            "source_reference": "Survey A",
                        },
                        {
                            "start_distance_m": 450.0,
                            "end_distance_m": 700.0,
                            "terrain_category": "TC3",
                            "source_reference": "Survey B",
                        },
                    ],
                }
            ],
        }
    )

    assert request.mixed_terrain_profiles[0].direction == "N"
    assert [segment.terrain_category for segment in request.mixed_terrain_profiles[0].segments] == [
        "TC2",
        "TC3",
    ]


@pytest.mark.parametrize("second_start", [449.0, 451.0])
def test_mixed_terrain_profile_rejects_overlaps_and_gaps(second_start: float) -> None:
    with pytest.raises(ValidationError, match="ordered and contiguous"):
        WindWorkflowRequest.model_validate(
            {
                "latitude": -34.550445,
                "longitude": 150.848728,
                "building_height_m": 10.0,
                "mixed_terrain_profiles": [
                    {
                        "direction": "N",
                        "segments": [
                            {
                                "start_distance_m": 200.0,
                                "end_distance_m": 450.0,
                                "terrain_category": "TC2",
                                "source_reference": "Survey A",
                            },
                            {
                                "start_distance_m": second_start,
                                "end_distance_m": 700.0,
                                "terrain_category": "TC3",
                                "source_reference": "Survey B",
                            },
                        ],
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    "class_override",
    [
        {"terrain_category": "TC3", "reason": "Conflicting terrain input"},
        {
            "terrain_category": "TC3",
            "mzcat": 0.9,
            "reason": "Conflicting class multiplier input",
        },
    ],
)
def test_mixed_terrain_profile_rejects_same_direction_terrain_class_override(
    class_override: dict,
) -> None:
    with pytest.raises(ValidationError, match="cannot be combined"):
        WindWorkflowRequest.model_validate(
            {
                "latitude": -34.550445,
                "longitude": 150.848728,
                "building_height_m": 10.0,
                "mixed_terrain_profiles": [
                    {
                        "direction": "N",
                        "segments": [
                            {
                                "start_distance_m": 200.0,
                                "end_distance_m": 700.0,
                                "terrain_category": "TC2",
                                "source_reference": "Survey A",
                            }
                        ],
                    }
                ],
                "class_multiplier_overrides": [
                    {
                        "direction": "N",
                        **class_override,
                    }
                ],
            }
        )


def test_mixed_terrain_profiles_reject_duplicate_directions() -> None:
    profile = {
        "direction": "N",
        "segments": [
            {
                "start_distance_m": 200.0,
                "end_distance_m": 700.0,
                "terrain_category": "TC2",
                "source_reference": "Reviewed survey segment",
            }
        ],
    }

    with pytest.raises(ValidationError, match="duplicate directions"):
        WindWorkflowRequest.model_validate(
            {
                "latitude": -34.550445,
                "longitude": 150.848728,
                "building_height_m": 10.0,
                "mixed_terrain_profiles": [profile, profile],
            }
        )
