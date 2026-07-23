"""Geospatial helpers for geocoding and distance calculations."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import requests

from openwind_au.http_client import APPLICATION_USER_AGENT
from openwind_au.models import SUPPORTED_LATITUDE_RANGE, SUPPORTED_LONGITUDE_RANGE

EARTH_RADIUS_M = 6_371_008.8
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_PHOTON_URL = "https://photon.komoot.io/api/"


def geocode_address(address: str, user_agent: str = APPLICATION_USER_AGENT) -> dict[str, Any]:
    """Geocode an address with OpenStreetMap Nominatim.

    Args:
        address: Street address or locality string.
        user_agent: Nominatim-compliant user agent.

    Returns:
        A dictionary containing latitude, longitude, and display_name.

    Raises:
        ValueError: If the address is empty or no result is returned.
        RuntimeError: If Nominatim cannot be queried.
    """

    if not address.strip():
        raise ValueError("address must not be empty.")

    params = {
        "q": address,
        "format": "jsonv2",
        "limit": 5,
        "countrycodes": "au",
    }
    try:
        data = _get_json(NOMINATIM_URL, params, user_agent)
    except Exception as exc:
        raise RuntimeError(f"Failed to geocode address with Nominatim: {exc}") from exc

    if not data:
        raise ValueError(f"No geocoding result found for address: {address}")

    first = next((item for item in data if _is_supported_coordinate(item)), None)
    if first is None:
        raise ValueError(f"No supported Australian location found for address: {address}")
    return {
        "latitude": float(first["lat"]),
        "longitude": float(first["lon"]),
        "display_name": first.get("display_name"),
        "source": "OpenStreetMap Nominatim",
    }


def geocode_address_suggestions(
    query: str,
    limit: int = 5,
    user_agent: str = APPLICATION_USER_AGENT,
) -> list[dict[str, Any]]:
    """Return candidate Australian address matches from a Photon search service."""

    cleaned_query = query.strip()
    if len(cleaned_query) < 3:
        return []

    bounded_limit = max(1, min(int(limit), 10))
    photon_url = os.getenv("OPENWIND_PHOTON_URL", DEFAULT_PHOTON_URL).strip()
    params = {
        "q": cleaned_query,
        "limit": bounded_limit,
        "lang": "en",
        "bbox": (
            f"{SUPPORTED_LONGITUDE_RANGE[0]},{SUPPORTED_LATITUDE_RANGE[0]},"
            f"{SUPPORTED_LONGITUDE_RANGE[1]},{SUPPORTED_LATITUDE_RANGE[1]}"
        ),
    }
    try:
        data = _cached_get_json(photon_url, tuple(params.items()), user_agent)
    except Exception as exc:
        raise RuntimeError(f"Failed to query address suggestions with Photon: {exc}") from exc

    suggestions = []
    seen = set()
    for feature in data.get("features", []) if isinstance(data, dict) else []:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if len(coordinates) < 2:
            continue
        item = {"lat": coordinates[1], "lon": coordinates[0]}
        if not _is_supported_coordinate(item):
            continue
        properties = feature.get("properties") or {}
        if str(properties.get("countrycode", "")).upper() not in {"", "AU"}:
            continue
        display_name = _photon_display_name(properties)
        if not display_name or display_name in seen:
            continue
        seen.add(display_name)
        suggestions.append(
            {
                "latitude": float(item["lat"]),
                "longitude": float(item["lon"]),
                "display_name": display_name,
                "source": "Komoot Photon (OpenStreetMap)",
            }
        )
    return suggestions


@lru_cache(maxsize=256)
def _cached_get_json(
    url: str,
    parameter_items: tuple[tuple[str, Any], ...],
    user_agent: str,
) -> Any:
    """Cache repeated autocomplete queries to reduce public service traffic."""

    return _get_json(url, dict(parameter_items), user_agent)


def _photon_display_name(properties: dict[str, Any]) -> str:
    """Build a readable Australian address label from Photon properties."""

    name = str(properties.get("name") or "").strip()
    street = str(properties.get("street") or "").strip()
    house_number = str(properties.get("housenumber") or "").strip()
    street_address = " ".join(part for part in (house_number, street) if part)
    parts = []
    if name and name.casefold() != street_address.casefold():
        parts.append(name)
    if street_address:
        parts.append(street_address)
    for key in ("locality", "district", "city", "state", "postcode", "country"):
        value = str(properties.get(key) or "").strip()
        if value and value.casefold() not in {part.casefold() for part in parts}:
            parts.append(value)
    return ", ".join(parts)


def _is_supported_coordinate(item: dict[str, Any]) -> bool:
    """Return whether a geocoder item is inside the application's supported bounds."""

    try:
        latitude = float(item["lat"])
        longitude = float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        SUPPORTED_LATITUDE_RANGE[0] <= latitude <= SUPPORTED_LATITUDE_RANGE[1]
        and SUPPORTED_LONGITUDE_RANGE[0] <= longitude <= SUPPORTED_LONGITUDE_RANGE[1]
    )


def destination_point(
    latitude: float,
    longitude: float,
    bearing_deg: float,
    distance_m: float,
) -> tuple[float, float]:
    """Return the WGS84 destination point from a start, bearing, and distance."""

    lat1 = math.radians(latitude)
    lon1 = math.radians(longitude)
    bearing = math.radians(bearing_deg)
    angular_distance = distance_m / EARTH_RADIUS_M

    sin_lat2 = math.sin(lat1) * math.cos(angular_distance) + math.cos(lat1) * math.sin(
        angular_distance
    ) * math.cos(bearing)
    lat2 = math.asin(sin_lat2)
    y = math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1)
    x = math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2)
    lon2 = lon1 + math.atan2(y, x)

    return math.degrees(lat2), ((math.degrees(lon2) + 540) % 360) - 180


def haversine_distance_m(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return great-circle distance between two WGS84 points in metres."""

    lat1 = math.radians(latitude_a)
    lat2 = math.radians(latitude_b)
    dlat = lat2 - lat1
    dlon = math.radians(longitude_b - longitude_a)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_deg(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return initial bearing from one WGS84 point to another in degrees clockwise from north."""

    lat1 = math.radians(latitude_a)
    lat2 = math.radians(latitude_b)
    dlon = math.radians(longitude_b - longitude_a)
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _get_json(url: str, params: dict[str, Any], user_agent: str) -> Any:
    """GET JSON from a public API using curl first, then requests."""

    curl = shutil.which("curl") or shutil.which("curl.exe")
    full_url = f"{url}?{urlencode(params)}"
    if curl:
        command = [
            curl,
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--user-agent",
            user_agent,
        ]
        if os.name == "nt":
            command.append("--ssl-no-revoke")
        command.append(full_url)
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or f"curl exited {completed.returncode}")
        return json.loads(completed.stdout)

    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": user_agent},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()
