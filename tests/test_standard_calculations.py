"""Focused tests for normative AS/NZS 1170.2 calculation primitives."""

from __future__ import annotations

import pytest

from openwind_au.standard_calculations import (
    climate_change_multiplier,
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
