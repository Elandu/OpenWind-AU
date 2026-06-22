"""Tests for report and export helpers."""

from __future__ import annotations

import json
import re

from openwind_au.analysis import run_site_analysis
from openwind_au.dem import DEMProvider
from openwind_au.models import ObstructionInventoryRequest, SiteAnalysisRequest
from openwind_au.obstructions import run_obstruction_inventory
from openwind_au.reports import (
    combined_map_html,
    map_html,
    obstruction_map_html,
    profile_plot_html,
    render_html_report,
    result_to_json,
    terrain_category_map_html,
)
from openwind_au.terrain_category import run_terrain_category_evidence


class FlatDEM(DEMProvider):
    def elevation(self, latitude: float, longitude: float) -> float:
        return 50.0


def test_report_helpers_render_outputs() -> None:
    result = run_site_analysis(
        SiteAnalysisRequest(
            latitude=-33.86,
            longitude=151.21,
            building_height_m=10,
            radius_m=500,
            sample_interval_m=100,
        ),
        FlatDEM(),
    )

    data = result_to_json(result)
    html = render_html_report(result)
    plot = profile_plot_html(result)
    fmap = map_html(result)

    assert data["site"]["ground_elevation_m"] == 50
    assert data["profiles"][0]["direction"] == "N"
    assert len(data["features"]) == 8
    assert data["features"][0]["feature_type"] == "no significant feature"
    assert "competent engineer" in " ".join(data["features"][0]["notes"])
    assert "Preliminary Terrain Report" in html
    assert "Terrain Profile Summary" in html
    assert "Preliminary Topographic Screening" in html
    assert "no significant feature" in html
    assert "competent engineer" in html
    assert "plotly" in plot.lower()
    assert "site" in plot
    assert "leaflet" in fmap.lower()
    assert "Analysis radius" in fmap


def microsoft_footprint(index: int, north: int, east: int, height: float = 12.0) -> dict:
    lat = -33.86 + north * 0.00008
    lon = 151.21 + east * 0.00008
    ring = [
        [lon - 0.00002, lat - 0.00002],
        [lon + 0.00002, lat - 0.00002],
        [lon + 0.00002, lat + 0.00002],
        [lon - 0.00002, lat + 0.00002],
        [lon - 0.00002, lat - 0.00002],
    ]
    return {
        "source_id": f"ms-{index}",
        "footprint_source": "microsoft_building_footprints",
        "footprint_geometry": {"type": "Polygon", "coordinates": [ring]},
        "tags": {"height": str(height), "building": "yes"},
        "source_provenance": [f"ms-{index}"],
    }


def many_microsoft_footprints(count: int) -> list[dict]:
    side = int(count**0.5) + 1
    footprints = []
    for index in range(count):
        row = index // side
        col = index % side
        footprints.append(microsoft_footprint(index, row - side // 2, col - side // 2))
    return footprints


def map_diagnostics(html: str) -> dict:
    match = re.search(r"window\.openWindMapDiagnostics = (\{.*?\});", html, re.S)
    assert match, "map diagnostics script missing"
    return json.loads(match.group(1))


def test_obstruction_map_generation_limits_1000_footprints() -> None:
    result = run_obstruction_inventory(
        ObstructionInventoryRequest(
            latitude=-33.86,
            longitude=151.21,
            radius_m=500,
            building_height_m=8,
            map_max_display_obstructions=500,
        ),
        footprints=many_microsoft_footprints(1000),
    )

    html = obstruction_map_html(result)
    diagnostics = map_diagnostics(html)

    assert len(result.obstructions) == 1000
    assert diagnostics["selected_obstructions"] == 500
    assert diagnostics["plotted_polygons"] == 500
    assert diagnostics["total_geojson_payload_size"] > 0
    assert "Map display limited to 500 of 1000 obstructions" in html


def test_terrain_category_map_uses_display_limited_obstruction_layers() -> None:
    site_result = run_site_analysis(
        SiteAnalysisRequest(
            latitude=-33.86,
            longitude=151.21,
            building_height_m=8,
            radius_m=500,
            sample_interval_m=100,
        ),
        FlatDEM(),
    )
    obstruction_result = run_obstruction_inventory(
        ObstructionInventoryRequest(
            latitude=-33.86,
            longitude=151.21,
            radius_m=500,
            building_height_m=8,
            map_max_display_obstructions=500,
        ),
        footprints=many_microsoft_footprints(1000),
    )
    evidence = run_terrain_category_evidence(site_result, obstruction_result)

    html = terrain_category_map_html(site_result, obstruction_result, evidence)
    diagnostics = map_diagnostics(html)

    assert "Indicative Mz,cat ranges" in html
    assert diagnostics["selected_obstructions"] == 500
    assert diagnostics["plotted_polygons"] == 500
    assert "Map display limited to 500 of 1000 obstructions" in html


def test_combined_map_shows_clean_workflow_layers_by_default() -> None:
    site_result = run_site_analysis(
        SiteAnalysisRequest(
            latitude=-33.86,
            longitude=151.21,
            building_height_m=8,
            radius_m=500,
            sample_interval_m=100,
        ),
        FlatDEM(),
    )
    obstruction_result = run_obstruction_inventory(
        ObstructionInventoryRequest(
            latitude=-33.86,
            longitude=151.21,
            radius_m=500,
            building_height_m=8,
            map_max_display_obstructions=500,
        ),
        footprints=many_microsoft_footprints(25),
    )

    html = combined_map_html(site_result, obstruction_result)

    assert "Shielding sectors" in html
    assert "Shielding obstruction polygons" in html
    assert "Topographic feature candidates" in html
    assert "Nearby obstructions" in html
    assert "Topographic circles" not in html
    assert "Raw OSM building polygons before filtering" not in html
    assert "Manual reviewed obstruction geometry" not in html
    assert "Microsoft building footprints" not in html
    assert "OSM fallback and matched attributes" not in html
    assert "Vegetation polygons" not in html
    assert "Shielding candidates" not in html
    shielding_layer = re.search(r'"Shielding sectors" : (feature_group_[a-f0-9]+)', html)
    assert shielding_layer
    assert f"{shielding_layer.group(1)}.addTo(map_" in html


def test_invalid_geometry_is_repaired_or_reported_for_map_display() -> None:
    bowtie = {
        "source_id": "ms-bowtie",
        "footprint_source": "microsoft_building_footprints",
        "footprint_geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [151.2099, -33.8601],
                    [151.2101, -33.8599],
                    [151.2099, -33.8599],
                    [151.2101, -33.8601],
                    [151.2099, -33.8601],
                ]
            ],
        },
        "tags": {"building": "yes"},
    }
    result = run_obstruction_inventory(
        ObstructionInventoryRequest(latitude=-33.86, longitude=151.21, radius_m=500),
        footprints=[bowtie],
    )

    html = obstruction_map_html(result)
    diagnostics = map_diagnostics(html)

    assert diagnostics["invalid_geometry_count"] == 1
    assert diagnostics["skipped_geometry_count"] == 0


def test_centroid_fallback_map_generation() -> None:
    result = run_obstruction_inventory(
        ObstructionInventoryRequest(
            latitude=-33.86,
            longitude=151.21,
            radius_m=500,
            building_height_m=8,
            map_display_mode="centroids_only",
        ),
        footprints=many_microsoft_footprints(25),
    )

    html = obstruction_map_html(result)
    diagnostics = map_diagnostics(html)

    assert diagnostics["fallback_mode"] is True
    assert diagnostics["plotted_polygons"] == 0
    assert diagnostics["plotted_centroids"] == 25
    assert "Centroids-only map display mode selected" in html


def test_display_limit_does_not_reduce_shielding_calculation_dataset() -> None:
    result = run_obstruction_inventory(
        ObstructionInventoryRequest(
            latitude=-33.86,
            longitude=151.21,
            radius_m=500,
            building_height_m=8,
            map_max_display_obstructions=10,
        ),
        footprints=many_microsoft_footprints(80),
    )
    before_ids = [record.obstruction_id for record in result.obstructions]

    html = obstruction_map_html(result)
    diagnostics = map_diagnostics(html)

    assert len(result.obstructions) == 80
    assert [record.obstruction_id for record in result.obstructions] == before_ids
    assert diagnostics["selected_obstructions"] == 10
    assert sum(sector.ns for sector in result.shielding_sectors) > 10
