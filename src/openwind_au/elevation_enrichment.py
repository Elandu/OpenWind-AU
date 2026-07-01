"""DSM-DTM obstruction height enrichment."""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Protocol

import rasterio

from openwind_au.models import ObstructionRecord

EXTREME_HEIGHT_M = 80.0
LOW_HEIGHT_M = 1.0


class ElevationProvider(Protocol):
    """Minimal elevation provider protocol for DSM and DTM datasets."""

    def elevation(self, latitude: float, longitude: float) -> float:
        """Return elevation in metres above mean sea level."""


class RasterElevationProvider:
    """Read elevations from a raster DSM or DTM dataset."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.dataset = rasterio.open(self.path)

    def elevation(self, latitude: float, longitude: float) -> float:
        """Return nearest-sample raster elevation for a WGS84 coordinate."""

        if self.dataset.crs and self.dataset.crs.to_epsg() not in {4326, None}:
            raise RuntimeError(
                "RasterElevationProvider currently expects WGS84 rasters; reproject DSM/DTM first."
            )
        row, col = self.dataset.index(longitude, latitude)
        value = next(self.dataset.sample([(longitude, latitude)]))[0]
        if self.dataset.nodata is not None and value == self.dataset.nodata:
            raise RuntimeError(f"No elevation data at raster row {row}, col {col}.")
        return float(value)

    def close(self) -> None:
        """Close the raster dataset."""

        self.dataset.close()


def enrich_obstruction_heights(
    records: list[ObstructionRecord],
    dsm_provider: ElevationProvider | None,
    dtm_provider: ElevationProvider | None,
) -> tuple[list[ObstructionRecord], list[str]]:
    """Enrich obstruction records with DSM-DTM height estimates where possible."""

    warnings: list[str] = []
    if dsm_provider is None:
        warnings.append(
            "DSM unavailable; DSM-DTM obstruction height estimates were not calculated."
        )
    if dtm_provider is None:
        warnings.append(
            "DTM unavailable; DSM-DTM obstruction height estimates were not calculated."
        )
    if dsm_provider is None or dtm_provider is None:
        return records, warnings

    enriched = [enrich_obstruction_height(record, dsm_provider, dtm_provider) for record in records]
    return enriched, warnings


def enrich_obstruction_height(
    record: ObstructionRecord,
    dsm_provider: ElevationProvider,
    dtm_provider: ElevationProvider,
) -> ObstructionRecord:
    """Return one obstruction record enriched with DSM-DTM height data."""

    sample_points = footprint_sample_points(record.footprint_geometry)
    record_warnings = list(record.warnings)
    if not sample_points:
        record_warnings.append("No footprint sample points available for DSM-DTM enrichment.")
        return record.model_copy(update={"warnings": record_warnings})
    try:
        surface_values = [
            dsm_provider.elevation(latitude, longitude) for longitude, latitude in sample_points
        ]
    except Exception as exc:
        record_warnings.append(f"DSM unavailable for obstruction footprint: {exc}")
        return record.model_copy(update={"warnings": record_warnings})
    try:
        ground_values = [
            dtm_provider.elevation(latitude, longitude) for longitude, latitude in sample_points
        ]
    except Exception as exc:
        record_warnings.append(f"DTM unavailable for obstruction footprint: {exc}")
        return record.model_copy(update={"warnings": record_warnings})

    surface_rl = statistics.fmean(surface_values)
    ground_rl = statistics.fmean(ground_values)
    estimated_height = surface_rl - ground_rl
    if estimated_height < 0:
        record_warnings.append("Negative DSM-DTM height estimate; estimate was not used.")
        estimated_height_value = None
    else:
        estimated_height_value = estimated_height
        if estimated_height > EXTREME_HEIGHT_M:
            record_warnings.append("Extreme DSM-DTM height estimate; engineering review required.")
        if estimated_height < LOW_HEIGHT_M:
            record_warnings.append("Low confidence DSM-DTM height estimate below 1 m.")

    updates = {
        "ground_rl_m": ground_rl,
        "surface_rl_m": surface_rl,
        "obstruction_height_m": estimated_height_value,
        "enrichment_method": "DSM-DTM mean footprint samples",
        "warnings": record_warnings,
    }
    if estimated_height_value is not None:
        updates.update(
            {
                "obstruction_height_m": estimated_height_value,
                "notes": [
                    *record.notes,
                    "DSM-DTM height estimate recorded.",
                ],
            }
        )
    return record.model_copy(update=updates)


def classify_obstruction(tags: dict) -> str:
    """Classify an obstruction footprint from OSM-style tags."""

    normalized = {str(key): str(value).lower() for key, value in tags.items()}
    building = normalized.get("building")
    landuse = normalized.get("landuse")
    amenity = normalized.get("amenity")
    shop = normalized.get("shop")
    vegetation_keys = {"natural", "leaf_type", "leaf_cycle", "tree", "wood"}
    vegetation_values = {"tree", "wood", "forest", "orchard", "scrub", "grassland"}
    has_building = bool(building and building not in {"no", "false"})
    has_vegetation = any(key in normalized for key in vegetation_keys) or any(
        value in vegetation_values for key, value in normalized.items() if key != "landuse"
    )
    has_vegetation = has_vegetation or landuse in {"forest", "orchard", "grassland"}
    if has_building and has_vegetation:
        return "mixed"
    if has_vegetation:
        return "vegetation"
    if building in {"yes", "house", "detached", "semidetached_house", "terrace", "residential"}:
        return "residential"
    if landuse == "residential":
        return "residential"
    if building in {"apartments", "residential_apartment"}:
        return "apartment"
    if building in {"commercial", "retail", "office"} or shop or amenity in {"cafe", "restaurant"}:
        return "commercial"
    if building in {"industrial", "warehouse"} or landuse == "industrial":
        return "industrial"
    if has_building:
        return "unknown"
    return "unknown"


def footprint_sample_points(geometry: dict) -> list[tuple[float, float]]:
    """Return lon/lat sample points from a polygon footprint."""

    ring = geometry.get("coordinates", [[]])[0]
    if not ring:
        return []
    points = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    lon = statistics.fmean(point[0] for point in points)
    lat = statistics.fmean(point[1] for point in points)
    return [(lon, lat), *points]
