"""Building obstruction inventory for shielding review."""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import shutil
import subprocess
from io import StringIO
from json import JSONDecodeError
from typing import Any

import requests
from shapely.errors import ShapelyError
from shapely.geometry import shape

from openwind_au.elevation_enrichment import (
    ElevationProvider,
    RasterElevationProvider,
    classify_obstruction,
    enrich_obstruction_heights,
)
from openwind_au.geo import bearing_deg, geocode_address, haversine_distance_m
from openwind_au.height_estimation import (
    HeightEstimationConfig,
    height_source_summary,
    resolve_operational_heights,
)
from openwind_au.microsoft_footprints import (
    MICROSOFT_FOOTPRINT_SOURCE,
    MicrosoftFootprintResult,
    query_microsoft_building_footprints,
)
from openwind_au.models import (
    ExcludedObstructionObject,
    ObstructionDataQuality,
    ObstructionInventoryRequest,
    ObstructionInventoryResult,
    ObstructionManualOverride,
    ObstructionRecord,
    ReviewedFootprint,
    SiteLocation,
)
from openwind_au.shielding import run_shielding_sector_analysis

LOGGER = logging.getLogger(__name__)

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OVERPASS_QUERY_TIMEOUT_SECONDS = 15
OVERPASS_HTTP_TIMEOUT_SECONDS = 25
DUPLICATE_OVERLAP_THRESHOLD = 0.5
COMMON_OSM_BUILDING_VALUES = {
    "yes",
    "house",
    "residential",
    "detached",
    "semidetached_house",
    "terrace",
    "apartments",
    "commercial",
    "industrial",
    "retail",
    "school",
    "roof",
    "garage",
    "shed",
}
FOOTPRINT_SOURCES = {
    "OSM",
    MICROSOFT_FOOTPRINT_SOURCE,
    "manual_reviewed",
    "DSM_DERIVED",
}


class FootprintQueryError(RuntimeError):
    """Raised when public building footprint data cannot be retrieved."""


def run_obstruction_inventory(
    request: ObstructionInventoryRequest,
    footprints: list[dict[str, Any]] | None = None,
    dsm_provider: ElevationProvider | None = None,
    dtm_provider: ElevationProvider | None = None,
) -> ObstructionInventoryResult:
    """Build a review inventory of nearby obstructions."""

    site = resolve_obstruction_site(request)
    raw_footprints = footprints
    warnings: list[str] = []
    data_source_status = "ok"
    inventory_radius_m = request.radius_m
    if request.building_height_m is not None:
        inventory_radius_m = max(inventory_radius_m, math.ceil(20 * request.building_height_m))
    overpass_debug = empty_overpass_debug(
        site.latitude,
        site.longitude,
        inventory_radius_m,
    )
    microsoft_result = empty_microsoft_result(site.latitude, site.longitude, inventory_radius_m)
    osm_footprints: list[dict[str, Any]] = []
    microsoft_footprints: list[dict[str, Any]] = []
    if raw_footprints is None:
        try:
            microsoft_result = query_microsoft_building_footprints(
                site.latitude,
                site.longitude,
                inventory_radius_m,
            )
        except Exception as exc:
            microsoft_result = MicrosoftFootprintResult(
                footprints=[],
                source_status="unavailable",
                cache_status="error",
                warnings=[f"Microsoft Building Footprints cache query failed: {exc}"],
            )
        microsoft_footprints = normalise_footprints(
            microsoft_result.footprints,
            default_source=MICROSOFT_FOOTPRINT_SOURCE,
        )
        warnings.extend(microsoft_result.warnings)
        enrich_microsoft_with_overpass = os.environ.get(
            "OPENWIND_OVERPASS_ENRICH_MICROSOFT", ""
        ).lower() in {"1", "true", "yes"}
        if microsoft_footprints and not enrich_microsoft_with_overpass:
            raw_footprints = []
            overpass_debug["pipeline_log"].append(
                "Skipped live Overpass query because Microsoft Building Footprints cache "
                "supplied usable building geometry."
            )
            warnings.append(
                "Microsoft Building Footprints cache supplied obstruction geometry; "
                "live Overpass enrichment was skipped to keep the inventory responsive."
            )
        else:
            try:
                raw_footprints, overpass_debug = query_building_footprints_with_debug(
                    site.latitude,
                    site.longitude,
                    inventory_radius_m,
                )
            except FootprintQueryError as exc:
                raw_footprints = []
                if not microsoft_footprints:
                    data_source_status = "unavailable"
                    warnings.append(
                        "Building footprint query failed. The obstruction inventory is empty "
                        "until Microsoft Building Footprints cache data or OSM data is available; "
                        "indicative Ms cannot be calculated."
                    )
                warnings.append(str(exc))
        osm_footprints = normalise_footprints(raw_footprints, default_source="OSM")
    else:
        osm_footprints = normalise_footprints(raw_footprints, default_source="OSM")
    reviewed_footprints = reviewed_footprints_to_records(request.reviewed_footprints)
    preferred_footprints = [*reviewed_footprints, *microsoft_footprints]
    merged_footprints, duplicate_exclusions = merge_duplicate_footprints(
        osm_footprints,
        preferred_footprints,
    )
    records, excluded_objects = build_obstruction_records_with_exclusions(
        merged_footprints,
        site.latitude,
        site.longitude,
        inventory_radius_m,
        request.default_storey_height_m,
    )
    excluded_objects = [*duplicate_exclusions, *excluded_objects]
    if dsm_provider is None or dtm_provider is None:
        env_dsm_provider, env_dtm_provider, provider_warnings = elevation_providers_from_env()
        dsm_provider = dsm_provider or env_dsm_provider
        dtm_provider = dtm_provider or env_dtm_provider
        warnings.extend(provider_warnings)
    records, enrichment_warnings = enrich_obstruction_heights(records, dsm_provider, dtm_provider)
    warnings.extend(enrichment_warnings)
    records = apply_manual_overrides(
        records,
        request.manual_overrides,
        request.default_storey_height_m,
    )
    records = resolve_operational_heights(
        records,
        HeightEstimationConfig(
            residential_storey_height_m=request.residential_storey_height_m,
            residential_two_storey_height_m=request.residential_two_storey_height_m,
            commercial_storey_height_m=request.commercial_storey_height_m,
        ),
    )
    result_request = (
        request.model_copy(update={"radius_m": inventory_radius_m})
        if inventory_radius_m != request.radius_m
        else request
    )
    shielding_sectors = (
        run_shielding_sector_analysis(site, records, request.building_height_m)
        if request.building_height_m is not None
        else []
    )
    data_quality = obstruction_data_quality(
        source_footprints=[
            *osm_footprints,
            *microsoft_footprints,
            *reviewed_footprints,
        ],
        records=records,
        excluded_objects=excluded_objects,
        data_source_status=data_source_status,
        overpass_debug=overpass_debug,
        microsoft_result=microsoft_result,
    )
    warnings.extend(data_quality.warnings)
    return ObstructionInventoryResult(
        input=result_request,
        site=site,
        obstructions=records,
        missing_height_count=sum(item.height_m is None for item in records),
        reviewed_height_count=sum(
            item.height_source == "manual_verified" and item.height_m is not None
            for item in records
        ),
        height_source_summary=height_source_summary(records),
        data_quality=data_quality,
        shielding_sectors=shielding_sectors,
        data_source_status=data_source_status,
        warnings=warnings,
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
    """Query OpenStreetMap obstruction footprints around a site using Overpass."""

    footprints, _debug = query_building_footprints_with_debug(
        latitude,
        longitude,
        radius_m,
        user_agent,
    )
    return footprints


def query_building_footprints_with_debug(
    latitude: float,
    longitude: float,
    radius_m: int,
    user_agent: str = "OpenWind-AU/0.1",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Query OpenStreetMap building footprints and return pipeline diagnostics."""

    query = build_overpass_building_query(latitude, longitude, radius_m)
    LOGGER.info(
        "Overpass obstruction query centre=(%s,%s) radius_m=%s", latitude, longitude, radius_m
    )
    LOGGER.info("Overpass obstruction query string:\n%s", query)
    data = _post_overpass(query, user_agent)
    elements = data.get("elements", [])
    footprints, conversion_debug = overpass_elements_to_footprints_with_debug(elements)
    debug = {
        **empty_overpass_debug(latitude, longitude, radius_m),
        "overpass_query": query,
        "raw_overpass_counts": overpass_element_counts(elements),
        "parsed_counts": conversion_debug["parsed_counts"],
        "sample_building_ids": conversion_debug["sample_building_ids"],
        "returned_geometry_bbox": geometry_collection_bbox(
            [item["footprint_geometry"] for item in footprints]
        ),
        "raw_osm_building_footprints": footprints,
        "pipeline_log": conversion_debug["pipeline_log"],
    }
    log_obstruction_debug(debug)
    return footprints, debug


def build_overpass_building_query(latitude: float, longitude: float, radius_m: int) -> str:
    """Return the broad Overpass query used for OSM building retrieval."""

    return f"""
    [out:json][timeout:{OVERPASS_QUERY_TIMEOUT_SECONDS}];
    (
      way(around:{radius_m},{latitude},{longitude})["building"];
      relation(around:{radius_m},{latitude},{longitude})["building"];
    );
    out body geom;
    """


def overpass_elements_to_footprints(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Overpass elements with geometry into simple footprint records."""

    footprints, _debug = overpass_elements_to_footprints_with_debug(elements)
    return footprints


def overpass_elements_to_footprints_with_debug(
    elements: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Convert Overpass elements with geometry and report conversion diagnostics."""

    footprints: list[dict[str, Any]] = []
    converted_way_count = 0
    converted_relation_count = 0
    relation_incomplete_count = 0
    missing_geometry_count = 0
    sample_building_ids: list[str] = []
    pipeline_log: list[str] = []
    for element in elements:
        geometry = _element_to_geometry(element)
        element_type = element.get("type", "feature")
        element_id = element.get("id")
        source_id = f"osm-{element_type}-{element_id}"
        if element.get("tags", {}).get("building") and len(sample_building_ids) < 10:
            sample_building_ids.append(source_id)
        if not geometry:
            if element.get("tags", {}).get("building"):
                missing_geometry_count += 1
                pipeline_log.append(f"{source_id}: building element missing polygon geometry")
            continue
        if element_type == "way":
            converted_way_count += 1
        if element_type == "relation":
            converted_relation_count += 1
            if relation_has_multiple_outer_geometries(element):
                relation_incomplete_count += 1
                pipeline_log.append(
                    f"{source_id}: relation has multiple outer geometries; first outer polygon used"
                )
        footprints.append(
            {
                "source_id": source_id,
                "footprint_geometry": geometry,
                "tags": element.get("tags", {}),
                "footprint_source": "OSM",
                "source_provenance": [source_id],
            }
        )
    parsed_counts = {
        "converted_to_polygons": len(footprints),
        "converted_way_polygons": converted_way_count,
        "converted_relation_polygons": converted_relation_count,
        "building_elements_without_polygon_geometry": missing_geometry_count,
        "relation_multipolygons_reported_incomplete": relation_incomplete_count,
    }
    return footprints, {
        "parsed_counts": parsed_counts,
        "sample_building_ids": sample_building_ids,
        "pipeline_log": pipeline_log,
    }


def overpass_element_counts(elements: list[dict[str, Any]]) -> dict[str, int]:
    """Return raw Overpass element counts by type and building tag."""

    ways = [item for item in elements if item.get("type") == "way"]
    relations = [item for item in elements if item.get("type") == "relation"]
    nodes = [item for item in elements if item.get("type") == "node"]
    return {
        "raw_elements": len(elements),
        "nodes": len(nodes),
        "ways": len(ways),
        "relations": len(relations),
        "building_tagged_ways": sum(bool(item.get("tags", {}).get("building")) for item in ways),
        "building_tagged_relations": sum(
            bool(item.get("tags", {}).get("building")) for item in relations
        ),
    }


def empty_overpass_debug(latitude: float, longitude: float, radius_m: int) -> dict[str, Any]:
    """Return an empty diagnostics object for supplied or failed footprint runs."""

    return {
        "query_centre": {"latitude": latitude, "longitude": longitude},
        "query_radius_m": radius_m,
        "overpass_query": build_overpass_building_query(latitude, longitude, radius_m),
        "raw_overpass_counts": {
            "raw_elements": 0,
            "nodes": 0,
            "ways": 0,
            "relations": 0,
            "building_tagged_ways": 0,
            "building_tagged_relations": 0,
        },
        "parsed_counts": {
            "converted_to_polygons": 0,
            "converted_way_polygons": 0,
            "converted_relation_polygons": 0,
            "building_elements_without_polygon_geometry": 0,
            "relation_multipolygons_reported_incomplete": 0,
        },
        "sample_building_ids": [],
        "returned_geometry_bbox": None,
        "raw_osm_building_footprints": [],
        "pipeline_log": [],
    }


def empty_microsoft_result(
    latitude: float,
    longitude: float,
    radius_m: int,
) -> MicrosoftFootprintResult:
    """Return empty Microsoft diagnostics for supplied-footprint runs."""

    return MicrosoftFootprintResult(
        footprints=[],
        source_status="not_queried",
        cache_status="not_queried",
        warnings=[],
    )


def log_obstruction_debug(debug: dict[str, Any]) -> None:
    """Emit obstruction pipeline counts to the application log."""

    LOGGER.info("Obstruction query centre: %s", debug.get("query_centre"))
    LOGGER.info("Obstruction query radius_m: %s", debug.get("query_radius_m"))
    LOGGER.info("Raw Overpass counts: %s", debug.get("raw_overpass_counts"))
    LOGGER.info("Parsed obstruction counts: %s", debug.get("parsed_counts"))


def normalise_footprints(
    footprints: list[dict[str, Any]],
    default_source: str,
) -> list[dict[str, Any]]:
    """Ensure footprint dictionaries carry source/provenance fields."""

    normalised = []
    for index, footprint in enumerate(footprints):
        source_id = (
            footprint.get("source_id") or footprint.get("id") or f"{default_source}-{index + 1}"
        )
        source = normalise_footprint_source(
            footprint.get("footprint_source") or footprint.get("source") or default_source
        )
        normalised.append(
            {
                **footprint,
                "source_id": source_id,
                "footprint_source": source,
                "source_provenance": footprint.get("source_provenance") or [source_id],
                "tags": footprint.get("tags", {}),
            }
        )
    return normalised


def reviewed_footprints_to_records(reviewed: list[ReviewedFootprint]) -> list[dict[str, Any]]:
    """Convert reviewed JSON obstruction geometries into preferred footprints."""

    return [
        {
            "source_id": item.id,
            "footprint_geometry": item.geometry,
            "classification": item.classification,
            "height_m": item.height_m,
            "building_levels": item.building_levels,
            "footprint_source": "manual_reviewed",
            "source": item.source,
            "source_provenance": [f"manual_reviewed:{item.id}"],
            "tags": {
                "source": item.source,
                "height": item.height_m,
                "building:levels": item.building_levels,
                "classification": item.classification,
            },
            "notes": [item.notes] if item.notes else [],
        }
        for item in reviewed
    ]


def merge_duplicate_footprints(
    osm_footprints: list[dict[str, Any]],
    preferred_footprints: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[ExcludedObstructionObject]]:
    """Merge preferred and OSM footprints that substantially overlap."""

    if not preferred_footprints:
        return osm_footprints, []
    merged: list[dict[str, Any]] = []
    excluded: list[ExcludedObstructionObject] = []
    for preferred in preferred_footprints:
        if preferred_overlaps_existing(preferred, merged, excluded):
            continue
        merged.append(dict(preferred))
    duplicate_osm_ids: set[str] = set()
    for preferred in merged:
        preferred_duplicates = []
        for osm in osm_footprints:
            osm_id = str(osm.get("source_id"))
            if osm_id in duplicate_osm_ids:
                continue
            if (
                geometry_overlap_ratio(
                    preferred.get("footprint_geometry", {}),
                    osm.get("footprint_geometry", {}),
                )
                >= DUPLICATE_OVERLAP_THRESHOLD
            ):
                duplicate_osm_ids.add(osm_id)
                preferred_duplicates.append(osm_id)
                merge_osm_attributes_into_preferred(preferred, osm)
                excluded.append(
                    ExcludedObstructionObject(
                        object_id=osm_id,
                        source="OSM",
                        reason=duplicate_reason_for_preferred(preferred),
                        footprint_geometry=osm.get("footprint_geometry"),
                    )
                )
        if preferred_duplicates:
            preferred["source_provenance"] = [
                *preferred.get("source_provenance", []),
                *[f"OSM:{item}" for item in preferred_duplicates],
            ]
            preferred["duplicate_source_ids"] = preferred_duplicates
    for osm in osm_footprints:
        if str(osm.get("source_id")) not in duplicate_osm_ids:
            merged.append(osm)
    return merged, excluded


def preferred_overlaps_existing(
    preferred: dict[str, Any],
    existing_footprints: list[dict[str, Any]],
    excluded: list[ExcludedObstructionObject],
) -> bool:
    """Return whether a lower-priority preferred footprint overlaps an existing one."""

    for existing in existing_footprints:
        if (
            geometry_overlap_ratio(
                preferred.get("footprint_geometry", {}),
                existing.get("footprint_geometry", {}),
            )
            < DUPLICATE_OVERLAP_THRESHOLD
        ):
            continue
        excluded.append(
            ExcludedObstructionObject(
                object_id=str(preferred.get("source_id")),
                source=normalise_footprint_source(preferred.get("footprint_source")),
                reason=duplicate_reason_for_preferred(existing),
                footprint_geometry=preferred.get("footprint_geometry"),
            )
        )
        return True
    return False


def duplicate_reason_for_preferred(preferred: dict[str, Any]) -> str:
    """Return a duplicate exclusion reason for a preferred footprint source."""

    source = preferred.get("footprint_source")
    if source == MICROSOFT_FOOTPRINT_SOURCE:
        return "duplicate_microsoft_overlap"
    if source == "manual_reviewed":
        return "duplicate_manual_reviewed_overlap"
    return "duplicate_preferred_overlap"


def merge_osm_attributes_into_preferred(
    preferred: dict[str, Any],
    osm: dict[str, Any],
) -> None:
    """Copy useful OSM building attributes onto a preferred footprint."""

    preferred_tags = dict(preferred.get("tags", {}))
    osm_tags = dict(osm.get("tags", {}))
    for key in ("height", "building:height", "building:levels", "levels", "building"):
        if key not in preferred_tags and key in osm_tags:
            preferred_tags[key] = osm_tags[key]
    if osm_tags:
        preferred_tags.setdefault("osm:matched_source_id", osm.get("source_id"))
    preferred["tags"] = preferred_tags


def build_obstruction_records(
    footprints: list[dict[str, Any]],
    site_latitude: float,
    site_longitude: float,
    radius_m: int,
    default_storey_height_m: float = 3.0,
) -> list[ObstructionRecord]:
    """Create obstruction records from footprint geometries and tags."""

    records, _excluded = build_obstruction_records_with_exclusions(
        footprints,
        site_latitude,
        site_longitude,
        radius_m,
        default_storey_height_m,
    )
    return records


def build_obstruction_records_with_exclusions(
    footprints: list[dict[str, Any]],
    site_latitude: float,
    site_longitude: float,
    radius_m: int,
    default_storey_height_m: float = 3.0,
) -> tuple[list[ObstructionRecord], list[ExcludedObstructionObject]]:
    """Create obstruction records and excluded-object diagnostics."""

    records: list[ObstructionRecord] = []
    excluded: list[ExcludedObstructionObject] = []
    for index, footprint in enumerate(footprints):
        source_id = str(footprint.get("source_id") or f"obstruction-{index + 1}")
        source = normalise_footprint_source(footprint.get("footprint_source") or "OSM")
        geometry = footprint.get("footprint_geometry")
        if not is_polygon_geometry(geometry):
            excluded.append(
                ExcludedObstructionObject(
                    object_id=source_id,
                    source=source,
                    reason="invalid_or_missing_polygon_geometry",
                    footprint_geometry=geometry,
                )
            )
            continue
        centroid_lon, centroid_lat = polygon_centroid(geometry["coordinates"][0])
        distance = haversine_distance_m(
            site_latitude,
            site_longitude,
            centroid_lat,
            centroid_lon,
        )
        if distance > radius_m:
            excluded.append(
                ExcludedObstructionObject(
                    object_id=source_id,
                    source=source,
                    reason="outside_inventory_radius",
                    footprint_geometry=geometry,
                )
            )
            continue
        tags = footprint.get("tags", {})
        height = height_from_footprint(footprint, tags, default_storey_height_m)
        obstruction_id = source_id
        records.append(
            ObstructionRecord(
                obstruction_id=obstruction_id,
                source_id=source_id,
                classification=footprint.get("classification") or classify_obstruction(tags),
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
                selected_height_m=height["height_m"],
                raw_source_height_m=height["height_m"],
                raw_source_height_source=height["height_source"]
                if height["height_source"] != "missing"
                else None,
                building_levels=height["building_levels"],
                height_source=height["height_source"],
                confidence=height["confidence"],
                manual_review_required=height["manual_review_required"],
                review_required=height["manual_review_required"],
                footprint_source=source,
                source_provenance=footprint.get("source_provenance", [source_id]),
                duplicate_source_ids=footprint.get("duplicate_source_ids", []),
                tags=tags,
                notes=[*height["notes"], *footprint.get("notes", [])],
            )
        )

    records.sort(key=lambda item: item.distance_m)
    return records, excluded


def elevation_providers_from_env() -> tuple[
    ElevationProvider | None,
    ElevationProvider | None,
    list[str],
]:
    """Load DSM and DTM raster providers from environment variables when configured."""

    warnings: list[str] = []
    dsm_path = os.environ.get("OPENWIND_DSM_PATH")
    dtm_path = os.environ.get("OPENWIND_DTM_PATH")
    dsm_provider = None
    dtm_provider = None
    if dsm_path:
        try:
            dsm_provider = RasterElevationProvider(dsm_path)
        except Exception as exc:
            warnings.append(f"DSM unavailable from OPENWIND_DSM_PATH: {exc}")
    if dtm_path:
        try:
            dtm_provider = RasterElevationProvider(dtm_path)
        except Exception as exc:
            warnings.append(f"DTM unavailable from OPENWIND_DTM_PATH: {exc}")
    return dsm_provider, dtm_provider, warnings


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
            "height_source": "OSM_HEIGHT",
            "confidence": "medium",
            "manual_review_required": True,
            "notes": ["Height taken from explicit OSM height tag."],
        }
    if building_levels is not None:
        return {
            "height_m": building_levels * default_storey_height_m,
            "building_levels": building_levels,
            "height_source": "OSM_LEVELS",
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


def height_from_footprint(
    footprint: dict[str, Any],
    tags: dict[str, Any],
    default_storey_height_m: float = 3.0,
) -> dict[str, Any]:
    """Resolve height from imported attributes before falling back to tags."""

    imported_height = parse_float(footprint.get("height_m"))
    imported_levels = parse_float(footprint.get("building_levels"))
    if footprint.get("footprint_source") == "manual_reviewed":
        if imported_height is not None:
            return {
                "height_m": imported_height,
                "building_levels": imported_levels,
                "height_source": "manual_verified",
                "confidence": "high",
                "manual_review_required": False,
                "notes": ["Height supplied by reviewed obstruction JSON."],
            }
        if imported_levels is not None:
            return {
                "height_m": imported_levels * default_storey_height_m,
                "building_levels": imported_levels,
                "height_source": "manual_verified",
                "confidence": "high",
                "manual_review_required": False,
                "notes": ["Height estimated from reviewed obstruction levels."],
            }
    if imported_height is not None:
        return {
            "height_m": imported_height,
            "building_levels": imported_levels,
            "height_source": "IMPORTED",
            "confidence": "medium",
            "manual_review_required": True,
            "notes": ["Height supplied by imported footprint source."],
        }
    if imported_levels is not None:
        return {
            "height_m": imported_levels * default_storey_height_m,
            "building_levels": imported_levels,
            "height_source": "IMPORTED",
            "confidence": "medium",
            "manual_review_required": True,
            "notes": ["Height estimated from imported building levels."],
        }
    return height_from_tags(tags, default_storey_height_m)


def obstruction_data_quality(
    *,
    source_footprints: list[dict[str, Any]],
    records: list[ObstructionRecord],
    excluded_objects: list[ExcludedObstructionObject],
    data_source_status: str,
    overpass_debug: dict[str, Any] | None = None,
    microsoft_result: MicrosoftFootprintResult | None = None,
) -> ObstructionDataQuality:
    """Summarise obstruction source completeness and usability."""

    overpass_debug = overpass_debug or empty_overpass_debug(0.0, 0.0, 0)
    microsoft_result = microsoft_result or empty_microsoft_result(0.0, 0.0, 0)
    excluded_reasons: dict[str, int] = {}
    for item in excluded_objects:
        excluded_reasons[item.reason] = excluded_reasons.get(item.reason, 0) + 1
    LOGGER.info("Obstruction excluded reason counts: %s", excluded_reasons)
    source_summary: dict[str, int] = {"DSM_DERIVED": 0}
    for record in records:
        source_summary[record.footprint_source] = source_summary.get(record.footprint_source, 0) + 1
    total = len(records)
    with_height = sum(has_source_height_data(record) for record in records)
    review_required = sum(record.review_required for record in records)
    microsoft_count = sum(
        footprint.get("footprint_source") == MICROSOFT_FOOTPRINT_SOURCE
        for footprint in source_footprints
    )
    osm_count = sum(is_osm_building_footprint(footprint) for footprint in source_footprints)
    warnings = obstruction_data_quality_warnings(
        data_source_status=data_source_status,
        records=records,
        microsoft_count=microsoft_count,
        osm_count=osm_count,
        microsoft_result=microsoft_result,
        overpass_debug=overpass_debug,
    )
    parsed_counts = overpass_debug.get("parsed_counts", {})
    raw_overpass_counts = overpass_debug.get("raw_overpass_counts", {})
    pipeline_log = [
        f"query_centre={overpass_debug.get('query_centre')}",
        f"query_radius_m={overpass_debug.get('query_radius_m')}",
        f"raw_overpass_counts={raw_overpass_counts}",
        f"parsed_counts={parsed_counts}",
        f"excluded_reasons={excluded_reasons}",
        *overpass_debug.get("pipeline_log", []),
    ]
    return ObstructionDataQuality(
        query_centre=overpass_debug.get("query_centre"),
        query_radius_m=overpass_debug.get("query_radius_m"),
        overpass_query=overpass_debug.get("overpass_query"),
        raw_overpass_counts=raw_overpass_counts,
        parsed_counts={
            **parsed_counts,
            "excluded": len(excluded_objects),
        },
        total_osm_building_footprints_found=sum(
            is_osm_building_footprint(footprint) for footprint in source_footprints
        ),
        total_microsoft_building_footprints_found=microsoft_count,
        total_vegetation_polygons_found=sum(
            is_vegetation_footprint(footprint) for footprint in source_footprints
        ),
        microsoft_source_status=microsoft_result.source_status,
        microsoft_cache_status=microsoft_result.cache_status,
        microsoft_cache_path=microsoft_result.cache_path,
        microsoft_cache_files=microsoft_result.cache_files,
        osm_fallback_used=bool(osm_count and not microsoft_count),
        total_usable_obstruction_polygons=total,
        number_excluded=len(excluded_objects),
        excluded_reasons=excluded_reasons,
        percentage_with_height_data=round((with_height / total * 100) if total else 0.0, 1),
        percentage_requiring_manual_review=round(
            (review_required / total * 100) if total else 0.0,
            1,
        ),
        source_summary=source_summary,
        duplicate_overlap_count=sum(
            count
            for reason, count in excluded_reasons.items()
            if reason.startswith("duplicate_") and reason.endswith("_overlap")
        ),
        warnings=warnings,
        excluded_objects=excluded_objects,
        raw_osm_building_footprints=overpass_debug.get("raw_osm_building_footprints", []),
        sample_building_ids=overpass_debug.get("sample_building_ids", []),
        returned_geometry_bbox=overpass_debug.get("returned_geometry_bbox"),
        pipeline_log=pipeline_log,
    )


def obstruction_data_quality_warnings(
    *,
    data_source_status: str,
    records: list[ObstructionRecord],
    microsoft_count: int,
    osm_count: int,
    microsoft_result: MicrosoftFootprintResult,
    overpass_debug: dict[str, Any] | None = None,
) -> list[str]:
    """Return obstruction data quality warnings."""

    overpass_debug = overpass_debug or {}
    raw_counts = overpass_debug.get("raw_overpass_counts", {})
    parsed_counts = overpass_debug.get("parsed_counts", {})
    warnings = ["Missing footprints can materially affect shielding evidence."]
    if data_source_status == "unavailable" or len(records) < 5:
        warnings.append("Building footprint coverage appears incomplete.")
    if microsoft_count:
        warnings.append("Microsoft Australia Building Footprints cache supplied building geometry.")
    elif osm_count:
        warnings.append(
            "Microsoft footprint cache unavailable; OSM building polygons used as fallback."
        )
    elif microsoft_result.cache_status in {"miss", "hit_empty"}:
        warnings.append(
            "Microsoft building footprint cache returned no usable footprints for this site."
        )
    if (
        raw_counts.get("building_tagged_ways", 0) + raw_counts.get("building_tagged_relations", 0)
        >= 10
        and parsed_counts.get("converted_to_polygons", 0) < 5
    ):
        warnings.append(
            "Fewer than expected building footprints were detected for a visibly built-up area."
        )
    if raw_counts.get("nodes", 0) and not (
        raw_counts.get("ways", 0) or raw_counts.get("relations", 0)
    ):
        warnings.append("Overpass returned only nodes; building polygon geometry is incomplete.")
    if parsed_counts.get("building_elements_without_polygon_geometry", 0):
        warnings.append("Some Overpass building elements did not include usable polygon geometry.")
    if parsed_counts.get("relation_multipolygons_reported_incomplete", 0):
        warnings.append(
            "Some relation/multipolygon buildings were simplified; review raw OSM geometry."
        )
    if any(record.height_m is None for record in records):
        warnings.append("Some obstruction footprints are missing usable height data.")
    return warnings


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
                    "selected_height_m": height_m,
                    "raw_source_height_m": height_m,
                    "raw_source_height_source": "manual_verified" if height_m is not None else None,
                    "building_levels": building_levels
                    if building_levels is not None
                    else record.building_levels,
                    "height_source": "manual_verified",
                    "confidence": "high" if height_m is not None else "unknown",
                    "manual_review_required": height_m is None,
                    "review_required": height_m is None,
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


def relation_has_multiple_outer_geometries(element: dict[str, Any]) -> bool:
    """Return whether a relation has multiple outer geometries."""

    if element.get("type") != "relation":
        return False
    outer_members = [
        member
        for member in element.get("members", [])
        if member.get("role") in {"outer", ""} and member.get("geometry")
    ]
    return len(outer_members) > 1


def _polygon_from_ring(ring: list[list[float]]) -> dict[str, Any] | None:
    if len(ring) < 3:
        return None
    if ring[0] != ring[-1]:
        ring = [*ring, ring[0]]
    return {"type": "Polygon", "coordinates": [ring]}


def is_polygon_geometry(geometry: Any) -> bool:
    """Return whether geometry is a supported polygon footprint."""

    return (
        isinstance(geometry, dict)
        and geometry.get("type") == "Polygon"
        and bool(geometry.get("coordinates"))
        and bool(geometry.get("coordinates", [[]])[0])
    )


def geometry_collection_bbox(geometries: list[dict[str, Any]]) -> list[float] | None:
    """Return [min_lon, min_lat, max_lon, max_lat] for polygon geometries."""

    points: list[list[float]] = []
    for geometry in geometries:
        if not is_polygon_geometry(geometry):
            continue
        points.extend(geometry.get("coordinates", [[]])[0])
    if not points:
        return None
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]


def normalise_footprint_source(value: Any) -> str:
    """Return a supported footprint source label."""

    source = str(value or "OSM")
    return source if source in FOOTPRINT_SOURCES else "OSM"


def geometry_overlap_ratio(geometry_a: dict, geometry_b: dict) -> float:
    """Return overlap ratio against the smaller polygon area."""

    if not is_polygon_geometry(geometry_a) or not is_polygon_geometry(geometry_b):
        return 0.0
    try:
        origin_latitude, origin_longitude = geometry_pair_projection_origin(geometry_a, geometry_b)
        polygon_a = shape(
            project_polygon_geometry_to_local_m(geometry_a, origin_latitude, origin_longitude)
        )
        polygon_b = shape(
            project_polygon_geometry_to_local_m(geometry_b, origin_latitude, origin_longitude)
        )
        if polygon_a.is_empty or polygon_b.is_empty:
            return 0.0
        min_area = min(polygon_a.area, polygon_b.area)
        if min_area <= 0:
            return 0.0
        return polygon_a.intersection(polygon_b).area / min_area
    except (ShapelyError, AttributeError, ValueError):
        return 0.0


def geometry_pair_projection_origin(
    geometry_a: dict[str, Any],
    geometry_b: dict[str, Any],
) -> tuple[float, float]:
    """Return a local projection origin as latitude, longitude."""

    points = [
        *geometry_a.get("coordinates", [[]])[0],
        *geometry_b.get("coordinates", [[]])[0],
    ]
    longitude = sum(point[0] for point in points) / max(len(points), 1)
    latitude = sum(point[1] for point in points) / max(len(points), 1)
    return latitude, longitude


def project_polygon_geometry_to_local_m(
    geometry: dict[str, Any],
    origin_latitude: float,
    origin_longitude: float,
) -> dict[str, Any]:
    """Project a WGS84 lon/lat polygon to local metre offsets for area operations."""

    projected_ring = []
    for longitude, latitude in geometry.get("coordinates", [[]])[0]:
        east, north = local_offsets_m(latitude, longitude, origin_latitude, origin_longitude)
        projected_ring.append([east, north])
    return {"type": "Polygon", "coordinates": [projected_ring]}


def local_offsets_m(
    latitude: float,
    longitude: float,
    origin_latitude: float,
    origin_longitude: float,
) -> tuple[float, float]:
    """Return local east/north offsets in metres from an origin."""

    earth_radius_m = 6_371_008.8
    east = (
        math.radians(longitude - origin_longitude)
        * earth_radius_m
        * math.cos(math.radians(origin_latitude))
    )
    north = math.radians(latitude - origin_latitude) * earth_radius_m
    return east, north


def is_osm_building_footprint(footprint: dict[str, Any]) -> bool:
    """Return whether a footprint is an OSM building footprint."""

    tags = footprint.get("tags", {})
    return footprint.get("footprint_source") == "OSM" and bool(tags.get("building"))


def is_common_osm_building_tag(tags: dict[str, Any]) -> bool:
    """Return whether tags include one of the audited common OSM building values."""

    value = str(tags.get("building", "")).lower()
    return value in COMMON_OSM_BUILDING_VALUES


def is_vegetation_footprint(footprint: dict[str, Any]) -> bool:
    """Return whether a footprint represents vegetation."""

    tags = footprint.get("tags", {})
    classification = footprint.get("classification") or classify_obstruction(tags)
    return classification == "vegetation"


def has_source_height_data(record: ObstructionRecord) -> bool:
    """Return whether a record has source-supplied or reviewed height data."""

    return record.raw_source_height_m is not None and record.raw_source_height_source in {
        "manual_verified",
        "IMPORTED",
        "OSM_HEIGHT",
        "OSM_LEVELS",
        "DSM_DTM",
    }


def _post_overpass(query: str, user_agent: str) -> dict[str, Any]:
    errors: list[str] = []
    for url in OVERPASS_URLS:
        try:
            return _post_overpass_url(url, query, user_agent)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise FootprintQueryError("; ".join(errors))


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
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=OVERPASS_HTTP_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            timeout = exc.timeout or OVERPASS_HTTP_TIMEOUT_SECONDS
            raise RuntimeError(f"request timed out after {timeout:g} seconds") from exc
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or f"curl exited {completed.returncode}")
        if not completed.stdout:
            raise RuntimeError("empty Overpass response")
        try:
            return json.loads(completed.stdout)
        except (TypeError, JSONDecodeError) as exc:
            raise RuntimeError(f"invalid Overpass JSON response: {exc}") from exc

    response = requests.post(
        url,
        data={"data": query},
        headers={"User-Agent": user_agent},
        timeout=OVERPASS_HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"invalid Overpass JSON response: {exc}") from exc
