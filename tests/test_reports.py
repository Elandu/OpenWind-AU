"""Tests for report and export helpers."""

from __future__ import annotations

import json
import re

from openwind_au.analysis import run_site_analysis
from openwind_au.dem import DEMProvider
from openwind_au.models import ObstructionInventoryRequest, SiteAnalysisRequest
from openwind_au.obstructions import run_obstruction_inventory
from openwind_au.report_lineage import CALCULATION_BASIS_URL
from openwind_au.reports import (
    _wind_pdf_lineage_reference,
    combined_map_html,
    map_html,
    obstruction_map_html,
    profile_plot_html,
    render_html_report,
    render_pdf_report,
    result_to_json,
    terrain_category_map_html,
)
from openwind_au.terrain_category import run_terrain_category_evidence


class FlatDEM(DEMProvider):
    def elevation(self, latitude: float, longitude: float) -> float:
        return 50.0


def test_calculation_basis_lineage_uses_an_immutable_commit() -> None:
    assert re.fullmatch(
        r"https://github\.com/Elandu/OpenWind-AU/blob/[0-9a-f]{40}/docs/calculation-basis\.md",
        CALCULATION_BASIS_URL,
    )


def test_wind_pdf_lineage_is_compact_clickable_and_immutable() -> None:
    revision = CALCULATION_BASIS_URL.split("/blob/", maxsplit=1)[1].split("/", maxsplit=1)[0]
    reference = _wind_pdf_lineage_reference()

    assert f'href="{CALCULATION_BASIS_URL}"' in reference
    assert f"source snapshot {revision}" in reference
    assert CALCULATION_BASIS_URL not in reference.replace(
        f'href="{CALCULATION_BASIS_URL}"',
        "",
    )


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
    assert CALCULATION_BASIS_URL in html
    assert "plotly" in plot.lower()
    assert "Plotly.newPlot" in plot
    assert 'src="/vendor/plotly.min.js"' in plot
    assert "site" in plot
    assert "leaflet" in fmap.lower()
    assert "Analysis radius" in fmap


def test_pdf_report_renders_in_memory() -> None:
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

    pdf = render_pdf_report(result)

    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1_000


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
    assert r"Terrain profiles \u0026 topographic candidates" in html
    assert "Nearby obstructions" in html
    assert "Nearby obstructions (selected)" in html
    assert 'color: "#ea580c"' in html
    assert 'dashArray: "6 3"' in html
    assert "window.openWindNearbyObstructionFootprintLayer" in html
    assert "Topographic circles" not in html
    assert "Raw OSM building polygons before filtering" not in html
    assert "Manual reviewed obstruction geometry" not in html
    assert "Design building" in html
    assert "openWindDesignBuilding" in html
    assert "orientation_options" in html
    assert "Building footprints (source context)" not in html
    assert "OSM fallback and matched attributes" not in html
    assert "Vegetation polygons" not in html
    assert "Shielding candidates" not in html
    shielding_layer = re.search(r'"Shielding sectors" : (feature_group_[a-f0-9]+)', html)
    assert shielding_layer
    assert f"{shielding_layer.group(1)}.addTo(map_" in html
    assert "explicit_leaflet_geojson" in html
    assert "openWindAttachNearbyFootprints" in html
    assert "openWindAttachShieldingFootprints" in html
    assert "window.setTimeout(openWindAttachNearbyFootprints" in html
    assert "OpenWind-AU map dependency failed" in html
    assert "Leaflet failed to load from the local static assets" in html
    assert "/static/vendor/leaflet/leaflet.js" in html
    assert "/static/vendor/jquery/jquery-3.7.1.min.js" in html
    assert "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js" not in html
    assert "https://code.jquery.com/jquery-3.7.1.min.js" not in html


def test_combined_map_limits_shielding_obstruction_polygon_overlay() -> None:
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
            map_max_display_obstructions=3,
        ),
        footprints=many_microsoft_footprints(25),
    )

    html = combined_map_html(site_result, obstruction_result)
    diagnostics = map_diagnostics(html)
    shielding_polygon_layer = re.search(
        r'"Shielding obstruction polygons" : (feature_group_[a-f0-9]+)',
        html,
    )

    assert shielding_polygon_layer
    assert f"{shielding_polygon_layer.group(1)}.addTo(map_" in html
    assert "window.openWindShieldingFootprintLayer" in html
    assert diagnostics["plotted_polygons"] == 3
    assert diagnostics["plotted_microsoft_polygons"] == 0
    assert diagnostics["plotted_shielding_polygons"] == 3
    assert diagnostics["total_geojson_payload_size"] > 0
    assert "Shielding polygon display limited to 3" in html
    assert "Building footprint display limited to 3" not in html
    assert "window.openWindMicrosoftFootprintLayer" not in html
    assert "window.openWindShieldingFootprintLayer" in html


def test_combined_map_shows_below_height_shielding_candidate_polygons() -> None:
    site_result = run_site_analysis(
        SiteAnalysisRequest(
            latitude=-33.86,
            longitude=151.21,
            building_height_m=20,
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
            building_height_m=20,
            map_max_display_obstructions=10,
        ),
        footprints=[
            microsoft_footprint(1, 0, 0, height=8),
            microsoft_footprint(2, 1, 0, height=9),
        ],
    )

    html = combined_map_html(site_result, obstruction_result)
    diagnostics = map_diagnostics(html)

    assert all(sector.ns == 0 for sector in obstruction_result.shielding_sectors)
    assert diagnostics["plotted_shielding_polygons"] == 2
    assert "height_below_subject" in html
    assert "window.openWindShieldingFootprintLayer" in html


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


def test_obstruction_map_escapes_hostile_inline_json_and_tooltip_content() -> None:
    payload = "</script><img src=x onerror=alert(1)>&\u2028"
    footprint = microsoft_footprint(1, 0, 0)
    footprint["source_id"] = payload
    footprint["source_provenance"] = [payload]
    result = run_obstruction_inventory(
        ObstructionInventoryRequest(
            latitude=-33.86,
            longitude=151.21,
            radius_m=500,
            building_height_m=8,
            map_display_mode="centroids_only",
        ),
        footprints=[footprint],
    )

    html = obstruction_map_html(result)
    diagnostics = map_diagnostics(html)

    assert diagnostics["selected_obstructions"] == 1
    assert diagnostics["plotted_centroids"] == 1
    assert "</script><img" not in html
    assert "<img" not in html
    assert payload not in html
    # Folium's JSON escaping alone would produce ``\u003cimg`` and restore an
    # active tag in GeoJsonTooltip. HTML entities remain inert after parsing.
    assert r"\u0026lt;/script\u0026gt;\u0026lt;img" in html


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
