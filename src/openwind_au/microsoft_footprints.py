"""Microsoft Australia Building Footprints cache provider."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
from shapely.errors import ShapelyError
from shapely.geometry import Point, shape

MICROSOFT_AUSTRALIA_DATASET_URL = "https://github.com/microsoft/AustraliaBuildingFootprints"
MICROSOFT_AUSTRALIA_DOWNLOAD_URL = (
    "https://usbuildingdata.blob.core.windows.net/australia-buildings/Australia.geojson.zip"
)
MICROSOFT_FOOTPRINT_SOURCE = "microsoft_building_footprints"
MICROSOFT_DATA_LICENSE = "ODbL"
COORDINATE_PREFIX_RE = re.compile(
    r'"coordinates"\s*:\s*\[\s*\[\s*\[\s*'
    r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)"
)
COORDINATE_PAIR_RE = re.compile(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]")


@dataclass(frozen=True)
class MicrosoftFootprintResult:
    """Footprints and provider diagnostics for a Microsoft cache query."""

    footprints: list[dict[str, Any]]
    source_status: str
    cache_status: str
    cache_path: str | None = None
    cache_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def query_microsoft_building_footprints(
    latitude: float,
    longitude: float,
    radius_m: int,
    *,
    cache_dir: str | Path | None = None,
    footprint_file: str | Path | None = None,
    allow_download: bool = True,
) -> MicrosoftFootprintResult:
    """Read Microsoft Australia building footprints from a local tile/cache."""

    cache_root = Path(cache_dir) if cache_dir else default_microsoft_cache_dir()
    explicit_file = Path(footprint_file) if footprint_file else configured_footprint_file()
    warnings: list[str] = []
    candidate_files = candidate_cache_files(
        latitude,
        longitude,
        radius_m,
        cache_root,
        explicit_file=explicit_file,
    )
    if not candidate_files and allow_download:
        downloaded = download_indexed_tiles(latitude, longitude, radius_m, cache_root)
        candidate_files.extend(downloaded)
    if not candidate_files:
        return MicrosoftFootprintResult(
            footprints=[],
            source_status="unavailable",
            cache_status="miss",
            cache_path=str(cache_root),
            warnings=[
                "Microsoft Australia Building Footprints cache not found for this site. "
                "OSM/Overpass will be used as a fallback if available."
            ],
        )

    footprints: list[dict[str, Any]] = []
    used_files: list[str] = []
    for path in candidate_files:
        try:
            path_footprints = read_footprint_file(path, latitude, longitude, radius_m)
        except Exception as exc:
            warnings.append(f"Microsoft footprint cache file could not be read: {path}: {exc}")
            continue
        if path_footprints:
            used_files.append(str(path))
            footprints.extend(path_footprints)
    if not used_files:
        return MicrosoftFootprintResult(
            footprints=[],
            source_status="available",
            cache_status="hit_empty",
            cache_path=str(cache_root),
            cache_files=[str(path) for path in candidate_files],
            warnings=warnings,
        )
    return MicrosoftFootprintResult(
        footprints=deduplicate_by_source_id(footprints),
        source_status="available",
        cache_status="hit",
        cache_path=str(cache_root),
        cache_files=used_files,
        warnings=warnings,
    )


def default_microsoft_cache_dir() -> Path:
    """Return the configured/default Microsoft footprint cache directory."""

    configured = os.environ.get("OPENWIND_MICROSOFT_FOOTPRINT_CACHE")
    if configured:
        return Path(configured)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "OpenWind-AU" / "microsoft_building_footprints"
    return Path.home() / ".cache" / "openwind-au" / "microsoft_building_footprints"


def configured_footprint_file() -> Path | None:
    """Return an explicitly configured Microsoft footprint file if supplied."""

    configured = os.environ.get("OPENWIND_MICROSOFT_FOOTPRINT_FILE")
    return Path(configured) if configured else None


def candidate_cache_files(
    latitude: float,
    longitude: float,
    radius_m: int,
    cache_root: Path,
    *,
    explicit_file: Path | None = None,
) -> list[Path]:
    """Return likely cache files for the query tile and nearby radius."""

    if explicit_file:
        return [explicit_file] if explicit_file.exists() else []
    candidates: list[Path] = []
    for tile_key in tile_keys_for_radius(latitude, longitude, radius_m):
        candidates.extend(
            [
                cache_root / "tiles" / f"{tile_key}.geojsonl",
                cache_root / "tiles" / f"{tile_key}.ndjson",
                cache_root / "tiles" / f"{tile_key}.geojson",
                cache_root / f"{tile_key}.geojsonl",
                cache_root / f"{tile_key}.ndjson",
                cache_root / f"{tile_key}.geojson",
                cache_root / f"microsoft_au_{tile_key}.geojsonl",
                cache_root / f"microsoft_au_{tile_key}.geojson",
            ]
        )
    if cache_root.exists():
        candidates.extend(
            path
            for path in cache_root.iterdir()
            if path.is_file()
            and path.suffix.lower() in {".geojson", ".json", ".geojsonl", ".ndjson"}
        )
    seen: set[Path] = set()
    existing: list[Path] = []
    for path in candidates:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        existing.append(path)
    return existing


def tile_keys_for_radius(latitude: float, longitude: float, radius_m: int) -> list[str]:
    """Return integer-degree tile keys touched by a radius around the site."""

    lat_delta = radius_m / 111_320
    lon_delta = radius_m / max(111_320 * math.cos(math.radians(latitude)), 1)
    lat_min = math.floor(latitude - lat_delta)
    lat_max = math.floor(latitude + lat_delta)
    lon_min = math.floor(longitude - lon_delta)
    lon_max = math.floor(longitude + lon_delta)
    return [
        f"{lat}_{lon}" for lat in range(lat_min, lat_max + 1) for lon in range(lon_min, lon_max + 1)
    ]


def download_indexed_tiles(
    latitude: float,
    longitude: float,
    radius_m: int,
    cache_root: Path,
) -> list[Path]:
    """Download only site-relevant cache tiles when a local/remote index is configured."""

    index = load_tile_index(cache_root)
    if not index:
        return []
    downloaded: list[Path] = []
    tiles = index.get("tiles", {}) if isinstance(index, dict) else {}
    for tile_key in tile_keys_for_radius(latitude, longitude, radius_m):
        entry = tiles.get(tile_key)
        if not isinstance(entry, dict) or not entry.get("url"):
            continue
        relative_file = entry.get("file") or f"tiles/{tile_key}.geojsonl"
        target = cache_root / relative_file
        if target.exists():
            downloaded.append(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(entry["url"], timeout=60)
        response.raise_for_status()
        target.write_bytes(response.content)
        downloaded.append(target)
    return downloaded


def load_tile_index(cache_root: Path) -> dict[str, Any] | None:
    """Load a local tile index or a configured remote index."""

    local_index = os.environ.get("OPENWIND_MICROSOFT_FOOTPRINT_INDEX")
    index_path = Path(local_index) if local_index else cache_root / "index.json"
    if index_path.exists():
        return json.loads(index_path.read_text(encoding="utf-8"))
    index_url = os.environ.get("OPENWIND_MICROSOFT_FOOTPRINT_INDEX_URL")
    if not index_url:
        return None
    response = requests.get(index_url, timeout=30)
    response.raise_for_status()
    return response.json()


def read_footprint_file(
    path: Path,
    latitude: float,
    longitude: float,
    radius_m: int,
) -> list[dict[str, Any]]:
    """Read a GeoJSON/GeoJSONL Microsoft footprint cache file and clip it to a radius."""

    suffix = path.suffix.lower()
    bbox = query_bbox(latitude, longitude, radius_m)
    features = (
        iter_geojson_lines(path, bbox=bbox)
        if suffix in {".geojsonl", ".ndjson"}
        else iter(read_geojson_features(path))
    )
    footprints: list[dict[str, Any]] = []
    for index, feature in enumerate(features):
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        properties = feature.get("properties") or {}
        for polygon_index, polygon in enumerate(polygon_geometries(geometry)):
            if not geometry_intersects_radius(polygon, latitude, longitude, radius_m):
                continue
            source_id = microsoft_source_id(path, index, polygon_index, properties)
            footprints.append(
                {
                    "source_id": source_id,
                    "footprint_geometry": polygon,
                    "classification": "unknown",
                    "footprint_source": MICROSOFT_FOOTPRINT_SOURCE,
                    "source": "Microsoft Australia Building Footprints",
                    "source_provenance": [source_id],
                    "tags": {
                        **properties,
                        "source": "Microsoft Australia Building Footprints",
                        "source:dataset": MICROSOFT_AUSTRALIA_DATASET_URL,
                        "source:license": MICROSOFT_DATA_LICENSE,
                    },
                }
            )
    return footprints


def read_geojson_features(path: Path) -> list[dict[str, Any]]:
    """Read GeoJSON features from a FeatureCollection, Feature, or geometry file."""

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        return [feature for feature in data.get("features", []) if isinstance(feature, dict)]
    if isinstance(data, dict) and data.get("type") == "Feature":
        return [data]
    if isinstance(data, dict) and data.get("type") in {"Polygon", "MultiPolygon"}:
        return [{"type": "Feature", "properties": {}, "geometry": data}]
    return []


def read_geojson_lines(path: Path) -> list[dict[str, Any]]:
    """Read newline-delimited GeoJSON features."""

    return list(iter_geojson_lines(path))


def iter_geojson_lines(
    path: Path,
    *,
    bbox: tuple[float, float, float, float] | None = None,
):
    """Yield newline-delimited GeoJSON features without loading the whole tile."""

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            if bbox and not line_may_intersect_bbox(line, bbox):
                continue
            data = json.loads(line)
            if isinstance(data, dict) and data.get("type") == "Feature":
                yield data
            elif isinstance(data, dict) and data.get("type") in {"Polygon", "MultiPolygon"}:
                yield {"type": "Feature", "properties": {}, "geometry": data}


def query_bbox(
    latitude: float,
    longitude: float,
    radius_m: int,
) -> tuple[float, float, float, float]:
    """Return a padded WGS84 bbox for fast line-level cache filtering."""

    margin_m = max(radius_m + 100, radius_m * 1.1)
    lat_delta = margin_m / 111_320
    lon_delta = margin_m / max(111_320 * math.cos(math.radians(latitude)), 1)
    return (
        longitude - lon_delta,
        latitude - lat_delta,
        longitude + lon_delta,
        latitude + lat_delta,
    )


def line_may_intersect_bbox(line: str, bbox: tuple[float, float, float, float]) -> bool:
    """Return whether a GeoJSONL feature is worth parsing for this small query bbox."""

    first_match = COORDINATE_PREFIX_RE.search(line)
    if not first_match:
        return True
    min_lon, min_lat, max_lon, max_lat = bbox
    line_min_lon = line_max_lon = float(first_match.group(1))
    line_min_lat = line_max_lat = float(first_match.group(2))
    if min_lon <= line_min_lon <= max_lon and min_lat <= line_min_lat <= max_lat:
        return True
    for match in COORDINATE_PAIR_RE.finditer(line, first_match.end()):
        longitude = float(match.group(1))
        latitude = float(match.group(2))
        if min_lon <= longitude <= max_lon and min_lat <= latitude <= max_lat:
            return True
        line_min_lon = min(line_min_lon, longitude)
        line_max_lon = max(line_max_lon, longitude)
        line_min_lat = min(line_min_lat, latitude)
        line_max_lat = max(line_max_lat, latitude)
    return (
        line_min_lon <= max_lon
        and line_max_lon >= min_lon
        and line_min_lat <= max_lat
        and line_max_lat >= min_lat
    )


def polygon_geometries(geometry: Any) -> list[dict[str, Any]]:
    """Return Polygon geometries, splitting MultiPolygons where needed."""

    if not isinstance(geometry, dict):
        return []
    if geometry.get("type") == "Polygon":
        return [geometry]
    if geometry.get("type") != "MultiPolygon":
        return []
    return [
        {"type": "Polygon", "coordinates": coordinates}
        for coordinates in geometry.get("coordinates", [])
        if coordinates
    ]


def microsoft_source_id(
    path: Path,
    feature_index: int,
    polygon_index: int,
    properties: dict[str, Any],
) -> str:
    """Return a stable source id for a cached Microsoft footprint."""

    property_id = properties.get("id") or properties.get("OBJECTID") or properties.get("fid")
    if property_id:
        return f"ms-au-{property_id}"
    suffix = f"{feature_index + 1}"
    if polygon_index:
        suffix = f"{suffix}-{polygon_index + 1}"
    return f"ms-au-{path.stem}-{suffix}"


def geometry_intersects_radius(
    geometry: dict[str, Any],
    latitude: float,
    longitude: float,
    radius_m: int,
) -> bool:
    """Return whether a WGS84 polygon intersects a local radius around the site."""

    try:
        projected = project_polygon_geometry_to_local_m(geometry, latitude, longitude)
        polygon = shape(projected)
        if polygon.is_empty:
            return False
        return polygon.intersects(Point(0, 0).buffer(radius_m))
    except (ShapelyError, AttributeError, ValueError, TypeError):
        return False


def project_polygon_geometry_to_local_m(
    geometry: dict[str, Any],
    origin_latitude: float,
    origin_longitude: float,
) -> dict[str, Any]:
    """Project a WGS84 polygon into local metre offsets around the site."""

    projected_rings = []
    for ring in geometry.get("coordinates", []):
        projected_ring = []
        for longitude, latitude in ring:
            east, north = local_offsets_m(latitude, longitude, origin_latitude, origin_longitude)
            projected_ring.append([east, north])
        projected_rings.append(projected_ring)
    return {"type": "Polygon", "coordinates": projected_rings}


def local_offsets_m(
    latitude: float,
    longitude: float,
    origin_latitude: float,
    origin_longitude: float,
) -> tuple[float, float]:
    """Return local east/north metre offsets for WGS84 coordinates."""

    earth_radius_m = 6_371_008.8
    east = (
        math.radians(longitude - origin_longitude)
        * earth_radius_m
        * math.cos(math.radians(origin_latitude))
    )
    north = math.radians(latitude - origin_latitude) * earth_radius_m
    return east, north


def deduplicate_by_source_id(footprints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate source ids while preserving order."""

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for footprint in footprints:
        source_id = str(footprint.get("source_id"))
        if source_id in seen:
            continue
        seen.add(source_id)
        unique.append(footprint)
    return unique
