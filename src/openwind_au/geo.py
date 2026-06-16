"""Geospatial helpers for geocoding and distance calculations."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from typing import Any
from urllib.parse import urlencode

import requests

EARTH_RADIUS_M = 6_371_008.8
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def geocode_address(address: str, user_agent: str = "OpenWind-AU/0.1") -> dict[str, Any]:
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
        "limit": 1,
        "countrycodes": "au",
    }
    try:
        data = _get_json(NOMINATIM_URL, params, user_agent)
    except Exception as exc:
        raise RuntimeError(f"Failed to geocode address with Nominatim: {exc}") from exc

    if not data:
        raise ValueError(f"No geocoding result found for address: {address}")

    first = data[0]
    return {
        "latitude": float(first["lat"]),
        "longitude": float(first["lon"]),
        "display_name": first.get("display_name"),
        "source": "OpenStreetMap Nominatim",
    }


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
