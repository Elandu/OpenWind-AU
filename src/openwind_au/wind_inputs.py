"""Regional wind speed and direction multiplier lookup inputs."""

from __future__ import annotations

import json
import math
import os
from importlib import resources
from pathlib import Path
from typing import Any

import folium
from shapely.geometry import mapping, shape

from openwind_au.models import (
    DirectionMultiplierAssessment,
    DirectionMultiplierRow,
    RegionalWindSpeedAssessment,
    SiteLocation,
    WindDirection,
    WindRegionAssessment,
)
from openwind_au.wind_region import assess_wind_region, wind_region_debug

VR_TABLE_ENV = "OPENWIND_VR_TABLE_PATH"
MD_TABLE_ENV = "OPENWIND_MD_TABLE_PATH"
VR_DATA_FILE = "regional_wind_speeds.json"
MD_DATA_FILE = "direction_multipliers.json"
DIRECTIONS: tuple[WindDirection, ...] = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def regional_wind_speed_assessment(
    wind_region: WindRegionAssessment,
    *,
    importance_level: str | None,
    annual_exceedance_probability: str,
) -> RegionalWindSpeedAssessment:
    """Look up VR,ult and VR,serv for the selected region and ARI."""

    data = load_vr_tables()
    ari_years = parse_ari_years(annual_exceedance_probability)
    table_key = table_region_key(wind_region.wind_region, data.get("tables", {}))
    table = data.get("tables", {}).get(table_key, {})
    source = source_reference(data)
    warnings = [
        "VR values are table lookups for engineering review; confirm against the current "
        "project standard."
    ]
    vr_ult, interpolation = lookup_vr(table.get("ultimate", {}), ari_years)
    vr_serv, service_note = lookup_vr(table.get("serviceability", {}), 25)
    if vr_ult is None:
        warnings.append(
            "Regional wind speed table value missing for selected ultimate ARI; "
            "manual input required."
        )
    if vr_serv is None:
        warnings.append(
            "Regional wind speed serviceability table value missing; manual input required."
        )
    if service_note:
        warnings.append(service_note)
    lookup_values = [
        f"Selected wind region: {wind_region.wind_region}",
        f"Base region table: {table_key}",
        f"Ultimate ARI: {ari_years} years",
        "Serviceability ARI: 25 years",
    ]
    lookup_values.append(
        f"VR,ult: {vr_ult:.1f} m/s" if vr_ult is not None else "VR,ult: manual input required"
    )
    lookup_values.append(
        f"VR,serv: {vr_serv:.1f} m/s" if vr_serv is not None else "VR,serv: manual input required"
    )
    return RegionalWindSpeedAssessment(
        wind_region=wind_region.wind_region,
        importance_level=importance_level,
        ari_years=ari_years,
        annual_exceedance_probability=annual_exceedance_probability,
        vr_ult=vr_ult,
        vr_serv=vr_serv,
        selected_table=source,
        lookup_values=lookup_values,
        interpolation=interpolation,
        warnings=warnings,
    )


def direction_multiplier_assessment(
    wind_region: WindRegionAssessment,
) -> DirectionMultiplierAssessment:
    """Return Md values for all eight directions."""

    data = load_md_tables()
    table_key = table_region_key(wind_region.wind_region, data.get("tables", {}))
    values = data.get("tables", {}).get(table_key, {})
    source = source_reference(data)
    numeric_values = [
        float(values[direction]) for direction in DIRECTIONS if values.get(direction) is not None
    ]
    highest = max(numeric_values) if numeric_values else None
    rows: list[DirectionMultiplierRow] = []
    warnings = ["Md values are automatically selected and require engineering review."]
    for direction in DIRECTIONS:
        raw = values.get(direction)
        md = float(raw) if raw is not None else None
        if md is None:
            warnings.append(f"Md table value missing for {direction}; manual input required.")
        rows.append(
            DirectionMultiplierRow(
                direction=direction,
                md=md,
                is_governing=highest is not None and md == highest,
            )
        )
    return DirectionMultiplierAssessment(
        wind_region=wind_region.wind_region,
        source_table=source,
        directions=rows,
        highest_md=highest,
        governing_directions=[row.direction for row in rows if row.is_governing],
        lookup_values=[
            f"Selected wind region: {wind_region.wind_region}",
            f"Base Md table: {table_key}",
            *[
                f"{row.direction}: Md {row.md:.2f}"
                if row.md is not None
                else f"{row.direction}: manual input required"
                for row in rows
            ],
        ],
        warnings=warnings,
    )


def wind_region_map_html(site: SiteLocation, assessment: WindRegionAssessment) -> str:
    """Render a lightweight wind-region map overlay."""

    fmap = folium.Map(location=[site.latitude, site.longitude], zoom_start=8, control_scale=True)
    folium.Marker(
        location=[site.latitude, site.longitude],
        tooltip="Site location",
    ).add_to(fmap)
    try:
        diagnostics = wind_region_debug(site, include_geometry=True)
    except ValueError:
        diagnostics = None
    if diagnostics:
        for neighbour in diagnostics.get("neighbouring_polygons", []):
            geometry = neighbour.get("geometry")
            if not geometry:
                continue
            folium.GeoJson(
                display_geometry(geometry),
                name=f"Neighbour {neighbour.get('region_name')}",
                style_function=lambda _feature: {
                    "color": "#f59e0b",
                    "weight": 2,
                    "fillColor": "#fef3c7",
                    "fillOpacity": 0.08,
                },
                tooltip=(
                    f"Neighbour region {neighbour.get('region_name')} "
                    f"({neighbour.get('area_name')})"
                ),
            ).add_to(fmap)
    if assessment.region_polygon:
        folium.GeoJson(
            display_geometry(assessment.region_polygon),
            name=f"Selected wind region {assessment.wind_region}",
            style_function=lambda _feature: {
                "color": "#1d4ed8",
                "weight": 3,
                "fillColor": "#93c5fd",
                "fillOpacity": 0.16,
            },
            tooltip=f"Selected Wind Region {assessment.wind_region}",
        ).add_to(fmap)
    if assessment.near_boundary:
        folium.Circle(
            location=[site.latitude, site.longitude],
            radius=assessment.distance_to_boundary_m or 0,
            color="#b45309",
            fill=False,
            tooltip="Approximate distance to wind-region boundary",
        ).add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)
    return fmap.get_root().render()


def display_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    """Simplify wind-region geometry for diagnostic map display only."""

    return mapping(shape(geometry).simplify(0.02, preserve_topology=True))


def run_wind_region_validation_cases() -> list[dict[str, Any]]:
    """Run validation cases only when a wind-region dataset is configured."""

    cases: tuple[dict[str, Any], ...] = (
        {
            "site": "Wollongong",
            "latitude": -34.4278,
            "longitude": 150.8931,
            "expected_region": "A2",
        },
        {
            "site": "Sydney",
            "latitude": -33.8688,
            "longitude": 151.2093,
            "expected_region": "A2",
        },
        {
            "site": "Newcastle",
            "latitude": -32.9283,
            "longitude": 151.7817,
            "expected_region": "A2",
        },
        {
            "site": "Canberra",
            "latitude": -35.2809,
            "longitude": 149.1300,
            "expected_region": "A3",
        },
        {
            "site": "Bourke",
            "latitude": -30.0901,
            "longitude": 145.9360,
            "expected_region": "A0",
        },
    )
    results = []
    for case in cases:
        site = SiteLocation(
            latitude=case["latitude"],
            longitude=case["longitude"],
            ground_elevation_m=0.0,
            source="validation case",
            display_name=case["site"],
        )
        try:
            assessment = assess_wind_region(site)
            actual = assessment.wind_region
            status = "pass" if actual == case["expected_region"] else "fail"
            confidence = assessment.confidence
            distance = assessment.distance_to_boundary_m
            diagnosis = validation_diagnosis(case, assessment, status)
        except ValueError as exc:
            actual = None
            status = "warning"
            confidence = "low"
            distance = None
            case = case | {"warning": str(exc)}
            diagnosis = "Wind-region validation could not run because the dataset was unavailable."
        results.append(
            {
                **case,
                "actual_region": actual,
                "status": status,
                "confidence": confidence,
                "distance_to_boundary_m": distance,
                "diagnosis": diagnosis,
            }
        )
    return results


def validation_diagnosis(
    case: dict[str, Any],
    assessment: WindRegionAssessment,
    status: str,
) -> str:
    """Explain validation result in terms of the active dataset."""

    if status == "pass":
        return "Active dataset matches the expected validation region."
    if assessment.dataset_name == "wind_regions_sample":
        return (
            "Active dataset is the test fixture; fixture polygons are not authoritative "
            "production wind-region boundaries."
        )
    return (
        "Active production dataset returned "
        f"{assessment.wind_region}, not requested expected region {case['expected_region']}. "
        "Treat as a source-data conflict unless a more authoritative dataset is supplied."
    )


def parse_ari_years(value: str) -> int:
    """Parse AEP/ARI text such as 1/500, 1:500, or 500 into an ARI year count."""

    text = str(value or "").strip().lower().replace("ari", "")
    for separator in ("/", ":"):
        if separator in text:
            text = text.split(separator)[-1]
            break
    digits = "".join(character for character in text if character.isdigit())
    return int(digits or "500")


def lookup_vr(
    table: dict[str, Any] | dict[int, Any],
    ari_years: int,
) -> tuple[float | None, str | None]:
    """Return VR from a table, interpolating only between available ARI rows."""

    numeric_table = {int(year): float(value) for year, value in table.items() if value is not None}
    if not numeric_table:
        return None, None
    if ari_years in numeric_table:
        return numeric_table[ari_years], None
    years = sorted(numeric_table)
    if ari_years <= years[0] or ari_years >= years[-1]:
        return None, f"ARI {ari_years} years is outside the VR table range; manual input required."
    lower = max(year for year in years if year < ari_years)
    upper = min(year for year in years if year > ari_years)
    ratio = (math.log(ari_years) - math.log(lower)) / (math.log(upper) - math.log(lower))
    value = numeric_table[lower] + (numeric_table[upper] - numeric_table[lower]) * ratio
    return round(value, 1), f"Interpolated between {lower} and {upper} year ARI rows."


def table_region_key(region: str, tables: dict[str, Any]) -> str:
    """Return the most specific available table key for a wind-region label."""

    if region in tables:
        return region
    if region.startswith("A") and "A" in tables:
        return "A"
    if region.startswith("B") and "B" in tables:
        return "B"
    return region


def load_vr_tables() -> dict[str, Any]:
    """Load editable regional wind speed lookup data."""

    return load_lookup_data(VR_TABLE_ENV, VR_DATA_FILE)


def load_md_tables() -> dict[str, Any]:
    """Load editable direction multiplier lookup data."""

    return load_lookup_data(MD_TABLE_ENV, MD_DATA_FILE)


def load_lookup_data(env_var: str, package_file: str) -> dict[str, Any]:
    """Load lookup JSON from an env override or packaged data file."""

    configured = os.environ.get(env_var)
    if configured:
        path = Path(configured)
        return json.loads(path.read_text(encoding="utf-8"))
    data_path = resources.files("openwind_au.data").joinpath(package_file)
    return json.loads(data_path.read_text(encoding="utf-8"))


def source_reference(data: dict[str, Any]) -> str:
    """Build a compact source reference string from lookup metadata."""

    source = data.get("source", {})
    parts = [
        source.get("title"),
        source.get("standard_reference"),
        source.get("status"),
    ]
    return "; ".join(str(part) for part in parts if part)
