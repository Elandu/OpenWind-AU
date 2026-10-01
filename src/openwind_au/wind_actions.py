# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Elandu and contributors

"""Reviewed AS/NZS 1170.2 pressure cases mapped to tributary frame loads.

Aerodynamic shape factors and tributary geometry are reviewed inputs. This
module applies the standard pressure equation and distributes its resultant; it
does not select coefficients, design combinations, or structural capacities.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from openwind_au.models import WindDirection

STANDARD = "AS/NZS 1170.2:2021"
AIR_DENSITY_KG_M3 = 1.2
PRESSURE_EQUATION = "2.4(1)"
FORCE_EQUATION = "2.5(1)"
_LIMIT_STATES = ("ultimate", "serviceability")
_DIRECTIONS = ("Fx", "Fy", "Fz")


class WindPressureCaseInput(BaseModel):
    """One selected direction/limit-state case with separate speed provenance."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    case_id: str = Field(min_length=1, max_length=100)
    source_run_id: str = Field(min_length=1, max_length=200)
    standard: Literal["AS/NZS 1170.2:2021"] = STANDARD
    limit_state: Literal["ultimate", "serviceability"]
    wind_direction: WindDirection
    vdes_external_mps: float = Field(gt=0, json_schema_extra={"unit": "m/s"})
    vdes_internal_mps: float = Field(gt=0, json_schema_extra={"unit": "m/s"})
    dynamic_wind_sensitive: bool

    @model_validator(mode="after")
    def validate_scope(self) -> WindPressureCaseInput:
        if self.dynamic_wind_sensitive:
            raise ValueError(
                "Dynamically wind-sensitive structures are unsupported; determine C_dyn "
                "and wind actions under Section 6 before frame-load mapping."
            )
        if (
            self.limit_state == "ultimate"
            and min(self.vdes_external_mps, self.vdes_internal_mps) < 30.0
        ):
            raise ValueError(
                "Clause 2.3 requires Vdes,theta of at least 30 m/s for ultimate limit states."
            )
        return self


class WindPanelInput(BaseModel):
    """One uniformly pressured panel using separately reviewed aggregate Cshp values."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    panel_id: str = Field(min_length=1, max_length=100)
    case_id: str = Field(min_length=1, max_length=100)
    area_m2: float = Field(gt=0)
    cshp_external: float
    cshp_internal: float
    external_coefficient_reference: str = Field(min_length=1, max_length=300)
    internal_coefficient_reference: str = Field(min_length=1, max_length=300)
    area_review_reference: str = Field(min_length=1, max_length=300)
    coefficient_reviewer: str = Field(min_length=1, max_length=200)
    coefficient_review_date: date
    coefficient_review_note: str = Field(min_length=1, max_length=1000)


class TributaryMemberInput(BaseModel):
    """A reviewed panel-area share assigned to a beam/column segment."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    panel_id: str = Field(min_length=1, max_length=100)
    member_id: str = Field(min_length=1, max_length=100)
    member_length_m: float = Field(gt=0)
    x_start_m: float = Field(ge=0)
    x_end_m: float = Field(gt=0)
    tributary_width_m: float = Field(gt=0)
    direction: Literal["Fx", "Fy", "Fz"]
    axis_reference: str = Field(min_length=1, max_length=300)
    positive_direction_toward_inside: bool


class WindFrameLoadRequest(BaseModel):
    """Explicit pressure-to-frame conversion request.

    Tributary rectangles must exactly partition each reviewed panel area.
    ``axis_reference`` documents the model coordinate convention and each
    segment's positive axis is explicitly related to the panel's inside normal.
    """

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    pressure_cases: list[WindPressureCaseInput] = Field(min_length=1)
    panels: list[WindPanelInput] = Field(min_length=1)
    tributary_members: list[TributaryMemberInput] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references_and_geometry(self) -> WindFrameLoadRequest:
        case_ids = [case.case_id for case in self.pressure_cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("pressure case_id values must be unique.")
        panel_ids = [panel.panel_id for panel in self.panels]
        if len(panel_ids) != len(set(panel_ids)):
            raise ValueError("panel_id values must be unique.")
        known_cases = set(case_ids)
        known_panels = set(panel_ids)
        for panel in self.panels:
            if panel.case_id not in known_cases:
                raise ValueError(f"Panel {panel.panel_id!r} references an unknown pressure case.")
        grouped: dict[str, list[TributaryMemberInput]] = {}
        for tributary in self.tributary_members:
            if tributary.panel_id not in known_panels:
                raise ValueError(
                    f"Member tributary references unknown panel {tributary.panel_id!r}."
                )
            if tributary.x_end_m > tributary.member_length_m:
                raise ValueError(
                    f"Member {tributary.member_id!r} tributary end exceeds its length."
                )
            if tributary.x_end_m <= tributary.x_start_m:
                raise ValueError("Each tributary member segment must have positive length.")
            grouped.setdefault(tributary.panel_id, []).append(tributary)

        missing = known_panels - grouped.keys()
        if missing:
            raise ValueError(f"Panels require tributary member assignments: {sorted(missing)}.")
        panels_by_id = {panel.panel_id: panel for panel in self.panels}
        for panel_id, members in grouped.items():
            panel = panels_by_id[panel_id]
            assigned_area = sum(
                (member.x_end_m - member.x_start_m) * member.tributary_width_m for member in members
            )
            if not math.isclose(assigned_area, panel.area_m2, rel_tol=1e-8, abs_tol=1e-8):
                raise ValueError(
                    f"Panel {panel_id!r} tributary areas total {assigned_area:g} m2; "
                    f"expected its reviewed area {panel.area_m2:g} m2."
                )
            # Segment coordinates are member-local; only segments on the same
            # member can be checked for overlap without the panel geometry model.
            intervals: dict[str, list[tuple[float, float]]] = {}
            for member in members:
                intervals.setdefault(member.member_id, []).append(
                    (member.x_start_m, member.x_end_m)
                )
            for member_id, spans in intervals.items():
                spans.sort()
                for previous, current in zip(spans, spans[1:], strict=False):
                    if current[0] < previous[1] - 1e-9:
                        raise ValueError(
                            f"Tributary segments for panel {panel_id!r} overlap on "
                            f"member {member_id!r}."
                        )
        return self


class PanelPressureResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    panel_id: str
    load_case: str
    source_run_id: str
    standard: Literal["AS/NZS 1170.2:2021"]
    limit_state: Literal["ultimate", "serviceability"]
    wind_direction: WindDirection
    pressure_unit: Literal["kPa"] = "kPa"
    vdes_external_mps: float
    vdes_internal_mps: float
    q_external_kpa: float
    q_internal_kpa: float
    cshp_external: float
    cshp_internal: float
    external_pressure_kpa: float
    internal_pressure_kpa: float
    net_pressure_toward_inside_kpa: float
    coefficient_reviewer: str
    coefficient_review_date: date
    external_coefficient_reference: str
    internal_coefficient_reference: str
    area_review_reference: str
    coefficient_review_note: str
    source_clauses: tuple[str, ...]


class MemberDistributedLoad(BaseModel):
    """OpenCalcs contract record plus source and sign-attribution metadata."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    member_id: str
    load_case: str
    direction: Literal["Fx", "Fy", "Fz"]
    start_kn_m: float
    end_kn_m: float
    start_m: float
    end_m: float
    source_run_id: str
    standard: Literal["AS/NZS 1170.2:2021"]
    limit_state: Literal["ultimate", "serviceability"]
    wind_direction: WindDirection
    load_unit: Literal["kN/m"] = "kN/m"
    length_unit: Literal["m"] = "m"
    axis_reference: str
    panel_id: str
    net_pressure_toward_inside_kpa: float
    tributary_width_m: float
    tributary_area_m2: float
    area_review_reference: str
    coefficient_reviewer: str
    coefficient_review_date: date


class WindFrameLoadResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    standard: Literal["AS/NZS 1170.2:2021"] = STANDARD
    pressure_unit: Literal["kPa"] = "kPa"
    load_unit: Literal["kN/m"] = "kN/m"
    length_unit: Literal["m"] = "m"
    panel_pressures: tuple[PanelPressureResult, ...]
    member_loads: tuple[MemberDistributedLoad, ...]
    source_clauses: tuple[str, ...] = ("2.3", "2.4.1", "2.5.3.1")
    warnings: tuple[str, ...] = (
        "Aggregate aerodynamic shape factors and panel/tributary geometry are reviewed inputs.",
        "No AS/NZS 1170.0 design combinations or pressure coefficient selection is performed.",
        "Dynamic response is unsupported; accepted cases use C_dyn = 1.0 under Clause 2.4.1.",
        "Each assigned member axis must align with the panel normal; inclined vector projection "
        "is not performed. Assignments require engineering review.",
    )

    @property
    def member_distributed_loads(self) -> list[dict[str, object]]:
        """Return fields in the OpenCalcs member distributed-load contract."""

        return [
            {
                "member_id": load.member_id,
                "load_case": load.load_case,
                "direction": load.direction,
                "start_kn_m": load.start_kn_m,
                "end_kn_m": load.end_kn_m,
                "start_m": load.start_m,
                "end_m": load.end_m,
            }
            for load in self.member_loads
        ]


def calculate_wind_frame_loads(request: WindFrameLoadRequest) -> WindFrameLoadResult:
    """Calculate AS/NZS 1170.2 panel pressure and distribute it to frame members.

    Equation 2.4(1) is p = 0.5 rho Vdes,theta^2 Cshp Cdyn. This implementation
    uses the reviewed aggregate Cshp values, separate external/internal design
    speeds, rho=1.2 kg/m3, and Cdyn=1; dynamic-sensitive cases are rejected.
    External positive pressure acts toward a panel. Internal positive pressure
    acts away from it, so net inward pressure is p_external - p_internal.
    Equation 2.5(1) requires vector summation of pressure times area; the load
    sign below follows each explicitly supplied member-axis convention.
    """

    cases = {case.case_id: case for case in request.pressure_cases}
    tribs_by_panel: dict[str, list[TributaryMemberInput]] = {}
    for tributary in request.tributary_members:
        tribs_by_panel.setdefault(tributary.panel_id, []).append(tributary)

    pressures: list[PanelPressureResult] = []
    loads: list[MemberDistributedLoad] = []
    for panel in request.panels:
        case = cases[panel.case_id]
        q_external_kpa = 0.5 * AIR_DENSITY_KG_M3 * case.vdes_external_mps**2 / 1000.0
        q_internal_kpa = 0.5 * AIR_DENSITY_KG_M3 * case.vdes_internal_mps**2 / 1000.0
        external_pressure_kpa = q_external_kpa * panel.cshp_external
        internal_pressure_kpa = q_internal_kpa * panel.cshp_internal
        net_pressure_kpa = external_pressure_kpa - internal_pressure_kpa
        pressures.append(
            PanelPressureResult(
                panel_id=panel.panel_id,
                load_case=case.case_id,
                source_run_id=case.source_run_id,
                standard=case.standard,
                limit_state=case.limit_state,
                wind_direction=case.wind_direction,
                vdes_external_mps=case.vdes_external_mps,
                vdes_internal_mps=case.vdes_internal_mps,
                q_external_kpa=q_external_kpa,
                q_internal_kpa=q_internal_kpa,
                cshp_external=panel.cshp_external,
                cshp_internal=panel.cshp_internal,
                external_pressure_kpa=external_pressure_kpa,
                internal_pressure_kpa=internal_pressure_kpa,
                net_pressure_toward_inside_kpa=net_pressure_kpa,
                coefficient_reviewer=panel.coefficient_reviewer,
                coefficient_review_date=panel.coefficient_review_date,
                external_coefficient_reference=panel.external_coefficient_reference,
                internal_coefficient_reference=panel.internal_coefficient_reference,
                area_review_reference=panel.area_review_reference,
                coefficient_review_note=panel.coefficient_review_note,
                source_clauses=(PRESSURE_EQUATION, "5", FORCE_EQUATION),
            )
        )
        mapped_force_toward_inside_kn = 0.0
        for tributary in tribs_by_panel[panel.panel_id]:
            span_m = tributary.x_end_m - tributary.x_start_m
            tributary_area_m2 = span_m * tributary.tributary_width_m
            positive_sign = 1.0 if tributary.positive_direction_toward_inside else -1.0
            line_load_kn_m = net_pressure_kpa * tributary.tributary_width_m * positive_sign
            mapped_force_toward_inside_kn += line_load_kn_m * span_m * positive_sign
            loads.append(
                MemberDistributedLoad(
                    member_id=tributary.member_id,
                    load_case=case.case_id,
                    direction=tributary.direction,
                    start_kn_m=line_load_kn_m,
                    end_kn_m=line_load_kn_m,
                    start_m=tributary.x_start_m,
                    end_m=tributary.x_end_m,
                    source_run_id=case.source_run_id,
                    standard=case.standard,
                    limit_state=case.limit_state,
                    wind_direction=case.wind_direction,
                    axis_reference=tributary.axis_reference,
                    panel_id=panel.panel_id,
                    net_pressure_toward_inside_kpa=net_pressure_kpa,
                    tributary_width_m=tributary.tributary_width_m,
                    tributary_area_m2=tributary_area_m2,
                    area_review_reference=panel.area_review_reference,
                    coefficient_reviewer=panel.coefficient_reviewer,
                    coefficient_review_date=panel.coefficient_review_date,
                )
            )
        expected_force_kn = net_pressure_kpa * panel.area_m2
        if not math.isclose(
            mapped_force_toward_inside_kn,
            expected_force_kn,
            rel_tol=1e-8,
            abs_tol=1e-8,
        ):
            raise ValueError(
                f"Panel {panel.panel_id!r} mapped line-load resultant does not conserve "
                "its net pressure force."
            )

    return WindFrameLoadResult(panel_pressures=tuple(pressures), member_loads=tuple(loads))
