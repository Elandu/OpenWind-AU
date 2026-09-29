# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Elandu and contributors

"""Separate, traceable AS 4055:2021 housing classification and load helpers.

The site table and pressure coefficients below are derived lookup data from the
licensed AS 4055:2021 copy. They are isolated from the AS/NZS 1170.2 path. The
package remains preliminary until the independent review gate in the docs is met.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from openwind_au.as4055_racking_data import RACKING_TABLES

STANDARD = "AS 4055"
EDITION = "2021"
SOURCE_CLAUSES = (
    "1.1",
    "1.2",
    "2.1",
    "2.2",
    "2.3",
    "2.4",
    "2.5",
    "2.6",
    "3.1",
    "3.2",
    "3.3",
    "3.4",
)
SOURCE_TABLES = (
    "Table 2.1(A)",
    "Table 2.1(B)",
    "Table 2.2",
    "Table 2.6.1(A)",
    "Table 2.6.1(B)",
    "Table 3.2.1",
    "Table 3.2.2(A)",
    "Table 3.2.2(B)",
    "Table 4",
    "Table 5.2(A)",
)

TerrainCategory = Literal["TC1", "TC2", "TC2.5", "TC3"]
WindRegion = Literal["A", "B", "C", "D"]
ShieldingClass = Literal["FS", "PS", "NS"]
TopographicClass = Literal["T0", "T1", "T2", "T3", "T4", "T5"]
LimitState = Literal["serviceability", "ultimate"]

# Clause 2.2 / Table 2.2 column order. Region C/D cells contain distance bands.
_SITE_COLUMNS = (
    ("T0", "FS"),
    ("T0", "PS"),
    ("T0", "NS"),
    ("T1", "FS"),
    ("T1", "PS"),
    ("T1", "NS"),
    ("T2", "FS"),
    ("T2", "PS"),
    ("T2", "NS"),
    ("T3", "PS"),
    ("T3", "NS"),
    ("T4", "NS"),
    ("T5", "NS"),
)
_NON_CYCLONIC = {
    "A": {
        "TC3": "N1 N1 N1 N1 N2 N2 N2 N2 N2 N3 N3 N3 N4",
        "TC2.5": "N1 N1 N2 N1 N2 N2 N2 N3 N3 N3 N3 N4 N4",
        "TC2": "N1 N2 N2 N2 N2 N3 N2 N3 N3 N3 N3 N4 N4",
        "TC1": "N2 N2 N3 N2 N3 N3 N3 N3 N3 N4 N4 N4 N5",
    },
    "B": {
        "TC3": "N2 N2 N3 N2 N3 N3 N3 N3 N4 N4 N4 N4 N5",
        "TC2.5": "N2 N3 N3 N3 N3 N3 N3 N4 N4 N4 N4 N5 N5",
        "TC2": "N2 N3 N3 N3 N3 N4 N3 N4 N4 N4 N5 N5 N6",
        "TC1": "N3 N3 N4 N3 N4 N4 N4 N4 N5 N5 N5 N6 N6",
    },
}

# Each item is a comma-separated sequence aligned to _SITE_COLUMNS. A token is
# CLASS:LOW-HIGH; NA bands are retained to produce a safe out-of-scope referral.
_CYCLONIC: dict[str, dict[str, tuple[str, ...]]] = {
    "C": {
        "TC3": (
            "C1:0-50",
            "C2:0-10,C1:10-50",
            "C2:0-20,C1:20-50",
            "C2:0-5,C1:5-50",
            "C2:0-30,C1:30-50",
            "C2:0-40,C1:40-50",
            "C2:0-25,C1:25-50",
            "C3:0-5,C2:5-50",
            "C3:0-20,C2:20-50",
            "C3:0-25,C2:25-50",
            "C3:0-30,C2:30-50",
            "C4:0-10,C3:10-50",
            "C4:0-35,C3:35-50",
        ),
        "TC2.5": (
            "C1:0-50",
            "C2:0-25,C1:25-50",
            "C2:0-35,C1:35-50",
            "C2:0-20,C1:20-50",
            "C2:0-40,C1:40-50",
            "C3:0-10,C2:10-50",
            "C2:0-35,C1:35-50",
            "C3:0-20,C2:20-50",
            "C3:0-30,C2:30-50",
            "C3:0-35,C2:35-50",
            "C4:0-5,C3:5-50",
            "C4:0-25,C3:25-50",
            "NA:0-15,C4:15-50",
        ),
        "TC2": (
            "C2:0-10,C1:10-50",
            "C2:0-35,C1:35-50",
            "C2:0-45,C1:45-50",
            "C2:0-30,C1:30-50",
            "C3:0-10,C2:10-50",
            "C3:0-25,C2:25-50",
            "C3:0-10,C2:10-50",
            "C3:0-30,C2:30-50",
            "C3:0-40,C2:40-50",
            "C4:0-10,C3:10-50",
            "C4:0-20,C3:20-50",
            "NA:0-5,C4:5-50",
            "NA:0-25,C4:25-50",
        ),
        "TC1": (
            "C2:0-30,C1:30-50",
            "C3:0-10,C2:10-50",
            "C3:0-25,C2:25-50",
            "C3:0-10,C2:10-50",
            "C3:0-30,C2:30-50",
            "C4:0-5,C3:5-50",
            "C3:0-25,C2:25-50",
            "C4:0-10,C3:10-50",
            "C4:0-20,C3:20-50",
            "C4:0-30,C3:30-50",
            "NA:0-5,C4:5-50",
            "NA:0-25,C4:25-50",
            "NA:0-45,C4:45-50",
        ),
    },
    "D": {
        "TC3": (
            "C2:0-30,C1:30-50",
            "C3:0-10,C2:10-50",
            "C3:0-25,C2:25-50",
            "C3:0-5,C2:5-50",
            "C3:0-35,C2:35-50",
            "C3:0-50",
            "C3:0-30,C2:30-50",
            "C4:0-5,C3:5-50",
            "C4:0-20,C3:20-50",
            "C4:0-30,C3:30-50",
            "C4:0-40,C3:40-50",
            "NA:0-25,C4:25-50",
            "NA:0-50",
        ),
        "TC2.5": (
            "C2:0-50",
            "C3:0-25,C2:25-50",
            "C3:0-40,C2:40-50",
            "C3:0-25,C2:25-50",
            "C3:0-50",
            "C4:0-15,C3:15-50",
            "C3:0-45,C2:45-50",
            "C4:0-25,C3:25-50",
            "C4:0-40,C3:40-50",
            "NA:0-5,C4:5-50",
            "NA:0-20,C4:20-50",
            "NA:0-40,C4:40-50",
            "NA:0-50",
        ),
        "TC2": (
            "C3:0-10,C2:10-50",
            "C3:0-40,C2:40-50",
            "C4:0-5,C3:5-50",
            "C3:0-35,C2:35-50",
            "C4:0-15,C3:15-50",
            "C4:0-30,C3:30-50",
            "C4:0-10,C3:10-50",
            "C4:0-40,C3:40-50",
            "NA:0-15,C4:15-50",
            "NA:0-20,C4:20-50",
            "NA:0-35,C4:35-50",
            "NA:0-50",
            "NA:0-50",
        ),
        "TC1": (
            "C3:0-35,C2:35-50",
            "C4:0-10,C3:10-50",
            "C4:0-30,C3:30-50",
            "C4:0-10,C3:10-50",
            "C4:0-40,C3:40-50",
            "NA:0-15,C4:15-50",
            "C4:0-35,C3:35-50",
            "NA:0-25,C4:25-50",
            "NA:0-40,C4:40-50",
            "NA:0-45,C4:45-50",
            "NA:0-50",
            "NA:0-50",
            "NA:0-50",
        ),
    },
}

_WIND_SPEEDS = {
    "N1": {"serviceability": 26.0, "ultimate": 34.0},
    "N2": {"serviceability": 26.0, "ultimate": 40.0},
    "N3": {"serviceability": 32.0, "ultimate": 50.0},
    "N4": {"serviceability": 39.0, "ultimate": 61.0},
    "N5": {"serviceability": 47.0, "ultimate": 74.0},
    "N6": {"serviceability": 55.0, "ultimate": 86.0},
    "C1": {"serviceability": 32.0, "ultimate": 50.0},
    "C2": {"serviceability": 39.0, "ultimate": 61.0},
    "C3": {"serviceability": 47.0, "ultimate": 74.0},
    "C4": {"serviceability": 55.0, "ultimate": 86.0},
}


@dataclass(frozen=True)
class HousingGeometry:
    building_class: Literal["1", "10a"]
    eaves_height_m: float
    roof_height_m: float
    width_m: float
    length_m: float
    roof_pitch_degrees: float


@dataclass(frozen=True)
class SiteConditions:
    region: WindRegion
    terrain_category: TerrainCategory
    topographic_class: TopographicClass
    shielding_class: ShieldingClass
    distance_km: float | None = None
    distance_basis: Literal["smoothed_coastline", "higher_wind_region_boundary"] | None = None


class AS4055GeometryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    building_class: Literal["1", "10a"]
    eaves_height_m: float = Field(gt=0)
    roof_height_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    length_m: float = Field(gt=0)
    roof_pitch_degrees: float = Field(ge=0, le=35)


class AS4055SiteConditionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    region: WindRegion
    terrain_category: TerrainCategory
    topographic_class: TopographicClass
    shielding_class: ShieldingClass
    distance_km: float | None = Field(default=None, ge=0, le=50)
    distance_basis: Literal["smoothed_coastline", "higher_wind_region_boundary"] | None = None


class AS4055ClassificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    geometry: AS4055GeometryRequest
    site_conditions: AS4055SiteConditionsRequest


class AS4055SurfaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    component: Literal["roof_structure", "roof_cladding", "wall_structure", "wall_cladding"]
    zone: Literal["G", "RE", "RC", "SC"]
    area_m2: float = Field(gt=0)


class AS4055LoadsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    classification: dict
    surfaces: list[AS4055SurfaceRequest] = Field(min_length=1)
    limit_state: LimitState
    roof_pitch_degrees: float | None = Field(default=None, ge=0, le=35)


class AS4055ZoneAreasRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    geometry: AS4055GeometryRequest
    roof_form: Literal["flat", "gable"]


class AS4055AnchoringRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    classification: dict
    roof_type: Literal["tile", "sheet"]
    roof_surface_area_m2: float = Field(gt=0)
    limit_state: LimitState
    all_cladding_resists_design_wind: bool


class AS4055RackingPressureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    classification: dict
    elevation_type: Literal["flat_vertical", "hip_roof", "gable_side"]
    storey: Literal["single_or_upper", "lower"] = "single_or_upper"
    wind_on: Literal["side", "end"] | None = None
    width_m: float | None = Field(default=None, ge=4, le=16)
    roof_pitch_degrees: float | None = Field(default=None, ge=0, le=35)
    storey_height_m: float = Field(gt=0)
    floor_depth_m: float = Field(ge=0)
    elevation_area_m2: float = Field(gt=0)


class AS4055RackingElevationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    wind_on: Literal["side", "end"]
    storey: Literal["single_or_upper", "lower"]
    elevation_area_m2: float = Field(gt=0)
    storey_height_m: float = Field(gt=0)
    floor_depth_m: float = Field(ge=0)
    area_review_reference: str = Field(min_length=1)


class AS4055HousingAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    geometry: AS4055GeometryRequest
    site_conditions: AS4055SiteConditionsRequest
    roof_form: Literal["flat", "gable"]
    roof_type: Literal["tile", "sheet"]
    storeys: Literal[1, 2]
    all_cladding_resists_design_wind: bool
    site_review_reference: str = Field(min_length=1)
    racking_elevations: list[AS4055RackingElevationRequest] = Field(min_length=2, max_length=4)


@dataclass(frozen=True)
class SiteClassification:
    standard: str
    edition: str
    site_wind_classification: str
    wall_classification: str
    roof_classification: str
    serviceability_gust_speed_m_s: float
    ultimate_gust_speed_m_s: float
    source_clauses: tuple[str, ...]
    source_tables: tuple[str, ...]
    lookup_digest: str
    geometry: HousingGeometry
    site_conditions: SiteConditions
    status: str = "preliminary_independent_review_required"
    referral: str | None = None


def _lookup_digest() -> str:
    payload = json.dumps(
        {
            "columns": _SITE_COLUMNS,
            "non_cyclonic": _NON_CYCLONIC,
            "cyclonic": _CYCLONIC,
            "speeds": _WIND_SPEEDS,
            "coefficients": _COEFFICIENTS,
            "anchoring_pressures": _ANCHORING_PRESSURES,
            "flat_racking_pressures": _FLAT_RACKING_PRESSURES,
            "racking_tables": RACKING_TABLES,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_geometry(geometry: HousingGeometry) -> None:
    """Reject houses outside the AS 4055 Clause 1.2 limits."""
    values = (
        geometry.eaves_height_m,
        geometry.roof_height_m,
        geometry.width_m,
        geometry.length_m,
        geometry.roof_pitch_degrees,
    )
    if any(not math.isfinite(value) for value in values):
        raise ValueError("AS 4055 geometry values must be finite numbers.")
    if geometry.building_class not in {"1", "10a"}:
        raise ValueError("AS 4055 applies to NCC Class 1 and 10a only; refer to AS/NZS 1170.2.")
    if (
        min(geometry.eaves_height_m, geometry.roof_height_m, geometry.width_m, geometry.length_m)
        <= 0
    ):
        raise ValueError("Eaves, roof height, width, and length must be greater than zero.")
    if geometry.eaves_height_m > 6.0:
        raise ValueError("Eaves exceed the AS 4055 limit of 6.0 m; refer to AS/NZS 1170.2.")
    if geometry.roof_height_m > 8.5:
        raise ValueError("Roof height exceeds the AS 4055 limit of 8.5 m; refer to AS/NZS 1170.2.")
    if geometry.roof_height_m < geometry.eaves_height_m:
        raise ValueError("Roof height must not be below eaves height.")
    if geometry.width_m > 16.0 or geometry.length_m > 5.0 * geometry.width_m:
        raise ValueError("House plan dimensions exceed AS 4055 limits; refer to AS/NZS 1170.2.")
    if geometry.length_m < geometry.width_m:
        raise ValueError(
            "For AS 4055, length_m must be the longer plan dimension and width_m the shorter."
        )
    if not 0.0 <= geometry.roof_pitch_degrees <= 35.0:
        raise ValueError("Roof pitch must be between 0 and 35 degrees for AS 4055.")


def classify_site(geometry: HousingGeometry, site: SiteConditions) -> SiteClassification:
    """Map reviewed AS 4055 site-condition categories to a site class."""
    validate_geometry(geometry)
    if site.region not in {"A", "B", "C", "D"}:
        raise ValueError("Wind region must be A, B, C, or D.")
    try:
        column = _SITE_COLUMNS.index((site.topographic_class, site.shielding_class))
    except ValueError as exc:
        raise ValueError(
            "This topographic and shielding combination is not tabulated by AS 4055."
        ) from exc
    terrain = site.terrain_category
    if terrain not in {"TC1", "TC2", "TC2.5", "TC3"}:
        raise ValueError("AS 4055 terrain category must be TC1, TC2, TC2.5, or TC3.")
    if site.region in {"A", "B"}:
        raw = _NON_CYCLONIC[site.region][terrain].split()[column]
        wind_class = raw
    else:
        distance = site.distance_km
        if distance is None or not math.isfinite(distance) or not 0.0 <= distance <= 50.0:
            raise ValueError(
                "Regions C and D require a verified boundary/coast distance from 0 to 50 km."
            )
        if site.distance_basis is None:
            raise ValueError(
                "Regions C and D require a distance basis: smoothed_coastline or "
                "higher_wind_region_boundary."
            )
        cell = _CYCLONIC[site.region][terrain][column]
        matches: list[tuple[float, str]] = []
        for token in cell.split(","):
            label, band = token.split(":", 1)
            lower, upper = (float(part) for part in band.split("-", 1))
            if lower <= distance <= upper and label != "NA":
                matches.append((lower, label))
        if not matches:
            return SiteClassification(
                standard=STANDARD,
                edition=EDITION,
                site_wind_classification="NA",
                wall_classification="NA",
                roof_classification="NA",
                serviceability_gust_speed_m_s=0.0,
                ultimate_gust_speed_m_s=0.0,
                source_clauses=SOURCE_CLAUSES[:4],
                source_tables=SOURCE_TABLES[:3],
                lookup_digest=_lookup_digest(),
                geometry=geometry,
                site_conditions=site,
                referral=(
                    "AS 4055 Table 2.2 marks this site condition/distance NA; "
                    "refer to AS/NZS 1170.2."
                ),
            )
        # Overlapping tabulated boundaries resolve to the more conservative class.
        wind_class = max(matches, key=lambda item: int(item[1][1:]))[1]
    return SiteClassification(
        standard=STANDARD,
        edition=EDITION,
        site_wind_classification=wind_class,
        wall_classification=f"{wind_class}w",
        roof_classification=f"{wind_class}r",
        serviceability_gust_speed_m_s=_WIND_SPEEDS[wind_class]["serviceability"],
        ultimate_gust_speed_m_s=_WIND_SPEEDS[wind_class]["ultimate"],
        source_clauses=SOURCE_CLAUSES[:8],
        source_tables=SOURCE_TABLES[:5],
        lookup_digest=_lookup_digest(),
        geometry=geometry,
        site_conditions=site,
    )


@dataclass(frozen=True)
class HousingSurface:
    component: Literal["roof_structure", "roof_cladding", "wall_structure", "wall_cladding"]
    zone: Literal["G", "RE", "RC", "SC"]
    area_m2: float


@dataclass(frozen=True)
class SurfaceLoad:
    component: str
    zone: str
    area_m2: float
    pressure_basis: Literal["external", "internal", "net"]
    load_case: Literal["suction", "positive"]
    limit_state: LimitState
    design_gust_speed_m_s: float
    dynamic_gust_pressure_kpa: float
    pressure_coefficient: float
    pressure_kpa: float
    force_kn: float


_COEFFICIENTS = {
    "non_cyclonic": {
        "roof_structure": {"G": ((-0.9, 0.2, -1.0), (0.4, -0.3, 0.63))},
        "roof_cladding": {
            "G": ((-0.9, 0.2, -1.0), (0.4, -0.3, 0.63)),
            "RE": ((-1.8, 0.2, -1.8),),
            "RC": ((-2.7, 0.2, -2.61),),
        },
        "wall_structure": {"G": ((0.7, -0.3, 0.9), (-0.65, 0.2, -0.77))},
        "wall_cladding": {
            "G": ((-0.65, 0.2, -0.77), (0.7, -0.3, 0.9)),
            "SC": ((-1.3, 0.2, -1.35),),
        },
    },
    "cyclonic_ultimate": {
        "roof_structure": {"G": ((-0.9, 0.7, -1.44), (0.4, -0.65, 0.95))},
        "roof_cladding": {
            "G": ((-0.9, 0.7, -1.44), (0.4, -0.65, 0.95)),
            "RE": ((-1.8, 0.7, -2.25),),
            "RC": ((-2.7, 0.7, -3.06),),
        },
        "wall_structure": {"G": ((-0.65, 0.7, -1.22), (0.7, -0.65, 1.22))},
        "wall_cladding": {
            "G": ((-0.65, 0.7, -1.22), (0.7, -0.65, 1.22)),
            "SC": ((-1.3, 0.7, -1.8),),
        },
    },
}

# AS 4055:2021 Table 4, columns: serviceability tile/sheet, ultimate tile/sheet.
# These are net upward pressures for anchoring at tops of walls, including the
# dead-load combinations in Table 4 Notes 2, 4 and 5. They must never be added
# to Section 3 cladding or frame suction resultants.
_ANCHORING_PRESSURES = {
    "N1r": (0.0, 0.04, 0.0, 0.33),
    "N2r": (0.0, 0.04, 0.14, 0.59),
    "N3r": (0.0, 0.25, 0.68, 1.13),
    "N4r": (0.0, 0.54, 1.40, 1.85),
    "N5r": (0.42, 0.95, 2.44, 2.89),
    "N6r": (0.90, 1.44, 3.58, 4.03),
    "C1r": (0.0, 0.25, 1.35, 1.80),
    "C2r": (0.0, 0.54, 2.40, 2.85),
    "C3r": (0.41, 0.95, 3.92, 4.37),
    "C4r": (0.90, 1.44, 5.58, 6.03),
}

# AS 4055:2021 Table 5.2(A), vertical surfaces (flat walls, gable and
# skillion ends), pressure on the elevation area in kPa.
_FLAT_RACKING_PRESSURES = {
    "N1": 0.66,
    "N2": 0.92,
    "N3": 1.44,
    "N4": 2.14,
    "N5": 3.16,
    "N6": 4.26,
    "C1": 1.44,
    "C2": 2.14,
    "C3": 3.16,
    "C4": 4.26,
}


@dataclass(frozen=True)
class RoofAnchoringLoad:
    roof_classification: str
    roof_type: Literal["tile", "sheet"]
    limit_state: LimitState
    roof_surface_area_m2: float
    net_upward_pressure_kpa: float
    anchoring_force_kn: float
    source_table: str = "Table 4"
    load_path: str = "roof_to_wall_anchoring"
    status: str = "preliminary_independent_review_required"


def calculate_roof_anchoring(
    classification: SiteClassification,
    roof_type: Literal["tile", "sheet"],
    roof_surface_area_m2: float,
    limit_state: LimitState,
    *,
    all_cladding_resists_design_wind: bool,
) -> RoofAnchoringLoad:
    """Apply Table 4 over the entire roof surface for roof-to-wall anchoring."""
    classification = validate_classification(classification)
    if roof_type not in {"tile", "sheet"} or limit_state not in {"serviceability", "ultimate"}:
        raise ValueError(
            "Table 4 requires tile/sheet roof and serviceability/ultimate limit state."
        )
    if not math.isfinite(roof_surface_area_m2) or roof_surface_area_m2 <= 0:
        raise ValueError("Entire roof surface area must be finite and greater than zero.")
    if classification.roof_classification.startswith("N") and not all_cladding_resists_design_wind:
        raise ValueError(
            "Table 4 Note 7 requires all cladding, windows and doors to withstand design wind "
            "loads for N classifications."
        )
    try:
        pressures = _ANCHORING_PRESSURES[classification.roof_classification]
    except KeyError as exc:
        raise ValueError("Roof classification is not tabulated in AS 4055 Table 4.") from exc
    index = (0 if limit_state == "serviceability" else 2) + (roof_type == "sheet")
    pressure = pressures[index]
    return RoofAnchoringLoad(
        roof_classification=classification.roof_classification,
        roof_type=roof_type,
        limit_state=limit_state,
        roof_surface_area_m2=roof_surface_area_m2,
        net_upward_pressure_kpa=pressure,
        anchoring_force_kn=pressure * roof_surface_area_m2,
    )


def calculate_pressure_zone_areas(
    geometry: HousingGeometry,
    roof_form: Literal["flat", "gable"],
) -> tuple[HousingSurface, ...]:
    """Partition a simple rectangular roof and its walls under Figures 3.1(A/B).

    The roof edge and wall-corner distance is 1.2 m. Each gable plane is a
    rectangle in its own sloping surface coordinates. Hips, roof overhangs,
    verandas and non-rectangular plans need explicit measured zones.
    """
    validate_geometry(geometry)
    if roof_form not in {"flat", "gable"}:
        raise ValueError("Automatic zones support flat and rectangular gable roofs only.")
    pitch = geometry.roof_pitch_degrees
    rise = geometry.roof_height_m - geometry.eaves_height_m
    if roof_form == "flat":
        if pitch != 0 or not math.isclose(rise, 0.0, abs_tol=0.01):
            raise ValueError("Flat roof requires zero pitch and matching roof/eaves heights.")
        plane_width = geometry.width_m
        plane_count = 1
    else:
        if pitch <= 0:
            raise ValueError("Gable roof requires positive pitch.")
        expected_rise = geometry.width_m / 2 * math.tan(math.radians(pitch))
        if not math.isclose(rise, expected_rise, abs_tol=0.01):
            raise ValueError("Gable roof height must match width, eaves height and pitch.")
        plane_width = geometry.width_m / (2 * math.cos(math.radians(pitch)))
        plane_count = 2
    edge = 1.2
    if geometry.length_m <= 2 * edge or plane_width <= 2 * edge:
        raise ValueError(
            "Roof planes must exceed 2.4 m between opposite edges for automatic zones."
        )
    roof_area = plane_count * geometry.length_m * plane_width
    roof_general = plane_count * (geometry.length_m - 2 * edge) * (plane_width - 2 * edge)
    # Figure 3.1(A) marks the four exterior eave corners RC; ridge/end
    # intersections remain RE. The overlap of the two edge strips is counted once.
    roof_corner = 4 * edge**2 if pitch < 10 else 0.0
    roof_edge = roof_area - roof_general - roof_corner
    wall_area = 2 * (geometry.length_m + geometry.width_m) * geometry.eaves_height_m
    if roof_form == "gable":
        wall_area += geometry.width_m * rise  # two triangular gable ends
    wall_corner = 8 * edge * geometry.eaves_height_m
    if roof_form == "gable":
        wall_corner += 2 * edge**2 * math.tan(math.radians(pitch))
    if roof_edge < 0 or wall_area - wall_corner <= 0:
        raise ValueError("Geometry is too small for non-overlapping automatic zones.")
    result = [
        HousingSurface("roof_structure", "G", roof_area),
        HousingSurface("roof_cladding", "G", roof_general),
        HousingSurface("roof_cladding", "RE", roof_edge),
        HousingSurface("wall_structure", "G", wall_area),
        HousingSurface("wall_cladding", "G", wall_area - wall_corner),
        HousingSurface("wall_cladding", "SC", wall_corner),
    ]
    if roof_corner:
        result.insert(3, HousingSurface("roof_cladding", "RC", roof_corner))
    return tuple(result)


def calculate_housing_loads(
    classification: SiteClassification,
    surfaces: tuple[HousingSurface, ...],
    limit_state: LimitState = "ultimate",
    roof_pitch_degrees: float | None = None,
) -> tuple[SurfaceLoad, ...]:
    """Calculate signed AS 4055 pressures and resultant forces for supplied areas.

    Areas are explicit so users can preserve their measured tributary areas. The
    caller must not treat this surface calculator as member-capacity design.
    """
    classification = validate_classification(classification)
    if limit_state not in {"serviceability", "ultimate"}:
        raise ValueError("limit_state must be serviceability or ultimate.")
    if roof_pitch_degrees is not None and not 0 <= roof_pitch_degrees <= 35:
        raise ValueError("Roof pitch must be between 0 and 35 degrees.")
    if not surfaces:
        raise ValueError("At least one measured surface area is required.")
    speed = (
        classification.ultimate_gust_speed_m_s
        if limit_state == "ultimate"
        else classification.serviceability_gust_speed_m_s
    )
    q_u = 0.0006 * speed**2  # 0.5 rho V^2 / 1000; rho = 1.2 kg/m^3 (Clause 3.3)
    cyclonic_uls = (
        classification.site_wind_classification.startswith("C") and limit_state == "ultimate"
    )
    coefficient_set = (
        _COEFFICIENTS["cyclonic_ultimate"] if cyclonic_uls else _COEFFICIENTS["non_cyclonic"]
    )
    results: list[SurfaceLoad] = []
    for surface in surfaces:
        if not math.isfinite(surface.area_m2) or surface.area_m2 <= 0:
            raise ValueError("Every surface area must be finite and greater than zero.")
        if surface.zone not in coefficient_set.get(surface.component, {}):
            raise ValueError(
                f"Pressure zone {surface.zone} is not applicable to {surface.component}."
            )
        if surface.zone == "RC" and (roof_pitch_degrees is None or roof_pitch_degrees >= 10):
            raise ValueError(
                "AS 4055 roof-corner cladding coefficient applies only below 10 degrees pitch."
            )
        alternatives = coefficient_set[surface.component][surface.zone]
        for external, internal, net in alternatives:
            scenario = "suction" if external < 0 else "positive"
            for basis, coefficient in (
                ("external", external),
                ("internal", internal),
                ("net", net),
            ):
                pressure = q_u * coefficient
                results.append(
                    SurfaceLoad(
                        component=surface.component,
                        zone=surface.zone,
                        area_m2=surface.area_m2,
                        pressure_basis=basis,
                        load_case=scenario,
                        limit_state=limit_state,
                        design_gust_speed_m_s=speed,
                        dynamic_gust_pressure_kpa=q_u,
                        pressure_coefficient=coefficient,
                        pressure_kpa=pressure,
                        force_kn=pressure * surface.area_m2,
                    )
                )
    return tuple(results)


def calculate_uplift(
    loads: tuple[SurfaceLoad, ...],
    roof_component: Literal["roof_structure", "roof_cladding"],
) -> float:
    """Return outward resultant for one roof load path (avoid double-counting)."""
    uplift = -sum(
        load.force_kn
        for load in loads
        if load.component == roof_component
        and load.pressure_basis == "net"
        and load.load_case == "suction"
        and load.force_kn < 0
    )
    return uplift


def calculate_racking_force(elevation_area_m2: float, lateral_pressure_kpa: float) -> float:
    """Calculate racking force after the Section 5 lateral pressure is selected."""
    if not math.isfinite(elevation_area_m2) or elevation_area_m2 <= 0:
        raise ValueError("elevation_area_m2 must be finite and greater than zero.")
    if not math.isfinite(lateral_pressure_kpa) or lateral_pressure_kpa < 0:
        raise ValueError("lateral_pressure_kpa must be finite and not negative.")
    return elevation_area_m2 * lateral_pressure_kpa


def source_lookup_digest() -> str:
    """Return the canonical digest for the currently configured derived lookups."""
    return _lookup_digest()


def validate_classification(classification: SiteClassification) -> SiteClassification:
    """Reject tampered or obsolete saved classifications before deriving loads."""
    if classification.referral:
        raise ValueError(classification.referral)
    geometry = classification.geometry
    site = classification.site_conditions
    if isinstance(geometry, dict):
        geometry = HousingGeometry(**AS4055GeometryRequest.model_validate(geometry).model_dump())
    if isinstance(site, dict):
        site = SiteConditions(**AS4055SiteConditionsRequest.model_validate(site).model_dump())
    if not isinstance(geometry, HousingGeometry) or not isinstance(site, SiteConditions):
        raise ValueError("Saved classification requires complete geometry and site conditions.")
    expected = classify_site(geometry, site)
    for field in (
        "standard",
        "edition",
        "site_wind_classification",
        "wall_classification",
        "roof_classification",
        "serviceability_gust_speed_m_s",
        "ultimate_gust_speed_m_s",
        "lookup_digest",
    ):
        if getattr(classification, field) != getattr(expected, field):
            raise ValueError(f"Saved AS 4055 classification has inconsistent {field}; reclassify.")
    if expected.referral:
        raise ValueError(expected.referral)
    return expected


def calculate_racking_pressure(
    classification: SiteClassification,
    elevation_type: Literal["flat_vertical", "hip_roof", "gable_side"],
    *,
    storey: Literal["single_or_upper", "lower"],
    wind_on: Literal["side", "end"] | None,
    width_m: float | None,
    roof_pitch_degrees: float | None,
    storey_height_m: float,
    floor_depth_m: float,
    elevation_area_m2: float,
) -> dict:
    """Select Section 5 pressures, interpolating both tabulated dimensions.

    Elevation area must be measured for the storey under Figures 5.2(A-C).
    No extrapolation or automatic inference of complex elevation geometry.
    """
    classification = validate_classification(classification)
    if storey not in {"single_or_upper", "lower"}:
        raise ValueError("Select single_or_upper or lower storey.")
    if not all(math.isfinite(x) for x in (storey_height_m, floor_depth_m)):
        raise ValueError("Storey height and floor depth must be finite.")
    if storey_height_m <= 0 or floor_depth_m < 0:
        raise ValueError("Storey height must be positive and floor depth non-negative.")
    wind_class = classification.site_wind_classification
    interpolation = None
    if elevation_type == "flat_vertical":
        if any(value is not None for value in (wind_on, width_m, roof_pitch_degrees)):
            raise ValueError("Table 5.2(A) does not take roof pitch, width or roof direction.")
        pressure = _FLAT_RACKING_PRESSURES[wind_class]
        table = "A"
    elif elevation_type in {"hip_roof", "gable_side"}:
        if wind_on not in {"side", "end"}:
            raise ValueError("Roof elevation requires wind_on side or end.")
        if elevation_type == "gable_side" and wind_on != "side":
            raise ValueError("Gable end wind uses flat_vertical Table 5.2(A).")
        if not (
            math.isclose(storey_height_m, 2.4, abs_tol=1e-9)
            and math.isclose(floor_depth_m, 0.3, abs_tol=1e-9)
        ):
            raise ValueError(
                "Tables 5.2(B-M) use 2.4 m storey and 0.3 m floor; other heights "
                "require separate engineering assessment."
            )
        if width_m is None or not math.isfinite(width_m) or not 4 <= width_m <= 16:
            raise ValueError("Racking table width must be between 4 and 16 m.")
        if (
            roof_pitch_degrees is None
            or not math.isfinite(roof_pitch_degrees)
            or not 0 <= roof_pitch_degrees <= 35
        ):
            raise ValueError("Racking table roof pitch must be between 0 and 35 degrees.")
        if not math.isclose(width_m, classification.geometry.width_m, abs_tol=1e-9):
            raise ValueError("Width must match the classified shorter plan dimension.")
        if not math.isclose(
            roof_pitch_degrees, classification.geometry.roof_pitch_degrees, abs_tol=1e-9
        ):
            raise ValueError("Pitch must match the classified building geometry.")
        group = {
            "N1": 0,
            "N2": 1,
            "N3": 2,
            "C1": 2,
            "N4": 3,
            "C2": 3,
            "N5": 4,
            "C3": 4,
            "N6": 5,
            "C4": 5,
        }[wind_class]
        table = chr(ord("B") + group * 2 + (storey == "lower"))
        rows = RACKING_TABLES[table][wind_on]
        i = min(math.floor(width_m) - 4, 11)
        j = min(math.floor(roof_pitch_degrees / 5), 6)
        fw = width_m - (i + 4)
        fp = roof_pitch_degrees / 5 - j
        low = rows[i][j] * (1 - fp) + rows[i][j + 1] * fp
        high = rows[i + 1][j] * (1 - fp) + rows[i + 1][j + 1] * fp
        pressure = low * (1 - fw) + high * fw
        interpolation = {
            "width_bounds_m": [i + 4, i + 5],
            "pitch_bounds_degrees": [j * 5, (j + 1) * 5],
            "method": "linear_in_each_dimension",
        }
    else:
        raise ValueError("Unsupported racking elevation type.")
    return {
        "standard": STANDARD,
        "edition": EDITION,
        "source_table": f"Table 5.2({table})",
        "source_clause": "5.2",
        "limit_state": "ultimate",
        "site_wind_classification": wind_class,
        "elevation_type": elevation_type,
        "storey": storey,
        "wind_on": wind_on,
        "lateral_pressure_kpa": pressure,
        "elevation_area_m2": elevation_area_m2,
        "racking_force_kn": calculate_racking_force(elevation_area_m2, pressure),
        "interpolation": interpolation,
        "lookup_digest": source_lookup_digest(),
        "status": "preliminary_independent_review_required",
        "limitations": [
            "Check both building directions and every storey; use the most adverse case.",
            "Elevation areas require review under Figures 5.2(A-C).",
            "This is a demand calculation, not bracing or foundation capacity design.",
        ],
    }
