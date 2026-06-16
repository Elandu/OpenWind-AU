"""Tests for request validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from openwind_au.models import SiteAnalysisRequest


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
