"""Shared loading and provenance checks for editable AS/NZS lookup data."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from copy import deepcopy
from datetime import date
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

VR_TABLE_ENV = "OPENWIND_VR_TABLE_PATH"
MD_TABLE_ENV = "OPENWIND_MD_TABLE_PATH"
MZCAT_TABLE_ENV = "OPENWIND_MZCAT_TABLE_PATH"
MS_TABLE_ENV = "OPENWIND_MS_TABLE_PATH"
MZCAT_EXPECTED_SHA256_ENV = "OPENWIND_MZCAT_EXPECTED_SHA256"
MS_EXPECTED_SHA256_ENV = "OPENWIND_MS_EXPECTED_SHA256"

VR_DATA_FILE = "regional_wind_speeds.json"
MD_DATA_FILE = "direction_multipliers.json"
MZCAT_DATA_FILE = "terrain_height_multipliers.json"
MS_DATA_FILE = "shielding_multipliers.json"

VERIFIED_LOOKUP_REVIEW_STATUS = "verified_against_standard"
PENDING_LOOKUP_REVIEW_STATUS = "pending_independent_review"
AS_NZS_1170_2_EDITION = "AS/NZS 1170.2:2021 incorporating Amendments 1 and 2"
MAX_LOOKUP_FILE_BYTES = 256_000
TRUSTED_PACKAGED_VALUES_SHA256: dict[str, str] = {
    MZCAT_DATA_FILE: "0a89849ef40a1ad376c1dabb11614095afbdb27c7278a331aec31ab5182275b5",
    MS_DATA_FILE: "fc337acb9f85996304b3532b6572a1c99164244af1a34074581604eebfe2d531",
}
_KNOWN_LOOKUP_DATA_FILES = frozenset({VR_DATA_FILE, MD_DATA_FILE, MZCAT_DATA_FILE, MS_DATA_FILE})
_SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
_ISO_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def load_lookup_data(env_var: str, package_file: str) -> dict[str, Any]:
    """Load lookup JSON from an explicit path or the packaged data directory."""

    configured = os.environ.get(env_var)
    if configured:
        path = Path(configured).expanduser().resolve()
        return deepcopy(_parse_lookup_bytes(_read_bounded_path(path)))
    return load_packaged_lookup_data(package_file)


def load_packaged_lookup_data(package_file: str) -> dict[str, Any]:
    """Load one immutable lookup bundled in the installed package."""

    if package_file not in _KNOWN_LOOKUP_DATA_FILES:
        raise ValueError(f"Unsupported packaged lookup file: {package_file}")
    return deepcopy(_load_packaged_data(package_file))


def _read_bounded_path(path: Path) -> bytes:
    """Read a small lookup file without trusting a pre-read file-size check."""

    with path.open("rb") as stream:
        raw = stream.read(MAX_LOOKUP_FILE_BYTES + 1)
    if len(raw) > MAX_LOOKUP_FILE_BYTES:
        raise ValueError(f"Lookup JSON exceeds the {MAX_LOOKUP_FILE_BYTES}-byte limit")
    return raw


@lru_cache(maxsize=16)
def _load_packaged_data(package_file: str) -> dict[str, Any]:
    data_path = resources.files("openwind_au.data").joinpath(package_file)
    raw = data_path.read_bytes()
    if len(raw) > MAX_LOOKUP_FILE_BYTES:
        raise ValueError(f"Packaged lookup JSON exceeds the {MAX_LOOKUP_FILE_BYTES}-byte limit")
    return _parse_lookup_bytes(raw)


@lru_cache(maxsize=32)
def _parse_lookup_bytes(raw: bytes) -> dict[str, Any]:
    """Parse bounded UTF-8 JSON while rejecting duplicate keys and non-finite constants."""

    if len(raw) > MAX_LOOKUP_FILE_BYTES:
        raise ValueError(f"Lookup JSON exceeds the {MAX_LOOKUP_FILE_BYTES}-byte limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Lookup JSON must be valid UTF-8") from exc
    try:
        data = json.loads(
            text,
            object_pairs_hook=_unique_object_pairs,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("Lookup file must contain valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Lookup JSON root must be an object")
    return data


def _unique_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Lookup JSON must not contain duplicate object keys")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("Lookup JSON must not contain non-finite numeric constants")


def canonical_values_sha256(data: dict[str, Any]) -> str:
    """Return the stable digest for a lookup's calculation-affecting values."""

    encoded = json.dumps(
        data.get("values"),
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def lookup_provenance_issues(
    data: dict[str, Any],
    *,
    expected_clause: str,
    expected_standard_reference: str,
    expected_table: str,
    expected_values_sha256: str,
    require_reviewed: bool,
) -> list[str]:
    """Return deterministic source, schema, and digest validation failures."""

    issues: list[str] = []
    if data.get("schema_version") != 1:
        issues.append("schema_version must be 1")
    source = data.get("source")
    if not isinstance(source, dict):
        issues.append("source metadata is required")
    else:
        if source.get("standard") != AS_NZS_1170_2_EDITION:
            issues.append("source.standard does not identify the configured Standard edition")
        if source.get("clause") != expected_clause:
            issues.append(f"source.clause must be {expected_clause}")
        if source.get("table") != expected_table:
            issues.append(f"source.table must be {expected_table}")
        if source.get("standard_reference") != expected_standard_reference:
            issues.append("source.standard_reference does not match the configured lookup")
        for field in ("title", "status", "review_note"):
            value = source.get(field)
            if not isinstance(value, str) or not value.strip():
                issues.append(f"source.{field} must be a non-empty string")
        if require_reviewed:
            issues.extend(lookup_review_issues(data))
    digest = data.get("values_sha256")
    if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
        issues.append("values_sha256 must be a 64-character hexadecimal SHA-256 digest")
    else:
        try:
            actual_digest = canonical_values_sha256(data)
        except (TypeError, ValueError):
            issues.append("values must be canonical JSON without non-finite numbers")
        else:
            if digest.lower() != actual_digest:
                issues.append("values_sha256 does not match the calculation values")
            if actual_digest != expected_values_sha256:
                issues.append("calculation values do not match the trusted expected digest")
    return issues


def trusted_values_sha256(*, package_file: str, expected_digest_env: str) -> str:
    """Return an out-of-band expected values digest for a packaged or override lookup."""

    configured = os.environ.get(expected_digest_env)
    digest = configured.strip() if configured is not None else ""
    if not digest:
        try:
            digest = TRUSTED_PACKAGED_VALUES_SHA256[package_file]
        except KeyError as exc:
            raise ValueError(f"No trusted digest is configured for {package_file}") from exc
    if not _SHA256_PATTERN.fullmatch(digest):
        raise ValueError(f"{expected_digest_env} must be a 64-character hexadecimal SHA-256 digest")
    return digest.lower()


def lookup_review_issues(data: dict[str, Any]) -> list[str]:
    """Return missing or malformed independent-review metadata."""

    source = data.get("source")
    if not isinstance(source, dict):
        return ["source metadata is required for independent review"]
    issues: list[str] = []
    if source.get("review_status") != VERIFIED_LOOKUP_REVIEW_STATUS:
        issues.append("source.review_status is not verified_against_standard")
    reviewer = source.get("reviewed_by")
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer.strip()) > 200:
        issues.append("source.reviewed_by must identify the independent reviewer")
    reviewed_on = source.get("reviewed_on")
    if not _valid_iso_date(reviewed_on):
        issues.append("source.reviewed_on must be a valid ISO date (YYYY-MM-DD)")
    return issues


def lookup_is_reviewed(data: dict[str, Any]) -> bool:
    """Return whether independent-review metadata is complete and valid."""

    return not lookup_review_issues(data)


def _valid_iso_date(value: Any) -> bool:
    if not isinstance(value, str) or not _ISO_DATE_PATTERN.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def lookup_metadata_warnings(data: dict[str, Any], warning: str) -> list[str]:
    """Return a warning when independent reviewer/date metadata is incomplete."""

    if lookup_is_reviewed(data):
        return []
    return [warning]


def source_reference(data: dict[str, Any]) -> str:
    """Build a compact source reference string from lookup metadata."""

    source = data.get("source", {})
    if not isinstance(source, dict):
        return "Lookup source metadata unavailable."
    parts = [
        source.get("title"),
        source.get("standard_reference"),
        (
            f"schema_version={data.get('schema_version')}"
            if data.get("schema_version") is not None
            else None
        ),
        source.get("review_status"),
        source.get("reviewed_by"),
        source.get("reviewed_on"),
        source.get("status"),
        f"values_sha256={data.get('values_sha256')}" if data.get("values_sha256") else None,
    ]
    return "; ".join(str(part) for part in parts if part)


def lookup_provenance_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    """Return serialisable provenance for the exact lookup snapshot used."""

    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    return {
        "schema_version": data.get("schema_version"),
        "standard_reference": source.get("standard_reference"),
        "review_status": source.get("review_status"),
        "reviewed_by": source.get("reviewed_by"),
        "reviewed_on": source.get("reviewed_on"),
        "values_sha256": data.get("values_sha256"),
        "independent_review_recorded": lookup_is_reviewed(data),
        "source_reference": source_reference(data),
    }


def finite_lookup_number(
    value: Any,
    *,
    minimum: float,
    maximum: float | None = None,
    minimum_inclusive: bool = False,
) -> bool:
    """Return whether a lookup value is a bounded finite non-boolean number."""

    if not isinstance(value, int | float) or isinstance(value, bool):
        return False
    number = float(value)
    if not math.isfinite(number):
        return False
    invalid_minimum = number < minimum if minimum_inclusive else number <= minimum
    return not invalid_minimum and (maximum is None or number <= maximum)
