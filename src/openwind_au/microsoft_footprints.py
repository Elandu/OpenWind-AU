"""Microsoft Australia Building Footprints cache provider."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
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
MAX_MICROSOFT_TILE_BYTES = 50 * 1024 * 1024
MAX_MICROSOFT_INDEX_BYTES = 2 * 1024 * 1024
MAX_MICROSOFT_QUERY_CACHE_ENTRIES = 128
MICROSOFT_TILE_SUFFIXES = {".geojson", ".json", ".geojsonl", ".ndjson"}
COORDINATE_PREFIX_RE = re.compile(
    r'"coordinates"\s*:\s*\[\s*\[\s*\[\s*'
    r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)"
)
MICROSOFT_QUERY_CACHE: OrderedDict[tuple[Any, ...], MicrosoftFootprintResult] = OrderedDict()
MICROSOFT_QUERY_CACHE_LOCK = threading.RLock()
MICROSOFT_TARGET_LOCKS: dict[str, threading.Lock] = {}
MICROSOFT_TARGET_LOCKS_LOCK = threading.Lock()


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
    if allow_download and explicit_file is None:
        downloaded = download_indexed_tiles(latitude, longitude, radius_m, cache_root)
        candidate_files = list(dict.fromkeys([*candidate_files, *downloaded]))
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
    cache_key = microsoft_query_cache_key(
        latitude,
        longitude,
        radius_m,
        cache_root,
        explicit_file,
        candidate_files,
    )
    cached_result = cached_microsoft_query_result(cache_key)
    if cached_result is not None:
        return cached_result

    footprints: list[dict[str, Any]] = []
    used_files: list[str] = []
    for path in candidate_files:
        try:
            with microsoft_target_lock(path):
                path_footprints = read_footprint_file(path, latitude, longitude, radius_m)
        except Exception as exc:
            warnings.append(f"Microsoft footprint cache file could not be read: {path}: {exc}")
            continue
        if path_footprints:
            used_files.append(str(path))
            footprints.extend(path_footprints)
    if not used_files:
        result = MicrosoftFootprintResult(
            footprints=[],
            source_status="available",
            cache_status="hit_empty",
            cache_path=str(cache_root),
            cache_files=[str(path) for path in candidate_files],
            warnings=warnings,
        )
        cache_microsoft_query_result(cache_key, result)
        return result
    result = MicrosoftFootprintResult(
        footprints=deduplicate_by_source_id(footprints),
        source_status="available",
        cache_status="hit",
        cache_path=str(cache_root),
        cache_files=used_files,
        warnings=warnings,
    )
    cache_microsoft_query_result(cache_key, result)
    return result


def cache_microsoft_query_result(
    cache_key: tuple[Any, ...],
    result: MicrosoftFootprintResult,
) -> None:
    """Store a bounded copy of a Microsoft footprint query result."""

    with MICROSOFT_QUERY_CACHE_LOCK:
        MICROSOFT_QUERY_CACHE[cache_key] = deepcopy(result)
        MICROSOFT_QUERY_CACHE.move_to_end(cache_key)
        while len(MICROSOFT_QUERY_CACHE) > MAX_MICROSOFT_QUERY_CACHE_ENTRIES:
            MICROSOFT_QUERY_CACHE.popitem(last=False)


def cached_microsoft_query_result(
    cache_key: tuple[Any, ...],
) -> MicrosoftFootprintResult | None:
    """Return a copy of a cached result while synchronizing LRU access."""

    with MICROSOFT_QUERY_CACHE_LOCK:
        result = MICROSOFT_QUERY_CACHE.get(cache_key)
        if result is None:
            return None
        MICROSOFT_QUERY_CACHE.move_to_end(cache_key)
        return deepcopy(result)


def default_microsoft_cache_dir() -> Path:
    """Return the configured/default Microsoft footprint cache directory."""

    configured = os.environ.get("OPENWIND_MICROSOFT_FOOTPRINT_CACHE")
    if configured:
        return Path(configured)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "OpenWind-AU" / "microsoft_building_footprints"
    return Path.home() / ".cache" / "openwind-au" / "microsoft_building_footprints"


def microsoft_query_cache_key(
    latitude: float,
    longitude: float,
    radius_m: int,
    cache_root: Path,
    explicit_file: Path | None,
    candidate_files: list[Path],
) -> tuple[Any, ...]:
    """Return a cache key that changes when the source cache files change."""

    file_signatures = []
    for path in candidate_files:
        stat = path.stat()
        file_signatures.append((str(path), stat.st_size, stat.st_mtime_ns))
    return (
        round(latitude, 7),
        round(longitude, 7),
        radius_m,
        str(cache_root),
        str(explicit_file) if explicit_file else None,
        tuple(file_signatures),
    )


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
        target = safe_indexed_tile_target(cache_root, relative_file)
        url = str(entry["url"])
        if not url.lower().startswith("https://"):
            raise ValueError("Microsoft footprint tile URLs must use HTTPS")
        expected_sha256 = normalize_expected_sha256(entry.get("sha256"))
        with microsoft_target_lock(target):
            if target.exists():
                try:
                    validate_cached_tile(target, expected_sha256=expected_sha256)
                except (OSError, ValueError):
                    pass
                else:
                    downloaded.append(target)
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            response = requests.get(url, timeout=60, stream=True)
            try:
                response.raise_for_status()
                response_url = str(getattr(response, "url", url))
                if not response_url.lower().startswith("https://"):
                    raise ValueError("Microsoft footprint tile redirects must remain on HTTPS")
                download_tile_response(response, target, expected_sha256=expected_sha256)
            finally:
                close_response(response)
            downloaded.append(target)
    return downloaded


def microsoft_target_lock(target: Path) -> threading.Lock:
    """Return the process-local lock for an indexed cache target."""

    key = normalized_path_for_comparison(Path(os.path.abspath(os.fspath(target))))
    with MICROSOFT_TARGET_LOCKS_LOCK:
        return MICROSOFT_TARGET_LOCKS.setdefault(key, threading.Lock())


def safe_indexed_tile_target(cache_root: Path, relative_file: Any) -> Path:
    """Resolve an index-provided tile path and enforce cache containment."""

    if not isinstance(relative_file, str) or not relative_file.strip():
        raise ValueError("Microsoft footprint index tile file must be a relative path")
    relative = Path(relative_file)
    if relative.is_absolute() or PureWindowsPath(relative_file).is_absolute():
        raise ValueError("Microsoft footprint index tile file must be relative to the cache")
    root = cache_root.resolve()
    target = (root / relative).resolve()
    root_for_comparison = normalized_path_for_comparison(root)
    target_for_comparison = normalized_path_for_comparison(target)
    if os.path.commonpath([root_for_comparison, target_for_comparison]) != root_for_comparison:
        raise ValueError("Microsoft footprint index tile file escapes the cache directory")
    if target.suffix.lower() not in MICROSOFT_TILE_SUFFIXES:
        allowed = ", ".join(sorted(MICROSOFT_TILE_SUFFIXES))
        raise ValueError(f"Microsoft footprint tile must use one of: {allowed}")
    return target


def normalized_path_for_comparison(path: Path) -> str:
    """Normalize platform-specific absolute path forms for containment checks."""

    normalized = os.path.normcase(os.path.normpath(os.fspath(path)))
    if normalized.startswith("\\\\?\\"):
        normalized = normalized[4:]
    return normalized


def download_tile_response(
    response: Any,
    target: Path,
    *,
    expected_sha256: Any = None,
) -> None:
    """Stream a bounded tile to a temporary file, validate it, then replace atomically."""

    expected_hash = normalize_expected_sha256(expected_sha256)
    content_length = (
        response.headers.get("content-length") if hasattr(response, "headers") else None
    )
    if content_length:
        try:
            declared_size = int(content_length)
        except (TypeError, ValueError) as exc:
            raise ValueError("Microsoft footprint tile has an invalid Content-Length") from exc
        if declared_size > MAX_MICROSOFT_TILE_BYTES:
            raise ValueError(f"Microsoft footprint tile exceeds {MAX_MICROSOFT_TILE_BYTES} bytes")

    temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.part")
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_MICROSOFT_TILE_BYTES:
                    raise ValueError(
                        f"Microsoft footprint tile exceeds {MAX_MICROSOFT_TILE_BYTES} bytes"
                    )
                digest.update(chunk)
                handle.write(chunk)
        if size == 0:
            raise ValueError("Microsoft footprint tile download was empty")
        if expected_hash and digest.hexdigest() != expected_hash:
            raise ValueError("Microsoft footprint tile SHA-256 does not match the index")
        validate_downloaded_tile(temporary, target.suffix.lower())
        atomic_replace_with_retry(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_replace_with_retry(source: Path, target: Path) -> None:
    """Replace a cache target, tolerating brief Windows file-sharing races."""

    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.02 * (2**attempt))


def validate_cached_tile(path: Path, *, expected_sha256: str | None) -> None:
    """Validate the size, optional digest, and structure of an indexed cached tile."""

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError("Microsoft footprint tile could not be inspected") from exc
    if size == 0:
        raise ValueError("Microsoft footprint tile is empty")
    if size > MAX_MICROSOFT_TILE_BYTES:
        raise ValueError(f"Microsoft footprint tile exceeds {MAX_MICROSOFT_TILE_BYTES} bytes")
    if expected_sha256:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise ValueError("Microsoft footprint tile SHA-256 does not match the index")
    validate_downloaded_tile(path, path.suffix.lower())


def close_response(response: Any) -> None:
    """Close a requests-like response when it exposes a close method."""

    close = getattr(response, "close", None)
    if callable(close):
        close()


def normalize_expected_sha256(value: Any) -> str | None:
    """Validate an optional hexadecimal SHA-256 value from a tile index."""

    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise ValueError("Microsoft footprint tile sha256 must contain 64 hexadecimal characters")
    return normalized


def validate_downloaded_tile(path: Path, suffix: str) -> None:
    """Reject downloaded files that are not supported GeoJSON structures."""

    if suffix in {".geojsonl", ".ndjson"}:
        with path.open("r", encoding="utf-8-sig") as handle:
            first_line = next((line for line in handle if line.strip()), "")
        if not first_line:
            raise ValueError("Microsoft footprint tile contains no GeoJSON records")
        data = json.loads(first_line)
        if not isinstance(data, dict) or data.get("type") not in {
            "Feature",
            "Polygon",
            "MultiPolygon",
        }:
            raise ValueError("Microsoft footprint tile contains an unsupported GeoJSONL record")
        return
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("type") not in {
        "FeatureCollection",
        "Feature",
        "Polygon",
        "MultiPolygon",
    }:
        raise ValueError("Microsoft footprint tile contains unsupported GeoJSON")


def load_tile_index(cache_root: Path) -> dict[str, Any] | None:
    """Load a local tile index or a configured remote index."""

    local_index = os.environ.get("OPENWIND_MICROSOFT_FOOTPRINT_INDEX")
    index_path = Path(local_index) if local_index else cache_root / "index.json"
    if index_path.exists():
        return validate_tile_index(json.loads(index_path.read_text(encoding="utf-8")))
    index_url = os.environ.get("OPENWIND_MICROSOFT_FOOTPRINT_INDEX_URL")
    if not index_url:
        return None
    if not index_url.lower().startswith("https://"):
        raise ValueError("Microsoft footprint index URLs must use HTTPS")
    response = requests.get(index_url, timeout=30, stream=True)
    try:
        response.raise_for_status()
        response_url = str(getattr(response, "url", index_url))
        if not response_url.lower().startswith("https://"):
            raise ValueError("Microsoft footprint index redirects must remain on HTTPS")
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except (TypeError, ValueError) as exc:
                raise ValueError("Microsoft footprint index has an invalid Content-Length") from exc
            if declared_size > MAX_MICROSOFT_INDEX_BYTES:
                raise ValueError(
                    f"Microsoft footprint index exceeds {MAX_MICROSOFT_INDEX_BYTES} bytes"
                )
        payload = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            payload.extend(chunk)
            if len(payload) > MAX_MICROSOFT_INDEX_BYTES:
                raise ValueError(
                    f"Microsoft footprint index exceeds {MAX_MICROSOFT_INDEX_BYTES} bytes"
                )
        if not payload:
            raise ValueError("Microsoft footprint index download was empty")
        data = json.loads(payload.decode("utf-8-sig"))
        return validate_tile_index(data)
    finally:
        close_response(response)


def validate_tile_index(data: Any) -> dict[str, Any]:
    """Validate the minimum structure required from a tile index."""

    if not isinstance(data, dict) or not isinstance(data.get("tiles"), dict):
        raise ValueError("Microsoft footprint index must contain a tiles object")
    return data


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

    margin_m = max(radius_m + 500, radius_m * 1.5)
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
    longitude = float(first_match.group(1))
    latitude = float(first_match.group(2))
    return min_lon <= longitude <= max_lon and min_lat <= latitude <= max_lat


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
