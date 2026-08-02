"""Focused tests for normative AS/NZS 1170.2 calculation primitives."""

from __future__ import annotations

import pytest

from openwind_au.errors import ServiceNotReadyError
from openwind_au.standard_calculations import (
    DesignWindSpeedCandidate,
    climate_change_multiplier,
    design_wind_speed,
    direction_multiplier_row_issues,
    direction_multiplier_values,
    site_wind_speed,
)


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        ("A", 1.0),
        ("A0", 1.0),
        ("A1", 1.0),
        ("A2", 1.0),
        ("A3", 1.0),
        ("A4", 1.0),
        ("A5", 1.0),
        ("B1", 1.0),
        ("B2", 1.05),
        ("C", 1.05),
        ("D", 1.05),
    ],
)
def test_climate_change_multiplier_table_3_3(region: str, expected: float) -> None:
    assert climate_change_multiplier(region) == expected


def test_generic_b_is_rejected_as_ambiguous_for_mc() -> None:
    with pytest.raises(ValueError, match="B1 or B2"):
        climate_change_multiplier("B")


def test_md_row_validator_quarantines_oversized_integer_values() -> None:
    row = {
        direction: (10**10_000 if direction == "N" else 1.0)
        for direction in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    }

    issues = direction_multiplier_row_issues(row)

    assert any(issue.startswith("N must be a finite number") for issue in issues)


def test_md_lookup_rejects_non_object_table_container() -> None:
    with pytest.raises(ServiceNotReadyError, match="tables must be an object"):
        direction_multiplier_values("A2", data={"tables": []})


def test_site_wind_speed_includes_mc_in_clause_2_2_product() -> None:
    assert site_wind_speed(vr=57.0, mc=1.05, md=0.9, mzcat=1.0, ms=1.0, mt=1.0) == (
        pytest.approx(53.865)
    )
    assert site_wind_speed(vr=45.0, mc=1.0, md=0.85, mzcat=0.83, ms=0.85, mt=1.0) == (
        pytest.approx(26.985375)
    )


@pytest.mark.parametrize(
    "values",
    [
        (float("nan"), 1, 1, 1, 1, 1),
        (45, float("inf"), 1, 1, 1, 1),
        (45, 1, 0, 1, 1, 1),
    ],
)
def test_site_wind_speed_rejects_invalid_factors(values: tuple[float, ...]) -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        site_wind_speed(
            vr=values[0],
            mc=values[1],
            md=values[2],
            mzcat=values[3],
            ms=values[4],
            mt=values[5],
        )


def test_design_wind_speed_uses_exact_knots_in_closed_sector() -> None:
    result = design_wind_speed(
        theta_degrees=90.0,
        direction_speeds={
            "N": 31.0,
            "NE": 35.0,
            "E": 43.0,
            "SE": 37.0,
            "S": 33.0,
            "SW": 32.0,
            "W": 31.0,
            "NW": 30.0,
        },
    )

    assert result.theta_degrees == 90.0
    assert result.sector_start_degrees == 45.0
    assert result.sector_end_degrees == 135.0
    assert result.candidates == (
        DesignWindSpeedCandidate(bearing_degrees=45.0, site_wind_speed_m_s=35.0),
        DesignWindSpeedCandidate(bearing_degrees=90.0, site_wind_speed_m_s=43.0),
        DesignWindSpeedCandidate(bearing_degrees=135.0, site_wind_speed_m_s=37.0),
    )
    assert result.raw_maximum_m_s == 43.0
    assert result.design_wind_speed_m_s == 43.0
    assert result.minimum_applied is False


def test_design_wind_speed_interpolates_arbitrary_sector_boundaries() -> None:
    result = design_wind_speed(
        theta_degrees=20.0,
        direction_speeds={
            "N": 32.0,
            "NE": 41.0,
            "E": 50.0,
            "SE": 44.0,
            "S": 38.0,
            "SW": 36.0,
            "W": 34.0,
            "NW": 30.0,
        },
    )

    assert [candidate.bearing_degrees for candidate in result.candidates] == [
        335.0,
        0.0,
        45.0,
        65.0,
    ]
    assert [candidate.site_wind_speed_m_s for candidate in result.candidates] == pytest.approx(
        [30.8888888889, 32.0, 41.0, 45.0]
    )
    assert result.raw_maximum_m_s == pytest.approx(45.0)
    assert result.design_wind_speed_m_s == pytest.approx(45.0)


def test_design_wind_speed_wraps_north_and_can_govern_at_nw_knot() -> None:
    result = design_wind_speed(
        theta_degrees=350.0,
        direction_speeds={
            "N": 38.0,
            "NE": 34.0,
            "E": 32.0,
            "SE": 31.0,
            "S": 30.0,
            "SW": 32.0,
            "W": 36.0,
            "NW": 46.0,
        },
    )

    assert result.sector_start_degrees == 305.0
    assert result.sector_end_degrees == 35.0
    assert [candidate.bearing_degrees for candidate in result.candidates] == [
        305.0,
        315.0,
        0.0,
        35.0,
    ]
    assert result.raw_maximum_m_s == 46.0


def test_design_wind_speed_applies_uls_minimum_only_when_needed() -> None:
    low_speeds = {direction: 24.0 for direction in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")}

    ultimate = design_wind_speed(theta_degrees=0.0, direction_speeds=low_speeds)
    serviceability = design_wind_speed(
        theta_degrees=0.0,
        direction_speeds=low_speeds,
        ultimate_limit_state=False,
    )

    assert ultimate.raw_maximum_m_s == 24.0
    assert ultimate.design_wind_speed_m_s == 30.0
    assert ultimate.minimum_applied is True
    assert serviceability.design_wind_speed_m_s == 24.0
    assert serviceability.minimum_applied is False


@pytest.mark.parametrize(
    "theta_degrees",
    [-0.1, 360.0, float("nan"), float("inf"), True],
)
def test_design_wind_speed_rejects_invalid_orientation(theta_degrees: float) -> None:
    speeds = {direction: 35.0 for direction in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")}

    with pytest.raises(ValueError, match=r"\[0, 360\)"):
        design_wind_speed(theta_degrees=theta_degrees, direction_speeds=speeds)


def test_design_wind_speed_requires_exactly_eight_valid_direction_speeds() -> None:
    speeds = {direction: 35.0 for direction in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")}

    with pytest.raises(ValueError, match="missing directions: NW"):
        design_wind_speed(
            theta_degrees=0.0,
            direction_speeds={key: value for key, value in speeds.items() if key != "NW"},
        )
    with pytest.raises(ValueError, match="unexpected directions: NNE"):
        design_wind_speed(theta_degrees=0.0, direction_speeds={**speeds, "NNE": 35.0})
    with pytest.raises(ValueError, match="E must be positive and finite"):
        design_wind_speed(theta_degrees=0.0, direction_speeds={**speeds, "E": float("nan")})
    with pytest.raises(ValueError, match="ultimate_limit_state must be a boolean"):
        design_wind_speed(
            theta_degrees=0.0,
            direction_speeds=speeds,
            ultimate_limit_state=1,
        )
