"""HTML, PDF, map, and plot generation for OpenWind-AU."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import folium
import plotly.graph_objects as go
from jinja2 import Template
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from shapely.errors import ShapelyError
from shapely.geometry import GeometryCollection, mapping, shape

from openwind_au.geo import destination_point
from openwind_au.models import (
    ObstructionInventoryResult,
    ObstructionRecord,
    SiteAnalysisResult,
    SiteLocation,
    TerrainCategoryDirectionEvidence,
    TerrainCategoryEvidenceResult,
)
from openwind_au.shielding import shielding_sector_polygon

DEFAULT_MAP_DISPLAY_LIMIT = 500
MAX_POLYGON_GEOJSON_PAYLOAD_BYTES = 2_500_000


@dataclass
class MapRenderDiagnostics:
    """Display-only diagnostics for obstruction map rendering."""

    display_mode: str = "nearest_500"
    max_displayed_obstructions: int = DEFAULT_MAP_DISPLAY_LIMIT
    total_obstructions: int = 0
    selected_obstructions: int = 0
    plotted_polygons: int = 0
    plotted_centroids: int = 0
    total_geojson_payload_size: int = 0
    largest_polygon_vertex_count: int = 0
    invalid_geometry_count: int = 0
    skipped_geometry_count: int = 0
    skipped_geometry_reasons: dict[str, int] = field(default_factory=dict)
    map_html_size: int = 0
    fallback_mode: bool = False
    warnings: list[str] = field(default_factory=list)
    console_safe_errors: list[str] = field(default_factory=list)

    def skip(self, reason: str) -> None:
        self.skipped_geometry_count += 1
        self.skipped_geometry_reasons[reason] = self.skipped_geometry_reasons.get(reason, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "display_mode": self.display_mode,
            "max_displayed_obstructions": self.max_displayed_obstructions,
            "total_obstructions": self.total_obstructions,
            "selected_obstructions": self.selected_obstructions,
            "plotted_polygons": self.plotted_polygons,
            "plotted_centroids": self.plotted_centroids,
            "total_geojson_payload_size": self.total_geojson_payload_size,
            "largest_polygon_vertex_count": self.largest_polygon_vertex_count,
            "invalid_geometry_count": self.invalid_geometry_count,
            "skipped_geometry_count": self.skipped_geometry_count,
            "skipped_geometry_reasons": self.skipped_geometry_reasons,
            "map_html_size": self.map_html_size,
            "fallback_mode": self.fallback_mode,
            "warnings": self.warnings,
            "console_safe_errors": self.console_safe_errors,
        }


REPORT_TEMPLATE = Template(
    """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>OpenWind-AU Preliminary Terrain Report</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 32px; color: #202124; }
    h1, h2 { color: #17324d; }
    table { border-collapse: collapse; width: 100%; margin: 16px 0; }
    th, td { border: 1px solid #d0d7de; padding: 8px; text-align: left; }
    th { background: #f6f8fa; }
    .disclaimer { border-left: 4px solid #b42318; padding: 12px; background: #fff4f2; }
    .note { color: #57606a; font-size: 0.95em; }
  </style>
</head>
<body>
  <h1>OpenWind-AU Preliminary Terrain Report</h1>
  <p class="disclaimer">{{ result.disclaimer }}</p>

  <h2>Site</h2>
  <table>
    <tr><th>Latitude</th><td>{{ "%.6f"|format(result.site.latitude) }}</td></tr>
    <tr><th>Longitude</th><td>{{ "%.6f"|format(result.site.longitude) }}</td></tr>
    <tr><th>Ground elevation</th><td>{{ "%.2f"|format(result.site.ground_elevation_m) }} m</td></tr>
    <tr><th>Building height</th><td>{{ "%.2f"|format(result.input.building_height_m) }} m</td></tr>
    <tr><th>Location source</th><td>{{ result.site.source }}</td></tr>
  </table>

  <h2>Preliminary Topographic Screening</h2>
  <table>
    <tr>
      <th>Direction</th><th>Azimuth</th><th>Feature</th><th>Site RL</th><th>Crest RL</th>
      <th>Base RL</th><th>H</th><th>Lu</th><th>x</th><th>Average upwind slope</th>
      <th>Confidence</th><th>Notes</th>
    </tr>
    {% for feature in result.features %}
    <tr>
      <td>{{ feature.direction }}</td>
      <td>{{ "%.0f"|format(feature.azimuth_deg) }} deg</td>
      <td>{{ feature.feature_type }}</td>
      <td>{{ "%.2f"|format(feature.site_rl_m) }} m</td>
      <td>{{ "%.2f"|format(feature.crest_rl_m) }} m</td>
      <td>{{ "%.2f"|format(feature.base_rl_m) }} m</td>
      <td>{{ "%.2f"|format(feature.h_m) }} m</td>
      <td>{{ "%.1f"|format(feature.lu_m) }} m</td>
      <td>{{ "%.1f"|format(feature.x_m) }} m</td>
      <td>{{ "%.3f"|format(feature.average_upwind_slope) }}</td>
      <td>{{ feature.confidence }}</td>
      <td>{{ feature.notes|join(" ") }}</td>
    </tr>
    {% endfor %}
  </table>

  <h2>Terrain Profile Summary</h2>
  <table>
    <tr>
      <th>Direction</th><th>Azimuth</th><th>Endpoint</th><th>Min RL</th>
      <th>Max RL</th><th>Average slope</th>
    </tr>
    {% for profile in result.profiles %}
    <tr>
      <td>{{ profile.direction }}</td>
      <td>{{ "%.0f"|format(profile.azimuth_deg) }} deg</td>
      <td>
        {{ "%.6f"|format(profile.endpoint_latitude) }},
        {{ "%.6f"|format(profile.endpoint_longitude) }}
      </td>
      <td>{{ "%.2f"|format(profile.min_elevation_m) }} m</td>
      <td>{{ "%.2f"|format(profile.max_elevation_m) }} m</td>
      <td>{{ "%.4f"|format(profile.average_slope) }}</td>
    </tr>
    {% endfor %}
  </table>

  <h2>Assumptions</h2>
  <ul>{% for item in result.assumptions %}<li>{{ item }}</li>{% endfor %}</ul>

  <h2>Limitations</h2>
  <ul>{% for item in result.limitations %}<li>{{ item }}</li>{% endfor %}</ul>

  <p class="note">
    Generated by OpenWind-AU. This report is preliminary and requires engineering review.
  </p>
</body>
</html>
"""
)


def result_to_json(result: SiteAnalysisResult) -> dict:
    """Convert an analysis result into JSON-serialisable data."""

    return json.loads(result.model_dump_json())


def render_html_report(result: SiteAnalysisResult) -> str:
    """Render an HTML report string."""

    return REPORT_TEMPLATE.render(result=result)


def write_html_report(result: SiteAnalysisResult, path: Path) -> Path:
    """Write an HTML report to *path*."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html_report(result), encoding="utf-8")
    return path


def write_pdf_report(result: SiteAnalysisResult, path: Path) -> Path:
    """Write a simple PDF report to *path* using ReportLab."""

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("OpenWind-AU Preliminary Terrain Report", styles["Title"]),
        Paragraph(result.disclaimer, styles["BodyText"]),
        Spacer(1, 12),
        Paragraph("Site", styles["Heading2"]),
        Table(
            [
                ["Latitude", f"{result.site.latitude:.6f}"],
                ["Longitude", f"{result.site.longitude:.6f}"],
                ["Ground elevation", f"{result.site.ground_elevation_m:.2f} m"],
                ["Building height", f"{result.input.building_height_m:.2f} m"],
                ["Location source", result.site.source],
            ],
            hAlign="LEFT",
        ),
        Spacer(1, 12),
        Paragraph("Preliminary Topographic Screening", styles["Heading2"]),
    ]
    feature_rows = [
        [
            "Dir.",
            "Az.",
            "Feature",
            "Site RL",
            "Crest RL",
            "Base RL",
            "H",
            "Lu",
            "x",
            "Slope",
            "Conf.",
        ]
    ]
    for feature in result.features:
        feature_rows.append(
            [
                feature.direction,
                f"{feature.azimuth_deg:.0f}",
                feature.feature_type,
                f"{feature.site_rl_m:.1f}",
                f"{feature.crest_rl_m:.1f}",
                f"{feature.base_rl_m:.1f}",
                f"{feature.h_m:.1f}",
                f"{feature.lu_m:.0f}",
                f"{feature.x_m:.0f}",
                f"{feature.average_upwind_slope:.3f}",
                feature.confidence,
            ]
        )
    table = Table(feature_rows, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "Candidate topographic features require review by a competent engineer.",
            styles["BodyText"],
        )
    )
    profile_rows = [["Dir.", "Az.", "Min RL", "Max RL", "Avg slope"]]
    for profile in result.profiles:
        profile_rows.append(
            [
                profile.direction,
                f"{profile.azimuth_deg:.0f}",
                f"{profile.min_elevation_m:.1f}",
                f"{profile.max_elevation_m:.1f}",
                f"{profile.average_slope:.4f}",
            ]
        )
    profile_table = Table(profile_rows, repeatRows=1)
    profile_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend(
        [
            Spacer(1, 12),
            Paragraph("Terrain Profile Summary", styles["Heading2"]),
            profile_table,
            Spacer(1, 12),
            Paragraph("Assumptions", styles["Heading2"]),
            *[Paragraph(f"- {item}", styles["BodyText"]) for item in result.assumptions],
            Spacer(1, 12),
            Paragraph("Limitations", styles["Heading2"]),
            *[Paragraph(f"- {item}", styles["BodyText"]) for item in result.limitations],
        ]
    )
    doc.build(story)
    return path


def profile_plot_html(result: SiteAnalysisResult) -> str:
    """Return a Plotly HTML fragment for terrain profile plots."""

    fig = go.Figure()
    features_by_direction = {feature.direction: feature for feature in result.features}
    for profile in result.profiles:
        feature = features_by_direction.get(profile.direction)
        fig.add_trace(
            go.Scatter(
                x=[point.distance_m for point in profile.points],
                y=[point.elevation_m for point in profile.points],
                mode="lines",
                name=f"{profile.direction} ({profile.azimuth_deg:.0f} deg)",
                hovertemplate=(
                    f"{profile.direction}<br>"
                    "Distance: %{x:.0f} m<br>"
                    "RL: %{y:.2f} m<extra></extra>"
                ),
            )
        )
        if not feature:
            continue

        fig.add_trace(
            go.Scatter(
                x=[0],
                y=[feature.site_rl_m],
                mode="markers",
                name=f"{profile.direction} site",
                marker={"symbol": "circle", "size": 8, "color": "#0f766e"},
                hovertemplate=(
                    f"{profile.direction} site<br>Distance: 0 m<br>RL: %{{y:.2f}} m<extra></extra>"
                ),
                showlegend=False,
            )
        )
        if feature.feature_type == "no significant feature":
            continue

        fig.add_trace(
            go.Scatter(
                x=[feature.base_x_m],
                y=[feature.base_rl_m],
                mode="markers",
                name=f"{profile.direction} candidate base",
                marker={"symbol": "square", "size": 8, "color": "#f59e0b"},
                hovertemplate=(
                    f"{profile.direction} base<br>"
                    "Distance: %{x:.0f} m<br>"
                    "RL: %{y:.2f} m<extra></extra>"
                ),
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[feature.crest_x_m],
                y=[feature.crest_rl_m],
                mode="markers",
                name=f"{profile.direction} candidate crest",
                marker={"symbol": "diamond", "size": 9, "color": "#b42318"},
                hovertemplate=(
                    f"{profile.direction} crest<br>"
                    "Distance: %{x:.0f} m<br>"
                    "RL: %{y:.2f} m<extra></extra>"
                ),
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[feature.crest_x_m, feature.crest_x_m],
                y=[feature.base_rl_m, feature.crest_rl_m],
                mode="lines",
                name=f"{profile.direction} H",
                line={"color": "#b42318", "width": 2, "dash": "dot"},
                hovertemplate=f"H: {feature.h_m:.2f} m<extra></extra>",
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[feature.base_x_m, feature.crest_x_m],
                y=[feature.base_rl_m, feature.base_rl_m],
                mode="lines",
                name=f"{profile.direction} Lu",
                line={"color": "#f59e0b", "width": 2, "dash": "dash"},
                hovertemplate=f"Lu: {feature.lu_m:.1f} m<extra></extra>",
                showlegend=False,
            )
        )
    fig.update_layout(
        title="Radial terrain profiles with preliminary topographic screening overlays",
        xaxis_title="Distance from site (m)",
        yaxis_title="Elevation RL (m)",
        template="plotly_white",
    )
    return fig.to_html(full_html=False, include_plotlyjs="cdn")


def map_html(result: SiteAnalysisResult) -> str:
    """Return a Folium map HTML document for the site and detected features."""

    fmap = folium.Map(
        location=[result.site.latitude, result.site.longitude],
        zoom_start=13,
        control_scale=True,
    )
    folium.Marker(
        [result.site.latitude, result.site.longitude],
        tooltip="Site",
        popup=f"Ground RL {result.site.ground_elevation_m:.1f} m",
    ).add_to(fmap)
    folium.Circle(
        location=[result.site.latitude, result.site.longitude],
        radius=result.input.radius_m,
        color="#0f766e",
        weight=2,
        fill=False,
        tooltip=f"Analysis radius: {result.input.radius_m} m",
    ).add_to(fmap)
    for profile in result.profiles:
        coordinates = [(point.latitude, point.longitude) for point in profile.points]
        folium.PolyLine(
            locations=coordinates,
            color="#17324d",
            weight=2,
            opacity=0.75,
            tooltip=f"{profile.direction} profile ({profile.azimuth_deg:.0f} deg)",
        ).add_to(fmap)
        folium.CircleMarker(
            location=[profile.endpoint_latitude, profile.endpoint_longitude],
            radius=4,
            color="#0f766e",
            fill=True,
            fill_opacity=0.85,
            tooltip=f"{profile.direction} endpoint",
            popup=(
                f"{profile.direction} endpoint<br>"
                f"Azimuth {profile.azimuth_deg:.0f} deg<br>"
                f"Radius {profile.radius_m} m"
            ),
        ).add_to(fmap)
    for feature in result.features:
        if feature.feature_type == "no significant feature":
            continue
        feature_lat, feature_lon = destination_point(
            result.site.latitude,
            result.site.longitude,
            feature.azimuth_deg,
            feature.x_m,
        )
        folium.CircleMarker(
            location=[feature_lat, feature_lon],
            radius=5,
            color="#b42318",
            fill=True,
            tooltip=f"{feature.feature_type} {feature.azimuth_deg:.0f} deg",
            popup=(
                f"{feature.feature_type}: H={feature.h_m:.1f} m, "
                f"Lu={feature.lu_m:.0f} m, x={feature.x_m:.0f} m"
            ),
        ).add_to(fmap)
    return fmap.get_root().render()


def obstruction_map_html(result: ObstructionInventoryResult) -> str:
    """Return a Folium map HTML document for obstruction footprint review."""

    fmap = folium.Map(
        location=[result.site.latitude, result.site.longitude],
        zoom_start=16,
        control_scale=True,
    )
    folium.Marker(
        [result.site.latitude, result.site.longitude],
        tooltip="Subject site",
        popup="Subject site",
    ).add_to(fmap)
    folium.Circle(
        location=[result.site.latitude, result.site.longitude],
        radius=result.input.radius_m,
        color="#17324d",
        weight=2,
        fill=False,
        tooltip=f"Obstruction inventory radius: {result.input.radius_m} m",
    ).add_to(fmap)
    diagnostics = _add_obstruction_review_layers(fmap, result)
    folium.LayerControl(collapsed=False, position="topright").add_to(fmap)
    return _render_map_with_diagnostics(fmap, diagnostics)


def combined_map_html(
    site_result: SiteAnalysisResult,
    obstruction_result: ObstructionInventoryResult,
) -> str:
    """Return a Folium map with toggleable layers for site, profiles, features, and obstructions.

    The returned document embeds a Folium/Leaflet map with a non-collapsed layer control so
    reviewers can show or hide the four layer groups: site & analysis radius, terrain profiles,
    topographic feature candidates, and obstruction footprints. The terrain analysis radius and
    the obstruction inventory radius are both drawn so the difference in coverage is visible.
    """

    fmap = folium.Map(
        location=[site_result.site.latitude, site_result.site.longitude],
        zoom_start=14,
        control_scale=True,
    )

    site_layer = folium.FeatureGroup(name="Site & analysis radius", show=True)
    profile_layer = folium.FeatureGroup(name="Terrain profiles", show=True)
    feature_layer = folium.FeatureGroup(name="Topographic feature candidates", show=True)
    shielding_layer = folium.FeatureGroup(name="Shielding sectors", show=False)

    folium.Marker(
        [site_result.site.latitude, site_result.site.longitude],
        tooltip="Site",
        popup=f"Ground RL {site_result.site.ground_elevation_m:.1f} m",
    ).add_to(site_layer)
    folium.Circle(
        location=[site_result.site.latitude, site_result.site.longitude],
        radius=site_result.input.radius_m,
        color="#0f766e",
        weight=2,
        fill=False,
        tooltip=f"Terrain analysis radius: {site_result.input.radius_m} m",
    ).add_to(site_layer)
    if obstruction_result.input.radius_m != site_result.input.radius_m:
        folium.Circle(
            location=[site_result.site.latitude, site_result.site.longitude],
            radius=obstruction_result.input.radius_m,
            color="#17324d",
            weight=2,
            dash_array="6 4",
            fill=False,
            tooltip=f"Obstruction inventory radius: {obstruction_result.input.radius_m} m",
        ).add_to(site_layer)

    for profile in site_result.profiles:
        coordinates = [(point.latitude, point.longitude) for point in profile.points]
        folium.PolyLine(
            locations=coordinates,
            color="#17324d",
            weight=2,
            opacity=0.75,
            tooltip=f"{profile.direction} profile ({profile.azimuth_deg:.0f} deg)",
        ).add_to(profile_layer)
        folium.CircleMarker(
            location=[profile.endpoint_latitude, profile.endpoint_longitude],
            radius=4,
            color="#0f766e",
            fill=True,
            fill_opacity=0.85,
            tooltip=f"{profile.direction} endpoint",
            popup=(
                f"{profile.direction} endpoint<br>"
                f"Azimuth {profile.azimuth_deg:.0f} deg<br>"
                f"Radius {profile.radius_m} m"
            ),
        ).add_to(profile_layer)

    for feature in site_result.features:
        if feature.feature_type == "no significant feature":
            continue
        feature_lat, feature_lon = destination_point(
            site_result.site.latitude,
            site_result.site.longitude,
            feature.azimuth_deg,
            feature.x_m,
        )
        folium.CircleMarker(
            location=[feature_lat, feature_lon],
            radius=5,
            color="#b42318",
            fill=True,
            tooltip=f"{feature.feature_type} {feature.azimuth_deg:.0f} deg",
            popup=(
                f"{feature.feature_type}: H={feature.h_m:.1f} m, "
                f"Lu={feature.lu_m:.0f} m, x={feature.x_m:.0f} m"
            ),
        ).add_to(feature_layer)

    diagnostics = _add_obstruction_review_layers(fmap, obstruction_result)

    for sector in obstruction_result.shielding_sectors:
        color = _shielding_sector_color(sector.indicative_ms)
        folium.GeoJson(
            shielding_sector_polygon(obstruction_result.site, sector),
            style_function=lambda _feature, color=color: {
                "color": color,
                "weight": 1,
                "fillColor": color,
                "fillOpacity": 0.08,
            },
            tooltip=(
                f"{sector.direction} shielding sector: ns={sector.ns}, "
                f"indicative Ms={sector.indicative_ms:.3f}, "
                f"confidence={sector.overall_confidence}"
            ),
        ).add_to(shielding_layer)

    site_layer.add_to(fmap)
    profile_layer.add_to(fmap)
    feature_layer.add_to(fmap)
    shielding_layer.add_to(fmap)
    folium.LayerControl(collapsed=False, position="topright").add_to(fmap)

    return _render_map_with_diagnostics(fmap, diagnostics)


def render_obstruction_report_html(result: ObstructionInventoryResult) -> str:
    """Render an HTML obstruction inventory report."""

    return OBSTRUCTION_REPORT_TEMPLATE.render(result=result)


def render_terrain_category_report_html(result: TerrainCategoryEvidenceResult) -> str:
    """Render an HTML terrain category evidence report."""

    return TERRAIN_CATEGORY_REPORT_TEMPLATE.render(result=result)


def terrain_category_map_html(
    site_result: SiteAnalysisResult,
    obstruction_result: ObstructionInventoryResult,
    evidence_result: TerrainCategoryEvidenceResult,
) -> str:
    """Return a Folium map for terrain category evidence review."""

    fmap = folium.Map(
        location=[site_result.site.latitude, site_result.site.longitude],
        zoom_start=14,
        control_scale=True,
    )
    sector_layer = folium.FeatureGroup(
        name="Directional terrain category evidence and controlling fetch areas",
        show=True,
    )
    mzcat_layer = folium.FeatureGroup(name="Indicative Mz,cat ranges", show=True)
    density_layer = folium.FeatureGroup(name="Dominant obstruction zones", show=True)
    mzcat_by_direction = {
        assessment.direction: assessment for assessment in evidence_result.mzcat_assessment
    }

    folium.Marker(
        [site_result.site.latitude, site_result.site.longitude],
        tooltip="Subject site",
        popup="Terrain category evidence origin",
    ).add_to(sector_layer)

    for direction in evidence_result.directions:
        color = _terrain_category_color(direction.suggested_category_range)
        folium.GeoJson(
            terrain_category_sector_polygon(evidence_result.site, direction),
            style_function=lambda _feature, color=color: {
                "color": color,
                "weight": 1,
                "fillColor": color,
                "fillOpacity": 0.10,
            },
            tooltip=(
                f"{direction.direction}: open={direction.open_terrain_percentage:.1f}%, "
                f"built-up={direction.built_up_area_percentage:.1f}%, "
                f"vegetation={direction.vegetation_area_percentage:.1f}%, "
                f"density={direction.obstruction_density_per_km2:.1f}/km2, "
                f"range={direction.suggested_category_range}"
            ),
        ).add_to(sector_layer)
        mzcat = mzcat_by_direction.get(direction.direction)
        if mzcat is not None:
            folium.GeoJson(
                terrain_category_sector_polygon(evidence_result.site, direction),
                style_function=lambda _feature, color=color: {
                    "color": color,
                    "weight": 2,
                    "dashArray": "5 4",
                    "fillColor": color,
                    "fillOpacity": 0.05,
                },
                tooltip=(
                    f"{direction.direction}: indicative Mz,cat "
                    f"{mzcat.lower_indicative_mzcat:.3f}-"
                    f"{mzcat.upper_indicative_mzcat:.3f}, "
                    f"TC range={mzcat.controlling_category_range}, "
                    f"confidence={mzcat.confidence}"
                ),
            ).add_to(mzcat_layer)
        folium.CircleMarker(
            location=destination_point(
                evidence_result.site.latitude,
                evidence_result.site.longitude,
                direction.azimuth_deg,
                max(direction.assessment_radius_m * 0.55, 20),
            ),
            radius=max(4, min(18, direction.obstruction_density_per_km2 / 80)),
            color=color,
            fill=True,
            fill_opacity=0.35,
            tooltip=(
                f"{direction.direction} obstruction density: "
                f"{direction.obstruction_density_per_km2:.1f}/km2"
            ),
        ).add_to(density_layer)

    sector_layer.add_to(fmap)
    mzcat_layer.add_to(fmap)
    density_layer.add_to(fmap)
    diagnostics = _add_obstruction_review_layers(fmap, obstruction_result)
    folium.LayerControl(collapsed=False, position="topright").add_to(fmap)
    return _render_map_with_diagnostics(fmap, diagnostics)


def terrain_category_sector_polygon(
    site: SiteLocation,
    evidence: TerrainCategoryDirectionEvidence,
    steps: int = 8,
) -> dict:
    """Return a GeoJSON polygon for a terrain category evidence sector."""

    start = evidence.sector_start_deg
    end = evidence.sector_end_deg
    sweep = (end - start) % 360
    if sweep == 0:
        sweep = 45.0
    bearings = [start + (sweep * index / steps) for index in range(steps + 1)]
    arc = [
        list(
            reversed(
                destination_point(
                    site.latitude,
                    site.longitude,
                    bearing,
                    evidence.assessment_radius_m,
                )
            )
        )
        for bearing in bearings
    ]
    site_point = [site.longitude, site.latitude]
    return {"type": "Polygon", "coordinates": [[site_point, *arc, site_point]]}


def _add_obstruction_review_layers(
    fmap: folium.Map,
    result: ObstructionInventoryResult,
) -> MapRenderDiagnostics:
    """Add source-quality obstruction review layers to a Folium map."""

    diagnostics = MapRenderDiagnostics(
        display_mode=getattr(result.input, "map_display_mode", "nearest_500"),
        max_displayed_obstructions=getattr(
            result.input,
            "map_max_display_obstructions",
            DEFAULT_MAP_DISPLAY_LIMIT,
        ),
        total_obstructions=len(result.obstructions),
    )
    raw_osm_layer = folium.FeatureGroup(
        name="Raw OSM building polygons before filtering",
        show=False,
    )
    excluded_layer = folium.FeatureGroup(name="Excluded and skipped objects", show=False)
    centroid_layer = folium.FeatureGroup(name="Obstruction centroids", show=True)
    polygon_layers = {
        "manual_reviewed": folium.FeatureGroup(
            name="Manual reviewed obstruction geometry",
            show=True,
        ),
        "microsoft_building_footprints": folium.FeatureGroup(
            name="Microsoft building footprints",
            show=True,
        ),
        "OSM": folium.FeatureGroup(name="OSM fallback and matched attributes", show=True),
        "vegetation": folium.FeatureGroup(name="Vegetation polygons", show=True),
        "shielding": folium.FeatureGroup(name="Shielding candidates", show=True),
        "missing_height": folium.FeatureGroup(name="Missing height objects", show=False),
    }
    selected = select_obstructions_for_map(result, diagnostics)
    diagnostics.selected_obstructions = len(selected)
    for warning in map_display_warnings(result, diagnostics):
        diagnostics.warnings.append(warning)
    feature_groups = obstruction_display_feature_groups(result, selected, diagnostics)
    if diagnostics.total_geojson_payload_size > MAX_POLYGON_GEOJSON_PAYLOAD_BYTES:
        diagnostics.fallback_mode = True
        diagnostics.console_safe_errors.append(
            "Polygon payload exceeded map display budget; rendered centroid fallback."
        )
    if diagnostics.display_mode == "centroids_only":
        diagnostics.fallback_mode = True
        diagnostics.console_safe_errors.append("Centroids-only map display mode selected.")

    if not diagnostics.fallback_mode:
        for key, features in feature_groups.items():
            if not features:
                continue
            feature_collection = {"type": "FeatureCollection", "features": features}
            folium.GeoJson(
                feature_collection,
                style_function=lambda feature: obstruction_feature_style(
                    str(feature.get("properties", {}).get("map_layer", "OSM"))
                ),
                tooltip=folium.GeoJsonTooltip(
                    fields=["id", "source", "height", "confidence"],
                    aliases=["ID", "Source", "Height", "Confidence"],
                    sticky=False,
                ),
            ).add_to(polygon_layers.get(key, polygon_layers["OSM"]))
        diagnostics.plotted_polygons = sum(len(features) for features in feature_groups.values())

    _add_obstruction_centroid_collection(centroid_layer, selected, diagnostics)

    for excluded in result.data_quality.excluded_objects:
        if not excluded.footprint_geometry:
            continue
        display_geometry = display_geometry_for_map(
            excluded.footprint_geometry,
            result.site,
            result.input.radius_m,
            diagnostics,
        )
        if display_geometry:
            folium.GeoJson(
                display_geometry,
                style_function=lambda _feature: {
                    "color": "#7f1d1d",
                    "weight": 2,
                    "dashArray": "6 4",
                    "fillColor": "#fecaca",
                    "fillOpacity": 0.18,
                },
                tooltip=(
                    f"{excluded.object_id}: excluded, source={excluded.source}, "
                    f"reason={excluded.reason}"
                ),
            ).add_to(excluded_layer)

    raw_osm_layer.add_to(fmap)
    for layer in polygon_layers.values():
        layer.add_to(fmap)
    centroid_layer.add_to(fmap)
    excluded_layer.add_to(fmap)
    _add_map_diagnostics_banner(fmap, diagnostics)
    return diagnostics


def select_obstructions_for_map(
    result: ObstructionInventoryResult,
    diagnostics: MapRenderDiagnostics,
) -> list[ObstructionRecord]:
    """Return obstructions selected for display without changing calculation data."""

    records = list(result.obstructions)
    mode = diagnostics.display_mode
    max_display = diagnostics.max_displayed_obstructions
    if mode == "shielding_candidates":
        records = [
            record
            for record in records
            if _is_shielding_candidate(record, result.input.building_height_m)
        ]
    if mode == "centroids_only":
        return sorted(records, key=lambda record: record.distance_m)[: max(max_display, 1)]
    if mode == "all_footprints":
        return sorted(
            records,
            key=lambda record: map_relevance_sort_key(record, result.input.building_height_m),
        )
    return sorted(
        records,
        key=lambda record: map_relevance_sort_key(record, result.input.building_height_m),
    )[:max_display]


def map_relevance_sort_key(
    record: ObstructionRecord,
    subject_height_m: float | None,
) -> tuple[bool, float, float, bool]:
    """Sort higher relevance records first for map display limits."""

    height = record.selected_height_m or record.height_m or 0.0
    missing_or_review = _is_missing_source_height(record) or record.review_required
    return (
        not _is_shielding_candidate(record, subject_height_m),
        record.distance_m,
        -height,
        not missing_or_review,
    )


def map_display_warnings(
    result: ObstructionInventoryResult,
    diagnostics: MapRenderDiagnostics,
) -> list[str]:
    """Return human-facing warnings for the map display."""

    warnings: list[str] = []
    if diagnostics.selected_obstructions < diagnostics.total_obstructions:
        warnings.append(
            "Map display limited to "
            f"{diagnostics.selected_obstructions} of {diagnostics.total_obstructions} "
            "obstructions. Calculations used full dataset."
        )
    if diagnostics.display_mode == "centroids_only":
        warnings.append(
            "Map is rendering centroids only; calculations used full footprint geometry."
        )
    return warnings


def obstruction_display_feature_groups(
    result: ObstructionInventoryResult,
    selected: list[ObstructionRecord],
    diagnostics: MapRenderDiagnostics,
) -> dict[str, list[dict[str, Any]]]:
    """Build grouped display-only GeoJSON features for obstruction polygons."""

    groups: dict[str, list[dict[str, Any]]] = {
        "manual_reviewed": [],
        "microsoft_building_footprints": [],
        "OSM": [],
        "vegetation": [],
        "shielding": [],
        "missing_height": [],
    }
    for obstruction in selected:
        display_geometry = display_geometry_for_map(
            obstruction.footprint_geometry,
            result.site,
            result.input.radius_m,
            diagnostics,
        )
        if display_geometry is None:
            continue
        diagnostics.largest_polygon_vertex_count = max(
            diagnostics.largest_polygon_vertex_count,
            geometry_vertex_count(display_geometry),
        )
        if _is_shielding_candidate(obstruction, result.input.building_height_m):
            layer_key = "shielding"
        elif _is_missing_source_height(obstruction):
            layer_key = "missing_height"
        else:
            layer_key = obstruction_feature_group_key(obstruction)
        groups[layer_key].append(
            obstruction_display_feature(obstruction, display_geometry, layer_key)
        )
    diagnostics.total_geojson_payload_size = sum(
        len(json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")))
        for features in groups.values()
    )
    return groups


def obstruction_display_feature(
    obstruction: ObstructionRecord,
    geometry: dict[str, Any],
    layer_key: str | None = None,
) -> dict[str, Any]:
    """Return a display-only GeoJSON feature for an obstruction."""

    height = obstruction.selected_height_m or obstruction.height_m
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "id": obstruction.obstruction_id,
            "source": obstruction.footprint_source,
            "height": f"{height:.1f} m" if height is not None else "missing",
            "confidence": obstruction.confidence,
            "classification": obstruction.classification,
            "map_layer": layer_key or obstruction_feature_group_key(obstruction),
        },
    }


def obstruction_feature_group_key(obstruction: ObstructionRecord) -> str:
    """Return the display group key for an obstruction."""

    if obstruction.classification == "vegetation":
        return "vegetation"
    if obstruction.footprint_source == "manual_reviewed":
        return "manual_reviewed"
    if obstruction.footprint_source == "microsoft_building_footprints":
        return "microsoft_building_footprints"
    return "OSM"


def display_geometry_for_map(
    geometry: dict[str, Any],
    site: SiteLocation,
    radius_m: int,
    diagnostics: MapRenderDiagnostics,
) -> dict[str, Any] | None:
    """Return repaired/simplified display geometry, leaving source geometry untouched."""

    if not geometry:
        diagnostics.skip("empty_geometry")
        return None
    try:
        polygon = shape(geometry)
    except (ShapelyError, AttributeError, TypeError, ValueError) as exc:
        diagnostics.console_safe_errors.append(f"Geometry parse failed: {safe_error_message(exc)}")
        diagnostics.skip("invalid_geometry_parse")
        return None
    if polygon.is_empty:
        diagnostics.skip("empty_geometry")
        return None
    if not polygon.is_valid:
        diagnostics.invalid_geometry_count += 1
        try:
            polygon = polygon.buffer(0)
        except (ShapelyError, ValueError) as exc:
            diagnostics.console_safe_errors.append(
                f"Geometry repair failed: {safe_error_message(exc)}"
            )
            diagnostics.skip("invalid_geometry_unrepairable")
            return None
    polygon = polygon_collection_to_polygons(polygon)
    if polygon is None or polygon.is_empty:
        diagnostics.skip("no_polygon_after_repair")
        return None
    tolerance = map_simplification_tolerance_degrees(site, radius_m)
    if tolerance > 0:
        polygon = polygon.simplify(tolerance, preserve_topology=True)
    if polygon.is_empty:
        diagnostics.skip("empty_after_simplification")
        return None
    return mapping(polygon)


def polygon_collection_to_polygons(geometry):
    """Return polygonal geometry from a repaired Shapely geometry."""

    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    if isinstance(geometry, GeometryCollection):
        polygons = [
            item for item in geometry.geoms if item.geom_type in {"Polygon", "MultiPolygon"}
        ]
        if not polygons:
            return None
        return max(polygons, key=lambda item: item.area)
    return None


def map_simplification_tolerance_degrees(site: SiteLocation, radius_m: int) -> float:
    """Return a display-only simplification tolerance in degrees."""

    tolerance_m = min(max(radius_m / 1000, 0.5), 2.0)
    latitude_scale = max(abs(math.cos(math.radians(site.latitude))), 0.2)
    return tolerance_m / (111_320 * latitude_scale)


def geometry_vertex_count(geometry: dict[str, Any]) -> int:
    """Return the number of coordinate vertices in a GeoJSON geometry."""

    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    if geometry_type == "Polygon":
        return sum(len(ring) for ring in coordinates)
    if geometry_type == "MultiPolygon":
        return sum(len(ring) for polygon in coordinates for ring in polygon)
    return 0


def obstruction_feature_style(layer: str) -> dict[str, Any]:
    """Return style for a grouped obstruction display feature."""

    styles = {
        "manual_reviewed": {"color": "#0f766e", "fillColor": "#99f6e4", "fillOpacity": 0.30},
        "microsoft_building_footprints": {
            "color": "#334155",
            "fillColor": "#cbd5e1",
            "fillOpacity": 0.22,
        },
        "OSM": {"color": "#2563eb", "fillColor": "#bfdbfe", "fillOpacity": 0.20},
        "vegetation": {"color": "#16a34a", "fillColor": "#bbf7d0", "fillOpacity": 0.22},
        "shielding": {"color": "#047857", "fillColor": "#047857", "fillOpacity": 0.12},
        "missing_height": {"color": "#b42318", "fillColor": "#fee2e2", "fillOpacity": 0.28},
    }
    return {"weight": 1, **styles.get(layer, styles["OSM"])}


def _add_obstruction_centroid_collection(
    layer: folium.FeatureGroup,
    selected: list[ObstructionRecord],
    diagnostics: MapRenderDiagnostics,
) -> None:
    """Add obstruction centroids as one lightweight GeoJSON point layer."""

    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [record.centroid_longitude, record.centroid_latitude],
            },
            "properties": {
                "id": record.obstruction_id,
                "source": record.footprint_source,
                "height": f"{(record.selected_height_m or record.height_m):.1f} m"
                if (record.selected_height_m or record.height_m) is not None
                else "missing",
                "confidence": record.confidence,
            },
        }
        for record in selected
    ]
    diagnostics.plotted_centroids = len(features)
    if not features:
        return
    folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        marker=folium.CircleMarker(
            radius=3,
            color="#334155",
            fill=True,
            fill_opacity=0.85,
        ),
        tooltip=folium.GeoJsonTooltip(
            fields=["id", "source", "height", "confidence"],
            aliases=["ID", "Source", "Height", "Confidence"],
            sticky=False,
        ),
    ).add_to(layer)


def _add_map_diagnostics_banner(
    fmap: folium.Map,
    diagnostics: MapRenderDiagnostics,
) -> None:
    """Add a visible map diagnostic/warning banner."""

    if not diagnostics.warnings and not diagnostics.fallback_mode:
        return
    warning_text = "<br>".join(diagnostics.warnings or diagnostics.console_safe_errors)
    html = f"""
    <div style="position: fixed; bottom: 18px; left: 18px; z-index: 9999;
      max-width: 440px; padding: 10px 12px; background: #fff7ed; color: #7c2d12;
      border: 1px solid #fdba74; border-radius: 6px; font: 13px/1.35 Arial, sans-serif;">
      <strong>Map display notice</strong><br>{warning_text}
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(html))


def _render_map_with_diagnostics(
    fmap: folium.Map,
    diagnostics: MapRenderDiagnostics,
) -> str:
    """Render Folium HTML and inject final diagnostics."""

    html = fmap.get_root().render()
    diagnostics.map_html_size = len(html.encode("utf-8"))
    diagnostics_json = json.dumps(diagnostics.as_dict(), ensure_ascii=True)
    diagnostics_panel = f"""
    <script>
      window.openWindMapDiagnostics = {diagnostics_json};
      console.info("OpenWind-AU map diagnostics", window.openWindMapDiagnostics);
    </script>
    <!-- OpenWind-AU map diagnostics: {diagnostics_json} -->
    """
    return html.replace("</body>", f"{diagnostics_panel}</body>")


def safe_error_message(error: Exception) -> str:
    """Return a console-safe single-line error message."""

    return str(error).replace("\n", " ")[:240]


def _obstruction_source_layer(
    obstruction,
    manual_layer: folium.FeatureGroup,
    microsoft_layer: folium.FeatureGroup,
    osm_layer: folium.FeatureGroup,
    vegetation_layer: folium.FeatureGroup,
) -> folium.FeatureGroup:
    if obstruction.classification == "vegetation":
        return vegetation_layer
    if obstruction.footprint_source == "manual_reviewed":
        return manual_layer
    if obstruction.footprint_source == "microsoft_building_footprints":
        return microsoft_layer
    return osm_layer


def _add_obstruction_polygon(
    layer: folium.FeatureGroup,
    obstruction,
    outline_color: str | None = None,
    fill_color: str | None = None,
    fill_opacity: float = 0.25,
) -> None:
    outline = outline_color or _obstruction_color(obstruction.confidence)
    fill = fill_color or _obstruction_height_color(obstruction.height_m)
    folium.GeoJson(
        obstruction.footprint_geometry,
        style_function=lambda _feature, outline=outline, fill=fill: {
            "color": outline,
            "weight": 2,
            "fillColor": fill,
            "fillOpacity": fill_opacity,
        },
        tooltip=_obstruction_tooltip(obstruction),
    ).add_to(layer)


def _add_obstruction_centroid(layer: folium.FeatureGroup, obstruction) -> None:
    color = _obstruction_color(obstruction.confidence)
    folium.CircleMarker(
        location=[obstruction.centroid_latitude, obstruction.centroid_longitude],
        radius=3,
        color=color,
        fill=True,
        popup=(
            f"{obstruction.obstruction_id}<br>"
            f"Distance {obstruction.distance_m:.1f} m<br>"
            f"Bearing {obstruction.bearing_deg:.0f} deg<br>"
            f"Classification {obstruction.classification}<br>"
            f"Footprint source {obstruction.footprint_source}<br>"
            f"Height source {obstruction.height_source}<br>"
            f"Confidence {obstruction.confidence}"
        ),
    ).add_to(layer)


def _obstruction_tooltip(obstruction) -> str:
    height = f"{obstruction.height_m:.1f} m" if obstruction.height_m is not None else "missing"
    return (
        f"{obstruction.obstruction_id}: height={height}, "
        f"source={obstruction.footprint_source}, "
        f"height_source={obstruction.height_source}, confidence={obstruction.confidence}"
    )


def _is_shielding_candidate(obstruction, subject_height_m: float | None) -> bool:
    height = (
        obstruction.selected_height_m
        if obstruction.selected_height_m is not None
        else obstruction.height_m
    )
    if height is None:
        return False
    if subject_height_m is None:
        return True
    return height >= subject_height_m


def _is_missing_source_height(obstruction) -> bool:
    source_height_labels = {"manual_verified", "IMPORTED", "OSM_HEIGHT", "OSM_LEVELS"}
    return obstruction.height_source in {"missing", "ESTIMATED"} or (
        obstruction.raw_source_height_m is None
        and obstruction.raw_source_height_source not in source_height_labels
    )


def _obstruction_color(confidence: str) -> str:
    return {
        "high": "#0f766e",
        "medium": "#b45309",
        "low": "#f97316",
        "unknown": "#b42318",
    }.get(confidence, "#57606a")


def _obstruction_height_color(height_m: float | None) -> str:
    if height_m is None:
        return "#d0d7de"
    if height_m < 5:
        return "#bbf7d0"
    if height_m < 10:
        return "#86efac"
    if height_m < 20:
        return "#22c55e"
    if height_m < 40:
        return "#15803d"
    return "#14532d"


def _shielding_sector_color(indicative_ms: float) -> str:
    if indicative_ms <= 0.75:
        return "#047857"
    if indicative_ms <= 0.9:
        return "#b45309"
    return "#57606a"


def _terrain_category_color(suggested_range: str) -> str:
    if suggested_range == "TC1.5-TC2":
        return "#38bdf8"
    if suggested_range == "TC2-TC2.5":
        return "#2563eb"
    if suggested_range == "TC2.5-TC3":
        return "#0f766e"
    if suggested_range == "TC3-TC4":
        return "#b45309"
    return "#b42318"


OBSTRUCTION_REPORT_TEMPLATE = Template(
    """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>OpenWind-AU Obstruction Inventory Report</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 32px; color: #202124; }
    h1, h2 { color: #17324d; }
    table { border-collapse: collapse; width: 100%; margin: 16px 0; }
    th, td { border: 1px solid #d0d7de; padding: 8px; text-align: left; }
    th { background: #f6f8fa; }
    .disclaimer { border-left: 4px solid #b42318; padding: 12px; background: #fff4f2; }
    .warning { border-left: 4px solid #b45309; padding: 12px; background: #fff7ed; }
  </style>
</head>
<body>
  <h1>OpenWind-AU Obstruction Inventory Report</h1>
  <p class="disclaimer">{{ result.disclaimer }}</p>
  {% if result.warnings %}
  <div class="warning">
    <strong>Inventory warning</strong>
    <ul>{% for warning in result.warnings %}<li>{{ warning }}</li>{% endfor %}</ul>
  </div>
  {% endif %}

  <h2>Subject Site</h2>
  <table>
    <tr><th>Latitude</th><td>{{ "%.6f"|format(result.site.latitude) }}</td></tr>
    <tr><th>Longitude</th><td>{{ "%.6f"|format(result.site.longitude) }}</td></tr>
    <tr><th>Inventory radius</th><td>{{ result.input.radius_m }} m</td></tr>
    <tr>
      <th>Default storey height</th>
      <td>{{ "%.2f"|format(result.input.default_storey_height_m) }} m</td>
    </tr>
  </table>

  <h2>Missing Height Summary</h2>
  <table>
    <tr><th>Total obstructions</th><th>Missing heights</th><th>Reviewed heights</th></tr>
    <tr>
      <td>{{ result.obstructions|length }}</td>
      <td>{{ result.missing_height_count }}</td>
      <td>{{ result.reviewed_height_count }}</td>
    </tr>
  </table>

  <h2>Obstruction Data Quality</h2>
  <table>
    <tr><th>Metric</th><th>Value</th></tr>
    <tr>
      <td>Total Microsoft building footprints found</td>
      <td>{{ result.data_quality.total_microsoft_building_footprints_found }}</td>
    </tr>
    <tr>
      <td>Total OSM building footprints found</td>
      <td>{{ result.data_quality.total_osm_building_footprints_found }}</td>
    </tr>
    <tr>
      <td>Microsoft source status</td>
      <td>{{ result.data_quality.microsoft_source_status }}</td>
    </tr>
    <tr>
      <td>Microsoft cache status</td>
      <td>{{ result.data_quality.microsoft_cache_status }}</td>
    </tr>
    <tr>
      <td>OSM fallback used</td>
      <td>{{ "yes" if result.data_quality.osm_fallback_used else "no" }}</td>
    </tr>
    <tr>
      <td>Total vegetation polygons found</td>
      <td>{{ result.data_quality.total_vegetation_polygons_found }}</td>
    </tr>
    <tr>
      <td>Total usable obstruction polygons</td>
      <td>{{ result.data_quality.total_usable_obstruction_polygons }}</td>
    </tr>
    <tr>
      <td>Number excluded</td>
      <td>{{ result.data_quality.number_excluded }}</td>
    </tr>
    <tr>
      <td>Percentage with height data</td>
      <td>{{ "%.1f"|format(result.data_quality.percentage_with_height_data) }}%</td>
    </tr>
    <tr>
      <td>Percentage requiring manual review</td>
      <td>{{ "%.1f"|format(result.data_quality.percentage_requiring_manual_review) }}%</td>
    </tr>
    <tr>
      <td>Duplicate overlaps removed</td>
      <td>{{ result.data_quality.duplicate_overlap_count }}</td>
    </tr>
  </table>

  <h2>Footprint Source Summary</h2>
  <table>
    <tr><th>Source</th><th>Usable polygons</th></tr>
    {% for source, count in result.data_quality.source_summary.items() %}
    <tr><td>{{ source }}</td><td>{{ count }}</td></tr>
    {% endfor %}
  </table>

  <h2>Excluded Object Reasons</h2>
  <table>
    <tr><th>Reason</th><th>Count</th></tr>
    {% if result.data_quality.excluded_reasons %}
    {% for reason, count in result.data_quality.excluded_reasons.items() %}
    <tr><td>{{ reason }}</td><td>{{ count }}</td></tr>
    {% endfor %}
    {% else %}
    <tr><td>No exclusions recorded.</td><td>0</td></tr>
    {% endif %}
  </table>

  <h2>Height Source Summary</h2>
  <table>
    <tr><th>Source</th><th>Count</th></tr>
    {% for source, count in result.height_source_summary.items() %}
    <tr><td>{{ source }}</td><td>{{ count }}</td></tr>
    {% endfor %}
  </table>

  <h2>Obstruction Map</h2>
  <p>
    Use <code>POST /api/obstructions/map</code> for the interactive footprint map. Footprints are
    filled by selected height band and outlined by confidence.
  </p>

  <h2>Obstruction Table</h2>
  <table>
    <tr>
      <th>ID</th><th>Class</th><th>Distance</th><th>Bearing</th><th>Selected height</th>
      <th>Raw source height</th><th>Estimated height</th><th>DSM-DTM estimate</th><th>Ground RL</th>
      <th>Surface RL</th><th>Source</th><th>Confidence</th><th>Review required</th><th>Warnings</th>
    </tr>
    {% for obstruction in result.obstructions %}
    <tr>
      <td>{{ obstruction.obstruction_id }}</td>
      <td>{{ obstruction.classification }}</td>
      <td>{{ "%.1f"|format(obstruction.distance_m) }} m</td>
      <td>{{ "%.0f"|format(obstruction.bearing_deg) }} deg</td>
      <td>
        {% if obstruction.height_m is not none %}
        {{ "%.2f"|format(obstruction.height_m) }} m
        {% else %}
        missing
        {% endif %}
      </td>
      <td>
        {% if obstruction.raw_source_height_m is not none %}
        {{ "%.2f"|format(obstruction.raw_source_height_m) }} m
        {% endif %}
      </td>
      <td>
        {% if obstruction.estimated_height_m is not none %}
        {{ "%.2f"|format(obstruction.estimated_height_m) }} m
        {% endif %}
      </td>
      <td>
        {% if obstruction.obstruction_height_m is not none %}
        {{ "%.2f"|format(obstruction.obstruction_height_m) }} m
        {% endif %}
      </td>
      <td>
        {{ "%.2f"|format(obstruction.ground_rl_m) if obstruction.ground_rl_m is not none else "" }}
      </td>
      <td>
        {% if obstruction.surface_rl_m is not none %}
        {{ "%.2f"|format(obstruction.surface_rl_m) }}
        {% endif %}
      </td>
      <td>{{ obstruction.height_source }}</td>
      <td>{{ obstruction.confidence }}</td>
      <td>{{ obstruction.review_required }}</td>
      <td>{{ obstruction.warnings|join(" ") }}</td>
    </tr>
    {% endfor %}
  </table>

  <h2>Preliminary Shielding Sector Analysis</h2>
  <p>
    Each wind direction uses a 45 degree upwind sector with radius 20 times the subject building
    height. Obstructions are counted only where selected hs is at least the subject building
    height z=
    {% if result.input.building_height_m is not none %}
    {{ "%.2f"|format(result.input.building_height_m) }} m
    {% else %}
    not set
    {% endif %}.
    Indicative Ms values require engineering review.
  </p>
  <table>
    <tr>
      <th>Dir.</th><th>Sector</th><th>Radius</th><th>ns</th><th>Avg hs</th>
      <th>Avg bs</th><th>ls</th><th>s</th><th>Indicative Ms</th>
      <th>In sector</th><th>Usable height</th><th>Rejected below z</th>
      <th>Rejected missing</th><th>Overall confidence</th>
    </tr>
    {% for sector in result.shielding_sectors %}
    <tr>
      <td>{{ sector.direction }}</td>
      <td>
        {{ "%.1f"|format(sector.sector_start_deg) }}-{{ "%.1f"|format(sector.sector_end_deg) }} deg
      </td>
      <td>{{ "%.1f"|format(sector.sector_radius_m) }} m</td>
      <td>{{ sector.ns }}</td>
      <td>{{ "%.2f"|format(sector.average_hs_m) if sector.average_hs_m is not none else "" }}</td>
      <td>{{ "%.2f"|format(sector.average_bs_m) if sector.average_bs_m is not none else "" }}</td>
      <td>{{ "%.2f"|format(sector.ls_m) if sector.ls_m is not none else "" }}</td>
      <td>{{ "%.2f"|format(sector.s) if sector.s is not none else "" }}</td>
      <td>{{ "%.3f"|format(sector.indicative_ms) }}</td>
      <td>{{ sector.total_obstructions_in_sector }}</td>
      <td>{{ sector.usable_height_count }}</td>
      <td>{{ sector.rejected_height_below_z_count }}</td>
      <td>{{ sector.rejected_height_missing_count }}</td>
      <td>{{ sector.overall_confidence }}</td>
    </tr>
    {% if sector.warnings %}
    <tr>
      <td></td>
      <td colspan="13">{{ sector.warnings|join(" ") }}</td>
    </tr>
    {% endif %}
    {% if sector.rejection_reason_counts %}
    <tr>
      <td></td>
      <td colspan="13">
        Rejection reasons:
        {% for reason, count in sector.rejection_reason_counts.items() %}
        {{ reason }}={{ count }}
        {% endfor %}
      </td>
    </tr>
    {% endif %}
    {% endfor %}
  </table>

  <p>
    Indicative Ms values are preliminary screening outputs only and are not certified design
    values.
  </p>
</body>
</html>
"""
)


TERRAIN_CATEGORY_REPORT_TEMPLATE = Template(
    """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>OpenWind-AU Terrain Category Evidence Report</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 32px; color: #202124; }
    h1, h2 { color: #17324d; }
    table { border-collapse: collapse; width: 100%; margin: 16px 0; }
    th, td { border: 1px solid #d0d7de; padding: 8px; text-align: left; vertical-align: top; }
    th { background: #f6f8fa; }
    .disclaimer { border-left: 4px solid #b42318; padding: 12px; background: #fff4f2; }
    .warning { border-left: 4px solid #b45309; padding: 12px; background: #fff7ed; }
  </style>
</head>
<body>
  <h1>OpenWind-AU Terrain Category Evidence Report</h1>
  <p class="disclaimer">{{ result.disclaimer }}</p>
  {% if result.warnings %}
  <div class="warning">
    <strong>Workflow warnings</strong>
    <ul>{% for warning in result.warnings %}<li>{{ warning }}</li>{% endfor %}</ul>
  </div>
  {% endif %}

  <h2>Subject Site</h2>
  <table>
    <tr><th>Latitude</th><td>{{ "%.6f"|format(result.site.latitude) }}</td></tr>
    <tr><th>Longitude</th><td>{{ "%.6f"|format(result.site.longitude) }}</td></tr>
    <tr><th>Analysis radius</th><td>{{ result.input.radius_m }} m</td></tr>
  </table>

  <h2>Terrain Category Evidence Summary</h2>
  <table>
    <tr>
      <th>Direction</th><th>Fetch</th><th>Built-up coverage</th><th>Vegetation coverage</th>
      <th>Open terrain</th><th>Average obstruction height</th><th>Median height</th>
      <th>Maximum height</th><th>Obstruction density</th><th>Average spacing</th>
      <th>Vegetation density</th><th>Obstruction count</th><th>Shielding confidence</th>
      <th>Suggested range</th><th>Confidence</th><th>Warnings</th>
    </tr>
    {% for direction in result.directions %}
    <tr>
      <td>{{ direction.direction }}</td>
      <td>{{ "%.0f"|format(direction.directional_fetch_distance_m) }} m</td>
      <td>{{ "%.1f"|format(direction.built_up_area_percentage) }}%</td>
      <td>{{ "%.1f"|format(direction.vegetation_area_percentage) }}%</td>
      <td>{{ "%.1f"|format(direction.open_terrain_percentage) }}%</td>
      <td>
        {% if direction.average_obstruction_height_m is not none %}
        {{ "%.2f"|format(direction.average_obstruction_height_m) }}
        {% else %}
        unknown
        {% endif %}
      </td>
      <td>
        {% if direction.median_obstruction_height_m is not none %}
        {{ "%.2f"|format(direction.median_obstruction_height_m) }}
        {% else %}
        unknown
        {% endif %}
      </td>
      <td>
        {% if direction.maximum_obstruction_height_m is not none %}
        {{ "%.2f"|format(direction.maximum_obstruction_height_m) }}
        {% else %}
        unknown
        {% endif %}
      </td>
      <td>{{ "%.1f"|format(direction.obstruction_density_per_km2) }}/km2</td>
      <td>
        {% if direction.average_obstruction_spacing_m is not none %}
        {{ "%.1f"|format(direction.average_obstruction_spacing_m) }} m
        {% else %}
        unknown
        {% endif %}
      </td>
      <td>{{ "%.1f"|format(direction.vegetation_density_per_km2) }}/km2</td>
      <td>{{ direction.obstruction_count }}</td>
      <td>{{ direction.shielding_confidence }}</td>
      <td>{{ direction.suggested_category_range }}</td>
      <td>{{ direction.confidence }}</td>
      <td>{{ direction.warnings|join(" ") }}</td>
    </tr>
    {% endfor %}
  </table>

  <h2>Directional Mz,cat Summary</h2>
  <p class="disclaimer">
    Indicative evidence only. Terrain category is not confirmed, Mz,cat values are not final
    design values, and engineer review is required.
  </p>
  <table>
    <tr>
      <th>Direction</th><th>Suggested TC Range</th><th>Indicative Mz,cat Range</th>
      <th>Recommended TC</th><th>Recommended Mz,cat</th><th>Recommendation Confidence</th>
      <th>Engineer-selected Final TC</th><th>Engineer-selected Final Mz,cat</th>
      <th>Review Status</th><th>Review Notes</th><th>Warnings</th>
    </tr>
    {% for assessment in result.mzcat_assessment %}
    <tr>
      <td>{{ assessment.direction }}</td>
      <td>{{ assessment.controlling_category_range }}</td>
      <td>
        {{ "%.3f"|format(assessment.lower_indicative_mzcat) }}-
        {{ "%.3f"|format(assessment.upper_indicative_mzcat) }}
      </td>
      <td>{{ assessment.recommended_terrain_category }}</td>
      <td>
        {% if assessment.recommended_mzcat is not none %}
        {{ "%.3f"|format(assessment.recommended_mzcat) }}
        {% else %}
        review required
        {% endif %}
      </td>
      <td>{{ assessment.recommendation_confidence }}</td>
      <td>
        {% if assessment.review_status in ["accepted", "overridden"] %}
        {{ assessment.final_terrain_category }}
        {% else %}
        unreviewed
        {% endif %}
      </td>
      <td>
        {% if assessment.review_status in ["accepted", "overridden"]
          and assessment.final_mzcat is not none %}
        {{ "%.3f"|format(assessment.final_mzcat) }}
        {% else %}
        hidden until engineer review
        {% endif %}
      </td>
      <td>{{ assessment.review_status }}</td>
      <td>{{ assessment.review_notes or "" }}</td>
      <td>
        {% if assessment.review_status == "unreviewed" %}
        Engineer review required before final Mz,cat may be used.
        {% endif %}
        {{ assessment.warnings|join(" ") }}
      </td>
    </tr>
    <tr>
      <td></td>
      <td colspan="10">
        Recommendation reasoning:
        <ul>
          {% for reason in assessment.recommendation_reasoning %}
          <li>{{ reason }}</li>
          {% endfor %}
          {% for reason in assessment.reasoning %}
          <li>{{ reason }}</li>
          {% endfor %}
        </ul>
      </td>
    </tr>
    {% endfor %}
  </table>

  <h2>Evidence Score Components</h2>
  <table>
    <tr>
      <th>Direction</th><th>Open Exposure Score</th><th>Vegetation Score</th>
      <th>Urban Density Score</th><th>Obstruction Height Score</th>
    </tr>
    {% for direction in result.directions %}
    <tr>
      <td>{{ direction.direction }}</td>
      <td>{{ "%.1f"|format(direction.evidence_scores.open_exposure_score) }}</td>
      <td>{{ "%.1f"|format(direction.evidence_scores.vegetation_score) }}</td>
      <td>{{ "%.1f"|format(direction.evidence_scores.urban_density_score) }}</td>
      <td>{{ "%.1f"|format(direction.evidence_scores.obstruction_height_score) }}</td>
    </tr>
    {% endfor %}
  </table>

  <p>
    Suggested ranges are review prompts only. A competent engineer must confirm terrain category
    using project-specific context, survey information, imagery, and the applicable standard.
  </p>
</body>
</html>
"""
)
