"""Tests for AS/NZS 1170.2:2021 Clause 4.4 Mt calculations."""

from __future__ import annotations

import pytest

from openwind_au.models import (
    SiteAnalysisResult,
    SiteLocation,
    TopographicFeature,
    WindRegionAssessment,
    WindWorkflowRequest,
)
from openwind_au.topographic_multiplier import calculate_topographic_multiplier
from openwind_au.wind_workflow import mt_assessments


@pytest.mark.parametrize(
    ("slope", "expected_mh"),
    [
        (0.05, 1.0793650794),
        (0.10, 1.1587301587),
        (0.20, 1.3174603175),
        (0.30, 1.4761904762),
        (0.45, 1.7142857143),
    ],
)
def test_mh_crest_values_follow_clause_4_4_2(slope: float, expected_mh: float) -> None:
    h_m = 20.0
    result = calculate_topographic_multiplier(
        feature_type="hill",
        h_m=h_m,
        lu_m=h_m / (2.0 * slope),
        x_m=0.0,
        z_m=0.0,
        wind_region="A2",
        site_elevation_m=100.0,
    )

    assert result.mh == pytest.approx(expected_mh)
    assert result.mt == pytest.approx(expected_mh)
    assert "4.4(3)" in result.equation


def test_reference_height_and_distance_reduce_mh() -> None:
    at_crest = calculate_topographic_multiplier(
        feature_type="ridge",
        h_m=30.0,
        lu_m=75.0,
        x_m=0.0,
        z_m=0.0,
        wind_region="A2",
        site_elevation_m=100.0,
    )
    elevated_and_downwind = calculate_topographic_multiplier(
        feature_type="ridge",
        h_m=30.0,
        lu_m=75.0,
        x_m=20.0,
        z_m=10.0,
        wind_region="A2",
        site_elevation_m=100.0,
    )

    assert elevated_and_downwind.mh < at_crest.mh
    assert elevated_and_downwind.l1_m == pytest.approx(27.0)
    assert elevated_and_downwind.l2_m == pytest.approx(108.0)


def test_steep_peak_zone_uses_equation_4_4_4() -> None:
    result = calculate_topographic_multiplier(
        feature_type="hill",
        h_m=20.0,
        lu_m=20.0,
        x_m=2.0,
        z_m=8.0,
        wind_region="A2",
        site_elevation_m=100.0,
    )

    assert result.l2_m == pytest.approx(32.0)
    assert result.mh == pytest.approx(1.665625)
    assert "4.4(4)" in result.equation


def test_downwind_escarpment_uses_ten_l1_zone() -> None:
    result = calculate_topographic_multiplier(
        feature_type="escarpment",
        h_m=30.0,
        lu_m=50.0,
        x_m=100.0,
        z_m=10.0,
        wind_region="A2",
        site_elevation_m=100.0,
    )

    assert result.l1_m == pytest.approx(18.0)
    assert result.l2_m == pytest.approx(180.0)
    assert result.mh > 1.0


def test_no_feature_still_applies_high_elevation_a4_factor() -> None:
    result = calculate_topographic_multiplier(
        feature_type="no significant feature",
        h_m=0.0,
        lu_m=0.0,
        x_m=0.0,
        z_m=10.0,
        wind_region="A4",
        site_elevation_m=1000.0,
    )

    assert result.mh == 1.0
    assert result.elevation_factor == pytest.approx(1.15)
    assert result.mt == pytest.approx(1.15)
    assert "4.4(1)" in result.equation


def test_region_a0_reduces_hill_shape_increment() -> None:
    result = calculate_topographic_multiplier(
        feature_type="hill",
        h_m=20.0,
        lu_m=50.0,
        x_m=0.0,
        z_m=0.0,
        wind_region="A0",
        site_elevation_m=100.0,
    )

    assert result.mt == pytest.approx(0.5 + 0.5 * result.mh)
    assert "4.4(2)" in result.equation


def test_low_or_gentle_feature_has_no_hill_shape_increase() -> None:
    low = calculate_topographic_multiplier(
        feature_type="ridge",
        h_m=9.9,
        lu_m=20.0,
        x_m=0.0,
        z_m=0.0,
        wind_region="A2",
        site_elevation_m=100.0,
    )
    gentle = calculate_topographic_multiplier(
        feature_type="ridge",
        h_m=20.0,
        lu_m=250.0,
        x_m=0.0,
        z_m=0.0,
        wind_region="A2",
        site_elevation_m=100.0,
    )

    assert low.mt == 1.0
    assert gentle.mt == 1.0


def test_workflow_mt_uses_dem_feature_geometry_and_exposes_calculation() -> None:
    request = WindWorkflowRequest(
        latitude=-33.86,
        longitude=151.21,
        building_height_m=10.0,
        radius_m=500,
    )
    site_result = SiteAnalysisResult(
        input=request,
        site=SiteLocation(
            latitude=-33.86,
            longitude=151.21,
            ground_elevation_m=100.0,
            source="test DEM",
        ),
        profiles=[],
        features=[
            TopographicFeature(
                direction="N",
                azimuth_deg=0.0,
                feature_type="ridge",
                site_rl_m=100.0,
                crest_rl_m=130.0,
                base_rl_m=100.0,
                h_m=30.0,
                lu_m=75.0,
                x_m=20.0,
                base_x_m=95.0,
                crest_x_m=20.0,
                average_upwind_slope=0.4,
                mt_geometry_resolved=True,
                confidence="medium",
                notes=["Derived from test elevation profile."],
            )
        ],
        assumptions=[],
        limitations=[],
    )
    wind_region = WindRegionAssessment(
        latitude=-33.86,
        longitude=151.21,
        wind_region="A2",
        source="test polygons",
        confidence="high",
    )

    assessment = mt_assessments(request, site_result, wind_region, {}, {})[0]

    assert assessment.calculated_value == pytest.approx(1.189)
    assert assessment.final_value == assessment.calculated_value
    assert assessment.final_label == "Calculated Mt from terrain profile"
    assert "Equation 4.4(3)" in assessment.formula_basis
    assert "Mh: 1.189" in assessment.calculation_inputs
    assert "Reference height z: 10.000 m" in assessment.calculation_inputs
    assert any("public DEM geometry" in warning for warning in assessment.warnings)


def test_workflow_mt_blocks_unresolved_upwind_geometry() -> None:
    request = WindWorkflowRequest(
        latitude=-33.86,
        longitude=151.21,
        building_height_m=10.0,
        radius_m=500,
    )
    feature = TopographicFeature(
        direction="N",
        azimuth_deg=0.0,
        feature_type="hill",
        site_rl_m=100.0,
        crest_rl_m=130.0,
        base_rl_m=100.0,
        h_m=30.0,
        lu_m=100.0,
        x_m=500.0,
        base_x_m=0.0,
        crest_x_m=500.0,
        average_upwind_slope=0.15,
        mt_geometry_resolved=False,
        confidence="low",
        notes=["Crest occurs at the profile endpoint."],
    )
    site_result = SiteAnalysisResult(
        input=request,
        site=SiteLocation(
            latitude=-33.86,
            longitude=151.21,
            ground_elevation_m=100.0,
            source="test DEM",
        ),
        profiles=[],
        features=[feature],
        assumptions=[],
        limitations=[],
    )
    wind_region = WindRegionAssessment(
        latitude=-33.86,
        longitude=151.21,
        wind_region="A2",
        source="test polygons",
        confidence="high",
    )

    assessment = mt_assessments(request, site_result, wind_region, {}, {})[0]

    assert assessment.calculated_value is None
    assert assessment.final_value is None
    assert assessment.final_label is None
    assert "calculation blocked" in assessment.formula_basis
    assert "Mt unavailable" in assessment.calculation_result
    assert any("half-height point" in warning for warning in assessment.warnings)
