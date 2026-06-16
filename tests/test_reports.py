"""Tests for report and export helpers."""

from __future__ import annotations

from openwind_au.analysis import run_site_analysis
from openwind_au.dem import DEMProvider
from openwind_au.models import SiteAnalysisRequest
from openwind_au.reports import map_html, profile_plot_html, render_html_report, result_to_json


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
            radial_count=8,
            sample_interval_m=100,
        ),
        FlatDEM(),
    )

    data = result_to_json(result)
    html = render_html_report(result)
    plot = profile_plot_html(result)
    fmap = map_html(result)

    assert data["site"]["ground_elevation_m"] == 50
    assert "Preliminary Terrain Report" in html
    assert "plotly" in plot.lower()
    assert "leaflet" in fmap.lower()
