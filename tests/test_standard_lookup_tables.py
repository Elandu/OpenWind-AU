"""Validation tests for packaged AS/NZS 1170.2:2021 lookup tables."""

from __future__ import annotations

import json
from copy import deepcopy
from importlib import resources
from typing import Any

import pytest

from openwind_au.errors import ServiceNotReadyError
from openwind_au.mzcat import mzcat_lookup_issues
from openwind_au.standard_calculations import shielding_lookup_issues
from openwind_au.standard_lookup_tables import (
    MAX_LOOKUP_FILE_BYTES,
    MS_DATA_FILE,
    MS_EXPECTED_SHA256_ENV,
    MZCAT_DATA_FILE,
    MZCAT_EXPECTED_SHA256_ENV,
    PENDING_LOOKUP_REVIEW_STATUS,
    VERIFIED_LOOKUP_REVIEW_STATUS,
    canonical_values_sha256,
    load_lookup_data,
    load_packaged_lookup_data,
)

EXPECTED_REGIONAL_WIND_SPEEDS_2021 = {
    "A": {
        "ultimate": {
            "1": 30.0,
            "5": 32.0,
            "10": 34.0,
            "20": 37.0,
            "25": 37.0,
            "50": 39.0,
            "100": 41.0,
            "200": 43.0,
            "250": 43.0,
            "500": 45.0,
            "1000": 46.0,
            "2000": 48.0,
            "2500": 48.0,
            "5000": 50.0,
            "10000": 51.0,
        },
        "serviceability": {"25": 37.0},
    },
    "B": {
        "ultimate": {
            "1": 26.0,
            "5": 28.0,
            "10": 33.0,
            "20": 38.0,
            "25": 39.0,
            "50": 44.0,
            "100": 48.0,
            "200": 52.0,
            "250": 53.0,
            "500": 57.0,
            "1000": 60.0,
            "2000": 63.0,
            "2500": 64.0,
            "5000": 67.0,
            "10000": 69.0,
        },
        "serviceability": {"25": 39.0},
    },
    "C": {
        "ultimate": {
            "1": 23.0,
            "5": 33.0,
            "10": 39.0,
            "20": 45.0,
            "25": 47.0,
            "50": 52.0,
            "100": 56.0,
            "200": 61.0,
            "250": 62.0,
            "500": 66.0,
            "1000": 70.0,
            "2000": 73.0,
            "2500": 74.0,
            "5000": 78.0,
            "10000": 81.0,
        },
        "serviceability": {"25": 47.0},
    },
    "D": {
        "ultimate": {
            "1": 23.0,
            "5": 35.0,
            "10": 43.0,
            "20": 51.0,
            "25": 53.0,
            "50": 60.0,
            "100": 66.0,
            "200": 72.0,
            "250": 74.0,
            "500": 80.0,
            "1000": 85.0,
            "2000": 90.0,
            "2500": 91.0,
            "5000": 95.0,
            "10000": 99.0,
        },
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

EXPECTED_MZCAT_ROWS_2021 = [
    [0.97, 0.91, 0.87, 0.83, 0.75],
    [1.01, 0.91, 0.87, 0.83, 0.75],
    [1.08, 1.00, 0.92, 0.83, 0.75],
    [1.12, 1.05, 0.97, 0.89, 0.75],
    [1.14, 1.08, 1.01, 0.94, 0.75],
    [1.18, 1.12, 1.06, 1.00, 0.80],
    [1.21, 1.16, 1.10, 1.04, 0.85],
    [1.23, 1.18, 1.13, 1.07, 0.90],
    [1.27, 1.22, 1.17, 1.12, 0.98],
    [1.31, 1.24, 1.20, 1.16, 1.03],
    [1.36, 1.27, 1.24, 1.21, 1.11],
    [1.39, 1.29, 1.27, 1.24, 1.16],
]

EXPECTED_MS_POINTS_2021 = [
    {"s": 1.5, "ms": 0.7},
    {"s": 3.0, "ms": 0.8},
    {"s": 6.0, "ms": 0.9},
    {"s": 12.0, "ms": 1.0},
]


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


def test_packaged_terrain_height_table_matches_independent_2021_snapshot() -> None:
    data = load_packaged_lookup_data(MZCAT_DATA_FILE)

    assert data["values"]["rows"] == EXPECTED_MZCAT_ROWS_2021
    assert data["values"]["categories"] == [1.0, 2.0, 2.5, 3.0, 4.0]
    assert data["values"]["heights_m"] == [
        3.0,
        5.0,
        10.0,
        15.0,
        20.0,
        30.0,
        40.0,
        50.0,
        75.0,
        100.0,
        150.0,
        200.0,
    ]
    assert data["source"]["table"] == "Table 4.1"
    assert data["source"]["review_status"] == PENDING_LOOKUP_REVIEW_STATUS
    assert data["values_sha256"] == canonical_values_sha256(data)
    assert mzcat_lookup_issues(data, require_reviewed=False) == []
    assert "source.reviewed_by" in " ".join(mzcat_lookup_issues(data))
    assert "source.reviewed_on" in " ".join(mzcat_lookup_issues(data))


def test_packaged_shielding_table_matches_independent_2021_snapshot() -> None:
    data = load_packaged_lookup_data(MS_DATA_FILE)

    assert data["values"]["points"] == EXPECTED_MS_POINTS_2021
    assert data["values"]["maximum_reduction_building_height_m"] == 25.0
    assert data["source"]["table"] == "Table 4.2"
    assert data["source"]["review_status"] == PENDING_LOOKUP_REVIEW_STATUS
    assert data["values_sha256"] == canonical_values_sha256(data)
    assert shielding_lookup_issues(data, require_reviewed=False) == []
    assert "source.reviewed_by" in " ".join(shielding_lookup_issues(data))
    assert "source.reviewed_on" in " ".join(shielding_lookup_issues(data))


@pytest.mark.parametrize(
    ("filename", "validator"),
    [
        (MZCAT_DATA_FILE, mzcat_lookup_issues),
        (MS_DATA_FILE, shielding_lookup_issues),
    ],
)
def test_complete_reviewer_and_date_metadata_satisfies_readiness(filename, validator) -> None:
    data = load_packaged_lookup_data(filename)
    data["source"].update(
        {
            "review_status": VERIFIED_LOOKUP_REVIEW_STATUS,
            "reviewed_by": "Independent Engineer",
            "reviewed_on": "2026-07-12",
        }
    )

    assert validator(data) == []


def test_review_metadata_rejects_invalid_date_and_empty_reviewer() -> None:
    data = load_packaged_lookup_data(MZCAT_DATA_FILE)
    data["source"].update(
        {
            "review_status": VERIFIED_LOOKUP_REVIEW_STATUS,
            "reviewed_by": "   ",
            "reviewed_on": "2026-02-30",
        }
    )

    issues = mzcat_lookup_issues(data)

    assert any("source.reviewed_by must identify" in issue for issue in issues)
    assert "source.reviewed_on must be a valid ISO date (YYYY-MM-DD)" in issues


def test_changed_values_require_an_out_of_band_expected_digest(monkeypatch) -> None:
    data = load_packaged_lookup_data(MZCAT_DATA_FILE)
    data["values"]["rows"][2][3] = 0.84
    replacement_digest = canonical_values_sha256(data)
    data["values_sha256"] = replacement_digest

    assert "calculation values do not match the trusted expected digest" in mzcat_lookup_issues(
        data,
        require_reviewed=False,
    )

    monkeypatch.setenv(MZCAT_EXPECTED_SHA256_ENV, replacement_digest)
    assert mzcat_lookup_issues(data, require_reviewed=False) == []


def test_invalid_out_of_band_expected_digest_is_rejected(monkeypatch) -> None:
    data = load_packaged_lookup_data(MS_DATA_FILE)
    monkeypatch.setenv(MS_EXPECTED_SHA256_ENV, "not-a-sha256")

    issues = shielding_lookup_issues(data, require_reviewed=False)

    assert any(MS_EXPECTED_SHA256_ENV in issue for issue in issues)


def test_normative_a0_rule_cannot_be_changed_by_a_trusted_override(monkeypatch) -> None:
    data = load_packaged_lookup_data(MZCAT_DATA_FILE)
    data["values"]["a0_rule"]["constant_above_value"] = 9.9
    replacement_digest = canonical_values_sha256(data)
    data["values_sha256"] = replacement_digest
    monkeypatch.setenv(MZCAT_EXPECTED_SHA256_ENV, replacement_digest)

    assert "a0_rule must match the normative A0 Table 4.1 rule" in mzcat_lookup_issues(
        data,
        require_reviewed=False,
    )


def test_normative_ms_nodes_and_height_limit_cannot_be_changed(monkeypatch) -> None:
    data = load_packaged_lookup_data(MS_DATA_FILE)
    data["values"]["maximum_reduction_building_height_m"] = 500.0
    data["values"]["points"][0]["s"] = 1.0
    replacement_digest = canonical_values_sha256(data)
    data["values_sha256"] = replacement_digest
    monkeypatch.setenv(MS_EXPECTED_SHA256_ENV, replacement_digest)

    issues = shielding_lookup_issues(data, require_reviewed=False)

    assert "maximum_reduction_building_height_m must be the normative 25 m" in issues
    assert "shielding parameter points must use the normative Table 4.2 nodes" in issues


def test_normative_source_metadata_must_match_exactly() -> None:
    data = deepcopy(load_packaged_lookup_data(MZCAT_DATA_FILE))
    data["source"]["clause"] = "Clause 4"

    assert "source.clause must be Clauses 4.2.2 and 4.2.3" in mzcat_lookup_issues(
        data,
        require_reviewed=False,
    )


def test_lookup_loader_rejects_duplicate_keys(monkeypatch, tmp_path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version": 1, "values": {}, "values": {}}', encoding="utf-8")
    monkeypatch.setenv("OPENWIND_TEST_LOOKUP_PATH", str(path))

    with pytest.raises(ServiceNotReadyError, match="duplicate object keys"):
        load_lookup_data("OPENWIND_TEST_LOOKUP_PATH", MZCAT_DATA_FILE)


def test_lookup_loader_rejects_oversized_files(monkeypatch, tmp_path) -> None:
    path = tmp_path / "oversized.json"
    path.write_bytes(b" " * (MAX_LOOKUP_FILE_BYTES + 1))
    monkeypatch.setenv("OPENWIND_TEST_LOOKUP_PATH", str(path))

    with pytest.raises(ServiceNotReadyError, match="byte limit"):
        load_lookup_data("OPENWIND_TEST_LOOKUP_PATH", MZCAT_DATA_FILE)


def test_lookup_loader_rejects_nonfinite_json_constants(monkeypatch, tmp_path) -> None:
    path = tmp_path / "nonfinite.json"
    path.write_text('{"values": {"value": NaN}}', encoding="utf-8")
    monkeypatch.setenv("OPENWIND_TEST_LOOKUP_PATH", str(path))

    with pytest.raises(ServiceNotReadyError, match="non-finite"):
        load_lookup_data("OPENWIND_TEST_LOOKUP_PATH", MZCAT_DATA_FILE)
