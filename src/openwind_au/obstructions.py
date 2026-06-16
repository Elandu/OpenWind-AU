"""Building obstruction inventory for shielding review."""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
from io import StringIO
from typing import Any

import requests

from openwind_au.geo import bearing_deg, geocode_address, haversine_distance_m
from openwind_au.models import (
    ObstructionInventoryRequest,
    ObstructionInventoryResult,
    ObstructionManualOverride,
    ObstructionRecord,
    SiteLocation,
)

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)


def run_obstruction_inventory(
    request: ObstructionInventoryRequest,
    footprints: list[dict[str, Any]] | None = None,
) -> ObstructionInventoryResult:
    """Build a review inventory of nearby building obstructions."""

    site = resolve_obstruction_site(request)
    raw_footprints = footprints
    if raw_footprints is None:
        raw_footprints = query_building_footprints(
            site.latitude,
            site.longitude,
            request.radius_m,
        )
    records = build_obstruction_records(
        raw_footprints,
        site.latitude,
        site.longitude,
        request.radius_m,
        request.default_storey_height_m,
    )
    records = apply_manual_overrides(
        records,
        request.manual_overrides,
        request.default_storey_height_m,
    )
    return ObstructionInventoryResult(
        input=request,
        site=site,
        obstructions=records,
        missing_height_count=sum(item.height_m is None for item in records),
        reviewed_height_count=sum(
            item.height_source == "manual_override" and item.height_m is not None
            for item in records
        ),
    )


def resolve_obstruction_site(request: ObstructionInventoryRequest) -> SiteLocation:
    """Resolve coordinates for an obstruction inventory request."""

    if request.latitude is not None and request.longitude is not None:
        return SiteLocation(
            latitude=request.latitude,
            longitude=request.longitude,
            ground_elevation_m=0.0,
            source="User supplied coordinates",
            display_name=request.address,
        )
    assert request.address is not None
    geocoded = geocode_address(request.address)
    return SiteLocation(
        latitude=geocoded["latitude"],
        longitude=geocoded["longitude"],
        ground_elevation_m=0.0,
        source=geocoded.get("source", "OpenStreetMap Nominatim"),
        display_name=geocoded.get("display_name"),
    )


def query_building_footprints(
    latitude: float,
    longitude: float,
    radius_m: int,
    user_agent: str = "OpenWind-AU/0.1",
) -> list[dict[str, Any]]:
    """Query OpenStreetMap building footprints around a site using Overpass."""

    query = f"""
    [out:json][timeout:25];
    (
      way["building"](around:{radius_m},{latitude},{longitude});
      relation["building"](around:{radius_m},{latitude},{longitude});
    );
    out tags geom;
    """
    data = _post_overpass(query, user_agent)
    return overpass_elements_to_footprints(data.get("elements", []))


def overpass_elements_to_footprints(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Overpass elements with geometry into simple footprint records."""

    footprints: list[dict[str, Any]] = []
    for element in elements:
        geometry = _element_to_geometry(element)
        if not geometry:
            continue
        source_id = f"osm-{element.get('type', 'feature')}-{element.get('id')}"
        footprints.append(
            {
                "source_id": source_id,
                "footprint_geometry": geometry,
                "tags": element.get("tags", {}),
            }
        )
    return footprints


def build_obstruction_records(
    footprints: list[dict[str, Any]],
    site_latitude: float,
    site_longitude: float,
    radius_m: int,
    default_storey_height_m: float = 3.0,
) -> list[ObstructionRecord]:
    """Create obstruction records from footprint geometries and tags."""

    records: list[ObstructionRecord] = []
    for index, footprint in enumerate(footprints):
        geometry = footprint["footprint_geometry"]
        centroid_lon, centroid_lat = polygon_centroid(geometry["coordinates"][0])
        distance = haversine_distance_m(
            site_latitude,
            site_longitude,
            centroid_lat,
            centroid_lon,
        )
        if distance > radius_m:
            continue
        tags = footprint.get("tags", {})
        height = height_from_tags(tags, default_storey_height_m)
        source_id = footprint.get("source_id")
        obstruction_id = source_id or f"obstruction-{index + 1}"
        records.append(
            ObstructionRecord(
                obstruction_id=obstruction_id,
                source_id=source_id,
                footprint_geometry=geometry,
                centroid_latitude=centroid_lat,
                centroid_longitude=centroid_lon,
                distance_m=distance,
                bearing_deg=bearing_deg(
                    site_latitude,
                    site_longitude,
                    centroid_lat,
                    centroid_lon,
                ),
                height_m=height["height_m"],
                building_levels=height["building_levels"],
                height_source=height["height_source"],
                confidence=height["confidence"],
                manual_review_required=height["manual_review_required"],
                tags=tags,
                notes=height["notes"],
            )
        )

    records.sort(key=lambda item: item.distance_m)
    return records


def height_from_tags(
    tags: dict[str, Any],
    default_storey_height_m: float = 3.0,
) -> dict[str, Any]:
    """Resolve obstruction height from explicit tags or building levels only."""

    explicit_height = parse_height_m(tags.get("height") or tags.get("building:height"))
    building_levels = parse_float(tags.get("building:levels") or tags.get("levels"))
    if explicit_height is not None:
        return {
            "height_m": explicit_height,
            "building_levels": building_levels,
            "height_source": "explicit_height",
            "confidence": "high",
            "manual_review_required": False,
            "notes": ["Height taken from explicit OSM height tag."],
        }
    if building_levels is not None:
        return {
            "height_m": building_levels * default_storey_height_m,
            "building_levels": building_levels,
            "height_source": "building_levels",
            "confidence": "medium",
            "manual_review_required": True,
            "notes": [
                "Height estimated from building:levels using configured storey height.",
                "Manual review is required before shielding use.",
            ],
        }
    return {
        "height_m": None,
        "building_levels": None,
        "height_source": "missing",
        "confidence": "unknown",
        "manual_review_required": True,
        "notes": ["No explicit height or building:levels tag was available."],
    }


def apply_manual_overrides(
    records: list[ObstructionRecord],
    overrides: list[ObstructionManualOverride],
    default_storey_height_m: float = 3.0,
) -> list[ObstructionRecord]:
    """Apply reviewed height overrides to obstruction records."""

    overrides_by_id = {override.obstruction_id: override for override in overrides}
    updated: list[ObstructionRecord] = []
    for record in records:
        override = overrides_by_id.get(record.obstruction_id)
        if not override:
            updated.append(record)
            continue
        height_m = override.height_m
        building_levels = override.building_levels
        if height_m is None and building_levels is not None:
            height_m = building_levels * default_storey_height_m
        notes = ["Manual reviewed obstruction height applied."]
        if override.notes:
            notes.append(override.notes)
        updated.append(
            record.model_copy(
                update={
                    "height_m": height_m,
                    "building_levels": building_levels
                    if building_levels is not None
                    else record.building_levels,
                    "height_source": "manual_override",
                    "confidence": "verified" if height_m is not None else "unknown",
                    "manual_review_required": height_m is None,
                    "notes": notes,
                }
            )
        )
    return updated


def parse_manual_overrides_csv(content: str) -> list[ObstructionManualOverride]:
    """Parse reviewed obstruction heights from CSV text."""

    rows = csv.DictReader(StringIO(content))
    overrides: list[ObstructionManualOverride] = []
    for row in rows:
        obstruction_id = (row.get("obstruction_id") or "").strip()
        if not obstruction_id:
            continue
        overrides.append(
            ObstructionManualOverride(
                obstruction_id=obstruction_id,
                height_m=parse_float(row.get("height_m")),
                building_levels=parse_float(row.get("building_levels")),
                height_source=row.get("height_source") or "manual_review",
                notes=row.get("notes") or None,
            )
        )
    return overrides


def reviewed_obstructions_to_json(records: list[ObstructionRecord]) -> str:
    """Export reviewed obstruction records as JSON."""

    return json.dumps([record.model_dump() for record in records], indent=2)


def manual_overrides_from_json(content: str) -> list[ObstructionManualOverride]:
    """Import manual overrides from JSON text."""

    data = json.loads(content)
    if isinstance(data, dict) and "obstructions" in data:
        data = data["obstructions"]
    overrides: list[ObstructionManualOverride] = []
    for item in data:
        obstruction_id = item.get("obstruction_id")
        if not obstruction_id:
            continue
        overrides.append(
            ObstructionManualOverride(
                obstruction_id=obstruction_id,
                height_m=item.get("height_m"),
                building_levels=item.get("building_levels"),
                height_source=item.get("height_source", "manual_review"),
                notes=item.get("notes") if isinstance(item.get("notes"), str) else None,
            )
        )
    return overrides


def parse_height_m(value: Any) -> float | None:
    """Parse an OSM height value in metres."""

    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().lower().replace("metres", "").replace("meters", "")
    text = text.replace("meter", "").replace("metre", "").replace("m", "").strip()
    return parse_float(text)


def parse_float(value: Any) -> float | None:
    """Parse a positive float, returning None for absent or invalid values."""

    if value is None:
        return None
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    if number < 0:
        return None
    return number


def polygon_centroid(ring: list[list[float]]) -> tuple[float, float]:
    """Return centroid of a lon/lat polygon ring as (longitude, latitude)."""

    points = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    lon = sum(point[0] for point in points) / max(len(points), 1)
    lat = sum(point[1] for point in points) / max(len(points), 1)
    return lon, lat


def _element_to_geometry(element: dict[str, Any]) -> dict[str, Any] | None:
    if element.get("type") == "way" and element.get("geometry"):
        ring = [[point["lon"], point["lat"]] for point in element["geometry"]]
        return _polygon_from_ring(ring)
    if element.get("type") == "relation":
        for member in element.get("members", []):
            if member.get("role") in {"outer", ""} and member.get("geometry"):
                ring = [[point["lon"], point["lat"]] for point in member["geometry"]]
                return _polygon_from_ring(ring)
    return None


def _polygon_from_ring(ring: list[list[float]]) -> dict[str, Any] | None:
    if len(ring) < 3:
        return None
    if ring[0] != ring[-1]:
        ring = [*ring, ring[0]]
    return {"type": "Polygon", "coordinates": [ring]}


def _post_overpass(query: str, user_agent: str) -> dict[str, Any]:
    errors: list[str] = []
    for url in OVERPASS_URLS:
        try:
            return _post_overpass_url(url, query, user_agent)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("; ".join(errors))


def _post_overpass_url(url: str, query: str, user_agent: str) -> dict[str, Any]:
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if curl:
        command = [
            curl,
            "--fail",
            "--silent",
            "--show-error",
            "--user-agent",
            user_agent,
            "--data-urlencode",
            f"data={query}",
            url,
        ]
        if os.name == "nt":
            command.insert(4, "--ssl-no-revoke")
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or f"curl exited {completed.returncode}")
        if not completed.stdout:
            raise RuntimeError("empty Overpass response")
        return json.loads(completed.stdout)

    response = requests.post(
        url,
        data={"data": query},
        headers={"User-Agent": user_agent},
        timeout=45,
    )
    response.raise_for_status()
    return response.json()
