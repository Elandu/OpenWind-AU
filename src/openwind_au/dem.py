"""DEM providers for OpenWind-AU."""

from __future__ import annotations

import gzip
import json
import math
import os
import shutil
import subprocess
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import requests

DEM_PROVIDER_ENV = "OPENWIND_DEM_PROVIDER"
OPEN_METEO_ELEVATION_URL_ENV = "OPENWIND_OPEN_METEO_ELEVATION_URL"
OPEN_METEO_ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"


class DEMProvider(ABC):
    """Abstract elevation provider."""

    @abstractmethod
    def elevation(self, latitude: float, longitude: float) -> float:
        """Return elevation in metres above mean sea level."""


class SRTMProvider(DEMProvider):
    """Read SRTM HGT tiles from the AWS public terrain tile bucket.

    Tiles are downloaded on demand and cached locally. This provider is intended
    for preliminary public-data analysis only.
    """

    def __init__(self, cache_dir: Path | str = "data/cache/srtm") -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._arrays: dict[str, np.ndarray] = {}

    def elevation(self, latitude: float, longitude: float) -> float:
        """Return bilinearly interpolated SRTM elevation in metres."""

        tile_name = srtm_tile_name(latitude, longitude)
        grid = self._load_tile(tile_name, latitude, longitude)
        size = grid.shape[0]

        lat_floor = math.floor(latitude)
        lon_floor = math.floor(longitude)
        row_float = (lat_floor + 1 - latitude) * (size - 1)
        col_float = (longitude - lon_floor) * (size - 1)
        row = int(np.clip(math.floor(row_float), 0, size - 2))
        col = int(np.clip(math.floor(col_float), 0, size - 2))
        dr = row_float - row
        dc = col_float - col

        values = grid[row : row + 2, col : col + 2].astype(float)
        if np.any(values <= -32768):
            raise RuntimeError("SRTM void value encountered near site.")

        top = values[0, 0] * (1 - dc) + values[0, 1] * dc
        bottom = values[1, 0] * (1 - dc) + values[1, 1] * dc
        return float(top * (1 - dr) + bottom * dr)

    def _load_tile(self, tile_name: str, latitude: float, longitude: float) -> np.ndarray:
        """Load an SRTM tile into memory with per-provider caching."""

        if tile_name in self._arrays:
            return self._arrays[tile_name]

        tile_path = self._ensure_tile(latitude, longitude)
        data = np.fromfile(tile_path, dtype=">i2")
        size = int(math.sqrt(data.size))
        if size * size != data.size or size < 2:
            raise RuntimeError(f"Unexpected SRTM tile size for {tile_path}.")
        grid = data.reshape((size, size))
        self._arrays[tile_name] = grid
        return grid

    def _ensure_tile(self, latitude: float, longitude: float) -> Path:
        tile_name = srtm_tile_name(latitude, longitude)
        target = self.cache_dir / f"{tile_name}.hgt"
        if target.exists():
            return target

        folder = tile_name[:3]
        url = f"https://s3.amazonaws.com/elevation-tiles-prod/skadi/{folder}/{tile_name}.hgt.gz"
        token = uuid.uuid4().hex
        gz_path = self.cache_dir / f"{tile_name}.{token}.hgt.gz"
        temp_target = self.cache_dir / f"{tile_name}.{token}.hgt.tmp"
        try:
            _download_file(url, gz_path)
            if target.exists():
                return target
            with gzip.open(gz_path, "rb") as source, temp_target.open("wb") as destination:
                destination.write(source.read())
            os.replace(temp_target, target)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to download SRTM tile {tile_name} from {url}: {exc}"
            ) from exc
        finally:
            if gz_path.exists():
                gz_path.unlink()
            if temp_target.exists():
                temp_target.unlink()

        return target


class OpenMeteoElevationProvider(DEMProvider):
    """Read point elevations from the Open-Meteo Elevation API.

    Open-Meteo's elevation endpoint is based on Copernicus DEM GLO-90 data. The provider is
    intended for source comparison and opt-in public-data workflows; SRTM remains the default
    local-cache terrain source.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get(OPEN_METEO_ELEVATION_URL_ENV)
            or OPEN_METEO_ELEVATION_URL
        )
        self.timeout_seconds = timeout_seconds
        self._cache: dict[tuple[float, float], float] = {}

    def elevation(self, latitude: float, longitude: float) -> float:
        """Return Open-Meteo elevation in metres for a WGS84 point."""

        key = (round(latitude, 7), round(longitude, 7))
        if key in self._cache:
            return self._cache[key]
        try:
            payload = _get_json(
                self.base_url,
                params={"latitude": latitude, "longitude": longitude},
                timeout_seconds=self.timeout_seconds,
            )
            elevation = _parse_open_meteo_elevation(payload)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to retrieve Open-Meteo elevation for "
                f"{latitude},{longitude}: {exc}"
            ) from exc
        self._cache[key] = elevation
        return elevation


class ArrayDEMProvider(DEMProvider):
    """In-memory DEM provider used by tests and examples."""

    def __init__(
        self,
        origin_latitude: float,
        origin_longitude: float,
        cell_size_deg: float,
        elevations_m: np.ndarray,
    ) -> None:
        self.origin_latitude = origin_latitude
        self.origin_longitude = origin_longitude
        self.cell_size_deg = cell_size_deg
        self.elevations_m = elevations_m.astype(float)

    def elevation(self, latitude: float, longitude: float) -> float:
        """Return bilinearly interpolated elevation from the in-memory grid."""

        row_float = (self.origin_latitude - latitude) / self.cell_size_deg
        col_float = (longitude - self.origin_longitude) / self.cell_size_deg
        rows, cols = self.elevations_m.shape
        row = int(np.clip(math.floor(row_float), 0, rows - 2))
        col = int(np.clip(math.floor(col_float), 0, cols - 2))
        dr = row_float - row
        dc = col_float - col
        values = self.elevations_m[row : row + 2, col : col + 2]
        top = values[0, 0] * (1 - dc) + values[0, 1] * dc
        bottom = values[1, 0] * (1 - dc) + values[1, 1] * dc
        return float(top * (1 - dr) + bottom * dr)


def srtm_tile_name(latitude: float, longitude: float) -> str:
    """Return the SRTM HGT tile name for a WGS84 coordinate."""

    lat_floor = math.floor(latitude)
    lon_floor = math.floor(longitude)
    ns = "N" if lat_floor >= 0 else "S"
    ew = "E" if lon_floor >= 0 else "W"
    return f"{ns}{abs(lat_floor):02d}{ew}{abs(lon_floor):03d}"


def configured_dem_provider() -> DEMProvider:
    """Return the DEM provider selected by environment configuration."""

    provider = os.environ.get(DEM_PROVIDER_ENV, "srtm").strip().lower()
    if provider in {"", "srtm"}:
        return SRTMProvider()
    if provider in {"open-meteo", "open_meteo", "openmeteo"}:
        return OpenMeteoElevationProvider()
    raise ValueError(
        f"Unsupported {DEM_PROVIDER_ENV}={provider!r}. Use 'srtm' or 'open-meteo'."
    )


def dem_provider_label(provider: DEMProvider) -> str:
    """Return a user-facing source label for a DEM provider."""

    if isinstance(provider, SRTMProvider):
        return "public SRTM terrain data from AWS terrain tiles"
    if isinstance(provider, OpenMeteoElevationProvider):
        return "Open-Meteo Elevation API using Copernicus DEM GLO-90 public terrain data"
    if isinstance(provider, ArrayDEMProvider):
        return "in-memory DEM test fixture"
    return provider.__class__.__name__


def _parse_open_meteo_elevation(payload: dict) -> float:
    """Extract the first elevation value from an Open-Meteo response."""

    elevations = payload.get("elevation")
    if not isinstance(elevations, list) or not elevations:
        raise RuntimeError("response did not include an elevation array")
    value = elevations[0]
    if not isinstance(value, int | float):
        raise RuntimeError("response elevation value was not numeric")
    return float(value)


def _get_json(url: str, params: dict[str, float], timeout_seconds: float) -> dict:
    """Fetch JSON, falling back to curl for Windows Python TLS issues."""

    try:
        response = requests.get(url, params=params, timeout=timeout_seconds)
        response.raise_for_status()
        return response.json()
    except Exception as requests_exc:
        curl = shutil.which("curl") or shutil.which("curl.exe")
        if not curl:
            raise requests_exc
        query = urlencode(params)
        command = [curl, "--fail", "--location", "--silent", "--show-error"]
        if os.name == "nt":
            command.append("--ssl-no-revoke")
        command.append(f"{url}?{query}")
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip() or f"curl exited {completed.returncode}"
            ) from requests_exc
        return json.loads(completed.stdout)


def _download_file(url: str, target: Path) -> None:
    """Download a public data file.

    The downloader prefers the system `curl` executable because some Windows
    Python/geospatial runtime combinations can crash inside Python TLS bindings.
    A requests fallback is kept for environments without curl.
    """

    curl = shutil.which("curl") or shutil.which("curl.exe")
    if curl:
        command = [curl, "--fail", "--location", "--silent", "--show-error"]
        if os.name == "nt":
            command.append("--ssl-no-revoke")
        command.extend([url, "--output", str(target)])
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or f"curl exited {completed.returncode}")
        return

    response = requests.get(url, timeout=60)
    response.raise_for_status()
    target.write_bytes(response.content)
