"""Height source selection, estimation assumptions, and confidence scoring."""

from __future__ import annotations

from dataclasses import dataclass

from openwind_au.models import ObstructionRecord


@dataclass(frozen=True)
class HeightEstimationConfig:
    """Configurable assumptions for low-confidence obstruction height estimates."""

    residential_storey_height_m: float = 3.0
    residential_two_storey_height_m: float = 6.0
    commercial_storey_height_m: float = 4.0
    industrial_storey_height_m: float = 6.0
    apartment_storey_height_m: float = 3.0


HEIGHT_SOURCE_LABELS = {
    "manual_verified": "Manual Verified",
    "IMPORTED": "Imported",
    "DSM_DTM": "DSM-DTM",
    "OSM_HEIGHT": "OSM Height",
    "OSM_LEVELS": "OSM Levels",
    "ESTIMATED": "Estimated",
    "missing": "Unknown",
}

HEIGHT_SOURCE_METHODS = {
    "manual_verified": "manual",
    "DSM_DTM": "dsm_dtm",
    "OSM_HEIGHT": "osm_height",
    "OSM_LEVELS": "osm_levels",
    "ESTIMATED": "assumption",
}


def resolve_operational_heights(
    records: list[ObstructionRecord],
    config: HeightEstimationConfig,
) -> list[ObstructionRecord]:
    """Apply source priority and estimation assumptions to obstruction records."""

    return [resolve_operational_height(record, config) for record in records]


def resolve_operational_height(
    record: ObstructionRecord,
    config: HeightEstimationConfig,
) -> ObstructionRecord:
    """Return a record with selected operational height and confidence populated."""

    raw_source_height = record.raw_source_height_m
    raw_source = record.raw_source_height_source
    if raw_source_height is None and record.height_source in {"OSM_HEIGHT", "OSM_LEVELS"}:
        raw_source_height = record.height_m
        raw_source = record.height_source

    if record.height_source == "manual_verified" and record.height_m is not None:
        return _copy_with_height(
            record,
            height=record.height_m,
            source="manual_verified",
            confidence="high",
            review_required=False,
            raw_source_height=record.height_m,
            raw_source="manual_verified",
        )

    if record.height_source == "IMPORTED" and record.height_m is not None:
        return _copy_with_height(
            record,
            height=record.height_m,
            source="IMPORTED",
            confidence="medium",
            review_required=True,
            raw_source_height=record.height_m,
            raw_source="IMPORTED",
        )

    if record.obstruction_height_m is not None:
        confidence = "low" if record.warnings else "high"
        return _copy_with_height(
            record,
            height=record.obstruction_height_m,
            source="DSM_DTM",
            confidence=confidence,
            review_required=confidence != "high",
            raw_source_height=raw_source_height or record.obstruction_height_m,
            raw_source=raw_source or "DSM_DTM",
        )

    if record.height_source == "OSM_HEIGHT" and record.height_m is not None:
        return _copy_with_height(
            record,
            height=record.height_m,
            source="OSM_HEIGHT",
            confidence="medium",
            review_required=True,
            raw_source_height=raw_source_height,
            raw_source=raw_source,
        )

    if record.height_source == "OSM_LEVELS" and record.height_m is not None:
        return _copy_with_height(
            record,
            height=record.height_m,
            source="OSM_LEVELS",
            confidence="medium",
            review_required=True,
            raw_source_height=raw_source_height,
            raw_source=raw_source,
        )

    estimated_height = estimate_height_from_assumptions(record, config)
    if estimated_height is not None:
        return _copy_with_height(
            record,
            height=estimated_height,
            source="ESTIMATED",
            confidence="low",
            review_required=True,
            estimated_height=estimated_height,
            raw_source_height=raw_source_height or estimated_height,
            raw_source=raw_source or "ESTIMATED",
            note="Height estimated from configurable class assumptions.",
        )

    return record.model_copy(
        update={
            "height_m": None,
            "selected_height_m": None,
            "height_source": "missing",
            "height_method": "unknown",
            "confidence": "unknown",
            "manual_review_required": True,
            "review_required": True,
            "raw_source_height_m": raw_source_height,
            "raw_source_height_source": raw_source,
        }
    )


def estimate_height_from_assumptions(
    record: ObstructionRecord,
    config: HeightEstimationConfig,
) -> float | None:
    """Estimate height from class assumptions, never from footprint size."""

    tags = {str(key): str(value).lower() for key, value in record.tags.items()}
    levels = record.building_levels
    if record.classification == "residential":
        if levels is not None and levels >= 2:
            return config.residential_two_storey_height_m
        return config.residential_storey_height_m
    if record.classification == "commercial":
        return config.commercial_storey_height_m * max(levels or 1, 1)
    if record.classification == "industrial":
        return config.industrial_storey_height_m
    if record.classification == "apartment":
        if levels is not None:
            return config.apartment_storey_height_m * levels
        return config.apartment_storey_height_m * 2
    if record.classification == "vegetation" and _has_tree_tags(tags):
        return 8.0
    if record.classification == "mixed":
        return None
    return None


def height_source_summary(records: list[ObstructionRecord]) -> dict[str, int]:
    """Summarise selected height sources for reports."""

    summary = {label: 0 for label in HEIGHT_SOURCE_LABELS.values()}
    for record in records:
        label = HEIGHT_SOURCE_LABELS.get(record.height_source, "Unknown")
        summary[label] = summary.get(label, 0) + 1
    return summary


def _copy_with_height(
    record: ObstructionRecord,
    *,
    height: float,
    source: str,
    confidence: str,
    review_required: bool,
    raw_source_height: float | None,
    raw_source: str | None,
    estimated_height: float | None = None,
    note: str | None = None,
) -> ObstructionRecord:
    notes = list(record.notes)
    if note and note not in notes:
        notes.append(note)
    return record.model_copy(
        update={
            "height_m": height,
            "selected_height_m": height,
            "height_source": source,
            "height_method": HEIGHT_SOURCE_METHODS.get(source, "unknown"),
            "confidence": confidence,
            "manual_review_required": review_required,
            "review_required": review_required,
            "estimated_height_m": estimated_height,
            "raw_source_height_m": raw_source_height,
            "raw_source_height_source": raw_source,
            "notes": notes,
        }
    )


def _has_tree_tags(tags: dict[str, str]) -> bool:
    return any(value in {"tree", "wood", "forest", "orchard", "scrub"} for value in tags.values())
