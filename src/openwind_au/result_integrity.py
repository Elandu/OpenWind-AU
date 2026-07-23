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
from openwind_au.mzcat import indicative_mzcat
from openwind_au.standard_calculations import (
    DIRECTIONS,
    climate_change_multiplier,
    shielding_reduction_height_limit_m,
    site_wind_speed,
)

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
    expected_keys = {("VR", None), ("Mc", None)} | {
        (variable, direction)
        for variable in ("Md", "Mzcat", "Ms", "Mt", "Vsitb")
        for direction in DIRECTIONS
    }
    if set(variables) != expected_keys:
        raise ValueError("Workflow result variable set is incomplete or contains unexpected rows.")

    wind_region = result.wind_region_assessment.wind_region
    if wind_region == "A":
        raise ValueError(
            "Workflow result uses ambiguous wind region A; rerun after confirming A0 through A5."
        )
    if wind_region == "B":
        raise ValueError(
            "Workflow result uses ambiguous wind region B; rerun after confirming B1 or B2."
        )
    if result.direction_multiplier_assessment.wind_region != wind_region:
        raise ValueError("Direction multiplier assessment wind region is inconsistent.")
    if result.regional_wind_speed_assessment.wind_region != wind_region:
        raise ValueError("Regional wind speed assessment wind region is inconsistent.")

    expected_mc = climate_change_multiplier(wind_region)
    mc_variable = variables[("Mc", None)]
    if mc_variable.is_overridden or any(
        not _optional_float_equal(value, expected_mc)
        for value in (
            mc_variable.recommended_value,
            mc_variable.calculated_value,
            mc_variable.final_value,
        )
    ):
        raise ValueError("Climate-change multiplier Mc is inconsistent with the wind region.")

    md_rows = {row.direction: row for row in result.direction_multiplier_assessment.directions}
    if (
        len(result.direction_multiplier_assessment.directions) != len(DIRECTIONS)
        or set(md_rows) != expected_directions
    ):
        raise ValueError(
            "Direction multiplier assessment must contain exactly one row for every direction."
        )
    numeric_md = [float(row.md) for row in md_rows.values() if row.md is not None]
    highest_md = max(numeric_md) if numeric_md else None
    if not _optional_float_equal(
        result.direction_multiplier_assessment.highest_md,
        highest_md,
    ):
        raise ValueError("Direction multiplier assessment highest Md is inconsistent.")
    expected_md_governing = {
        direction
        for direction, row in md_rows.items()
        if highest_md is not None and _optional_float_equal(row.md, highest_md)
    }
    actual_md_governing = {row.direction for row in md_rows.values() if row.is_governing}
    if (
        actual_md_governing != expected_md_governing
        or set(result.direction_multiplier_assessment.governing_directions) != expected_md_governing
    ):
        raise ValueError("Direction multiplier assessment governing summary is inconsistent.")
    for direction, row in md_rows.items():
        recommended_md = variables[("Md", direction)].recommended_value
        if not _optional_float_equal(row.md, recommended_md):
            raise ValueError(
                f"Direction multiplier assessment conflicts with effective Md for {direction}."
            )

    mandatory_md = (
        result.input.wind_direction_multiplier_case == "circular_or_polygonal_chimney_tank_or_pole"
        or result.input.structure_class == "monopole"
        or (
            result.input.wind_direction_multiplier_case == "cladding_or_immediate_support"
            and result.wind_region_assessment.wind_region in {"B2", "C", "D"}
        )
    )
    if mandatory_md and (
        "Clause 3.3" not in result.direction_multiplier_assessment.source_table
        or any(not _optional_float_equal(row.md, 1.0) for row in md_rows.values())
    ):
        raise ValueError("Clause 3.3 mandatory Md assessment is inconsistent.")

    height_limit_m = shielding_reduction_height_limit_m()
    if result.input.reference_height_m > height_limit_m:
        if any(item.variable == "Ms" for item in result.input.workflow_overrides) or any(
            item.ms is not None for item in result.input.class_multiplier_overrides
        ):
            raise ValueError("Clause 4.3.1 mandatory Ms result contains a prohibited override.")
        for direction in DIRECTIONS:
            ms_variable = variables[("Ms", direction)]
            if ms_variable.is_overridden or any(
                not _optional_float_equal(value, 1.0)
                for value in (
                    ms_variable.recommended_value,
                    ms_variable.calculated_value,
                    ms_variable.final_value,
                    rows_by_direction[direction].ms,
                )
            ):
                raise ValueError("Clause 4.3.1 mandatory Ms assessment is inconsistent.")

    if wind_region == "A0":
        if any(item.variable == "Mzcat" for item in result.input.workflow_overrides) or any(
            item.mzcat is not None for item in result.input.class_multiplier_overrides
        ):
            raise ValueError("Region A0 mandatory Mz,cat result contains a prohibited override.")
        expected_mzcat = indicative_mzcat(
            "TC2",
            result.input.reference_height_m,
            wind_region="A0",
        )
        for direction in DIRECTIONS:
            mzcat_variable = variables[("Mzcat", direction)]
            if mzcat_variable.is_overridden or any(
                not _optional_float_equal(value, expected_mzcat)
                for value in (
                    mzcat_variable.recommended_value,
                    mzcat_variable.calculated_value,
                    mzcat_variable.final_value,
                    rows_by_direction[direction].mzcat,
                )
            ):
                raise ValueError("Region A0 mandatory Mz,cat assessment is inconsistent.")

    vr = variables[("VR", None)].final_value
    mc = variables[("Mc", None)].final_value
    for direction in DIRECTIONS:
        row = rows_by_direction[direction]
        inputs = [
            vr,
            mc,
            variables[("Md", direction)].final_value,
            variables[("Mzcat", direction)].final_value,
            variables[("Ms", direction)].final_value,
            variables[("Mt", direction)].final_value,
        ]
        row_inputs = [row.vr, row.mc, row.md, row.mzcat, row.ms, row.mt]
        if any(
            not _optional_float_equal(actual, expected)
            for actual, expected in zip(row_inputs, inputs, strict=True)
        ):
            raise ValueError(f"Workflow result inputs are inconsistent for direction {direction}.")
        complete = all(value is not None for value in inputs)
        expected_recommended = (
            site_wind_speed(
                vr=float(inputs[0]),
                mc=float(inputs[1]),
                md=float(inputs[2]),
                mzcat=float(inputs[3]),
                ms=float(inputs[4]),
                mt=float(inputs[5]),
            )
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
