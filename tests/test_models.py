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
