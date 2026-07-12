"""Tests for request validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from openwind_au.models import SiteAnalysisRequest, WindWorkflowRequest


def test_request_accepts_coordinates() -> None:
    request = SiteAnalysisRequest(
        latitude=-33.86,
        longitude=151.21,
        building_height_m=12,
    )

    assert request.latitude == -33.86
    assert request.longitude == 151.21


def test_request_accepts_address() -> None:
    request = SiteAnalysisRequest(
        address="Sydney NSW",
        building_height_m=12,
    )

    assert request.address == "Sydney NSW"


def test_request_rejects_missing_location() -> None:
    with pytest.raises(ValidationError, match="Provide either address or latitude and longitude"):
        SiteAnalysisRequest(building_height_m=12)


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
        average_height_m=3,
        base_rl_m=0,
    )

    assert request.structure_class == "building"
    assert request.structure_orientation_deg == 0
    assert request.roof_shape == "gable"
    assert request.building_width_m == 4
    assert request.building_length_m == 5


def test_wind_workflow_rejects_orientation_outside_reference_range() -> None:
    with pytest.raises(ValidationError):
        WindWorkflowRequest(
            latitude=-34.550445,
            longitude=150.848728,
            building_height_m=3,
            structure_orientation_deg=95,
        )
