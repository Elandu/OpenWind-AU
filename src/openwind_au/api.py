"""FastAPI application for OpenWind-AU."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from openwind_au.analysis import run_site_analysis
from openwind_au.dem import SRTMProvider
from openwind_au.models import SiteAnalysisRequest, SiteAnalysisResult
from openwind_au.reports import (
    map_html,
    profile_plot_html,
    render_html_report,
    result_to_json,
    write_pdf_report,
)

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"


def create_app() -> FastAPI:
    """Create the FastAPI app."""

    app = FastAPI(
        title="OpenWind-AU",
        description=(
            "Preliminary wind site terrain and topographic analysis for Australian buildings."
        ),
        version="0.1.0",
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/analyse", response_model=SiteAnalysisResult)
    def analyse(request: SiteAnalysisRequest) -> SiteAnalysisResult:
        try:
            return run_site_analysis(request, SRTMProvider())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/export/json")
    def export_json(request: SiteAnalysisRequest) -> Response:
        result = analyse(request)
        content = json.dumps(result_to_json(result), indent=2)
        return Response(content=content, media_type="application/json")

    @app.post("/api/report/html", response_class=HTMLResponse)
    def report_html(request: SiteAnalysisRequest) -> str:
        result = analyse(request)
        return render_html_report(result)

    @app.post("/api/report/pdf")
    def report_pdf(request: SiteAnalysisRequest) -> Response:
        result = analyse(request)
        report_path = Path("reports") / "openwind-au-report.pdf"
        try:
            write_pdf_report(result, report_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {exc}") from exc
        return Response(
            content=report_path.read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="openwind-au-report.pdf"'},
        )

    @app.post("/api/plots/profile", response_class=HTMLResponse)
    def profile_plot(request: SiteAnalysisRequest) -> str:
        result = analyse(request)
        return profile_plot_html(result)

    @app.post("/api/maps/site", response_class=HTMLResponse)
    def site_map(request: SiteAnalysisRequest) -> str:
        result = analyse(request)
        return map_html(result)

    return app


app = create_app()
