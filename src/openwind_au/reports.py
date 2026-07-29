"""HTML, PDF, map, and plot generation for OpenWind-AU."""

from __future__ import annotations

import base64
import binascii
import json
import math
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import folium
import plotly.graph_objects as go
from jinja2 import Environment, select_autoescape
from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
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
    WindRegionAssessment,
    WindWorkflowResult,
)
from openwind_au.report_lineage import (
    CALCULATION_BASIS_REPORT_TEXT,
    CALCULATION_BASIS_URL,
)
from openwind_au.shielding import shielding_sector_polygon

HTML_TEMPLATE_ENV = Environment(
    autoescape=select_autoescape(default_for_string=True),
)

DEFAULT_MAP_DISPLAY_LIMIT = 500
MAX_POLYGON_GEOJSON_PAYLOAD_BYTES = 2_500_000
MAX_WIND_PDF_MAP_SCREENSHOT_BYTES = 2_100_000
MIN_WIND_PDF_MAP_SCREENSHOT_DIMENSION_PX = 64
MAX_WIND_PDF_MAP_SCREENSHOT_DIMENSION_PX = 1_280
MAX_WIND_PDF_MAP_SCREENSHOT_PIXELS = 1_024_000
MAX_WIND_PDF_MAP_SCREENSHOT_ASPECT_RATIO = 8.0
MAP_ASSET_URL_REPLACEMENTS = {
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js": (
        "/static/vendor/leaflet/leaflet.js"
    ),
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css": (
        "/static/vendor/leaflet/leaflet.css"
    ),
    "https://code.jquery.com/jquery-3.7.1.min.js": ("/static/vendor/jquery/jquery-3.7.1.min.js"),
    "https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/js/bootstrap.bundle.min.js": (
        "/static/vendor/bootstrap/bootstrap.bundle.min.js"
    ),
    "https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/css/bootstrap.min.css": (
        "/static/vendor/bootstrap/bootstrap.min.css"
    ),
    "https://netdna.bootstrapcdn.com/bootstrap/3.0.0/css/bootstrap-glyphicons.css": (
        "/static/vendor/bootstrap/bootstrap-glyphicons.css"
    ),
    "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.2.0/css/all.min.css": (
        "/static/vendor/fontawesome/all.min.css"
    ),
    "https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/"
    "leaflet.awesome-markers.js": "/static/vendor/awesome-markers/leaflet.awesome-markers.js",
    "https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/"
    "leaflet.awesome-markers.css": "/static/vendor/awesome-markers/leaflet.awesome-markers.css",
    "https://cdn.jsdelivr.net/gh/python-visualization/folium/folium/templates/"
    "leaflet.awesome.rotate.min.css": "/static/vendor/folium/leaflet.awesome.rotate.min.css",
}


@dataclass(frozen=True)
class _ValidatedWindMapScreenshot:
    data: bytes
    media_type: str
    width_px: int
    height_px: int


def _json_for_inline_script(value: Any) -> str:
    """Serialize JSON without allowing data to terminate an inline script element."""

    return (
        json.dumps(value, ensure_ascii=True)
        .replace("<", r"\u003c")
        .replace(">", r"\u003e")
        .replace("&", r"\u0026")
        .replace("\u2028", r"\u2028")
        .replace("\u2029", r"\u2029")
    )


@dataclass
class MapRenderDiagnostics:
    """Display-only diagnostics for obstruction map rendering."""

    display_mode: str = "nearest_500"
    max_displayed_obstructions: int = DEFAULT_MAP_DISPLAY_LIMIT
    total_obstructions: int = 0
    selected_obstructions: int = 0
    plotted_polygons: int = 0
    plotted_microsoft_polygons: int = 0
    plotted_shielding_polygons: int = 0
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
            "plotted_microsoft_polygons": self.plotted_microsoft_polygons,
            "plotted_shielding_polygons": self.plotted_shielding_polygons,
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


REPORT_TEMPLATE = HTML_TEMPLATE_ENV.from_string(
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
  {% if calculation_basis_reference %}
  <p class="note">{{ calculation_basis_reference }}</p>
  {% endif %}

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

    return REPORT_TEMPLATE.render(
        result=result,
        calculation_basis_reference=calculation_basis_report_reference(),
    )


def write_html_report(result: SiteAnalysisResult, path: Path) -> Path:
    """Write an HTML report to *path*."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html_report(result), encoding="utf-8")
    return path


def write_pdf_report(result: SiteAnalysisResult, path: Path) -> Path:
    """Write a simple PDF report to *path* using ReportLab."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_pdf_report(result))
    return path


def render_pdf_report(result: SiteAnalysisResult) -> bytes:
    """Render a simple PDF report in memory using ReportLab."""

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("OpenWind-AU Preliminary Terrain Report", styles["Title"]),
        Paragraph(result.disclaimer, styles["BodyText"]),
        *(
            [Paragraph(reference, styles["BodyText"])]
            if (reference := calculation_basis_report_reference())
            else []
        ),
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
    return output.getvalue()


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
    return fig.to_html(full_html=False, include_plotlyjs="/vendor/plotly.min.js")


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
    return _localize_map_assets(fmap.get_root().render())


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
    evidence_result: TerrainCategoryEvidenceResult | None = None,
    wind_region_assessment: WindRegionAssessment | None = None,
) -> str:
    """Return a Folium map with toggleable wind workflow layers.

    The returned document embeds a Folium/Leaflet map with a non-collapsed layer control so
    users can show or hide wind regions, Mz,cat sectors, shielding sectors, topographic
    features, terrain profiles, and nearby obstruction centroids on one map.
    """

    fmap = folium.Map(
        location=[site_result.site.latitude, site_result.site.longitude],
        zoom_start=14,
        control_scale=True,
        tiles=None,
    )
    folium.TileLayer(
        tiles="OpenStreetMap",
        name="OpenStreetMap",
        overlay=False,
        control=True,
        show=True,
        cross_origin="anonymous",
    ).add_to(fmap)
    site_layer = folium.FeatureGroup(name="Site & analysis radius", show=True)
    wind_region_layer = folium.FeatureGroup(name="Wind regions", show=True)
    mzcat_layer = folium.FeatureGroup(name="Mz,cat sectors", show=True)
    profile_layer = folium.FeatureGroup(
        name="Terrain profiles & topographic candidates",
        show=True,
    )
    shielding_layer = folium.FeatureGroup(name="Shielding sectors", show=True)
    shielding_polygon_layer = folium.FeatureGroup(name="Shielding obstruction polygons", show=True)
    design_building_layer = folium.FeatureGroup(name="Design building (editable)", show=True)
    obstruction_layer = folium.FeatureGroup(name="Nearby obstructions (selected)", show=True)

    if wind_region_assessment is not None:
        _add_wind_region_layer(wind_region_layer, site_result.site, wind_region_assessment)

    folium.CircleMarker(
        location=[site_result.site.latitude, site_result.site.longitude],
        radius=6,
        color="#17324d",
        weight=2,
        fill=True,
        fill_color="#ffffff",
        fill_opacity=1,
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

    if evidence_result is not None:
        for direction in evidence_result.directions:
            color = _terrain_category_color(direction.suggested_category_range)
            folium.GeoJson(
                terrain_category_sector_polygon(evidence_result.site, direction),
                interactive=False,
                style_function=lambda _feature, color=color: {
                    "color": color,
                    "weight": 2,
                    "dashArray": "5 4",
                    "fillColor": color,
                    "fillOpacity": 0.08,
                },
                tooltip=(
                    f"{direction.direction}: Mz,cat input sector, "
                    f"range={direction.suggested_category_range}, "
                    f"confidence={direction.confidence}"
                ),
            ).add_to(mzcat_layer)

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
        ).add_to(profile_layer)

    diagnostics = _add_obstruction_centroid_layer(fmap, obstruction_layer, obstruction_result)

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

    wind_region_layer.add_to(fmap)
    site_layer.add_to(fmap)
    mzcat_layer.add_to(fmap)
    profile_layer.add_to(fmap)
    shielding_layer.add_to(fmap)
    shielding_polygon_layer.add_to(fmap)
    diagnostics = _add_workflow_shielding_polygon_layer(
        fmap,
        shielding_polygon_layer,
        obstruction_result,
        diagnostics,
    )
    design_building_layer.add_to(fmap)
    _add_design_building_overlay(fmap, design_building_layer, site_result)
    _add_workflow_map_capture_bridge(fmap)
    obstruction_layer.add_to(fmap)
    folium.LayerControl(collapsed=False, position="topright").add_to(fmap)

    return _render_map_with_diagnostics(fmap, diagnostics)


def _add_design_building_overlay(
    fmap: folium.Map,
    layer: folium.FeatureGroup,
    site_result: SiteAnalysisResult,
) -> None:
    """Add a parent-controllable design building footprint to the workflow map."""

    payload = {
        "latitude": site_result.site.latitude,
        "longitude": site_result.site.longitude,
        "width_m": getattr(site_result.input, "building_width_m", None) or 12,
        "length_m": getattr(site_result.input, "building_length_m", None) or 18,
        "orientation_deg": getattr(site_result.input, "structure_orientation_deg", None) or 0,
        "offset_east_m": 0,
        "offset_north_m": 0,
        "user_modified": False,
        "position_modified": False,
        "orientation_modified": False,
        "dimensions_modified": False,
        "orientation_options": [0, 45, 90, 135, 180, 225, 270, 315],
    }
    script = f"""
    (function() {{
      const mapName = "{fmap.get_name()}";
      const designLayerName = "{layer.get_name()}";
      const state = {_json_for_inline_script(payload)};
      let footprint = null;
      let bearingLine = null;
      let pointsLayer = null;
      let resizeHandlesLayer = null;
      let orientationDrag = null;
      let resizeDrag = null;
      let buildingDragStart = null;
      let suppressOrientationClick = false;
      let map = null;
      let designLayer = null;
      const minDimensionM = 0.1;
      const maxDimensionM = 5000;

      function clampDimension(value, fallback) {{
        const number = Number(value);
        return Number.isFinite(number) && number > 0
          ? Math.min(maxDimensionM, Math.max(minDimensionM, number))
          : fallback;
      }}

      function formatDegrees(value) {{
        return Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 2);
      }}

      function normalizeOrientation(value) {{
        const number = Number(value);
        if (!Number.isFinite(number)) return 0;
        const normalized = ((number % 360) + 360) % 360;
        const rounded = Math.round(normalized * 10) / 10;
        return rounded >= 360 ? 0 : rounded;
      }}

      function compassLabel(value) {{
        return {{
          0: "N",
          45: "NE",
          90: "E",
          135: "SE",
          180: "S",
          225: "SW",
          270: "W",
          315: "NW",
        }}[Number(value)] || "";
      }}

      function latLngFromMeters(eastM, northM) {{
        const earthRadiusM = 6378137;
        const adjustedEastM = eastM + state.offset_east_m;
        const adjustedNorthM = northM + state.offset_north_m;
        const lat = state.latitude + (adjustedNorthM / earthRadiusM) * (180 / Math.PI);
        const metresPerDegreeLon = earthRadiusM * Math.cos(state.latitude * Math.PI / 180);
        const lon = state.longitude
          + (adjustedEastM / metresPerDegreeLon) * (180 / Math.PI);
        return [lat, lon];
      }}

      function metersDelta(fromLatLng, toLatLng) {{
        const earthRadiusM = 6378137;
        const northM = (toLatLng.lat - fromLatLng.lat) * Math.PI / 180 * earthRadiusM;
        const eastM = (toLatLng.lng - fromLatLng.lng) * Math.PI / 180
          * earthRadiusM * Math.cos(state.latitude * Math.PI / 180);
        return {{ eastM, northM }};
      }}

      function footprintCorners() {{
        const theta = Number(state.orientation_deg) * Math.PI / 180;
        const halfLength = clampDimension(state.length_m, 18) / 2;
        const halfWidth = clampDimension(state.width_m, 12) / 2;
        const lengthAxis = [Math.sin(theta), Math.cos(theta)];
        const widthAxis = [Math.cos(theta), -Math.sin(theta)];
        return [
          [halfLength, halfWidth],
          [halfLength, -halfWidth],
          [-halfLength, -halfWidth],
          [-halfLength, halfWidth],
        ].map(([lengthOffset, widthOffset]) => latLngFromMeters(
          lengthAxis[0] * lengthOffset + widthAxis[0] * widthOffset,
          lengthAxis[1] * lengthOffset + widthAxis[1] * widthOffset,
        ));
      }}

      function bearingEndpoint(distanceM) {{
        const theta = Number(state.orientation_deg) * Math.PI / 180;
        return latLngFromMeters(Math.sin(theta) * distanceM, Math.cos(theta) * distanceM);
      }}

      function centerLatLng() {{
        return latLngFromMeters(0, 0);
      }}

      function notifyParent() {{
        try {{
          window.parent.postMessage({{
            type: "openwind-design-building-change",
            state: Object.assign({{}}, state),
          }}, "*");
        }} catch (_error) {{
          // Parent notification is best-effort for embedded previews.
        }}
      }}

      function applyOrientationFromLatLng(latlng) {{
        const center = centerLatLng();
        const delta = metersDelta({{ lat: center[0], lng: center[1] }}, latlng);
        const rawDegrees = Math.atan2(delta.eastM, delta.northM) * 180 / Math.PI;
        const orientation = normalizeOrientation(rawDegrees);
        if (Number(state.orientation_deg) === Number(orientation)) return;
        if (orientationDrag) orientationDrag.moved = true;
        state.orientation_deg = orientation;
        state.user_modified = true;
        state.orientation_modified = true;
        redraw();
        notifyParent();
        state.orientation_modified = false;
      }}

      function startOrientationDrag(event) {{
        L.DomEvent.preventDefault(event.originalEvent);
        L.DomEvent.stopPropagation(event.originalEvent);
        orientationDrag = {{ moved: false }};
        map.dragging.disable();
        map.getContainer().style.cursor = "grabbing";
        applyOrientationFromLatLng(event.latlng);
      }}

      function stopOrientationDrag() {{
        if (!orientationDrag) return;
        if (orientationDrag.moved) {{
          suppressOrientationClick = true;
          setTimeout(() => {{
            suppressOrientationClick = false;
          }}, 0);
        }}
        orientationDrag = null;
        map.dragging.enable();
        map.getContainer().style.cursor = "";
      }}

      function applyResizeFromLatLng(latlng) {{
        if (!resizeDrag) return;
        const center = centerLatLng();
        const delta = metersDelta({{ lat: center[0], lng: center[1] }}, latlng);
        const theta = Number(state.orientation_deg) * Math.PI / 180;
        const lengthAxis = [Math.sin(theta), Math.cos(theta)];
        const widthAxis = [Math.cos(theta), -Math.sin(theta)];
        const projectedHalfLength = resizeDrag.lengthSign * (
          delta.eastM * lengthAxis[0] + delta.northM * lengthAxis[1]
        );
        const projectedHalfWidth = resizeDrag.widthSign * (
          delta.eastM * widthAxis[0] + delta.northM * widthAxis[1]
        );
        const lengthM = Math.round(clampDimension(
          2 * Math.max(minDimensionM / 2, projectedHalfLength),
          state.length_m,
        ) * 10) / 10;
        const widthM = Math.round(clampDimension(
          2 * Math.max(minDimensionM / 2, projectedHalfWidth),
          state.width_m,
        ) * 10) / 10;
        if (
          Number(state.length_m) === Number(lengthM)
          && Number(state.width_m) === Number(widthM)
        ) return;
        resizeDrag.moved = true;
        state.length_m = lengthM;
        state.width_m = widthM;
        state.user_modified = true;
        state.dimensions_modified = true;
        redraw();
        notifyParent();
        state.dimensions_modified = false;
      }}

      function startResizeDrag(event, lengthSign, widthSign) {{
        L.DomEvent.preventDefault(event.originalEvent);
        L.DomEvent.stopPropagation(event.originalEvent);
        resizeDrag = {{ lengthSign, widthSign, moved: false }};
        map.dragging.disable();
        map.getContainer().style.cursor = "nwse-resize";
      }}

      function stopResizeDrag() {{
        if (!resizeDrag) return;
        resizeDrag = null;
        map.dragging.enable();
        map.getContainer().style.cursor = "";
      }}

      function stopDesignInteraction() {{
        stopOrientationDrag();
        stopResizeDrag();
        if (buildingDragStart) {{
          buildingDragStart = null;
          map.dragging.enable();
          map.getContainer().style.cursor = "";
        }}
      }}

      function renderOrientationPoints() {{
        if (!designLayer) return;
        if (pointsLayer) designLayer.removeLayer(pointsLayer);
        pointsLayer = L.layerGroup();
        const radius = Math.max(28, Math.min(70, Math.max(state.width_m, state.length_m) * 1.15));
        state.orientation_options.forEach((option) => {{
          const theta = Number(option) * Math.PI / 180;
          const point = latLngFromMeters(Math.sin(theta) * radius, Math.cos(theta) * radius);
          L.circleMarker(point, {{
            radius: 3,
            color: "#475569",
            weight: 1,
            fillColor: "#ffffff",
            fillOpacity: 0.8,
          }})
            .bindTooltip(
              compassLabel(option) + " " + formatDegrees(option) + " deg",
              {{ sticky: true }},
            )
            .on("click", () => {{
              if (orientationDrag || suppressOrientationClick) return;
              state.orientation_deg = Number(option);
              state.user_modified = true;
              state.orientation_modified = true;
              redraw();
              notifyParent();
              state.orientation_modified = false;
            }})
            .addTo(pointsLayer);
        }});
        [
          {{ label: "Front", theta: 0 }},
          {{ label: "Right", theta: 90 }},
          {{ label: "Back", theta: 180 }},
          {{ label: "Left", theta: 270 }},
        ].forEach((face) => {{
          const beta = normalizeOrientation(Number(state.orientation_deg) + face.theta);
          const theta = beta * Math.PI / 180;
          const point = latLngFromMeters(
            Math.sin(theta) * radius,
            Math.cos(theta) * radius,
          );
          const isFront = face.theta === 0;
          const marker = L.circleMarker(point, {{
            radius: isFront ? 6 : 4,
            color: isFront ? "#0f766e" : "#9a3412",
            weight: 2,
            fillColor: isFront ? "#14b8a6" : "#fdba74",
            fillOpacity: 0.95,
          }})
            .bindTooltip(
              (isFront ? "Drag " : "") + face.label
                + " (theta=" + face.theta + " deg), beta="
                + formatDegrees(beta) + " deg clockwise from North",
              {{ sticky: true }},
            )
            .addTo(pointsLayer);
          if (isFront) marker.on("mousedown", startOrientationDrag);
        }});
        pointsLayer.addTo(designLayer);
      }}

      function renderResizeHandles(corners) {{
        if (!designLayer) return;
        if (resizeHandlesLayer) designLayer.removeLayer(resizeHandlesLayer);
        resizeHandlesLayer = L.layerGroup();
        const signs = [[1, 1], [1, -1], [-1, -1], [-1, 1]];
        corners.forEach((corner, index) => {{
          const [lengthSign, widthSign] = signs[index];
          L.circleMarker(corner, {{
            radius: 5,
            color: "#9a3412",
            weight: 2,
            fillColor: "#fff7ed",
            fillOpacity: 1,
          }})
            .bindTooltip("Drag corner to resize", {{ sticky: true }})
            .on("mousedown", (event) => {{
              startResizeDrag(event, lengthSign, widthSign);
            }})
            .addTo(resizeHandlesLayer);
        }});
        resizeHandlesLayer.addTo(designLayer);
      }}

      function redraw() {{
        if (!map || !designLayer || typeof L === "undefined") return;
        const corners = footprintCorners();
        if (!footprint) {{
          footprint = L.polygon(corners, {{
            color: "#ea580c",
            weight: 4,
            dashArray: "10 5",
            fillColor: "#fb923c",
            fillOpacity: 0.22,
          }}).addTo(designLayer);
          enableBuildingDrag(footprint);
        }} else {{
          footprint.setLatLngs(corners);
        }}
        footprint.bindTooltip(
          "Design building " + formatDegrees(state.orientation_deg)
            + " deg - drag footprint to move; drag a corner to resize",
          {{ sticky: true }},
        );

        const bearingDistance = Math.max(state.length_m, 18) * 0.75;
        const line = [centerLatLng(), bearingEndpoint(bearingDistance)];
        if (!bearingLine) {{
          bearingLine = L.polyline(line, {{
            color: "#ea580c",
            weight: 3,
            dashArray: "4 4",
          }}).addTo(designLayer);
        }} else {{
          bearingLine.setLatLngs(line);
        }}
        renderOrientationPoints();
        renderResizeHandles(corners);
      }}

      function nudgeDesignBuilding(eastM, northM) {{
        const east = Number(eastM);
        const north = Number(northM);
        if (!Number.isFinite(east) || !Number.isFinite(north)) return;
        state.offset_east_m += east;
        state.offset_north_m += north;
        state.user_modified = true;
        state.position_modified = true;
        redraw();
        notifyParent();
        state.position_modified = false;
      }}

      function enableBuildingDrag(layer) {{
        layer.on("mousedown", (event) => {{
          L.DomEvent.preventDefault(event.originalEvent);
          L.DomEvent.stopPropagation(event.originalEvent);
          buildingDragStart = {{
            latlng: event.latlng,
            east: state.offset_east_m,
            north: state.offset_north_m,
          }};
          map.dragging.disable();
          map.getContainer().style.cursor = "move";
        }});
        map.on("mousemove", (event) => {{
          if (orientationDrag) {{
            applyOrientationFromLatLng(event.latlng);
            return;
          }}
          if (resizeDrag) {{
            applyResizeFromLatLng(event.latlng);
            return;
          }}
          if (!buildingDragStart) return;
          const delta = metersDelta(buildingDragStart.latlng, event.latlng);
          state.offset_east_m = buildingDragStart.east + delta.eastM;
          state.offset_north_m = buildingDragStart.north + delta.northM;
          state.user_modified = true;
          state.position_modified = true;
          redraw();
          notifyParent();
          state.position_modified = false;
        }});
        map.on("mouseup", stopDesignInteraction);
        window.addEventListener("mouseup", stopDesignInteraction, true);
        window.addEventListener("blur", stopDesignInteraction);
        document.documentElement.addEventListener("mouseleave", stopDesignInteraction);
      }}

      function attachOverlay() {{
        if (typeof L === "undefined" || !window[mapName]) {{
          setTimeout(attachOverlay, 50);
          return;
        }}
        map = window[mapName];
        designLayer = window[designLayerName] || L.layerGroup().addTo(map);

        window.openWindDesignBuilding = {{
          setOrientation(value) {{
            const number = Number(value);
            if (Number.isFinite(number)) {{
              state.orientation_deg = normalizeOrientation(number);
              state.orientation_modified = false;
              redraw();
              notifyParent();
            }}
          }},
          setDimensions(widthM, lengthM) {{
            state.width_m = clampDimension(widthM, 12);
            state.length_m = clampDimension(lengthM, 18);
            state.dimensions_modified = false;
            redraw();
            notifyParent();
          }},
          nudge(eastM, northM) {{
            nudgeDesignBuilding(eastM, northM);
          }},
          endInteraction() {{
            stopDesignInteraction();
          }},
          getState() {{
            return Object.assign({{}}, state);
          }},
        }};

        window.openWindWorkflowMap = {{
          setSite(site) {{
            const latitude = Number(site && site.latitude);
            const longitude = Number(site && site.longitude);
            if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
            state.latitude = latitude;
            state.longitude = longitude;
            state.offset_east_m = 0;
            state.offset_north_m = 0;
            state.user_modified = false;
            state.position_modified = false;
            state.orientation_modified = false;
            state.dimensions_modified = false;
            map.setView([state.latitude, state.longitude], 18);
            redraw();
            notifyParent();
          }},
          invalidate() {{
            map.invalidateSize();
          }},
          getState() {{
            return Object.assign({{}}, state);
          }},
        }};

        window.addEventListener("message", (event) => {{
          if (event.source !== window.parent || event.data?.type !== "openwind-map-command") return;
          const payload = event.data.payload || {{}};
          if (event.data.action === "set-site") {{
            window.openWindWorkflowMap.setSite(payload.site);
          }} else if (event.data.action === "set-dimensions") {{
            window.openWindDesignBuilding.setDimensions(payload.width_m, payload.length_m);
          }} else if (event.data.action === "set-orientation") {{
            window.openWindDesignBuilding.setOrientation(payload.orientation_deg);
          }} else if (event.data.action === "nudge") {{
            window.openWindDesignBuilding.nudge(payload.east_m, payload.north_m);
          }} else if (event.data.action === "end-interaction") {{
            window.openWindDesignBuilding.endInteraction();
          }} else if (event.data.action === "invalidate") {{
            window.openWindWorkflowMap.invalidate();
          }} else if (event.data.action === "capture-screenshot") {{
            window.openWindMapCapture?.request(payload);
          }}
        }});

        redraw();
        notifyParent();
        setTimeout(() => map.invalidateSize(), 100);
        setTimeout(() => map.invalidateSize(), 500);
      }}

      if (document.readyState === "complete") {{
        attachOverlay();
      }} else {{
        window.addEventListener("load", attachOverlay);
      }}
    }})();
    """
    fmap.get_root().script.add_child(folium.Element(script))


def _add_workflow_map_capture_bridge(fmap: folium.Map) -> None:
    """Allow the parent workflow page to request a bounded screenshot of the live map."""

    script = """
    (function() {
      const mapName = "__OPENWIND_MAP_NAME__";
      const maxWidthPx = 1280;
      const maxHeightPx = 800;
      const maxDataUrlCharacters = 2700000;
      let captureQueue = Promise.resolve();

      function nextRenderTick() {
        return new Promise((resolve) => window.setTimeout(resolve, 50));
      }

      function waitForVisibleTiles(container) {
        const pendingTiles = Array.from(container.querySelectorAll("img.leaflet-tile"))
          .filter((tile) => !tile.complete);
        if (!pendingTiles.length) return Promise.resolve();
        return new Promise((resolve) => {
          let remaining = pendingTiles.length;
          let settled = false;
          const finish = () => {
            if (settled) return;
            remaining -= 1;
            if (remaining <= 0) {
              settled = true;
              clearTimeout(timeoutId);
              resolve();
            }
          };
          const timeoutId = setTimeout(() => {
            if (settled) return;
            settled = true;
            resolve();
          }, 2500);
          pendingTiles.forEach((tile) => {
            if (tile.complete) {
              finish();
              return;
            }
            tile.addEventListener("load", finish, { once: true });
            tile.addEventListener("error", finish, { once: true });
          });
        });
      }

      function relativeRect(element, containerBounds, cropTop) {
        const bounds = element.getBoundingClientRect();
        return {
          x: bounds.left - containerBounds.left,
          y: bounds.top - containerBounds.top - cropTop,
          width: bounds.width,
          height: bounds.height,
        };
      }

      function imageFromUrl(url) {
        return new Promise((resolve, reject) => {
          const image = new Image();
          image.onload = () => resolve(image);
          image.onerror = () => reject(new Error("A map overlay could not be rasterised."));
          image.src = url;
        });
      }

      function drawVisibleTiles(context, container, containerBounds, cropTop) {
        let tileCount = 0;
        Array.from(container.querySelectorAll("img.leaflet-tile")).forEach((tile) => {
          if (!tile.complete || !tile.naturalWidth || tile.crossOrigin !== "anonymous") return;
          const rect = relativeRect(tile, containerBounds, cropTop);
          try {
            context.drawImage(tile, rect.x, rect.y, rect.width, rect.height);
            tileCount += 1;
          } catch (_error) {
            // A failed tile is skipped; at least one safe tile is required below.
          }
        });
        if (!tileCount) throw new Error("Map tiles are unavailable for the report screenshot.");
      }

      async function drawSvgOverlays(context, container, containerBounds, cropTop) {
        const serializer = new XMLSerializer();
        for (const svg of container.querySelectorAll(".leaflet-overlay-pane svg")) {
          const rect = relativeRect(svg, containerBounds, cropTop);
          if (rect.width <= 0 || rect.height <= 0) continue;
          const clone = svg.cloneNode(true);
          clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
          const markup = serializer.serializeToString(clone);
          const objectUrl = URL.createObjectURL(
            new Blob([markup], { type: "image/svg+xml;charset=utf-8" })
          );
          try {
            const image = await imageFromUrl(objectUrl);
            context.drawImage(image, rect.x, rect.y, rect.width, rect.height);
          } finally {
            URL.revokeObjectURL(objectUrl);
          }
        }
      }

      function drawMarkerImages(context, container, containerBounds, cropTop) {
        const selectors = [
          ".leaflet-overlay-pane img",
          ".leaflet-shadow-pane img",
          ".leaflet-marker-pane img",
        ];
        Array.from(container.querySelectorAll(selectors.join(","))).forEach((image) => {
          if (!image.complete || !image.naturalWidth) return;
          const source = String(image.currentSrc || image.src || "");
          if (
            !source.startsWith("data:")
            && !source.startsWith("blob:")
            && image.crossOrigin !== "anonymous"
          ) return;
          const rect = relativeRect(image, containerBounds, cropTop);
          try {
            context.drawImage(image, rect.x, rect.y, rect.width, rect.height);
          } catch (_error) {
            // Optional marker images must not invalidate an otherwise complete map.
          }
        });
      }

      function drawPermanentTooltips(context, container, containerBounds, cropTop) {
        Array.from(container.querySelectorAll(".leaflet-tooltip")).forEach((tooltip) => {
          const text = String(tooltip.textContent || "").trim().replace(/\\s+/g, " ");
          if (!text) return;
          const rect = relativeRect(tooltip, containerBounds, cropTop);
          if (rect.width <= 0 || rect.height <= 0) return;
          const style = window.getComputedStyle(tooltip);
          context.save();
          context.globalAlpha = Number.parseFloat(style.opacity) || 1;
          context.fillStyle = style.backgroundColor || "rgba(255,255,255,0.92)";
          context.fillRect(rect.x, rect.y, rect.width, rect.height);
          context.strokeStyle = style.borderColor || "#17324d";
          context.lineWidth = Number.parseFloat(style.borderWidth) || 1;
          context.strokeRect(rect.x, rect.y, rect.width, rect.height);
          context.fillStyle = style.color || "#17324d";
          context.font = style.font || "600 12px Arial";
          context.textAlign = "center";
          context.textBaseline = "middle";
          context.fillText(text, rect.x + rect.width / 2, rect.y + rect.height / 2);
          context.restore();
        });
      }

      function drawMapCredits(context, container, width, height) {
        const attribution = String(
          container.querySelector(".leaflet-control-attribution")?.textContent || ""
        ).trim().replace(/\\s+/g, " ");
        if (attribution) {
          context.save();
          context.font = "11px Arial";
          const textWidth = context.measureText(attribution).width;
          const boxWidth = Math.min(width - 12, textWidth + 10);
          context.fillStyle = "rgba(255,255,255,0.88)";
          context.fillRect(width - boxWidth - 4, height - 21, boxWidth, 17);
          context.fillStyle = "#333333";
          context.textAlign = "right";
          context.textBaseline = "middle";
          context.fillText(attribution, width - 9, height - 12, boxWidth - 8);
          context.restore();
        }
        const scaleText = String(
          container.querySelector(".leaflet-control-scale-line")?.textContent || ""
        ).trim();
        if (scaleText) {
          context.save();
          context.font = "11px Arial";
          const boxWidth = Math.max(48, context.measureText(scaleText).width + 14);
          context.fillStyle = "rgba(255,255,255,0.82)";
          context.fillRect(5, height - 23, boxWidth, 17);
          context.strokeStyle = "#555555";
          context.lineWidth = 1;
          context.beginPath();
          context.moveTo(5, height - 23);
          context.lineTo(5, height - 6);
          context.lineTo(5 + boxWidth, height - 6);
          context.lineTo(5 + boxWidth, height - 23);
          context.stroke();
          context.fillStyle = "#222222";
          context.textAlign = "center";
          context.textBaseline = "middle";
          context.fillText(scaleText, 5 + boxWidth / 2, height - 15);
          context.restore();
        }
      }

      async function captureMap() {
        const map = window[mapName];
        if (!map || !window.L) throw new Error("Interactive map is not ready.");
        const container = map.getContainer();
        map.invalidateSize();
        container.getBoundingClientRect();
        await nextRenderTick();
        await waitForVisibleTiles(container);
        await nextRenderTick();

        const bounds = container.getBoundingClientRect();
        const width = Math.round(bounds.width);
        const height = Math.round(bounds.height);
        if (width < 64 || height < 64) {
          throw new Error("Interactive map is not visible.");
        }
        const captureHeight = Math.min(height, Math.round(width * 9 / 16));
        const cropTop = Math.max(0, Math.round((height - captureHeight) / 2));
        const scale = Math.min(2, maxWidthPx / width, maxHeightPx / captureHeight);
        if (!Number.isFinite(scale) || scale <= 0) {
          throw new Error("Interactive map has invalid dimensions.");
        }
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(64, Math.floor(width * scale));
        canvas.height = Math.max(64, Math.floor(captureHeight * scale));
        const context = canvas.getContext("2d", { alpha: false });
        if (!context) throw new Error("Map screenshot canvas is unavailable.");
        context.scale(scale, scale);
        context.fillStyle = "#e5e7eb";
        context.fillRect(0, 0, width, captureHeight);
        drawVisibleTiles(context, container, bounds, cropTop);
        await drawSvgOverlays(context, container, bounds, cropTop);
        drawMarkerImages(context, container, bounds, cropTop);
        drawPermanentTooltips(context, container, bounds, cropTop);
        drawMapCredits(context, container, width, captureHeight);
        if (
          canvas.width < 64
          || canvas.height < 64
          || canvas.width > maxWidthPx
          || canvas.height > maxHeightPx
        ) {
          throw new Error("Captured map dimensions are outside the report limits.");
        }
        let dataUrl = canvas.toDataURL("image/jpeg", 0.88);
        if (dataUrl.length > maxDataUrlCharacters) {
          dataUrl = canvas.toDataURL("image/jpeg", 0.76);
        }
        if (dataUrl.length > maxDataUrlCharacters) {
          dataUrl = canvas.toDataURL("image/jpeg", 0.65);
        }
        if (dataUrl.length > maxDataUrlCharacters) {
          throw new Error("Captured map is too large for the report.");
        }
        return {
          data_url: dataUrl,
          width_px: canvas.width,
          height_px: canvas.height,
        };
      }

      function respond(payload, response) {
        window.parent.postMessage(Object.assign({
          type: "openwind-map-screenshot",
          request_id: payload.request_id,
          result_integrity_token: payload.result_integrity_token,
        }, response), "*");
      }

      function requestCapture(payload) {
        if (
          typeof payload.request_id !== "string"
          || !payload.request_id
          || typeof payload.result_integrity_token !== "string"
          || !payload.result_integrity_token
        ) return;
        captureQueue = captureQueue
          .catch(() => undefined)
          .then(captureMap)
          .then((capture) => respond(payload, capture))
          .catch((error) => {
            respond(payload, {
              error: String(error && error.message ? error.message : error),
            });
          });
      }

      window.openWindMapCapture = {
        capture: captureMap,
        request: requestCapture,
      };
    })();
    """.replace("__OPENWIND_MAP_NAME__", fmap.get_name())
    fmap.get_root().script.add_child(folium.Element(script))


def _add_workflow_shielding_polygon_layer(
    fmap: folium.Map,
    layer: folium.FeatureGroup,
    result: ObstructionInventoryResult,
    diagnostics: MapRenderDiagnostics,
) -> MapRenderDiagnostics:
    """Add polygons reviewed by shielding-sector evidence."""

    included_ids = {
        obstruction_id
        for sector in result.shielding_sectors
        for obstruction_id in sector.included_obstruction_ids
    }
    subject_height_m = result.input.building_height_m
    shielding_radius_m = 20.0 * subject_height_m if subject_height_m is not None else None

    max_display = max(
        int(getattr(result.input, "map_max_display_obstructions", DEFAULT_MAP_DISPLAY_LIMIT)),
        1,
    )
    records = sorted(
        (
            record
            for record in result.obstructions
            if record.obstruction_id in included_ids
            or (shielding_radius_m is not None and record.distance_m <= shielding_radius_m)
        ),
        key=lambda record: map_relevance_sort_key(record, result.input.building_height_m),
    )
    if not records:
        diagnostics.warnings.append("No shielding obstruction polygons qualified for map display.")
        return diagnostics

    features = []
    payload_size = 0
    for record in records:
        if len(features) >= max_display:
            break
        display_geometry = display_geometry_for_map(
            record.footprint_geometry,
            result.site,
            result.input.radius_m,
            diagnostics,
        )
        if display_geometry is None:
            continue
        feature = obstruction_display_feature(record, display_geometry, "shielding")
        feature["properties"]["status"] = shielding_obstruction_display_status(
            record,
            included_ids,
            subject_height_m,
        )
        feature_size = len(json.dumps(feature, separators=(",", ":")))
        if payload_size + feature_size > MAX_POLYGON_GEOJSON_PAYLOAD_BYTES:
            diagnostics.fallback_mode = True
            diagnostics.warnings.append(
                "Shielding obstruction polygon display stopped at the map payload budget."
            )
            break
        features.append(feature)
        payload_size += feature_size
        diagnostics.largest_polygon_vertex_count = max(
            diagnostics.largest_polygon_vertex_count,
            geometry_vertex_count(display_geometry),
        )

    diagnostics.total_geojson_payload_size += payload_size

    if len(records) > len(features):
        diagnostics.warnings.append(
            "Shielding polygon display limited to "
            f"{len(features)} of {len(records)} candidate obstructions."
        )
    if not features:
        diagnostics.warnings.append("Shielding obstruction polygons could not be rendered.")
        return diagnostics

    _add_explicit_shielding_footprint_loader(fmap, layer, features)
    diagnostics.plotted_polygons += len(features)
    diagnostics.plotted_shielding_polygons += len(features)
    return diagnostics


def shielding_obstruction_display_status(
    record: ObstructionRecord,
    included_ids: set[str],
    subject_height_m: float | None,
) -> str:
    """Return display status for a shielding obstruction polygon."""

    if record.obstruction_id in included_ids:
        return "included"
    height = record.selected_height_m if record.selected_height_m is not None else record.height_m
    if height is None:
        return "height_missing"
    if subject_height_m is not None and height < subject_height_m:
        return "height_below_subject"
    return "candidate"


def _add_explicit_shielding_footprint_loader(
    fmap: folium.Map,
    layer: folium.FeatureGroup,
    features: list[dict[str, Any]],
) -> None:
    """Inject a direct Leaflet shielding footprint loader for iframe map reliability."""

    feature_collection = {"type": "FeatureCollection", "features": features}
    feature_collection_json = _json_for_inline_script(feature_collection)
    map_name = fmap.get_name()
    layer_name = layer.get_name()
    script = f"""
    (function() {{
      const shieldingFootprints = {feature_collection_json};
      const shieldingLayer = {layer_name};
      const shieldingGeoJson = L.geoJson(shieldingFootprints, {{
        interactive: true,
        style: function(feature) {{
          const status = (feature.properties || {{}}).status || "candidate";
          if (status === "included") {{
            return {{
              color: "#047857",
              weight: 3,
              opacity: 1,
              fillColor: "#10b981",
              fillOpacity: 0.45
            }};
          }}
          if (status === "height_below_subject") {{
            return {{
              color: "#b45309",
              weight: 2,
              opacity: 0.95,
              fillColor: "#fbbf24",
              fillOpacity: 0.34
            }};
          }}
          if (status === "height_missing") {{
            return {{
              color: "#b42318",
              weight: 2,
              opacity: 0.95,
              fillColor: "#fca5a5",
              fillOpacity: 0.34
            }};
          }}
          return {{
            color: "#0f766e",
            weight: 2,
            opacity: 0.95,
            fillColor: "#99f6e4",
            fillOpacity: 0.34
          }};
        }},
        onEachFeature: function(feature, leafletLayer) {{
          const props = feature.properties || {{}};
          leafletLayer.bindTooltip(
            `<table>
              <tr><th>ID</th><td>${{props.id || ""}}</td></tr>
              <tr><th>Status</th><td>${{props.status || "candidate"}}</td></tr>
              <tr><th>Height</th><td>${{props.height || "missing"}}</td></tr>
              <tr><th>Source</th><td>${{props.source || ""}}</td></tr>
              <tr><th>Confidence</th><td>${{props.confidence || ""}}</td></tr>
            </table>`,
            {{sticky: false, className: "foliumtooltip"}}
          );
        }}
      }});
      shieldingGeoJson.addTo(shieldingLayer);
      shieldingLayer.addTo({map_name});
      shieldingGeoJson.bringToFront();
      shieldingLayer.on("add", function() {{
        shieldingGeoJson.bringToFront();
      }});
      window.openWindShieldingFootprintLayer = {{
        feature_count: shieldingFootprints.features.length,
        layer_name: "Shielding obstruction polygons",
        renderer: "explicit_leaflet_geojson"
      }};
      console.info(
        "OpenWind-AU shielding footprint layer",
        window.openWindShieldingFootprintLayer
      );
    }})();
    """
    script = _defer_leaflet_overlay_script(
        script,
        "openWindAttachShieldingFootprints",
        map_name,
        layer_name,
    )
    fmap.get_root().script.add_child(folium.Element(script))


def _add_obstruction_centroid_layer(
    fmap: folium.Map,
    layer: folium.FeatureGroup,
    result: ObstructionInventoryResult,
) -> MapRenderDiagnostics:
    """Add selected nearby obstruction footprints and centroid labels for workflow maps."""

    diagnostics = MapRenderDiagnostics(
        display_mode="nearby_footprints",
        max_displayed_obstructions=min(DEFAULT_MAP_DISPLAY_LIMIT, len(result.obstructions)),
        total_obstructions=len(result.obstructions),
    )
    selected = sorted(result.obstructions, key=lambda record: record.distance_m)[
        : diagnostics.max_displayed_obstructions
    ]
    diagnostics.selected_obstructions = len(selected)
    if diagnostics.selected_obstructions < diagnostics.total_obstructions:
        diagnostics.warnings.append(
            "Map display limited to "
            f"{diagnostics.selected_obstructions} of {diagnostics.total_obstructions} "
            "obstructions. Calculations used full dataset."
        )
    _add_nearby_obstruction_footprint_layer(fmap, layer, selected, result, diagnostics)
    _add_obstruction_centroid_collection(layer, selected, diagnostics)
    _add_map_diagnostics_banner(fmap, diagnostics)
    return diagnostics


def _add_nearby_obstruction_footprint_layer(
    fmap: folium.Map,
    layer: folium.FeatureGroup,
    selected: list[ObstructionRecord],
    result: ObstructionInventoryResult,
    diagnostics: MapRenderDiagnostics,
) -> None:
    """Inject selected nearby obstruction footprint polygons into the workflow map."""

    features = []
    payload_size = 0
    for record in selected:
        display_geometry = display_geometry_for_map(
            record.footprint_geometry,
            result.site,
            result.input.radius_m,
            diagnostics,
        )
        if display_geometry is None:
            continue
        feature = obstruction_display_feature(record, display_geometry, "nearby_obstruction")
        feature_size = len(json.dumps(feature, separators=(",", ":")))
        if payload_size + feature_size > MAX_POLYGON_GEOJSON_PAYLOAD_BYTES:
            diagnostics.fallback_mode = True
            diagnostics.warnings.append(
                "Nearby obstruction footprint display stopped at the map payload budget."
            )
            break
        features.append(feature)
        payload_size += feature_size
        diagnostics.largest_polygon_vertex_count = max(
            diagnostics.largest_polygon_vertex_count,
            geometry_vertex_count(display_geometry),
        )

    diagnostics.total_geojson_payload_size += payload_size
    if not features:
        diagnostics.fallback_mode = True
        diagnostics.warnings.append("Nearby obstruction footprints could not be rendered.")
        return

    feature_collection = {"type": "FeatureCollection", "features": features}
    feature_collection_json = _json_for_inline_script(feature_collection)
    map_name = fmap.get_name()
    layer_name = layer.get_name()
    script = f"""
    (function() {{
      const nearbyFootprints = {feature_collection_json};
      const nearbyLayer = {layer_name};
      const nearbyGeoJson = L.geoJson(nearbyFootprints, {{
        interactive: true,
        style: function(feature) {{
          const source = (feature.properties || {{}}).source || "";
          if (source === "microsoft_building_footprints") {{
            return {{
              color: "#7c3aed",
              weight: 3,
              opacity: 1,
              dashArray: "6 3",
              fillColor: "#8b5cf6",
              fillOpacity: 0.48
            }};
          }}
          return {{
            color: "#334155",
            weight: 3,
            opacity: 1,
            dashArray: "6 3",
            fillColor: "#64748b",
            fillOpacity: 0.44
          }};
        }},
        onEachFeature: function(feature, leafletLayer) {{
          const props = feature.properties || {{}};
          leafletLayer.bindTooltip(
            `<table>
              <tr><th>ID</th><td>${{props.id || ""}}</td></tr>
              <tr><th>Source</th><td>${{props.source || ""}}</td></tr>
              <tr><th>Height</th><td>${{props.height || "missing"}}</td></tr>
              <tr><th>Class</th><td>${{props.classification || ""}}</td></tr>
              <tr><th>Confidence</th><td>${{props.confidence || ""}}</td></tr>
            </table>`,
            {{sticky: false, className: "foliumtooltip"}}
          );
        }}
      }});
      nearbyGeoJson.addTo(nearbyLayer);
      nearbyLayer.addTo({map_name});
      nearbyGeoJson.bringToFront();
      nearbyLayer.on("add", function() {{
        nearbyGeoJson.bringToFront();
      }});
      window.openWindNearbyObstructionFootprintLayer = {{
        feature_count: nearbyFootprints.features.length,
        layer_name: "Nearby obstructions (selected)",
        renderer: "explicit_leaflet_geojson"
      }};
      console.info(
        "OpenWind-AU nearby obstruction footprint layer",
        window.openWindNearbyObstructionFootprintLayer
      );
    }})();
    """
    script = _defer_leaflet_overlay_script(
        script,
        "openWindAttachNearbyFootprints",
        map_name,
        layer_name,
    )
    fmap.get_root().script.add_child(folium.Element(script))


def _add_wind_region_layer(
    layer: folium.FeatureGroup,
    site: SiteLocation,
    assessment: WindRegionAssessment,
) -> None:
    if assessment.region_polygon:
        folium.GeoJson(
            display_region_geometry(assessment.region_polygon),
            style_function=lambda _feature: {
                "color": "#155eef",
                "weight": 3,
                "fillColor": "#84adff",
                "fillOpacity": 0.14,
            },
            tooltip=f"Selected wind region {assessment.wind_region}",
        ).add_to(layer)
    if assessment.near_boundary and assessment.distance_to_boundary_m is not None:
        folium.Circle(
            location=[site.latitude, site.longitude],
            radius=assessment.distance_to_boundary_m,
            color="#b54708",
            weight=2,
            fill=False,
            tooltip="Approximate distance to wind-region boundary",
        ).add_to(layer)


def display_region_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    """Simplify wind-region geometry for map display only."""

    return mapping(shape(geometry).simplify(0.02, preserve_topology=True))


def render_obstruction_report_html(result: ObstructionInventoryResult) -> str:
    """Render an HTML obstruction inventory report."""

    return OBSTRUCTION_REPORT_TEMPLATE.render(
        result=result,
        calculation_basis_reference=calculation_basis_report_reference(),
    )


def render_terrain_category_report_html(result: TerrainCategoryEvidenceResult) -> str:
    """Render an HTML terrain category evidence report."""

    return TERRAIN_CATEGORY_REPORT_TEMPLATE.render(
        result=result,
        calculation_basis_reference=calculation_basis_report_reference(),
    )


WIND_WORKFLOW_REPORT_SUBTITLE = (
    "Site wind inputs and calculated cardinal Vsit,b and building-orthogonal Vdes,theta."
)
WIND_WORKFLOW_REPORT_SCOPE = (
    "This report contains site wind inputs and calculated wind speeds through Vsit,b and "
    "Vdes,theta. Final design pressures, pressure coefficients and cladding pressures are "
    "outside its scope. Terrain, shielding and topographic inputs require competent "
    "engineering review."
)


def render_wind_workflow_report_html(result: WindWorkflowResult) -> str:
    """Render a concise HTML AS/NZS 1170.2 site wind workflow report."""

    return CONCISE_WIND_WORKFLOW_REPORT_TEMPLATE.render(
        result=result,
        class_override_summaries=[
            _wind_class_override_summary(override)
            for override in result.input.class_multiplier_overrides
        ],
        report_warnings=concise_workflow_warnings(result),
        basis_summary=_wind_report_basis(result),
        building_summary=_wind_report_building_summary(result),
        md_case_summary=_wind_report_md_case(result),
        vr_value=_wind_report_variable_value(result, "VR"),
        vr_is_overridden=_wind_report_variable_is_overridden(result, "VR"),
        mc_value=_wind_report_variable_value(result, "Mc"),
        has_vsitb_overrides=_wind_report_has_vsitb_overrides(result),
        vsitb_override_directions=_wind_report_vsitb_override_directions(result),
        calculation_basis_reference=calculation_basis_report_reference(),
        report_subtitle=WIND_WORKFLOW_REPORT_SUBTITLE,
        report_scope=WIND_WORKFLOW_REPORT_SCOPE,
    )


def concise_workflow_warnings(result: WindWorkflowResult, limit: int = 6) -> list[str]:
    """Return unique, decision-relevant warnings without report boilerplate."""

    omitted_prefixes = (
        "Workflow values are calculated automatically",
        "Pressure calculations are not included",
        "VR values are table lookups for engineering review",
        "Md values are automatically selected",
        "Indicative Ms is preliminary",
        "Selection rule:",
        "Terrain category not confirmed",
        "Mz,cat values are indicative only",
        "Engineer review required",
    )
    candidates = [
        *result.warnings,
        *(warning for variable in result.variables for warning in variable.warnings),
        *(warning for row in result.directional_vsitb for warning in row.warnings),
    ]
    warnings: list[str] = []
    seen: set[str] = set()
    for warning in candidates:
        cleaned = " ".join(str(warning).split())
        if not cleaned or cleaned.startswith(omitted_prefixes) or cleaned in seen:
            continue
        seen.add(cleaned)
        warnings.append(cleaned)
    warnings.sort(key=_workflow_warning_priority)
    if len(warnings) <= limit:
        return warnings
    return [
        *warnings[:limit],
        f"{len(warnings) - limit} additional warning(s) remain in the workflow diagnostics.",
    ]


def _workflow_warning_priority(warning: str) -> int:
    """Keep applicable normative limitations visible in compact issued reports."""

    normalized = warning.lower()
    if "coastal vr interpolation" in normalized or "smoothed coastline" in normalized:
        return 0
    if "clause 4.2.3 mixed-terrain" in normalized:
        return 1
    if "clause 4.4.2 most-adverse" in normalized:
        return 2
    return 3


def render_wind_workflow_pdf_report(
    result: WindWorkflowResult,
    *,
    map_screenshot: bytes | str | None = None,
) -> bytes:
    """Render a compact site wind assessment PDF in memory.

    ``map_screenshot`` may be raw PNG/JPEG bytes or a strict ``data:image/...;base64,``
    URI. It is optional so existing report callers remain compatible.
    """

    validated_map_screenshot = _validate_wind_pdf_map_screenshot(map_screenshot)
    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title="OpenWind-AU Site Wind Assessment",
        author="OpenWind-AU",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "WindReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=20,
        textColor=colors.HexColor("#17324d"),
        spaceAfter=3 * mm,
    )
    section_style = ParagraphStyle(
        "WindReportSection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=13,
        textColor=colors.HexColor("#17324d"),
        spaceBefore=3 * mm,
        spaceAfter=1.5 * mm,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "WindReportBody",
        parent=styles["BodyText"],
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#344054"),
        spaceAfter=1 * mm,
    )
    muted_style = ParagraphStyle(
        "WindReportMuted",
        parent=body_style,
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#667085"),
    )
    compact_body_style = ParagraphStyle(
        "WindReportCompactBody",
        parent=body_style,
        spaceAfter=0.5 * mm,
    )
    subheading_style = ParagraphStyle(
        "WindReportSubheading",
        parent=body_style,
        fontName="Helvetica-Bold",
        keepWithNext=True,
    )
    lineage_style = ParagraphStyle(
        "WindReportLineage",
        parent=muted_style,
        fontSize=7,
        leading=8.5,
        spaceAfter=0,
    )
    story = [
        Paragraph("OpenWind-AU Site Wind Assessment", title_style),
        Paragraph(WIND_WORKFLOW_REPORT_SUBTITLE, muted_style),
        Paragraph("Project and outcome", section_style),
    ]
    region = result.wind_region_assessment
    vr_value = _wind_report_variable_value(result, "VR")
    vr_is_overridden = _wind_report_variable_is_overridden(result, "VR")
    mc_value = _wind_report_variable_value(result, "Mc")
    vsitb_override_directions = _wind_report_vsitb_override_directions(result)
    has_vsitb_overrides = bool(vsitb_override_directions)
    site_label = (
        result.input.address
        or result.input.site_label
        or result.site.display_name
        or "Not supplied"
    )
    summary_rows = [
        ["Project", result.input.project_number or "Not supplied"],
        ["Assessment status", _wind_report_status(result)],
        ["Site", site_label],
        [
            "Coordinates",
            f"{result.site.latitude:+.6f}, {result.site.longitude:+.6f} "
            f"(RL {result.site.ground_elevation_m:.2f} m)",
        ],
        ["Building", _wind_report_building_summary(result)],
        ["Md design case", _wind_report_md_case(result)],
        ["Wind region", region.wind_region if region else "Not available"],
        ["AEP / ARI", result.input.annual_exceedance_probability],
        [
            "VR,ult (effective)" if vr_is_overridden else "VR,ult",
            (
                f"{vr_value:.1f} m/s{' (reviewed override)' if vr_is_overridden else ''}"
                if vr_value is not None
                else "Not available"
            ),
        ],
        ["Mc", _report_number(mc_value)],
        ["Governing Vsit,b", _wind_report_governing_summary(result)],
    ]
    if result.governing_vdes_mps is not None:
        summary_rows.append(["Governing Vdes,theta", _wind_report_vdes_summary(result)])
    story.append(_wind_pdf_table(summary_rows, [38 * mm, 140 * mm], header=False))
    if validated_map_screenshot is not None:
        story.append(
            KeepTogether(
                [
                    Paragraph("Site map", section_style),
                    _wind_pdf_map_screenshot_flowable(validated_map_screenshot),
                    Paragraph(
                        "Browser-captured map centred on the signed workflow location "
                        f"{result.site.latitude:+.6f}, {result.site.longitude:+.6f}. "
                        "Map imagery and displayed layers are contextual; the numerical "
                        "coordinates and report inputs govern.",
                        muted_style,
                    ),
                ]
            )
        )
    story.extend(
        [
            Paragraph("Directional site wind speeds", section_style),
            Paragraph("Vsit,b = VR x Mc x Md x Mz,cat x Ms x Mt", muted_style),
        ]
    )
    direction_rows = [
        (
            ["Dir.", "Md", "Mz,cat", "Ms", "Mt", "Calc. Vsit,b", "Final Vsit,b"]
            if has_vsitb_overrides
            else ["Dir.", "Md", "Mz,cat", "Ms", "Mt", "Vsit,b"]
        )
    ]
    for row in result.directional_vsitb:
        rendered_row = [
            f"{row.direction}{' *' if row.is_governing else ''}",
            _report_number(row.md),
            _report_number(row.mzcat),
            _report_number(row.ms),
            _report_number(row.mt),
        ]
        if has_vsitb_overrides:
            rendered_row.extend(
                [
                    (
                        f"{row.recommended_vsitb:.3f} m/s"
                        if row.recommended_vsitb is not None
                        else "N/A"
                    ),
                    (
                        f"{row.final_vsitb:.3f} m/s"
                        f"{' (override)' if row.direction in vsitb_override_directions else ''}"
                        if row.final_vsitb is not None
                        else "N/A"
                    ),
                ]
            )
        else:
            rendered_row.append(
                f"{row.final_vsitb:.3f} m/s" if row.final_vsitb is not None else "N/A"
            )
        direction_rows.append(rendered_row)
    story.append(
        _wind_pdf_table(
            direction_rows,
            (
                [14 * mm, 20 * mm, 25 * mm, 19 * mm, 19 * mm, 39 * mm, 42 * mm]
                if has_vsitb_overrides
                else [18 * mm, 25 * mm, 33 * mm, 25 * mm, 25 * mm, 52 * mm]
            ),
            header=True,
            governing_rows={
                index + 1 for index, row in enumerate(result.directional_vsitb) if row.is_governing
            },
        )
    )
    if result.design_wind_speeds:
        story.extend(
            [
                Paragraph("Building-orthogonal design wind speeds", section_style),
                Paragraph(
                    "Clause 2.3: maximum linearly interpolated Vsit,b within beta = "
                    "theta +/-45 degrees; ultimate Vdes,theta is not less than 30 m/s.",
                    muted_style,
                ),
            ]
        )
        design_rows = [["Face", "theta", "Face beta", "Beta sector", "Raw maximum", "Vdes,theta"]]
        design_rows.extend(
            [
                f"{row.face}{' *' if row.is_governing else ''}",
                f"{row.theta_deg:.1f} deg",
                f"{row.beta_deg:.1f} deg",
                (f"{row.sector_start_beta_deg:.1f} to {row.sector_end_beta_deg:.1f} deg"),
                f"{row.raw_vdes_theta_mps:.3f} m/s",
                (
                    f"{row.vdes_theta_mps:.3f} m/s"
                    f"{' (30 m/s min.)' if row.minimum_uls_applied else ''}"
                ),
            ]
            for row in result.design_wind_speeds
        )
        story.append(
            _wind_pdf_table(
                design_rows,
                [25 * mm, 22 * mm, 26 * mm, 39 * mm, 31 * mm, 35 * mm],
                header=True,
                governing_rows={
                    index + 1
                    for index, row in enumerate(result.design_wind_speeds)
                    if row.is_governing
                },
            )
        )
    # Keep the issued PDF to a compact engineering-review summary. The HTML
    # report and workflow diagnostics retain the broader warning set.
    warnings = concise_workflow_warnings(result, limit=3)
    if (
        warnings
        or result.input.workflow_overrides
        or result.input.class_multiplier_overrides
        or result.input.engineer_notes
    ):
        story.append(Paragraph("Review items", section_style))
    if warnings:
        story.append(Paragraph("Warnings", subheading_style))
        story.extend(
            Paragraph(f"- {escape(str(warning))}", compact_body_style) for warning in warnings
        )
    if result.input.workflow_overrides or result.input.class_multiplier_overrides:
        story.append(Paragraph("Edited values", subheading_style))
        override_rows = [["Variable", "Direction", "Value", "Reason"]]
        override_rows.extend(
            [
                override.variable,
                override.direction or "All",
                f"{override.override_value:.3f}",
                override.reason,
            ]
            for override in result.input.workflow_overrides
        )
        override_rows.extend(
            [
                "Reviewed classes",
                override.direction,
                _wind_class_override_summary(override),
                override.reason,
            ]
            for override in result.input.class_multiplier_overrides
        )
        story.append(
            _wind_pdf_table(
                override_rows,
                [30 * mm, 26 * mm, 25 * mm, 97 * mm],
                header=True,
            )
        )
    if result.input.engineer_notes:
        story.append(
            Paragraph(f"Engineer notes: {escape(result.input.engineer_notes)}", body_style)
        )
    story.extend(
        [
            Paragraph("Basis and limitations", section_style),
            Paragraph(escape(_wind_report_basis(result)), body_style),
            Paragraph(escape(WIND_WORKFLOW_REPORT_SCOPE), body_style),
        ]
    )
    story.append(Paragraph(_wind_pdf_lineage_reference(), lineage_style))
    doc.build(story, onFirstPage=_draw_wind_pdf_page, onLaterPages=_draw_wind_pdf_page)
    return output.getvalue()


def _validate_wind_pdf_map_screenshot(
    value: bytes | str | None,
) -> _ValidatedWindMapScreenshot | None:
    """Validate an in-memory browser map screenshot without accepting paths or URLs."""

    if value is None:
        return None

    declared_media_type: str | None = None
    if isinstance(value, bytes):
        data = value
    elif isinstance(value, str):
        prefixes = {
            "data:image/png;base64,": "image/png",
            "data:image/jpeg;base64,": "image/jpeg",
        }
        matched_prefix = next((prefix for prefix in prefixes if value.startswith(prefix)), None)
        if matched_prefix is None:
            raise ValueError(
                "Map screenshot data URI must use image/png or image/jpeg with base64 encoding."
            )
        declared_media_type = prefixes[matched_prefix]
        encoded = value[len(matched_prefix) :]
        maximum_encoded_length = ((MAX_WIND_PDF_MAP_SCREENSHOT_BYTES + 2) // 3) * 4
        if not encoded or len(encoded) > maximum_encoded_length:
            raise ValueError(
                f"Map screenshot must be non-empty and no larger than "
                f"{MAX_WIND_PDF_MAP_SCREENSHOT_BYTES // 1_000_000} MB."
            )
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Map screenshot data URI contains invalid base64 content.") from exc
    else:
        raise ValueError("Map screenshot must be PNG/JPEG bytes, a base64 data URI, or None.")

    if not data:
        raise ValueError("Map screenshot must not be empty.")
    if len(data) > MAX_WIND_PDF_MAP_SCREENSHOT_BYTES:
        raise ValueError(
            f"Map screenshot exceeds the {MAX_WIND_PDF_MAP_SCREENSHOT_BYTES // 1_000_000} MB limit."
        )

    media_type, header_width, header_height = _wind_pdf_map_screenshot_header(data)
    if declared_media_type is not None and declared_media_type != media_type:
        raise ValueError("Map screenshot content does not match its declared MIME type.")

    width_px = header_width
    height_px = header_height
    _validate_wind_pdf_map_screenshot_dimensions(width_px, height_px)
    try:
        reader = ImageReader(BytesIO(data))
        decoded_width, decoded_height = (int(value) for value in reader.getSize())
        if (decoded_width, decoded_height) != (width_px, height_px):
            raise ValueError("Map screenshot dimensions are internally inconsistent.")
        reader.getRGBData()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Map screenshot could not be decoded as a complete image.") from exc

    return _ValidatedWindMapScreenshot(
        data=data,
        media_type=media_type,
        width_px=width_px,
        height_px=height_px,
    )


def _wind_pdf_map_screenshot_header(data: bytes) -> tuple[str, int, int]:
    """Return strict PNG/JPEG media type and dimensions from trusted header structures."""

    png_signature = b"\x89PNG\r\n\x1a\n"
    if data.startswith(png_signature):
        if (
            len(data) < 45
            or data[8:12] != b"\x00\x00\x00\r"
            or data[12:16] != b"IHDR"
            or data[-12:-8] != b"\x00\x00\x00\x00"
            or data[-8:-4] != b"IEND"
        ):
            raise ValueError("Map screenshot is not a complete PNG image.")
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return "image/png", width, height

    if data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        width, height = _wind_pdf_jpeg_dimensions(data)
        return "image/jpeg", width, height

    raise ValueError("Map screenshot must contain a complete PNG or JPEG image.")


def _wind_pdf_jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Read JPEG SOF dimensions while rejecting truncated segment structures."""

    start_of_frame_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    offset = 2
    while offset < len(data) - 1:
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0x01, 0xD8, 0xD9, *range(0xD0, 0xD8)}:
            continue
        if offset + 2 > len(data):
            break
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(data):
            break
        if marker in start_of_frame_markers:
            if segment_length < 7:
                break
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            return width, height
        if marker == 0xDA:
            break
        offset += segment_length
    raise ValueError("Map screenshot JPEG is missing a valid size header.")


def _validate_wind_pdf_map_screenshot_dimensions(width_px: int, height_px: int) -> None:
    if (
        width_px < MIN_WIND_PDF_MAP_SCREENSHOT_DIMENSION_PX
        or height_px < MIN_WIND_PDF_MAP_SCREENSHOT_DIMENSION_PX
    ):
        raise ValueError(
            "Map screenshot dimensions must each be at least "
            f"{MIN_WIND_PDF_MAP_SCREENSHOT_DIMENSION_PX} px."
        )
    if (
        width_px > MAX_WIND_PDF_MAP_SCREENSHOT_DIMENSION_PX
        or height_px > MAX_WIND_PDF_MAP_SCREENSHOT_DIMENSION_PX
        or width_px * height_px > MAX_WIND_PDF_MAP_SCREENSHOT_PIXELS
    ):
        raise ValueError(
            "Map screenshot exceeds the "
            f"{MAX_WIND_PDF_MAP_SCREENSHOT_DIMENSION_PX} px per side or "
            f"{MAX_WIND_PDF_MAP_SCREENSHOT_PIXELS / 1_000_000:g} megapixel limit."
        )
    aspect_ratio = max(width_px / height_px, height_px / width_px)
    if aspect_ratio > MAX_WIND_PDF_MAP_SCREENSHOT_ASPECT_RATIO:
        raise ValueError(
            f"Map screenshot aspect ratio must not exceed "
            f"{MAX_WIND_PDF_MAP_SCREENSHOT_ASPECT_RATIO:g}:1."
        )


def _wind_pdf_map_screenshot_flowable(screenshot: _ValidatedWindMapScreenshot) -> Table:
    """Fit a validated screenshot into a bordered, full-width report frame."""

    frame_width = 178 * mm
    horizontal_padding = 2 * mm
    vertical_padding = 2 * mm
    maximum_image_width = frame_width - 2 * horizontal_padding
    maximum_image_height = 85 * mm
    scale = min(
        maximum_image_width / screenshot.width_px,
        maximum_image_height / screenshot.height_px,
    )
    rendered_width = screenshot.width_px * scale
    rendered_height = screenshot.height_px * scale
    image = Image(
        BytesIO(screenshot.data),
        width=rendered_width,
        height=rendered_height,
    )
    image.hAlign = "CENTER"
    frame = Table([[image]], colWidths=[frame_width], hAlign="LEFT")
    frame.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), horizontal_padding),
                ("RIGHTPADDING", (0, 0), (-1, -1), horizontal_padding),
                ("TOPPADDING", (0, 0), (-1, -1), vertical_padding),
                ("BOTTOMPADDING", (0, 0), (-1, -1), vertical_padding),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d0d5dd")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ]
        )
    )
    return frame


def _wind_pdf_site_map(result: WindWorkflowResult) -> Drawing:
    """Return a deterministic, offline site-plan map for the issued PDF.

    Completed workflow results intentionally contain no interactive Leaflet document,
    external map tiles, or server-only GIS geometry. This scaled vector view therefore
    records the signed report context that can be reproduced offline: site coordinates,
    wind region, cardinal wind directions and the design-building footprint/orientation.
    """

    drawing_width = 62 * mm
    drawing_height = 62 * mm
    drawing = Drawing(drawing_width, drawing_height)
    background = colors.HexColor("#f8fafc")
    border = colors.HexColor("#d0d5dd")
    grid = colors.HexColor("#e4e7ec")
    navy = colors.HexColor("#17324d")
    body = colors.HexColor("#344054")
    muted = colors.HexColor("#667085")
    orange = colors.HexColor("#d97706")
    governing = colors.HexColor("#b42318")

    drawing.add(
        Rect(
            0,
            0,
            drawing_width,
            drawing_height,
            rx=3,
            ry=3,
            fillColor=background,
            strokeColor=border,
            strokeWidth=0.6,
        )
    )

    plan_x = 4 * mm
    plan_y = 6 * mm
    plan_size = 54 * mm
    drawing.add(
        Rect(
            plan_x,
            plan_y,
            plan_size,
            plan_size,
            fillColor=colors.white,
            strokeColor=border,
            strokeWidth=0.6,
        )
    )
    for grid_index in range(1, 4):
        coordinate = plan_x + plan_size * grid_index / 4
        drawing.add(
            Line(
                coordinate,
                plan_y,
                coordinate,
                plan_y + plan_size,
                strokeColor=grid,
                strokeWidth=0.35,
            )
        )
        coordinate = plan_y + plan_size * grid_index / 4
        drawing.add(
            Line(
                plan_x,
                coordinate,
                plan_x + plan_size,
                coordinate,
                strokeColor=grid,
                strokeWidth=0.35,
            )
        )

    centre_x = plan_x + plan_size / 2
    centre_y = plan_y + plan_size / 2
    map_inset = 7 * mm
    usable_plan_size = plan_size - 2 * map_inset
    width_m = result.input.building_width_m
    length_m = result.input.building_length_m
    maximum_dimension_m = max(width_m or 0, length_m or 0)
    map_span_m = max(60.0, maximum_dimension_m * 2.2)
    points_per_metre = usable_plan_size / map_span_m

    governing_directions = set(result.governing_directions)
    direction_bearings = {
        "N": 0.0,
        "NE": 45.0,
        "E": 90.0,
        "SE": 135.0,
        "S": 180.0,
        "SW": 225.0,
        "W": 270.0,
        "NW": 315.0,
    }
    spoke_outer_radius = usable_plan_size / 2
    spoke_inner_radius = 4.5 * mm
    for direction, bearing in direction_bearings.items():
        radians = math.radians(bearing)
        east = math.sin(radians)
        north = math.cos(radians)
        outer_x = centre_x + east * spoke_outer_radius
        outer_y = centre_y + north * spoke_outer_radius
        inner_x = centre_x + east * spoke_inner_radius
        inner_y = centre_y + north * spoke_inner_radius
        colour = governing if direction in governing_directions else colors.HexColor("#98a2b3")
        drawing.add(
            Line(
                outer_x,
                outer_y,
                inner_x,
                inner_y,
                strokeColor=colour,
                strokeWidth=1.15 if direction in governing_directions else 0.6,
            )
        )
        arrow_base_x = inner_x + east * 3.2
        arrow_base_y = inner_y + north * 3.2
        perpendicular_x = north * 1.6
        perpendicular_y = -east * 1.6
        drawing.add(
            Polygon(
                [
                    inner_x,
                    inner_y,
                    arrow_base_x + perpendicular_x,
                    arrow_base_y + perpendicular_y,
                    arrow_base_x - perpendicular_x,
                    arrow_base_y - perpendicular_y,
                ],
                fillColor=colour,
                strokeColor=colour,
                strokeWidth=0.2,
            )
        )
        label_radius = spoke_outer_radius + 3.5 * mm
        drawing.add(
            String(
                centre_x + east * label_radius,
                centre_y + north * label_radius - 1.8,
                "TRUE N" if direction == "N" else direction,
                fontName="Helvetica-Bold",
                fontSize=5.2,
                fillColor=governing if direction in governing_directions else muted,
                textAnchor="middle",
            )
        )

    if width_m is not None and length_m is not None:
        orientation = result.input.structure_orientation_deg or 0.0
        orientation_radians = math.radians(orientation)
        front_east = math.sin(orientation_radians)
        front_north = math.cos(orientation_radians)
        right_east = math.cos(orientation_radians)
        right_north = -math.sin(orientation_radians)
        half_length = length_m * points_per_metre / 2
        half_width = width_m * points_per_metre / 2

        def footprint_point(front_factor: float, right_factor: float) -> tuple[float, float]:
            return (
                centre_x
                + front_east * half_length * front_factor
                + right_east * half_width * right_factor,
                centre_y
                + front_north * half_length * front_factor
                + right_north * half_width * right_factor,
            )

        front_left = footprint_point(1, -1)
        front_right = footprint_point(1, 1)
        back_right = footprint_point(-1, 1)
        back_left = footprint_point(-1, -1)
        drawing.add(
            Polygon(
                [
                    *front_left,
                    *front_right,
                    *back_right,
                    *back_left,
                ],
                fillColor=colors.HexColor("#dbeafe"),
                strokeColor=navy,
                strokeWidth=1.0,
            )
        )
        if result.input.structure_orientation_deg is not None:
            drawing.add(
                Line(
                    *front_left,
                    *front_right,
                    strokeColor=orange,
                    strokeWidth=2.0,
                )
            )
            arrow_end_x = centre_x + front_east * (half_length + 4 * mm)
            arrow_end_y = centre_y + front_north * (half_length + 4 * mm)
            drawing.add(
                Line(
                    centre_x,
                    centre_y,
                    arrow_end_x,
                    arrow_end_y,
                    strokeColor=orange,
                    strokeWidth=1.2,
                )
            )
            arrow_base_x = arrow_end_x - front_east * 4
            arrow_base_y = arrow_end_y - front_north * 4
            perpendicular_x = front_north * 2
            perpendicular_y = -front_east * 2
            drawing.add(
                Polygon(
                    [
                        arrow_end_x,
                        arrow_end_y,
                        arrow_base_x + perpendicular_x,
                        arrow_base_y + perpendicular_y,
                        arrow_base_x - perpendicular_x,
                        arrow_base_y - perpendicular_y,
                    ],
                    fillColor=orange,
                    strokeColor=orange,
                    strokeWidth=0.2,
                )
            )
    else:
        drawing.add(
            Circle(
                centre_x,
                centre_y,
                2.2 * mm,
                fillColor=colors.HexColor("#fee4e2"),
                strokeColor=governing,
                strokeWidth=1.0,
            )
        )

    drawing.add(Circle(centre_x, centre_y, 1.0, fillColor=governing, strokeColor=None))
    scale_distance_m = _wind_pdf_map_scale_distance(map_span_m)
    scale_length = scale_distance_m * points_per_metre
    scale_x = plan_x + 3 * mm
    scale_y = plan_y + 3 * mm
    drawing.add(
        Line(
            scale_x,
            scale_y,
            scale_x + scale_length,
            scale_y,
            strokeColor=navy,
            strokeWidth=1.4,
        )
    )
    drawing.add(Line(scale_x, scale_y - 2, scale_x, scale_y + 2, strokeColor=navy))
    drawing.add(
        Line(
            scale_x + scale_length,
            scale_y - 2,
            scale_x + scale_length,
            scale_y + 2,
            strokeColor=navy,
        )
    )
    drawing.add(
        String(
            scale_x + scale_length / 2,
            scale_y + 2.3,
            f"{scale_distance_m:g} m",
            fontName="Helvetica",
            fontSize=4.7,
            fillColor=body,
            textAnchor="middle",
        )
    )

    drawing.add(
        String(
            plan_x + 2 * mm,
            plan_y + plan_size - 3 * mm,
            "SITE / LOCATION MAP",
            fontName="Helvetica-Bold",
            fontSize=4.8,
            fillColor=navy,
        )
    )
    if width_m is not None and length_m is not None:
        if result.input.structure_orientation_deg is not None:
            map_context = f"FOOTPRINT | front beta {result.input.structure_orientation_deg:.1f} deg"
        else:
            map_context = "FOOTPRINT | orientation not supplied"
    else:
        map_context = "SITE MARKER | footprint not supplied"
    drawing.add(
        String(
            plan_x + plan_size - 2 * mm,
            plan_y + plan_size - 3 * mm,
            map_context,
            fontName="Helvetica",
            fontSize=4.3,
            fillColor=orange if result.input.structure_orientation_deg is not None else muted,
            textAnchor="end",
        )
    )
    drawing.add(
        String(
            plan_x + plan_size - 2 * mm,
            plan_y + 2 * mm,
            "wind from",
            fontName="Helvetica",
            fontSize=4.6,
            fillColor=muted,
            textAnchor="end",
        )
    )
    drawing.add(
        String(
            drawing_width / 2,
            2.2 * mm,
            f"Location {result.site.latitude:+.6f}, {result.site.longitude:+.6f}",
            fontName="Helvetica",
            fontSize=4.7,
            fillColor=body,
            textAnchor="middle",
        )
    )
    return drawing


def _wind_pdf_map_scale_distance(map_span_m: float) -> float:
    """Return a stable 1/2/5 scale-bar distance not exceeding one quarter of the map span."""

    target = max(map_span_m / 4, 1.0)
    exponent = math.floor(math.log10(target))
    magnitude = 10**exponent
    return max(factor * magnitude for factor in (1, 2, 5) if factor * magnitude <= target)


def _wind_report_building_summary(result: WindWorkflowResult) -> str:
    if result.input.average_roof_height_m is None:
        parts = [f"overall/reference height h,z {result.input.reference_height_m:.2f} m"]
    else:
        parts = [
            f"overall height {result.input.building_height_m:.2f} m",
            f"average roof/reference height h,z {result.input.reference_height_m:.2f} m",
        ]
    if result.input.base_rl_m is not None:
        parts.append(f"reviewed base RL {result.input.base_rl_m:.2f} m")
    if result.input.building_width_m is not None and result.input.building_length_m is not None:
        parts.append(
            f"breadth {result.input.building_width_m:.2f} m x "
            f"front-to-back depth {result.input.building_length_m:.2f} m"
        )
    if result.input.structure_orientation_deg is not None:
        parts.append(
            f"front beta {result.input.structure_orientation_deg:.1f} deg clockwise from true North"
        )
    if result.input.roof_shape:
        roof = f"{result.input.roof_shape} roof"
        if result.input.roof_pitch_deg is not None:
            roof += f" at {result.input.roof_pitch_deg:.1f} deg"
        parts.append(roof)
    if result.input.structure_class:
        parts.append(result.input.structure_class)
    return "; ".join(parts)


def _wind_class_override_summary(override) -> str:
    values = [
        override.terrain_category,
        override.shielding_class,
        override.topographic_class,
        f"Mz,cat {override.mzcat:.3f}" if override.mzcat is not None else None,
        f"Ms {override.ms:.3f}" if override.ms is not None else None,
        f"Mt {override.mt:.3f}" if override.mt is not None else None,
    ]
    return "; ".join(value for value in values if value) or "Reviewed input"


def _wind_report_governing_summary(result: WindWorkflowResult) -> str:
    if result.governing_vsitb is None:
        return "Not available"
    directions = result.governing_directions or (
        [result.governing_direction] if result.governing_direction else []
    )
    return f"{', '.join(directions) or 'N/A'} - {result.governing_vsitb:.3f} m/s"


def _wind_report_vdes_summary(result: WindWorkflowResult) -> str:
    if result.governing_vdes_mps is None:
        return "Not available"
    faces = result.governing_vdes_faces
    return f"{', '.join(faces) or 'N/A'} - {result.governing_vdes_mps:.3f} m/s"


def _wind_report_status(result: WindWorkflowResult) -> str:
    if result.input.assessment_status == "reviewed":
        return f"Reviewed preliminary - {result.input.reviewed_by}"
    return "Draft preliminary"


def _wind_report_md_case(result: WindWorkflowResult) -> str:
    value = result.input.wind_direction_multiplier_case
    if result.input.structure_class == "monopole":
        return "Circular/polygonal chimney, tank or pole (effective for monopole)"
    return {
        "main_structure": "Main structure",
        "cladding_or_immediate_support": "Cladding / immediate support",
        "circular_or_polygonal_chimney_tank_or_pole": ("Circular/polygonal chimney, tank or pole"),
    }.get(value, value.replace("_", " "))


def _wind_report_basis(result: WindWorkflowResult) -> str:
    md_clause = (
        "Clause 3.3 mandatory value"
        if any(
            item.variable == "Md" and "Clause 3.3" in item.source_reference
            for item in result.variables
        )
        else "Table 3.2(A)"
    )
    coastal_basis = ""
    if result.wind_region_assessment.wind_region in {"C", "D"}:
        coastal_basis = (
            f" Region {result.wind_region_assessment.wind_region} distance-based coastal VR "
            "interpolation is not automated and requires independent engineering review."
        )
    return (
        f"Wind region: {result.wind_region_assessment.source}. "
        "VR: AS/NZS 1170.2:2021 Table 3.1(A). Mc: Clause 3.4 and Table 3.3. "
        f"Md: {md_clause}. "
        "Mz,cat: Table 4.1. Ms: Clause 4.3 and Table 4.2. Mt: Clause 4.4. "
        "Vdes,theta: Clause 2.3."
        f"{coastal_basis}"
    )


def _wind_report_variable_value(result: WindWorkflowResult, variable: str) -> float | None:
    return next(
        (
            item.final_value
            for item in result.variables
            if item.variable == variable and item.direction is None
        ),
        None,
    )


def _wind_report_variable_is_overridden(result: WindWorkflowResult, variable: str) -> bool:
    return any(
        item.variable == variable and item.direction is None and item.is_overridden
        for item in result.variables
    )


def _wind_report_vsitb_override_directions(result: WindWorkflowResult) -> set[str]:
    return {
        item.direction
        for item in result.variables
        if item.variable == "Vsitb" and item.direction is not None and item.is_overridden
    }


def _wind_report_has_vsitb_overrides(result: WindWorkflowResult) -> bool:
    return bool(_wind_report_vsitb_override_directions(result))


def _report_number(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "N/A"


def _wind_pdf_table(
    rows: list[list[Any]],
    col_widths: list[float],
    *,
    header: bool,
    governing_rows: set[int] | None = None,
) -> Table:
    body_style = ParagraphStyle(
        "WindTableBody",
        fontName="Helvetica",
        fontSize=7.5,
        leading=9.2,
        textColor=colors.HexColor("#344054"),
    )
    label_style = ParagraphStyle(
        "WindTableLabel",
        parent=body_style,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#17324d"),
    )
    header_style = ParagraphStyle(
        "WindTableHeader",
        parent=body_style,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )
    rendered_rows = []
    for row_index, row in enumerate(rows):
        rendered_rows.append(
            [
                Paragraph(
                    escape(str(value)),
                    header_style
                    if header and row_index == 0
                    else label_style
                    if not header and column_index == 0
                    else body_style,
                )
                for column_index, value in enumerate(row)
            ]
        )
    table = Table(rendered_rows, colWidths=col_widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands: list[tuple] = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d0d5dd")),
    ]
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324d")))
    else:
        commands.append(("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f4f7")))
    for row_index in governing_rows or set():
        commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#ecfdf3")))
    table.setStyle(TableStyle(commands))
    return table


def _draw_wind_pdf_page(canvas, doc) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(colors.HexColor("#d0d5dd"))
    canvas.setLineWidth(0.5)
    canvas.line(14 * mm, height - 13 * mm, width - 14 * mm, height - 13 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(14 * mm, height - 10 * mm, "OpenWind-AU | Site Wind Assessment")
    canvas.drawRightString(width - 14 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _wind_pdf_lineage_reference() -> str:
    """Return compact, clickable lineage text for the issued workflow PDF."""

    revision = CALCULATION_BASIS_URL.split("/blob/", maxsplit=1)[1].split("/", maxsplit=1)[0]
    return (
        "Calculation basis/data lineage: "
        f'<link href="{CALCULATION_BASIS_URL}" color="#475467">'
        f"source snapshot {revision}</link>."
    )


def calculation_basis_report_reference() -> str:
    """Return a version-pinned calculation-basis reference in every installation."""

    return CALCULATION_BASIS_REPORT_TEXT


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
                    f"{escape(excluded.object_id)}: excluded, "
                    f"source={escape(excluded.source)}, reason={escape(excluded.reason)}"
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
            "id": escape(obstruction.obstruction_id),
            "source": escape(obstruction.footprint_source),
            "height": f"{height:.1f} m" if height is not None else "missing",
            "confidence": escape(obstruction.confidence),
            "classification": escape(obstruction.classification),
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
            "color": "#1d4ed8",
            "fillColor": "#60a5fa",
            "fillOpacity": 0.38,
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
                # GeoJsonTooltip renders property values as HTML. Escape display strings
                # before serialisation as well as relying on inline-script-safe JSON.
                "id": escape(record.obstruction_id),
                "source": escape(record.footprint_source),
                "height": f"{(record.selected_height_m or record.height_m):.1f} m"
                if (record.selected_height_m or record.height_m) is not None
                else "missing",
                "confidence": escape(record.confidence),
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
    warning_text = "<br>".join(
        escape(str(warning)) for warning in diagnostics.warnings or diagnostics.console_safe_errors
    )
    html = f"""
    <div style="position: fixed; bottom: 18px; left: 18px; z-index: 9999;
      max-width: 440px; padding: 10px 12px; background: #fff7ed; color: #7c2d12;
      border: 1px solid #fdba74; border-radius: 6px; font: 13px/1.35 Arial, sans-serif;">
      <strong>Map display notice</strong><br>{warning_text}
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(html))


def _defer_leaflet_overlay_script(
    script: str,
    function_name: str,
    map_name: str,
    layer_name: str,
) -> str:
    """Wait for Folium's generated map and layer variables before adding overlays."""

    guard = f"""    (function {function_name}() {{
      if (!(
        window.L &&
        typeof {map_name} !== "undefined" &&
        typeof {layer_name} !== "undefined"
      )) {{
        window.setTimeout({function_name}, 20);
        return;
      }}
"""
    return script.replace("    (function() {\n", guard, 1)


def _localize_map_assets(html: str) -> str:
    """Rewrite Folium CDN assets to local static files for reliable local rendering."""

    for external_url, local_url in MAP_ASSET_URL_REPLACEMENTS.items():
        html = html.replace(external_url, local_url)
    return html


def _render_map_with_diagnostics(
    fmap: folium.Map,
    diagnostics: MapRenderDiagnostics,
) -> str:
    """Render Folium HTML and inject final diagnostics."""

    html = _localize_map_assets(fmap.get_root().render())
    diagnostics.map_html_size = len(html.encode("utf-8"))
    diagnostics_json = _json_for_inline_script(diagnostics.as_dict())
    diagnostics_panel = f"""
    <script>
      window.openWindMapDiagnostics = {diagnostics_json};
      function openWindShowMapError(message) {{
        var existing = document.getElementById("openwind-map-error");
        if (existing) existing.remove();
        var notice = document.createElement("div");
        notice.id = "openwind-map-error";
        notice.style.cssText = [
          "position:fixed;left:18px;bottom:18px;z-index:10000;max-width:520px;",
          "padding:10px 12px;background:#fff7ed;color:#7c2d12;",
          "border:1px solid #fdba74;border-radius:6px;font:13px/1.35 Arial,sans-serif;",
          "box-shadow:0 6px 20px rgba(16,24,40,.14)"
        ].join("");
        var heading = document.createElement("strong");
        heading.textContent = "OpenWind-AU map dependency failed";
        notice.appendChild(heading);
        notice.appendChild(document.createElement("br"));
        notice.appendChild(document.createTextNode(String(message)));
        document.body.appendChild(notice);
      }}
      window.addEventListener("error", function(event) {{
        openWindShowMapError("Map script error: " + (event.message || "unknown error"));
      }});
      window.addEventListener("unhandledrejection", function(event) {{
        openWindShowMapError("Map script error: " + (event.reason || "unknown promise rejection"));
      }});
      console.info("OpenWind-AU map diagnostics", window.openWindMapDiagnostics);
      window.addEventListener("load", function() {{
        if (window.L && document.querySelector(".leaflet-container")) return;
        var reason = window.L
          ? "Leaflet loaded, but the map container was not initialised."
          : "Leaflet failed to load from the local static assets.";
        openWindShowMapError(reason + " Check the browser console for the first map error.");
      }});
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
            f"{escape(obstruction.obstruction_id)}<br>"
            f"Distance {obstruction.distance_m:.1f} m<br>"
            f"Bearing {obstruction.bearing_deg:.0f} deg<br>"
            f"Classification {escape(obstruction.classification)}<br>"
            f"Footprint source {escape(obstruction.footprint_source)}<br>"
            f"Height source {escape(obstruction.height_source)}<br>"
            f"Confidence {escape(obstruction.confidence)}"
        ),
    ).add_to(layer)


def _obstruction_tooltip(obstruction) -> str:
    height = f"{obstruction.height_m:.1f} m" if obstruction.height_m is not None else "missing"
    return (
        f"{escape(obstruction.obstruction_id)}: height={height}, "
        f"source={escape(obstruction.footprint_source)}, "
        f"height_source={escape(obstruction.height_source)}, "
        f"confidence={escape(obstruction.confidence)}"
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


OBSTRUCTION_REPORT_TEMPLATE = HTML_TEMPLATE_ENV.from_string(
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
  {% if calculation_basis_reference %}
  <p>{{ calculation_basis_reference }}</p>
  {% endif %}
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


TERRAIN_CATEGORY_REPORT_TEMPLATE = HTML_TEMPLATE_ENV.from_string(
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
  {% if calculation_basis_reference %}
  <p>{{ calculation_basis_reference }}</p>
  {% endif %}
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
      <th>Review Status</th><th>Reviewed By</th><th>Review Notes</th><th>Warnings</th>
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
      <td>{{ assessment.reviewed_by or "" }}</td>
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
      <td colspan="11">
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


CONCISE_WIND_WORKFLOW_REPORT_TEMPLATE = HTML_TEMPLATE_ENV.from_string(
    r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpenWind-AU Site Wind Assessment</title>
  <style>
    :root { color-scheme: light; font-family: Inter, Arial, sans-serif; color: #1d2939; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #f2f4f7; }
    header { padding: 22px 28px; background: #17324d; color: #fff; }
    h1 { margin: 0; font-size: 1.45rem; }
    header p { margin: 5px 0 0; color: #d0d5dd; }
    main { max-width: 1040px; margin: 0 auto; padding: 22px; }
    section {
      margin-bottom: 14px;
      border: 1px solid #d0d5dd;
      border-radius: 8px;
      padding: 16px;
      background: #fff;
    }
    h2 { margin: 0 0 12px; color: #17324d; font-size: 1.05rem; }
    h3 { margin: 14px 0 8px; color: #344054; font-size: 0.9rem; }
    p, li, td, th { font-size: 0.84rem; line-height: 1.4; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #d0d5dd; padding: 7px 8px; text-align: left; vertical-align: top; }
    th { background: #f2f4f7; color: #344054; font-size: 0.75rem; text-transform: uppercase; }
    .summary th { width: 180px; }
    .governing { background: #ecfdf3; font-weight: 700; }
    .note { color: #667085; }
    .warning { border-left: 4px solid #b54708; padding-left: 12px; }
    .limitation { border-left: 4px solid #b42318; background: #fffbfa; }
    ul { margin: 7px 0 0; padding-left: 20px; }
    @media print {
      body { background: #fff; }
      header {
        padding: 14px 0;
        background: #fff;
        color: #17324d;
        border-bottom: 2px solid #17324d;
      }
      header p { color: #667085; }
      main { max-width: none; padding: 14px 0; }
      section { break-inside: avoid; box-shadow: none; }
    }
  </style>
</head>
<body>
  <header>
    <h1>OpenWind-AU Site Wind Assessment</h1>
    <p>{{ report_subtitle|e }}</p>
  </header>
  <main>
    <section>
      <h2>Project and outcome</h2>
      <table class="summary">
        <tr>
          <th>Project</th>
          <td>
            {{ result.input.project_number|e if result.input.project_number else "Not supplied" }}
          </td>
        </tr>
        <tr>
          <th>Assessment status</th>
          <td>
            {% if result.input.assessment_status == "reviewed" %}
            Reviewed preliminary - {{ result.input.reviewed_by|e }}
            {% else %}Draft preliminary{% endif %}
          </td>
        </tr>
        <tr>
          <th>Site</th>
          <td>{{ (
            result.input.address
            or result.input.site_label
            or result.site.display_name
            or "Not supplied"
          )|e }}</td>
        </tr>
        <tr>
          <th>Coordinates / RL</th>
          <td>
            {{ "%.6f"|format(result.site.latitude) }},
            {{ "%.6f"|format(result.site.longitude) }};
            {{ "%.2f"|format(result.site.ground_elevation_m) }} m
          </td>
        </tr>
        <tr>
          <th>Building</th>
          <td>{{ building_summary|e }}</td>
        </tr>
        <tr><th>AEP / ARI</th><td>{{ result.input.annual_exceedance_probability|e }}</td></tr>
        <tr>
          <th>Md design case</th>
          <td>{{ md_case_summary|e }}</td>
        </tr>
        <tr>
          <th>Wind region</th>
          <td>
            {{ result.wind_region_assessment.wind_region
               if result.wind_region_assessment else "Not available" }}
          </td>
        </tr>
        <tr>
          <th>VR,ult{% if vr_is_overridden %} (effective){% endif %}</th>
          <td>
            {% if vr_value is not none %}
            {{ "%.1f"|format(vr_value) }} m/s
            {% if vr_is_overridden %}(reviewed override){% endif %}
            {% else %}Not available{% endif %}
          </td>
        </tr>
        <tr>
          <th>Mc</th>
          <td>{{ "%.3f"|format(mc_value) if mc_value is not none else "Not available" }}</td>
        </tr>
        <tr>
          <th>Governing Vsit,b</th>
          <td>
            {% if result.governing_vsitb is not none %}
            {{ (result.governing_directions
                if result.governing_directions
                else [result.governing_direction])|join(", ") }}
            - {{ "%.3f"|format(result.governing_vsitb) }} m/s
            {% else %}Not available{% endif %}
          </td>
        </tr>
        {% if result.design_wind_speeds %}
        <tr>
          <th>Governing Vdes,theta</th>
          <td>
            {{ result.governing_vdes_faces|join(", ") }}
            - {{ "%.3f"|format(result.governing_vdes_mps) }} m/s
          </td>
        </tr>
        {% endif %}
      </table>
    </section>

    {% if result.design_wind_speeds %}
    <section>
      <h2>Building-orthogonal design wind speeds</h2>
      <p class="note">
        Clause 2.3: maximum linearly interpolated Vsit,b within beta = theta +/-45 degrees.
        Ultimate Vdes,theta is not less than 30 m/s.
      </p>
      <table>
        <tr>
          <th>Plan face</th><th>theta</th><th>Face beta</th><th>Beta sector</th>
          <th>Raw maximum</th><th>Vdes,theta</th>
        </tr>
        {% for row in result.design_wind_speeds %}
        <tr class="{% if row.is_governing %}governing{% endif %}">
          <td>{{ row.face }}{% if row.is_governing %} *{% endif %}</td>
          <td>{{ "%.1f"|format(row.theta_deg) }} deg</td>
          <td>{{ "%.1f"|format(row.beta_deg) }} deg</td>
          <td>
            {{ "%.1f"|format(row.sector_start_beta_deg) }} to
            {{ "%.1f"|format(row.sector_end_beta_deg) }} deg
          </td>
          <td>{{ "%.3f"|format(row.raw_vdes_theta_mps) }} m/s</td>
          <td>
            {{ "%.3f"|format(row.vdes_theta_mps) }} m/s
            {% if row.minimum_uls_applied %}(30 m/s minimum applied){% endif %}
          </td>
        </tr>
        {% endfor %}
      </table>
    </section>
    {% endif %}

    <section>
      <h2>Directional site wind speeds</h2>
      <p class="note">
        Vsit,b = VR x Mc x Md x Mz,cat x Ms x Mt. The governing row is highlighted.
        {% if has_vsitb_overrides %}
        Calculated and final values are both shown where a direct reviewed Vsit,b override exists.
        {% endif %}
      </p>
      <table>
        <tr>
          <th>Direction</th><th>Md</th><th>Mz,cat</th><th>Ms</th><th>Mt</th>
          {% if has_vsitb_overrides %}
          <th>Calculated Vsit,b</th><th>Final Vsit,b</th>
          {% else %}<th>Vsit,b</th>{% endif %}
        </tr>
        {% for row in result.directional_vsitb %}
        <tr class="{% if row.is_governing %}governing{% endif %}">
          <td>{{ row.direction }}{% if row.is_governing %} *{% endif %}</td>
          <td>{{ "%.3f"|format(row.md) if row.md is not none else "N/A" }}</td>
          <td>{{ "%.3f"|format(row.mzcat) if row.mzcat is not none else "N/A" }}</td>
          <td>{{ "%.3f"|format(row.ms) if row.ms is not none else "N/A" }}</td>
          <td>{{ "%.3f"|format(row.mt) if row.mt is not none else "N/A" }}</td>
          {% if has_vsitb_overrides %}
          <td>
            {{ ("%.3f m/s"|format(row.recommended_vsitb))
               if row.recommended_vsitb is not none else "N/A" }}
          </td>
          <td>
            {{ ("%.3f m/s"|format(row.final_vsitb))
               if row.final_vsitb is not none else "N/A" }}
            {% if row.direction in vsitb_override_directions %}(override){% endif %}
          </td>
          {% else %}
          <td>
            {{ ("%.3f m/s"|format(row.final_vsitb))
               if row.final_vsitb is not none else "N/A" }}
          </td>
          {% endif %}
        </tr>
        {% endfor %}
      </table>
    </section>

    {% if report_warnings or result.input.workflow_overrides
          or result.input.class_multiplier_overrides or result.input.engineer_notes %}
    <section>
      <h2>Review items</h2>
      {% if report_warnings %}
      <div class="warning">
        <h3>Warnings</h3>
        <ul>{% for warning in report_warnings %}<li>{{ warning|e }}</li>{% endfor %}</ul>
      </div>
      {% endif %}
      {% if result.input.workflow_overrides or result.input.class_multiplier_overrides %}
      <h3>Overrides</h3>
      <table>
        <tr><th>Type</th><th>Direction</th><th>Selection / value</th><th>Reason</th></tr>
        {% for override in result.input.workflow_overrides %}
        <tr>
          <td>{{ override.variable }}</td><td>{{ override.direction or "All" }}</td>
          <td>{{ "%.3f"|format(override.override_value) }}</td><td>{{ override.reason|e }}</td>
        </tr>
        {% endfor %}
        {% for override in result.input.class_multiplier_overrides %}
        <tr>
          <td>Reviewed classes</td><td>{{ override.direction }}</td>
          <td>{{ class_override_summaries[loop.index0] }}</td>
          <td>{{ override.reason|e }}</td>
        </tr>
        {% endfor %}
      </table>
      {% endif %}
      {% if result.input.engineer_notes %}
      <p><strong>Engineer notes:</strong> {{ result.input.engineer_notes|e }}</p>
      {% endif %}
    </section>
    {% endif %}

    <section class="limitation">
      <h2>Basis and limitations</h2>
      <p>{{ basis_summary|e }}</p>
      <p>{{ report_scope|e }}</p>
      {% if calculation_basis_reference %}
      <p class="note">{{ calculation_basis_reference|e }}</p>
      {% endif %}
    </section>
  </main>
</body>
</html>
"""
)
