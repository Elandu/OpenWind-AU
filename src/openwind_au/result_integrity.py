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
    design_wind_speed,
    shielding_reduction_height_limit_m,
    site_wind_speed,
)

if TYPE_CHECKING:
    from openwind_au.models import WindVariableAssessment, WindWorkflowResult

RESULT_SIGNING_KEY_ENV = "OPENWIND_RESULT_SIGNING_KEY"
TOKEN_PREFIX = "owau-hmac-sha256-v1:"
_EPHEMERAL_SIGNING_KEY = secrets.token_bytes(32)
BUILDING_PLAN_FACE_OFFSETS = (
    ("Front", 0.0),
    ("Right", 90.0),
    ("Back", 180.0),
    ("Left", 270.0),
)


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
    valid = hmac.compare_digest(token, expected)
    if not valid:
        legacy_payload = _legacy_canonical_result_bytes(result)
        if legacy_payload is not None:
            legacy_expected = (
                TOKEN_PREFIX
                + hmac.new(
                    _signing_key(),
                    legacy_payload,
                    hashlib.sha256,
                ).hexdigest()
            )
            valid = hmac.compare_digest(token, legacy_expected)
    if not valid:
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

    _validate_mixed_terrain_assessments(result, variables)

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
        governing_value = max(float(row.final_vsitb or 0.0) for row in calculated)
        expected_governing_rows = [
            row
            for row in calculated
            if math.isclose(
                float(row.final_vsitb or 0.0),
                governing_value,
                rel_tol=1e-12,
                abs_tol=1e-9,
            )
        ]
        expected_directions = [row.direction for row in expected_governing_rows]
        if [row.direction for row in governing_rows] != expected_directions:
            raise ValueError("Workflow result governing direction is inconsistent.")
        if result.governing_directions != expected_directions:
            raise ValueError("Workflow result governing directions are inconsistent.")
        expected_governing = max(
            calculated,
            key=lambda row: float(row.final_vsitb or 0.0),
        )
        if result.governing_direction != expected_governing.direction or not _optional_float_equal(
            result.governing_vsitb,
            expected_governing.final_vsitb,
        ):
            raise ValueError("Workflow result governing summary is inconsistent.")
    elif (
        governing_rows
        or result.governing_directions
        or result.governing_direction is not None
        or result.governing_vsitb is not None
    ):
        raise ValueError("Blocked workflow result must not identify a governing wind speed.")

    _validate_design_wind_speeds(result)


def _validate_design_wind_speeds(result: WindWorkflowResult) -> None:
    """Verify the signed Clause 2.3 building-orthogonal design-speed rows."""

    complete_vsitb = all(row.final_vsitb is not None for row in result.directional_vsitb)
    orientation = result.input.structure_orientation_deg
    if orientation is None or not complete_vsitb:
        if (
            result.design_wind_speeds
            or result.governing_vdes_faces
            or result.governing_vdes_mps is not None
        ):
            raise ValueError(
                "Blocked Clause 2.3 design wind speeds must not identify calculated results."
            )
        return

    if [row.face for row in result.design_wind_speeds] != [
        face for face, _offset in BUILDING_PLAN_FACE_OFFSETS
    ]:
        raise ValueError(
            "Workflow result must contain Front, Right, Back, and Left design wind speeds."
        )
    direction_speeds = {
        row.direction: float(row.final_vsitb)
        for row in result.directional_vsitb
        if row.final_vsitb is not None
    }
    expected_design_speeds: list[float] = []
    for row, (face, theta_deg) in zip(
        result.design_wind_speeds,
        BUILDING_PLAN_FACE_OFFSETS,
        strict=True,
    ):
        beta_deg = (float(orientation) + theta_deg) % 360.0
        calculation = design_wind_speed(
            theta_degrees=beta_deg,
            direction_speeds=direction_speeds,
            ultimate_limit_state=True,
        )
        if row.face != face or not _optional_float_equal(row.theta_deg, theta_deg):
            raise ValueError(f"Clause 2.3 plan-face definition is inconsistent for {face}.")
        numeric_pairs = (
            (row.beta_deg, beta_deg),
            (row.sector_start_beta_deg, calculation.sector_start_degrees),
            (row.sector_end_beta_deg, calculation.sector_end_degrees),
            (row.raw_vdes_theta_mps, calculation.raw_maximum_m_s),
            (row.vdes_theta_mps, calculation.design_wind_speed_m_s),
        )
        if any(not _optional_float_equal(actual, expected) for actual, expected in numeric_pairs):
            raise ValueError(f"Clause 2.3 design wind speed is inconsistent for {face}.")
        if row.minimum_uls_applied != calculation.minimum_applied:
            raise ValueError(f"Clause 2.3 ULS minimum status is inconsistent for {face}.")
        if len(row.candidates) != len(calculation.candidates) or any(
            not _optional_float_equal(actual.beta_deg, expected.bearing_degrees)
            or not _optional_float_equal(actual.vsitb_mps, expected.site_wind_speed_m_s)
            for actual, expected in zip(row.candidates, calculation.candidates, strict=True)
        ):
            raise ValueError(f"Clause 2.3 interpolation candidates are inconsistent for {face}.")
        expected_design_speeds.append(calculation.design_wind_speed_m_s)

    governing_value = max(expected_design_speeds)
    expected_governing_faces = [
        row.face
        for row in result.design_wind_speeds
        if math.isclose(
            row.vdes_theta_mps,
            governing_value,
            rel_tol=1e-12,
            abs_tol=1e-9,
        )
    ]
    actual_governing_faces = [row.face for row in result.design_wind_speeds if row.is_governing]
    if (
        actual_governing_faces != expected_governing_faces
        or result.governing_vdes_faces != expected_governing_faces
        or not _optional_float_equal(result.governing_vdes_mps, governing_value)
    ):
        raise ValueError("Clause 2.3 governing design wind speed is inconsistent.")


def _validate_mixed_terrain_assessments(
    result: WindWorkflowResult,
    variables: dict[tuple[str, str | None], WindVariableAssessment],
) -> None:
    """Verify signed Clause 4.2.3 geometry, arithmetic, and Mz,cat linkage."""

    profiles = result.input.mixed_terrain_profiles
    assessments = result.mixed_terrain_assessments
    profile_directions = [profile.direction for profile in profiles]
    assessment_directions = [assessment.direction for assessment in assessments]
    expected_order = [direction for direction in DIRECTIONS if direction in profile_directions]
    if len(profile_directions) != len(set(profile_directions)):
        raise ValueError("Workflow result contains duplicate mixed-terrain profile directions.")
    if assessment_directions != expected_order:
        raise ValueError(
            "Workflow result mixed-terrain assessments do not match the supplied profiles."
        )
    profiles_by_direction = {profile.direction: profile for profile in profiles}
    wind_region = result.wind_region_assessment.wind_region
    if profiles and wind_region != "A0":
        if result.input.average_roof_height_m is None:
            raise ValueError(
                "Mixed-terrain workflow results require an explicit average roof height."
            )
        if result.input.average_roof_height_m > 25.0:
            raise ValueError(
                "Mixed-terrain workflow results cannot use average roof height as z above 25 m."
            )

    for assessment in assessments:
        profile = profiles_by_direction[assessment.direction]
        height = (
            result.input.reference_height_m
            if wind_region == "A0"
            else float(result.input.average_roof_height_m or 0.0)
        )
        expected_basis = (
            "a0_workflow_reference_height" if wind_region == "A0" else "average_roof_height_h"
        )
        lag_distance = 20.0 * height
        averaging_distance = max(500.0, 40.0 * height)
        window_end = lag_distance + averaging_distance
        scalar_pairs = (
            (assessment.assessment_height_z_m, height),
            (assessment.lag_distance_xi_m, lag_distance),
            (assessment.averaging_distance_xa_m, averaging_distance),
            (assessment.window_start_distance_m, lag_distance),
            (assessment.window_end_distance_m, window_end),
        )
        if any(not _optional_float_equal(actual, expected) for actual, expected in scalar_pairs):
            raise ValueError(
                f"Mixed-terrain assessment geometry is inconsistent for {assessment.direction}."
            )
        if assessment.assessment_height_basis != expected_basis:
            raise ValueError(
                f"Mixed-terrain assessment height basis is inconsistent for {assessment.direction}."
            )
        if not _optional_float_equal(
            assessment.reference_height_h_m,
            result.input.average_roof_height_m,
        ):
            raise ValueError(
                f"Mixed-terrain reference height is inconsistent for {assessment.direction}."
            )
        if assessment.profile_source_reference != profile.source_reference:
            raise ValueError(
                f"Mixed-terrain profile provenance is inconsistent for {assessment.direction}."
            )
        if not assessment.lookup_source_reference.strip():
            raise ValueError(
                f"Mixed-terrain lookup provenance is missing for {assessment.direction}."
            )

        if wind_region == "A0":
            if assessment.mode != "a0_mandatory":
                raise ValueError("Region A0 mixed-terrain assessment mode is inconsistent.")
            if assessment.contributions or not _optional_float_equal(
                assessment.covered_distance_m,
                0.0,
            ):
                raise ValueError(
                    "Region A0 terrain evidence must not contain weighted contributions."
                )
            mandatory_mzcat = indicative_mzcat("TC2", height, wind_region="A0")
            if not _optional_float_equal(assessment.weighted_mzcat, mandatory_mzcat):
                raise ValueError("Region A0 mandatory Mz,cat is inconsistent.")
        else:
            expected_segments = []
            for segment in profile.segments:
                clipped_start = max(float(segment.start_distance_m), lag_distance)
                clipped_end = min(float(segment.end_distance_m), window_end)
                if clipped_end > clipped_start:
                    expected_segments.append((segment, clipped_start, clipped_end))
            if len(assessment.contributions) != len(expected_segments):
                raise ValueError(
                    f"Mixed-terrain contributions are incomplete for {assessment.direction}."
                )
            for contribution, (segment, clipped_start, clipped_end) in zip(
                assessment.contributions,
                expected_segments,
                strict=True,
            ):
                included_length = clipped_end - clipped_start
                weight_fraction = included_length / averaging_distance
                if (
                    contribution.terrain_category != segment.terrain_category
                    or contribution.source_reference != segment.source_reference
                    or any(
                        not _optional_float_equal(actual, expected)
                        for actual, expected in (
                            (contribution.start_distance_m, segment.start_distance_m),
                            (contribution.end_distance_m, segment.end_distance_m),
                            (contribution.clipped_start_distance_m, clipped_start),
                            (contribution.clipped_end_distance_m, clipped_end),
                            (contribution.included_length_m, included_length),
                            (contribution.weight_fraction, weight_fraction),
                            (
                                contribution.weighted_contribution,
                                contribution.table_mzcat * weight_fraction,
                            ),
                        )
                    )
                ):
                    raise ValueError(
                        f"Mixed-terrain contribution is inconsistent for {assessment.direction}."
                    )

            covered_distance = math.fsum(
                contribution.included_length_m for contribution in assessment.contributions
            )
            if not _optional_float_equal(assessment.covered_distance_m, covered_distance):
                raise ValueError(
                    f"Mixed-terrain covered distance is inconsistent for {assessment.direction}."
                )
            if not _optional_float_equal(covered_distance, averaging_distance):
                raise ValueError(
                    f"Mixed-terrain coverage is incomplete for {assessment.direction}."
                )
            categories = {
                contribution.terrain_category for contribution in assessment.contributions
            }
            expected_mode = "homogeneous" if len(categories) == 1 else "mixed_weighted"
            if assessment.mode != expected_mode:
                raise ValueError(
                    f"Mixed-terrain calculation mode is inconsistent for {assessment.direction}."
                )
            weighted_mzcat = (
                math.fsum(
                    contribution.table_mzcat * contribution.included_length_m
                    for contribution in assessment.contributions
                )
                / covered_distance
            )
            if not _optional_float_equal(assessment.weighted_mzcat, weighted_mzcat):
                raise ValueError(
                    f"Mixed-terrain weighted Mz,cat is inconsistent for {assessment.direction}."
                )

        mzcat_variable = variables[("Mzcat", assessment.direction)]
        if any(
            not _optional_float_equal(value, assessment.weighted_mzcat)
            for value in (
                mzcat_variable.recommended_value,
                mzcat_variable.calculated_value,
            )
        ):
            raise ValueError(
                f"Mixed-terrain Mz,cat variable is inconsistent for {assessment.direction}."
            )


def _canonical_result_bytes(result: WindWorkflowResult) -> bytes:
    payload = result.model_dump(mode="json", exclude={"integrity_token"})
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _legacy_canonical_result_bytes(result: WindWorkflowResult) -> bytes | None:
    """Project empty post-v1 fields out so previously issued v1 tokens remain valid."""

    if result.input.mixed_terrain_profiles or result.mixed_terrain_assessments:
        return None
    payload = result.model_dump(mode="json", exclude={"integrity_token"})
    input_payload = payload.get("input")
    if isinstance(input_payload, dict):
        input_payload.pop("mixed_terrain_profiles", None)
    payload.pop("mixed_terrain_assessments", None)
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
