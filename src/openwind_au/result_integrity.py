"""Integrity sealing and structural checks for completed workflow results."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
from typing import TYPE_CHECKING

from openwind_au.errors import ServiceNotReadyError
from openwind_au.standard_calculations import DIRECTIONS, site_wind_speed

if TYPE_CHECKING:
    from openwind_au.models import WindVariableAssessment, WindWorkflowResult

RESULT_SIGNING_KEY_ENV = "OPENWIND_RESULT_SIGNING_KEY"
TOKEN_PREFIX = "owau-hmac-sha256-v1:"
_EPHEMERAL_SIGNING_KEY = secrets.token_bytes(32)


def result_signing_key_is_configured() -> bool:
    """Return whether a durable deployment signing key is configured."""

    value = os.getenv(RESULT_SIGNING_KEY_ENV)
    return bool(value and len(value.encode("utf-8")) >= 32)


def result_signing_readiness() -> dict[str, object]:
    """Return consumer-safe readiness details for completed-result sealing."""

    configured = os.getenv(RESULT_SIGNING_KEY_ENV) is not None
    ready = result_signing_key_is_configured()
    if ready:
        detail = "A durable result-signing key is configured."
    elif configured:
        detail = f"{RESULT_SIGNING_KEY_ENV} is configured but contains fewer than 32 UTF-8 bytes."
    else:
        detail = (
            f"{RESULT_SIGNING_KEY_ENV} must contain at least 32 UTF-8 bytes for durable "
            "completed-result verification. An ephemeral development key is active."
        )
    return {
        "ready": ready,
        "configured": configured,
        "detail": detail,
    }


def seal_workflow_result(result: WindWorkflowResult) -> WindWorkflowResult:
    """Validate and return a workflow result with a server-issued HMAC token."""

    validate_workflow_result_structure(result)
    token = (
        TOKEN_PREFIX
        + hmac.new(
            _signing_key(),
            _canonical_result_bytes(result),
            hashlib.sha256,
        ).hexdigest()
    )
    return result.model_copy(update={"integrity_token": token})


def verify_workflow_result(result: WindWorkflowResult) -> None:
    """Reject unsigned, modified, or structurally inconsistent workflow results."""

    token = result.integrity_token
    if not token or not token.startswith(TOKEN_PREFIX):
        raise ValueError(
            "Completed workflow result is missing its server-issued integrity token; rerun "
            "the workflow before generating a report."
        )
    validate_workflow_result_structure(result)
    expected = (
        TOKEN_PREFIX
        + hmac.new(
            _signing_key(),
            _canonical_result_bytes(result),
            hashlib.sha256,
        ).hexdigest()
    )
    if not hmac.compare_digest(token, expected):
        raise ValueError(
            "Completed workflow result failed integrity verification; rerun the workflow "
            "before generating a report."
        )


def validate_workflow_result_structure(result: WindWorkflowResult) -> None:
    """Check the signed result is internally complete and calculation-consistent."""

    expected_directions = set(DIRECTIONS)
    rows_by_direction = {row.direction: row for row in result.directional_vsitb}
    if len(result.directional_vsitb) != len(DIRECTIONS) or set(rows_by_direction) != (
        expected_directions
    ):
        raise ValueError("Workflow result must contain exactly one row for every direction.")

    variables: dict[tuple[str, str | None], WindVariableAssessment] = {}
    for item in result.variables:
        key = (item.variable, item.direction)
        if key in variables:
            raise ValueError(f"Workflow result contains duplicate variable {key!r}.")
        variables[key] = item
    expected_keys = {("VR", None)} | {
        (variable, direction)
        for variable in ("Md", "Mzcat", "Ms", "Mt", "Vsitb")
        for direction in DIRECTIONS
    }
    if set(variables) != expected_keys:
        raise ValueError("Workflow result variable set is incomplete or contains unexpected rows.")

    vr = variables[("VR", None)].final_value
    for direction in DIRECTIONS:
        row = rows_by_direction[direction]
        inputs = [
            vr,
            variables[("Md", direction)].final_value,
            variables[("Mzcat", direction)].final_value,
            variables[("Ms", direction)].final_value,
            variables[("Mt", direction)].final_value,
        ]
        row_inputs = [row.vr, row.md, row.mzcat, row.ms, row.mt]
        if any(
            not _optional_float_equal(actual, expected)
            for actual, expected in zip(row_inputs, inputs, strict=True)
        ):
            raise ValueError(f"Workflow result inputs are inconsistent for direction {direction}.")
        complete = all(value is not None for value in inputs)
        expected_recommended = (
            site_wind_speed(*(float(value) for value in inputs if value is not None))
            if complete
            else None
        )
        if not _optional_float_equal(row.recommended_vsitb, expected_recommended):
            raise ValueError(f"Workflow result Vsit,b product is inconsistent for {direction}.")
        vsitb = variables[("Vsitb", direction)]
        if not _optional_float_equal(vsitb.recommended_value, row.recommended_vsitb):
            raise ValueError(
                f"Workflow result Vsit,b recommendation is inconsistent for {direction}."
            )
        if not _optional_float_equal(vsitb.final_value, row.final_vsitb):
            raise ValueError(f"Workflow result final Vsit,b is inconsistent for {direction}.")
        expected_status = "calculated" if complete else "blocked"
        if row.status != expected_status:
            raise ValueError(f"Workflow result status is inconsistent for direction {direction}.")

    calculated = [row for row in result.directional_vsitb if row.final_vsitb is not None]
    governing_rows = [row for row in calculated if row.is_governing]
    if calculated:
        expected_governing = max(calculated, key=lambda row: float(row.final_vsitb or 0.0))
        if len(governing_rows) != 1 or governing_rows[0].direction != expected_governing.direction:
            raise ValueError("Workflow result governing direction is inconsistent.")
        if result.governing_direction != expected_governing.direction or not _optional_float_equal(
            result.governing_vsitb,
            expected_governing.final_vsitb,
        ):
            raise ValueError("Workflow result governing summary is inconsistent.")
    elif (
        governing_rows
        or result.governing_direction is not None
        or result.governing_vsitb is not None
    ):
        raise ValueError("Blocked workflow result must not identify a governing wind speed.")


def _canonical_result_bytes(result: WindWorkflowResult) -> bytes:
    payload = result.model_dump(mode="json", exclude={"integrity_token"})
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _signing_key() -> bytes:
    configured = os.getenv(RESULT_SIGNING_KEY_ENV)
    if configured is None:
        return _EPHEMERAL_SIGNING_KEY
    key = configured.encode("utf-8")
    if len(key) < 32:
        raise ServiceNotReadyError(
            f"{RESULT_SIGNING_KEY_ENV} must contain at least 32 UTF-8 bytes."
        )
    return key


def _optional_float_equal(actual: float | None, expected: float | None) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
