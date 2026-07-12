"""Validation tests for packaged AS/NZS 1170.2:2021 lookup tables."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

EXPECTED_REGIONAL_WIND_SPEEDS_2021 = {
    "A": {
        "ultimate": {"25": 37.0, "100": 41.0, "500": 45.0, "1000": 46.0, "2000": 48.0},
        "serviceability": {"25": 37.0},
    },
    "B": {
        "ultimate": {"25": 39.0, "100": 48.0, "500": 57.0, "1000": 60.0, "2000": 63.0},
        "serviceability": {"25": 39.0},
    },
    "C": {
        "ultimate": {"25": 47.0, "100": 56.0, "500": 66.0, "1000": 70.0, "2000": 73.0},
        "serviceability": {"25": 47.0},
    },
    "D": {
        "ultimate": {"25": 53.0, "100": 66.0, "500": 80.0, "1000": 85.0, "2000": 90.0},
        "serviceability": {"25": 53.0},
    },
}

EXPECTED_DIRECTION_MULTIPLIERS_2021 = {
    "A0": {
        "N": 0.90,
        "NE": 0.85,
        "E": 0.85,
        "SE": 0.90,
        "S": 0.90,
        "SW": 0.95,
        "W": 1.00,
        "NW": 0.95,
    },
    "A1": {
        "N": 0.90,
        "NE": 0.85,
        "E": 0.85,
        "SE": 0.80,
        "S": 0.80,
        "SW": 0.95,
        "W": 1.00,
        "NW": 0.95,
    },
    "A2": {
        "N": 0.85,
        "NE": 0.75,
        "E": 0.85,
        "SE": 0.95,
        "S": 0.95,
        "SW": 0.95,
        "W": 1.00,
        "NW": 0.95,
    },
    "A3": {
        "N": 0.90,
        "NE": 0.75,
        "E": 0.75,
        "SE": 0.90,
        "S": 0.90,
        "SW": 0.95,
        "W": 1.00,
        "NW": 0.95,
    },
    "A4": {
        "N": 0.85,
        "NE": 0.75,
        "E": 0.75,
        "SE": 0.80,
        "S": 0.80,
        "SW": 0.90,
        "W": 1.00,
        "NW": 1.00,
    },
    "A5": {
        "N": 0.95,
        "NE": 0.80,
        "E": 0.80,
        "SE": 0.80,
        "S": 0.80,
        "SW": 0.95,
        "W": 1.00,
        "NW": 0.95,
    },
    "B1": {
        "N": 0.75,
        "NE": 0.75,
        "E": 0.85,
        "SE": 0.90,
        "S": 0.95,
        "SW": 0.95,
        "W": 0.95,
        "NW": 0.90,
    },
    "B2": {
        "N": 0.90,
        "NE": 0.90,
        "E": 0.90,
        "SE": 0.90,
        "S": 0.90,
        "SW": 0.90,
        "W": 0.90,
        "NW": 0.90,
    },
    "C": {
        "N": 0.90,
        "NE": 0.90,
        "E": 0.90,
        "SE": 0.90,
        "S": 0.90,
        "SW": 0.90,
        "W": 0.90,
        "NW": 0.90,
    },
    "D": {
        "N": 0.90,
        "NE": 0.90,
        "E": 0.90,
        "SE": 0.90,
        "S": 0.90,
        "SW": 0.90,
        "W": 0.90,
        "NW": 0.90,
    },
}


def packaged_lookup_json(filename: str) -> dict[str, Any]:
    data_path = resources.files("openwind_au.data").joinpath(filename)
    return json.loads(data_path.read_text(encoding="utf-8"))


def test_packaged_regional_wind_speed_table_matches_expected_2021_values() -> None:
    data = packaged_lookup_json("regional_wind_speeds.json")

    assert data["tables"] == EXPECTED_REGIONAL_WIND_SPEEDS_2021
    assert data["source"]["standard"] == "AS/NZS 1170.2:2021"
    assert data["source"]["clause"] == "Section 3"
    assert data["source"]["table"] == "Table 3.1(A) - Regional wind speeds - Australia"
    assert data["source"]["review_status"] == "verified_against_standard"
    assert "licensed standard" in data["source"]["review_note"]


def test_packaged_direction_multiplier_table_matches_expected_2021_values() -> None:
    data = packaged_lookup_json("direction_multipliers.json")

    assert data["tables"] == EXPECTED_DIRECTION_MULTIPLIERS_2021
    assert data["source"]["standard"] == "AS/NZS 1170.2:2021"
    assert data["source"]["clause"] == "Section 3"
    assert data["source"]["table"] == "Table 3.2(A) - Wind direction multiplier (Md) - Australia"
    assert data["source"]["review_status"] == "verified_against_standard"
    assert "licensed standard" in data["source"]["review_note"]
