"""Lightweight, deterministic AS/NZS 1170.2 calculation primitives."""

from __future__ import annotations

import json
import math
from importlib import resources
from typing import Any

DIRECTIONS: tuple[str, ...] = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
REGIONAL_WIND_SPEED_EQUATIONS: dict[str, tuple[float, float]] = {
    "A": (67.0, 41.0),
    "B": (106.0, 92.0),
    "C": (122.0, 104.0),
    "D": (156.0, 142.0),
}
REGIONAL_WIND_SPEED_V1: dict[str, float] = {
    "A": 30.0,
    "B": 26.0,
    "C": 23.0,
    "D": 23.0,
}


def table_region_key(region: str, tables: dict[str, Any]) -> str:
    """Return the most specific available table key for a wind-region label."""

    if region in tables:
        return region
    if region.startswith("A") and "A" in tables:
        return "A"
    if region.startswith("B") and "B" in tables:
        return "B"
    return region


def regional_wind_speed(region: str, ari_years: int) -> float:
    """Calculate Australian VR from AS/NZS 1170.2:2021 Table 3.1(A).

    The regional equations apply for R >= 5 years and the result is rounded
    to the nearest 1 m/s. The R=1 row is an explicit table value.
    """

    if ari_years < 1:
        raise ValueError("Annual recurrence interval must be at least 1 year.")
    base_region = table_region_key(region, REGIONAL_WIND_SPEED_EQUATIONS)
    if base_region not in REGIONAL_WIND_SPEED_EQUATIONS:
        raise ValueError(f"Unsupported Australian wind region: {region}")
    if ari_years == 1:
        return REGIONAL_WIND_SPEED_V1[base_region]
    if ari_years < 5:
        raise ValueError(
            "AS/NZS 1170.2:2021 Table 3.1(A) defines V1 and the regional equation for R >= 5; "
            "R must be 1 or at least 5 years."
        )
    constant, coefficient = REGIONAL_WIND_SPEED_EQUATIONS[base_region]
    unrounded = constant - coefficient * ari_years**-0.1
    return float(math.floor(unrounded + 0.5))


def direction_multiplier_values(region: str) -> dict[str, float]:
    """Load the packaged Table 3.2(A) direction multipliers for a region."""

    path = resources.files("openwind_au.data").joinpath("direction_multipliers.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    table_key = table_region_key(region, data.get("tables", {}))
    row = data.get("tables", {}).get(table_key)
    if not row:
        raise ValueError(f"Unsupported Australian wind region: {region}")
    return {direction: float(row[direction]) for direction in DIRECTIONS}


def ms_from_shielding_parameter(s: float) -> float:
    """Return Ms by linear interpolation from AS/NZS 1170.2:2021 Table 4.2."""

    if not math.isfinite(s):
        raise ValueError("Shielding parameter s must be finite.")
    if s < 0:
        raise ValueError("Shielding parameter s must not be negative.")
    if s <= 1.5:
        return 0.7
    if s >= 12.0:
        return 1.0
    points = [(1.5, 0.7), (3.0, 0.8), (6.0, 0.9), (12.0, 1.0)]
    for (s0, ms0), (s1, ms1) in zip(points, points[1:], strict=True):
        if s <= s1:
            ratio = (s - s0) / (s1 - s0)
            return ms0 + ratio * (ms1 - ms0)
    return 1.0
