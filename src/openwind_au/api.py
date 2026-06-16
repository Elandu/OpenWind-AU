"""FastAPI application for OpenWind-AU."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from openwind_au.analysis import run_site_analysis
from openwind_au.dem import SRTMProvider
from openwind_au.models import (
    CombinedMapRequest,
    ObstructionInventoryRequest,
    ObstructionInventoryResult,
    SiteAnalysisRequest,
    SiteAnalysisResult,
)
from openwind_au.obstructions import (
    manual_overrides_from_json,
    parse_manual_overrides_csv,
    run_obstruction_inventory,
)
from openwind_au.reports import (
    combined_map_html,
    map_html,
    obstruction_map_html,
    profile_plot_html,
    render_html_report,
    render_obstruction_report_html,
    result_to_json,
    write_pdf_report,
)
from openwind_au.validation import (
    DEFAULT_VALIDATION_CASES,
    render_validation_report_html,
    run_validation_cases,
    validation_report_to_json,
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

    @app.get("/validation", response_class=HTMLResponse)
    def validation_page() -> str:
        return (STATIC_DIR / "validation.html").read_text(encoding="utf-8")

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

    @app.post("/api/obstructions/inventory", response_model=ObstructionInventoryResult)
    def obstruction_inventory(
        request: ObstructionInventoryRequest,
    ) -> ObstructionInventoryResult:
        try:
            return run_obstruction_inventory(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/obstructions/map", response_class=HTMLResponse)
    def obstruction_map(request: ObstructionInventoryRequest) -> str:
        result = obstruction_inventory(request)
        return obstruction_map_html(result)

    @app.post("/api/map/combined", response_class=HTMLResponse)
    def map_combined(request: CombinedMapRequest) -> str:
        try:
            site_result = analyse(request)
            obstruction_request = ObstructionInventoryRequest(
                address=request.address,
                latitude=request.latitude,
                longitude=request.longitude,
                radius_m=request.obstruction_radius_m,
                default_storey_height_m=request.default_storey_height_m,
                manual_overrides=request.manual_overrides,
            )
            obstruction_result = run_obstruction_inventory(obstruction_request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return combined_map_html(site_result, obstruction_result)

    @app.post("/api/obstructions/report/html", response_class=HTMLResponse)
    def obstruction_report_html(request: ObstructionInventoryRequest) -> str:
        result = obstruction_inventory(request)
        return render_obstruction_report_html(result)

    @app.post("/api/obstructions/import/csv")
    async def obstruction_import_csv(request: Request) -> Response:
        content = (await request.body()).decode("utf-8")
        overrides = parse_manual_overrides_csv(content)
        return Response(
            content=json.dumps([override.model_dump() for override in overrides], indent=2),
            media_type="application/json",
        )

    @app.post("/api/obstructions/import/json")
    async def obstruction_import_json(request: Request) -> Response:
        content = (await request.body()).decode("utf-8")
        overrides = manual_overrides_from_json(content)
        return Response(
            content=json.dumps([override.model_dump() for override in overrides], indent=2),
            media_type="application/json",
        )

    @app.get("/api/validation/cases")
    def validation_cases() -> Response:
        content = json.dumps(
            [case.model_dump() for case in DEFAULT_VALIDATION_CASES],
            indent=2,
        )
        return Response(content=content, media_type="application/json")

    @app.get("/api/validation")
    def validation_report() -> Response:
        try:
            report = run_validation_cases()
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        content = json.dumps(validation_report_to_json(report), indent=2)
        return Response(content=content, media_type="application/json")

    @app.get("/api/validation/report/html", response_class=HTMLResponse)
    def validation_report_html() -> str:
        try:
            report = run_validation_cases()
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return render_validation_report_html(report)

    return app


app = create_app()
