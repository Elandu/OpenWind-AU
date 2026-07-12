"""Wind-region lookup from configured Geoscience Australia GIS data."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import Point, mapping

from openwind_au.models import SiteLocation, WindRegionAssessment, WindRegionLabel

GA_WIND_REGION_METADATA_URL = (
    "https://ecat.ga.gov.au/geonetwork/srv/api/records/74dfa021-95cd-4090-9e25-a7a8efde5454"
)
GA_WIND_REGION_DOWNLOAD_URL = "https://d28rz98at9flks.cloudfront.net/146359/146359_01_0.zip"
GA_WIND_REGION_SOURCE = (
    "Geoscience Australia 1170.2 Wind Regions for Australia GIS dataset "
    f"({GA_WIND_REGION_METADATA_URL})"
)
DATASET_ENV = "OPENWIND_WIND_REGION_DATASET"
LAYER_ENV = "OPENWIND_WIND_REGION_LAYER"
FIELD_ENV = "OPENWIND_WIND_REGION_FIELD"
BOUNDARY_WARNING_DISTANCE_ENV = "OPENWIND_WIND_REGION_BOUNDARY_WARNING_M"
BOUNDARY_WARNING_DISTANCE_M = 25_000.0
PRODUCTION_DATASET_CANDIDATES = (
    Path("data/wind-region/ga-1170-2-wind-regions/as1170windzones.shp"),
    Path("data/wind-region/as1170windzones.shp"),
)
REGION_LABELS = (
    "A0",
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "B1",
    "B2",
    "A",
    "B",
    "C",
    "D",
)
REGION_FIELD_CANDIDATES = (
    "wind_region",
    "windregion",
    "region",
    "region_id",
    "regionid",
    "wind_reg",
    "windreg",
    "name",
    "label",
)


def assess_wind_region(site: SiteLocation) -> WindRegionAssessment:
    """Assign wind region by intersecting the site point with configured GIS polygons."""

    dataset_path = require_dataset_path()
    gdf = load_wind_region_geodataframe(dataset_path)
    if gdf.empty:
        raise ValueError(f"Wind-region GIS dataset contains no features: {dataset_path}")

    point = Point(site.longitude, site.latitude)
    matches = gdf[gdf.geometry.covers(point)]
    if matches.empty:
        nearest_index, distance_to_boundary_m = nearest_region_index_and_distance(
            gdf,
            site.latitude,
            site.longitude,
        )
        row = gdf.loc[nearest_index]
        confidence = "low"
        near_boundary = True
        selection_rule = "No polygon covered the site; selected nearest polygon."
        warnings = [
            "Site was not inside a wind-region polygon; nearest region returned for manual review.",
        ]
    else:
        row = select_matching_polygon(matches)
        distance_to_boundary_m = distance_to_geometry_boundary_m(
            row.geometry,
            site.latitude,
            site.longitude,
        )
        near_boundary = distance_to_boundary_m <= boundary_warning_distance_m()
        confidence = "medium" if near_boundary else "high"
        selection_rule = (
            "Selected the covering polygon with the smallest projected area."
            if len(matches) > 1
            else "Selected the only polygon covering the site."
        )
        warnings = []

    region = extract_region_label(row, gdf.columns)
    if region is None:
        raise ValueError(
            "Could not identify wind-region label in GIS feature. Set "
            f"{FIELD_ENV} to the attribute containing values such as A0, A1, B1, C or D."
        )
    if near_boundary:
        warnings.append(
            "Site is near a wind-region boundary; manual engineering review is required."
        )
    warnings.append(
        "Wind region is derived from Geoscience Australia's GIS interpretation. Professional "
        "designers must confirm the wind region against AS/NZS 1170.2 for the project."
    )
    if dataset_is_test_fixture(dataset_path):
        warnings.append(
            "Configured wind-region dataset is a test fixture and must not be used for production."
        )
    metadata = dataset_metadata()
    return WindRegionAssessment(
        latitude=site.latitude,
        longitude=site.longitude,
        wind_region=region,
        region_subclassification=None,
        dataset_path=metadata["dataset_path"],
        dataset_name=metadata["dataset_name"],
        polygon_count=metadata["polygon_count"],
        available_region_names=metadata["available_region_names"],
        source=f"{GA_WIND_REGION_SOURCE}; local path: {dataset_path}",
        confidence=confidence,
        distance_to_boundary_m=round(distance_to_boundary_m, 1),
        near_boundary=near_boundary,
        region_polygon=mapping(row.geometry),
        warnings=[f"Selection rule: {selection_rule}", *warnings],
    )


def configured_dataset_path() -> Path | None:
    """Return the configured local wind-region dataset path, if supplied."""

    configured = os.environ.get(DATASET_ENV)
    if configured:
        path = Path(configured)
        if not path.exists():
            raise ValueError(f"Configured wind-region dataset does not exist: {path}")
        return path
    for candidate in PRODUCTION_DATASET_CANDIDATES:
        path = Path.cwd() / candidate
        if path.exists():
            return path
    return None


def require_dataset_path() -> Path:
    """Return a configured or locally cached production wind-region dataset path."""

    path = configured_dataset_path()
    if path is None:
        raise ValueError(
            "Wind-region GIS dataset is not configured. Set "
            f"{DATASET_ENV} to the local GeoJSON/GPKG/SHP path for Geoscience Australia's "
            "1170.2 Wind Regions for Australia dataset."
        )
    if not path.exists():
        raise ValueError(f"Configured wind-region dataset does not exist: {path}")
    return path


def dataset_is_test_fixture(path: Path) -> bool:
    """Return true when the configured path points into the test fixture tree."""

    normalized = str(path).replace("\\", "/").lower()
    return "/tests/fixtures/" in normalized or normalized.endswith("wind_regions_sample.geojson")


def dataset_metadata() -> dict[str, Any]:
    """Return metadata for the active wind-region dataset."""

    path = configured_dataset_path()
    if path is None:
        return {
            "dataset_path": None,
            "dataset_name": None,
            "dataset_source": "not configured",
            "configured_by": None,
            "polygon_count": 0,
            "available_region_names": [],
            "is_test_fixture": False,
            "production_download_url": GA_WIND_REGION_DOWNLOAD_URL,
            "metadata_url": GA_WIND_REGION_METADATA_URL,
        }
    gdf = load_wind_region_geodataframe(path)
    regions = sorted(
        {
            region
            for _, row in gdf.iterrows()
            if (region := extract_region_label(row, gdf.columns)) is not None
        },
        key=region_sort_key,
    )
    configured = os.environ.get(DATASET_ENV)
    return {
        "dataset_path": str(path),
        "dataset_name": dataset_name(path),
        "dataset_source": GA_WIND_REGION_SOURCE,
        "configured_by": DATASET_ENV if configured else "local production cache",
        "polygon_count": int(len(gdf)),
        "available_region_names": regions,
        "columns": [str(column) for column in gdf.columns],
        "is_test_fixture": dataset_is_test_fixture(path),
        "production_download_url": GA_WIND_REGION_DOWNLOAD_URL,
        "metadata_url": GA_WIND_REGION_METADATA_URL,
    }


def wind_region_debug(site: SiteLocation, *, include_geometry: bool = False) -> dict[str, Any]:
    """Return diagnostic details for wind-region polygon selection."""

    path = require_dataset_path()
    gdf = load_wind_region_geodataframe(path)
    if gdf.empty:
        raise ValueError(f"Wind-region GIS dataset contains no features: {path}")

    point = Point(site.longitude, site.latitude)
    matches = gdf[gdf.geometry.covers(point)].copy()
    if matches.empty:
        nearest_index, _distance = nearest_region_index_and_distance(
            gdf,
            site.latitude,
            site.longitude,
        )
        selected = gdf.loc[nearest_index]
        selection_rule = "No polygon covered the site; selected nearest polygon."
    else:
        selected = select_matching_polygon(matches)
        selection_rule = (
            "Selected the covering polygon with the smallest projected area."
            if len(matches) > 1
            else "Selected the only polygon covering the site."
        )
    neighbours = neighbouring_polygons(gdf, selected.name, site.latitude, site.longitude)
    return {
        "site_coordinates": {
            "latitude": site.latitude,
            "longitude": site.longitude,
            "display_name": site.display_name,
        },
        "dataset": dataset_metadata(),
        "matched_polygons": [
            polygon_debug_record(index, row, gdf.columns, site, include_geometry=include_geometry)
            for index, row in matches.iterrows()
        ],
        "region_names": sorted(
            {
                region
                for _, row in matches.iterrows()
                if (region := extract_region_label(row, gdf.columns)) is not None
            },
            key=region_sort_key,
        ),
        "selected_polygon": polygon_debug_record(
            selected.name,
            selected,
            gdf.columns,
            site,
            include_geometry=include_geometry,
        ),
        "neighbouring_polygons": [
            polygon_debug_record(index, row, gdf.columns, site, include_geometry=include_geometry)
            for index, row in neighbours.iterrows()
        ],
        "selection_rule": selection_rule,
    }


def load_wind_region_geodataframe(path: Path) -> gpd.GeoDataFrame:
    """Load and normalise a GeoJSON/GPKG wind-region layer."""

    resolved = path.resolve()
    layer = os.environ.get(LAYER_ENV) or None
    return _load_wind_region_geodataframe(
        str(resolved),
        layer,
        resolved.stat().st_mtime_ns,
    )


@lru_cache(maxsize=4)
def _load_wind_region_geodataframe(
    path_text: str,
    layer: str | None,
    _modified_ns: int,
) -> gpd.GeoDataFrame:
    """Load a wind-region layer once per path, layer, and file revision."""

    path = Path(path_text)
    try:
        gdf = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    except Exception as exc:
        raise ValueError(f"Failed to read wind-region GIS dataset {path}: {exc}") from exc
    gdf = gdf.set_crs("EPSG:4326") if gdf.crs is None else gdf.to_crs("EPSG:4326")
    gdf = gdf[gdf.geometry.notna()].copy()
    return gdf


def select_matching_polygon(matches: gpd.GeoDataFrame) -> Any:
    """Select the most specific covering polygon from one or more matches."""

    projected = matches.to_crs("EPSG:3577")
    areas = projected.geometry.area
    selected_index = areas.sort_values().index[0]
    return matches.loc[selected_index]


def neighbouring_polygons(
    gdf: gpd.GeoDataFrame,
    selected_index: Any,
    latitude: float,
    longitude: float,
    *,
    limit: int = 5,
) -> gpd.GeoDataFrame:
    """Return nearest polygons excluding the selected polygon."""

    point_gdf = gpd.GeoDataFrame(geometry=[Point(longitude, latitude)], crs="EPSG:4326")
    projected_crs = gdf.estimate_utm_crs() or "EPSG:3857"
    projected = gdf.to_crs(projected_crs)
    point = point_gdf.to_crs(projected_crs).geometry.iloc[0]
    distances = projected.geometry.distance(point)
    candidates = distances.drop(index=selected_index, errors="ignore").sort_values().head(limit)
    return gdf.loc[candidates.index]


def polygon_debug_record(
    index: Any,
    row: Any,
    columns: Any,
    site: SiteLocation,
    *,
    include_geometry: bool,
) -> dict[str, Any]:
    """Build a JSON-safe diagnostic record for a wind-region polygon."""

    region = extract_region_label(row, columns)
    projected = gpd.GeoDataFrame(geometry=[row.geometry], crs="EPSG:4326").to_crs("EPSG:3577")
    point_distance = point_to_geometry_distance_m(
        row.geometry,
        site.latitude,
        site.longitude,
    )
    record = {
        "feature_index": str(index),
        "region_name": region,
        "area_name": str(row.get("area", "")) if hasattr(row, "get") else "",
        "polygon_area_sq_km": round(float(projected.geometry.area.iloc[0]) / 1_000_000, 3),
        "distance_to_point_m": round(point_distance, 1),
        "distance_to_boundary_m": round(
            distance_to_geometry_boundary_m(row.geometry, site.latitude, site.longitude),
            1,
        ),
        "bounds": [round(float(value), 6) for value in row.geometry.bounds],
    }
    if include_geometry:
        record["geometry"] = mapping(row.geometry)
    return record


def point_to_geometry_distance_m(geometry: Any, latitude: float, longitude: float) -> float:
    """Return approximate projected distance from a site point to a polygon."""

    gdf = gpd.GeoDataFrame(geometry=[geometry], crs="EPSG:4326")
    point_gdf = gpd.GeoDataFrame(geometry=[Point(longitude, latitude)], crs="EPSG:4326")
    projected_crs = gdf.estimate_utm_crs() or "EPSG:3857"
    projected_geom = gdf.to_crs(projected_crs).geometry.iloc[0]
    projected_point = point_gdf.to_crs(projected_crs).geometry.iloc[0]
    return float(projected_geom.distance(projected_point))


def dataset_name(path: Path) -> str:
    """Return a human-readable dataset name."""

    if path.name.lower() == "as1170windzones.shp":
        return "Geoscience Australia as1170windzones"
    return path.stem


def region_sort_key(region: str) -> tuple[str, int, str]:
    """Sort region labels in a natural A0, A1, A2, B1 order."""

    match = re.match(r"([A-Z]+)([0-9]*)", region)
    if not match:
        return region, -1, region
    prefix, suffix = match.groups()
    return prefix, int(suffix or -1), region


def extract_region_label(row: Any, columns: Any) -> WindRegionLabel | None:
    """Extract a supported wind-region label from a GIS feature row."""

    configured_field = os.environ.get(FIELD_ENV)
    fields = [configured_field] if configured_field else []
    normalized = {str(column).lower().replace(" ", "_"): column for column in columns}
    fields.extend(normalized[field] for field in REGION_FIELD_CANDIDATES if field in normalized)
    fields.extend(column for column in columns if column not in fields and column != "geometry")
    for field in fields:
        if field is None or field not in columns:
            continue
        label = normalize_region_label(row[field])
        if label is not None:
            return label
    return None


def normalize_region_label(value: Any) -> WindRegionLabel | None:
    """Return a canonical supported wind-region label from arbitrary attribute text."""

    text = str(value or "").upper().strip()
    for label in REGION_LABELS:
        if re.search(rf"(?<![A-Z0-9]){label}(?![A-Z0-9])", text):
            return label  # type: ignore[return-value]
    compact = re.sub(r"[^A-Z0-9]", "", text)
    return compact if compact in REGION_LABELS else None  # type: ignore[return-value]


def boundary_warning_distance_m() -> float:
    """Return configured near-boundary threshold in metres."""

    value = os.environ.get(BOUNDARY_WARNING_DISTANCE_ENV)
    if value is None:
        return BOUNDARY_WARNING_DISTANCE_M
    try:
        return float(value)
    except ValueError:
        return BOUNDARY_WARNING_DISTANCE_M


def distance_to_geometry_boundary_m(geometry: Any, latitude: float, longitude: float) -> float:
    """Calculate approximate point-to-boundary distance using a local projected CRS."""

    gdf = gpd.GeoDataFrame(geometry=[geometry], crs="EPSG:4326")
    point_gdf = gpd.GeoDataFrame(geometry=[Point(longitude, latitude)], crs="EPSG:4326")
    projected_crs = gdf.estimate_utm_crs() or "EPSG:3857"
    projected_geom = gdf.to_crs(projected_crs).geometry.iloc[0]
    projected_point = point_gdf.to_crs(projected_crs).geometry.iloc[0]
    return float(projected_geom.boundary.distance(projected_point))


def nearest_region_index_and_distance(
    gdf: gpd.GeoDataFrame,
    latitude: float,
    longitude: float,
) -> tuple[Any, float]:
    """Return nearest polygon index and point-to-polygon distance in metres."""

    point_gdf = gpd.GeoDataFrame(geometry=[Point(longitude, latitude)], crs="EPSG:4326")
    projected_crs = gdf.estimate_utm_crs() or "EPSG:3857"
    projected = gdf.to_crs(projected_crs)
    point = point_gdf.to_crs(projected_crs).geometry.iloc[0]
    distances = projected.geometry.distance(point)
    nearest_index = distances.idxmin()
    return nearest_index, float(distances.loc[nearest_index])
