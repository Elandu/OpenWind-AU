"""FastAPI application for OpenWind-AU."""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from plotly.offline import get_plotlyjs

from openwind_au import __version__
from openwind_au.analysis import run_site_analysis
from openwind_au.calculation_validation import (
    calculation_validation_report_to_json,
    run_calculation_validation_cases,
)
from openwind_au.dem import OpenMeteoElevationProvider, SRTMProvider, configured_dem_provider
from openwind_au.errors import ServiceNotReadyError
from openwind_au.geo import geocode_address, geocode_address_suggestions
from openwind_au.models import (
    CombinedMapRequest,
    GeocodeQueryRequest,
    MzCatAssessmentResult,
    MzCatReviewSelection,
    ObstructionInventoryRequest,
    ObstructionInventoryResult,
    PublicObstructionInventoryResult,
    SiteAnalysisRequest,
    SiteAnalysisResult,
    SiteLocation,
    TerrainCategoryEvidenceRequest,
    TerrainCategoryEvidenceResult,
    TerrainCategoryReportRequest,
    WindRegionAssessment,
    WindWorkflowRequest,
    WindWorkflowResult,
)
from openwind_au.mzcat import load_mzcat_table, mzcat_lookup_issues
from openwind_au.obstructions import (
    manual_overrides_from_json,
    parse_manual_overrides_csv,
    run_obstruction_inventory,
)
from openwind_au.reference_calc_validation import (
    compare_reference_calc_7989,
    reference_calc_7989_class_overrides,
    reference_calc_7989_osm_footprints,
)
from openwind_au.reports import (
    combined_map_html,
    map_html,
    obstruction_map_html,
    profile_plot_html,
    render_html_report,
    render_obstruction_report_html,
    render_pdf_report,
    render_terrain_category_report_html,
    render_wind_workflow_pdf_report,
    render_wind_workflow_report_html,
    result_to_json,
    terrain_category_map_html,
)
from openwind_au.result_integrity import (
    result_signing_readiness,
    verify_workflow_result,
)
from openwind_au.standard_calculations import (
    DIRECTIONS,
    load_ms_table,
    shielding_lookup_issues,
    table_region_key,
)
from openwind_au.standard_lookup_tables import lookup_is_reviewed
from openwind_au.terrain_category import run_terrain_category_evidence
from openwind_au.terrain_category_validation import (
    DEFAULT_TERRAIN_CATEGORY_VALIDATION_CASES,
    run_terrain_category_validation_cases,
)
from openwind_au.validation import (
    DEFAULT_VALIDATION_CASES,
    render_validation_report_html,
    run_validation_cases,
    validation_report_to_json,
)
from openwind_au.wind_inputs import (
    direction_multiplier_assessment,
    load_md_tables,
    load_vr_tables,
    regional_wind_speed_assessment,
    run_wind_region_validation_cases,
    wind_region_map_html,
)
from openwind_au.wind_region import (
    REGION_LABELS,
    assess_wind_region,
    dataset_metadata,
    wind_region_debug,
)
from openwind_au.wind_workflow import run_wind_workflow

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
LOGGER = logging.getLogger(__name__)
MAX_OBSTRUCTION_IMPORT_BYTES = 1_000_000
DEBUG_ENDPOINTS_ENV = "OPENWIND_ENABLE_DEBUG_ENDPOINTS"
DEPENDENCY_FAILURE_DETAIL = (
    "Required data provider failed; retry the request or inspect the server logs."
)


def debug_endpoints_enabled() -> bool:
    """Return whether trusted local diagnostic routes are enabled."""

    return os.environ.get(DEBUG_ENDPOINTS_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def require_debug_endpoints_enabled() -> None:
    """Hide diagnostic routes unless the deployment explicitly enables them."""

    if not debug_endpoints_enabled():
        raise HTTPException(status_code=404, detail="Not found")


def _log_dependency_failure(exc: RuntimeError) -> None:
    """Record dependency diagnostics without returning them to API consumers."""

    LOGGER.error(
        "Required assessment dependency failed",
        exc_info=(type(exc), exc, exc.__traceback__),
    )


async def _read_obstruction_import(
    request: Request,
    *,
    accepted_media_types: set[str],
) -> str:
    """Read a bounded UTF-8 obstruction import with an explicit media type."""

    media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if media_type not in accepted_media_types:
        expected = ", ".join(sorted(accepted_media_types))
        raise HTTPException(
            status_code=415,
            detail=f"Content-Type must be one of: {expected}",
        )

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from exc
        if declared_length > MAX_OBSTRUCTION_IMPORT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Import body exceeds {MAX_OBSTRUCTION_IMPORT_BYTES} bytes",
            )

    body = await request.body()
    if len(body) > MAX_OBSTRUCTION_IMPORT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Import body exceeds {MAX_OBSTRUCTION_IMPORT_BYTES} bytes",
        )
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Import body must be valid UTF-8") from exc


def create_app() -> FastAPI:
    """Create the FastAPI app."""

    app = FastAPI(
        title="OpenWind-AU",
        description=(
            "Preliminary wind site terrain and topographic analysis for Australian buildings."
        ),
        version=__version__,
    )

    @app.exception_handler(ServiceNotReadyError)
    async def service_not_ready_handler(
        _request: Request,
        exc: ServiceNotReadyError,
    ) -> JSONResponse:
        LOGGER.error("Assessment service is not ready: %s", exc)
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(RuntimeError)
    async def dependency_failure_handler(
        _request: Request,
        exc: RuntimeError,
    ) -> JSONResponse:
        _log_dependency_failure(exc)
        return JSONResponse(
            status_code=502,
            content={"detail": DEPENDENCY_FAILURE_DETAIL},
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "wind_workflow.html").read_text(encoding="utf-8")

    @app.get("/wind-workflow", response_class=HTMLResponse)
    def wind_workflow_page() -> str:
        return (STATIC_DIR / "wind_workflow.html").read_text(encoding="utf-8")

    @app.get("/site-analysis", response_class=HTMLResponse)
    def site_analysis_page() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/terrain-category", response_class=HTMLResponse)
    def terrain_category_page() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/validation", response_class=HTMLResponse)
    def validation_page() -> str:
        return (STATIC_DIR / "validation.html").read_text(encoding="utf-8")

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health")
    def health(response: Response) -> dict[str, Any]:
        report = readiness_report()
        if report["status"] != "ready":
            response.status_code = 503
        return report

    @app.get("/vendor/plotly.min.js", include_in_schema=False)
    def plotly_javascript() -> Response:
        return Response(
            content=get_plotlyjs(),
            media_type="application/javascript",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    @app.post("/api/geocode/suggest")
    def geocode_suggest(request: GeocodeQueryRequest) -> dict:
        return {
            "suggestions": geocode_address_suggestions(
                request.query,
                limit=request.limit,
            )
        }

    @app.post("/api/geocode/resolve")
    def geocode_resolve(request: GeocodeQueryRequest) -> dict:
        """Resolve one supported Australian address without running terrain analysis."""

        try:
            return geocode_address(request.query)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/analyse", response_model=SiteAnalysisResult)
    def analyse(request: SiteAnalysisRequest) -> SiteAnalysisResult:
        try:
            return run_site_analysis(request, _dem_provider())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/full-analysis")
    def full_analysis(request: TerrainCategoryEvidenceRequest) -> dict:
        """Run the browser workflow in one pass to avoid duplicate obstruction queries."""

        try:
            site_result, obstruction_result, evidence = _run_terrain_category_workflow(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "site_analysis": site_result,
            "obstruction_inventory": _obstruction_inventory_public_data(obstruction_result),
            "terrain_category_evidence": evidence,
            "profile_plot_html": profile_plot_html(site_result),
            "terrain_category_map_html": terrain_category_map_html(
                site_result,
                obstruction_result,
                evidence,
            ),
            "combined_map_html": combined_map_html(
                site_result,
                obstruction_result,
                evidence,
                wind_region_assessment=_optional_wind_region(site_result),
            ),
        }

    @app.post("/api/wind-workflow", response_model=WindWorkflowResult)
    def wind_workflow(request: WindWorkflowRequest) -> WindWorkflowResult:
        try:
            mzcat_lookup = load_mzcat_table()
            site_result, obstruction_result, evidence = _run_terrain_category_workflow(
                request,
                mzcat_lookup_data=mzcat_lookup,
            )
            return run_wind_workflow(
                request=request,
                site_result=site_result,
                obstruction_result=obstruction_result,
                terrain_result=evidence,
                mzcat_lookup_data=mzcat_lookup,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/wind-workflow/stream")
    def wind_workflow_stream(request: WindWorkflowRequest) -> StreamingResponse:
        return StreamingResponse(
            _wind_workflow_stream_events(request),
            media_type="application/x-ndjson",
        )

    @app.post("/api/wind-workflow/report/html", response_class=HTMLResponse)
    def wind_workflow_report_html(request: WindWorkflowRequest) -> str:
        result = wind_workflow(request)
        return render_wind_workflow_report_html(result)

    @app.post("/api/wind-workflow/result/report/html", response_class=HTMLResponse)
    def wind_workflow_result_report_html(result: WindWorkflowResult) -> str:
        """Render an already completed workflow without repeating external data calls."""

        _verify_completed_workflow_result(result)
        return render_wind_workflow_report_html(result)

    @app.post("/api/wind-workflow/report/pdf")
    def wind_workflow_report_pdf(request: WindWorkflowRequest) -> Response:
        result = wind_workflow(request)
        return _wind_workflow_pdf_response(result)

    @app.post("/api/wind-workflow/result/report/pdf")
    def wind_workflow_result_report_pdf(result: WindWorkflowResult) -> Response:
        """Render an already completed workflow without repeating external data calls."""

        _verify_completed_workflow_result(result)
        return _wind_workflow_pdf_response(result)

    def _verify_completed_workflow_result(result: WindWorkflowResult) -> None:
        try:
            verify_workflow_result(result)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _wind_workflow_pdf_response(result: WindWorkflowResult) -> Response:
        try:
            content = render_wind_workflow_pdf_report(result)
        except Exception as exc:
            LOGGER.exception("Failed to generate site-wind workflow PDF")
            raise HTTPException(
                status_code=500,
                detail="Failed to generate PDF report; inspect the server logs.",
            ) from exc
        return Response(
            content=content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    'attachment; filename="openwind-au-site-wind-assessment.pdf"'
                )
            },
        )

    @app.post("/api/wind-workflow/map", response_class=HTMLResponse)
    def wind_workflow_map(request: WindWorkflowRequest) -> str:
        try:
            site_result, obstruction_result, evidence = _run_terrain_category_workflow(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return combined_map_html(
            site_result,
            obstruction_result,
            evidence,
            wind_region_assessment=_optional_wind_region(site_result),
        )

    @app.post("/api/wind-region", response_model=WindRegionAssessment)
    def wind_region_assessment(request: SiteAnalysisRequest) -> WindRegionAssessment:
        try:
            site_result = analyse(request)
            return assess_wind_region(site_result.site)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/wind-region/map", response_class=HTMLResponse)
    def wind_region_map(request: SiteAnalysisRequest) -> str:
        try:
            site_result = analyse(request)
            assessment = assess_wind_region(site_result.site)
            return wind_region_map_html(site_result.site, assessment)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/debug/wind-region/dataset", include_in_schema=False)
    def wind_region_dataset_debug() -> dict:
        require_debug_endpoints_enabled()
        try:
            return dataset_metadata()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/debug/wind-region", include_in_schema=False)
    def wind_region_debug_get(
        address: str | None = Query(default=None),
        latitude: float | None = Query(default=None),
        longitude: float | None = Query(default=None),
    ) -> dict:
        require_debug_endpoints_enabled()
        try:
            site = _wind_region_debug_site(address, latitude, longitude)
            return wind_region_debug(site)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/debug/wind-region", include_in_schema=False)
    def wind_region_debug_post(request: SiteAnalysisRequest) -> dict:
        require_debug_endpoints_enabled()
        try:
            site_result = analyse(request)
            return wind_region_debug(site_result.site)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        try:
            content = render_pdf_report(result)
        except Exception as exc:
            LOGGER.exception("Failed to generate site-analysis PDF")
            raise HTTPException(
                status_code=500,
                detail="Failed to generate PDF report; inspect the server logs.",
            ) from exc
        return Response(
            content=content,
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

    @app.post(
        "/api/obstructions/inventory",
        response_model=PublicObstructionInventoryResult,
    )
    def obstruction_inventory(
        request: ObstructionInventoryRequest,
    ) -> ObstructionInventoryResult:
        try:
            return run_obstruction_inventory(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/obstructions/map", response_class=HTMLResponse)
    def obstruction_map(request: ObstructionInventoryRequest) -> str:
        result = obstruction_inventory(request)
        return obstruction_map_html(result)

    @app.get("/api/obstructions/debug", include_in_schema=False)
    def obstruction_debug(
        address: str | None = Query(default=None),
        latitude: float | None = Query(default=None),
        longitude: float | None = Query(default=None),
        radius_m: int = Query(default=500, ge=50, le=4000),
        building_height_m: float | None = Query(default=None, gt=0),
    ) -> dict:
        require_debug_endpoints_enabled()
        try:
            request = ObstructionInventoryRequest(
                address=address,
                latitude=latitude,
                longitude=longitude,
                radius_m=radius_m,
                building_height_m=building_height_m,
            )
            result = run_obstruction_inventory(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "query_centre": result.data_quality.query_centre,
            "radius": result.data_quality.query_radius_m,
            "microsoft_source_status": result.data_quality.microsoft_source_status,
            "microsoft_cache_status": result.data_quality.microsoft_cache_status,
            "microsoft_cache_path": result.data_quality.microsoft_cache_path,
            "microsoft_cache_files": result.data_quality.microsoft_cache_files,
            "total_microsoft_building_footprints_found": (
                result.data_quality.total_microsoft_building_footprints_found
            ),
            "osm_fallback_used": result.data_quality.osm_fallback_used,
            "overpass_query": result.data_quality.overpass_query,
            "raw_counts": result.data_quality.raw_overpass_counts,
            "parsed_counts": result.data_quality.parsed_counts,
            "excluded_counts": result.data_quality.excluded_reasons,
            "sample_building_ids": result.data_quality.sample_building_ids,
            "returned_geometry_bbox": result.data_quality.returned_geometry_bbox,
            "warnings": result.data_quality.warnings,
            "pipeline_log": result.data_quality.pipeline_log,
        }

    @app.post("/api/map/combined", response_class=HTMLResponse)
    def map_combined(request: CombinedMapRequest) -> str:
        try:
            site_result = analyse(request)
            obstruction_result = _run_obstruction_inventory_for_site(request, site_result)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return combined_map_html(site_result, obstruction_result)

    @app.post("/api/obstructions/report/html", response_class=HTMLResponse)
    def obstruction_report_html(request: ObstructionInventoryRequest) -> str:
        result = obstruction_inventory(request)
        return render_obstruction_report_html(result)

    @app.post("/api/terrain-category/evidence", response_model=TerrainCategoryEvidenceResult)
    def terrain_category_evidence(
        request: TerrainCategoryEvidenceRequest,
    ) -> TerrainCategoryEvidenceResult:
        try:
            site_result, obstruction_result, evidence = _run_terrain_category_workflow(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return evidence

    @app.post("/api/mzcat/assessment", response_model=MzCatAssessmentResult)
    def mzcat_assessment(request: TerrainCategoryEvidenceRequest) -> MzCatAssessmentResult:
        try:
            _site_result, _obstruction_result, evidence = _run_terrain_category_workflow(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return MzCatAssessmentResult(
            input=evidence.input,
            site=evidence.site,
            directions=evidence.mzcat_assessment,
            recommendation_mode=request.mzcat_recommendation_mode,
            lookup_provenance=evidence.mzcat_lookup_provenance,
            warnings=[
                "Terrain category not confirmed.",
                "Mz,cat values are indicative only.",
                "Engineer review required.",
            ],
        )

    @app.post("/api/terrain-category/map", response_class=HTMLResponse)
    def terrain_category_map(request: TerrainCategoryEvidenceRequest) -> str:
        try:
            site_result, obstruction_result, evidence = _run_terrain_category_workflow(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return terrain_category_map_html(site_result, obstruction_result, evidence)

    @app.post("/api/terrain-category/report/html", response_class=HTMLResponse)
    def terrain_category_report_html(request: TerrainCategoryReportRequest) -> str:
        try:
            _site_result, _obstruction_result, evidence = _run_terrain_category_workflow(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return render_terrain_category_report_html(
            _apply_mzcat_reviews(evidence, request.mzcat_reviews)
        )

    @app.get("/api/terrain-category/validation/cases")
    def terrain_category_validation_cases() -> Response:
        content = json.dumps(
            [case.model_dump() for case in DEFAULT_TERRAIN_CATEGORY_VALIDATION_CASES],
            indent=2,
        )
        return Response(content=content, media_type="application/json")

    @app.get("/api/terrain-category/validation")
    def terrain_category_validation() -> Response:
        content = json.dumps(
            [result.model_dump() for result in run_terrain_category_validation_cases()],
            indent=2,
        )
        return Response(content=content, media_type="application/json")

    @app.post("/api/obstructions/import/csv")
    async def obstruction_import_csv(request: Request) -> Response:
        content = await _read_obstruction_import(
            request,
            accepted_media_types={"application/csv", "text/csv"},
        )
        try:
            overrides = parse_manual_overrides_csv(content)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(
            content=json.dumps([override.model_dump() for override in overrides], indent=2),
            media_type="application/json",
        )

    @app.post("/api/obstructions/import/json")
    async def obstruction_import_json(request: Request) -> Response:
        content = await _read_obstruction_import(
            request,
            accepted_media_types={"application/json"},
        )
        try:
            overrides = manual_overrides_from_json(content)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        report = run_validation_cases()
        content = json.dumps(validation_report_to_json(report), indent=2)
        return Response(content=content, media_type="application/json")

    @app.get("/api/validation/report/html", response_class=HTMLResponse)
    def validation_report_html() -> str:
        report = run_validation_cases()
        return render_validation_report_html(report)

    @app.get("/api/calculation-validation")
    def calculation_validation_report() -> Response:
        content = json.dumps(
            calculation_validation_report_to_json(run_calculation_validation_cases()),
            indent=2,
        )
        return Response(content=content, media_type="application/json")

    @app.get("/api/reference-validation/7989")
    def reference_calc_7989_validation(apply_reference_overrides: bool = False) -> Response:
        class_overrides = reference_calc_7989_class_overrides() if apply_reference_overrides else []
        request = WindWorkflowRequest(
            latitude=-27.520503,
            longitude=152.936814,
            building_height_m=4.0,
            radius_m=2000,
            obstruction_radius_m=500,
            sample_interval_m=50,
            annual_exceedance_probability="1/500",
            mzcat_recommendation_mode="best_estimate",
            class_multiplier_overrides=class_overrides,
        )
        site_result = run_site_analysis(request, _dem_provider())
        obstruction_result = _run_obstruction_inventory_for_site(
            request,
            site_result,
            footprints=reference_calc_7989_osm_footprints(),
        )
        terrain_result = run_terrain_category_evidence(site_result, obstruction_result)
        content = compare_reference_calc_7989(
            site_result=site_result,
            obstruction_result=obstruction_result,
            terrain_result=terrain_result,
            class_overrides=class_overrides,
        ).model_dump_json(indent=2)
        return Response(content=content, media_type="application/json")

    @app.get("/api/wind-region/validation")
    def wind_region_validation() -> Response:
        content = json.dumps(run_wind_region_validation_cases(), indent=2)
        return Response(content=content, media_type="application/json")

    return app


def _run_terrain_category_workflow(
    request: TerrainCategoryEvidenceRequest,
    *,
    mzcat_lookup_data: dict[str, Any] | None = None,
) -> tuple[SiteAnalysisResult, ObstructionInventoryResult, TerrainCategoryEvidenceResult]:
    mzcat_lookup = mzcat_lookup_data if mzcat_lookup_data is not None else load_mzcat_table()
    site_result = run_site_analysis(request, _dem_provider())
    obstruction_result = _run_obstruction_inventory_for_site(request, site_result)
    evidence = run_terrain_category_evidence(
        site_result,
        obstruction_result,
        mzcat_lookup_data=mzcat_lookup,
    )
    return site_result, obstruction_result, evidence


def _wind_workflow_stream_events(request: WindWorkflowRequest):
    """Yield newline-delimited JSON workflow progress events."""

    def event(stage: str, percent: int, label: str, data: dict[str, Any] | None = None) -> str:
        payload: dict[str, Any] = {
            "stage": stage,
            "percent": percent,
            "label": label,
        }
        if data is not None:
            payload["data"] = data
        return json.dumps(payload, separators=(",", ":")) + "\n"

    try:
        yield event("start", 2, "Resolving site location and elevation")
        mzcat_lookup = load_mzcat_table()
        site_result = run_site_analysis(request, _dem_provider())
        yield event(
            "site",
            16,
            "Site resolved; calculating wind region, VR, and Md",
            {"site_analysis": result_to_json(site_result)},
        )

        wind_region = assess_wind_region(site_result.site)
        regional_speed = regional_wind_speed_assessment(
            wind_region,
            importance_level=request.importance_level,
            annual_exceedance_probability=request.annual_exceedance_probability,
        )
        direction_multipliers = direction_multiplier_assessment(wind_region)
        yield event(
            "wind_inputs",
            30,
            "Wind inputs calculated; building obstruction inventory",
            {
                "wind_region_assessment": wind_region.model_dump(),
                "regional_wind_speed_assessment": regional_speed.model_dump(),
                "direction_multiplier_assessment": direction_multipliers.model_dump(),
            },
        )

        obstruction_result = _run_obstruction_inventory_for_site(request, site_result)
        yield event(
            "obstructions",
            48,
            "Obstructions analysed; calculating terrain category and Mz,cat",
            {
                "obstruction_summary": {
                    "total_obstructions": len(obstruction_result.obstructions),
                    "shielding_sectors": len(obstruction_result.shielding_sectors),
                    "warnings": obstruction_result.warnings,
                }
            },
        )

        evidence = run_terrain_category_evidence(
            site_result,
            obstruction_result,
            mzcat_lookup_data=mzcat_lookup,
        )
        yield event(
            "terrain",
            68,
            "Terrain and Mz,cat calculated; calculating directional Vsit,b",
            {
                "terrain_category_evidence": {
                    "directions": [item.model_dump() for item in evidence.directions],
                    "mzcat_assessment": [item.model_dump() for item in evidence.mzcat_assessment],
                    "warnings": evidence.warnings,
                }
            },
        )

        workflow = run_wind_workflow(
            request=request,
            site_result=site_result,
            obstruction_result=obstruction_result,
            terrain_result=evidence,
            wind_region=wind_region,
            regional_speed=regional_speed,
            direction_multipliers=direction_multipliers,
            mzcat_lookup_data=mzcat_lookup,
        )
        yield event(
            "workflow",
            84,
            "Directional variables calculated; rendering combined map layers",
            {"workflow": workflow.model_dump(mode="json")},
        )

        map_html_content = combined_map_html(
            site_result,
            obstruction_result,
            evidence,
            wind_region_assessment=wind_region,
        )
        yield event(
            "map",
            96,
            "Combined map rendered; finalising assessment",
            {"map_html": map_html_content},
        )
        yield event("complete", 100, "Assessment complete")
    except ServiceNotReadyError as exc:
        yield event("error", 100, str(exc), {"status_code": 503})
    except ValueError as exc:
        yield event("error", 100, str(exc), {"status_code": 400})
    except RuntimeError as exc:
        _log_dependency_failure(exc)
        yield event("error", 100, DEPENDENCY_FAILURE_DETAIL, {"status_code": 502})
    except Exception:
        LOGGER.exception("Unexpected wind workflow stream failure")
        yield event(
            "error",
            100,
            "Unexpected workflow failure. Check the server logs for the incident details.",
            {"status_code": 500},
        )


def _optional_wind_region(site_result: SiteAnalysisResult) -> WindRegionAssessment | None:
    try:
        return assess_wind_region(site_result.site)
    except (ServiceNotReadyError, ValueError):
        return None


def _dem_provider():
    return configured_dem_provider(
        srtm_factory=SRTMProvider,
        open_meteo_factory=OpenMeteoElevationProvider,
    )


def readiness_report() -> dict[str, Any]:
    """Report whether required datasets and reviewed lookup rows are usable."""

    checks: dict[str, dict[str, Any]] = {}
    configured_region_names: list[str] = []
    try:
        metadata = dataset_metadata()
        region_names = metadata.get("available_region_names")
        dataset_ready = (
            isinstance(metadata, dict)
            and isinstance(metadata.get("polygon_count"), int)
            and metadata["polygon_count"] > 0
            and isinstance(region_names, list)
            and bool(region_names)
            and all(region in REGION_LABELS for region in region_names)
            and not metadata.get("is_test_fixture")
        )
        if isinstance(region_names, list) and all(
            isinstance(region, str) and region in REGION_LABELS for region in region_names
        ):
            configured_region_names = list(dict.fromkeys(region_names))
        checks["wind_region_dataset"] = {
            "ready": dataset_ready,
            "dataset_name": metadata.get("dataset_name"),
            "polygon_count": metadata.get("polygon_count", 0),
            "available_region_names": region_names if isinstance(region_names, list) else [],
            "message": (
                "Production wind-region dataset is available."
                if dataset_ready
                else "Configure a non-test Geoscience Australia wind-region dataset."
            ),
        }
    except Exception:
        LOGGER.exception("Wind-region dataset readiness check failed")
        checks["wind_region_dataset"] = {
            "ready": False,
            "message": "Wind-region dataset is not usable; inspect the server logs.",
        }

    try:
        md_data = load_md_tables()
        if not isinstance(md_data, dict) or not isinstance(md_data.get("tables"), dict):
            raise TypeError("Md lookup data must contain a tables object")
        tables = md_data["tables"]
        required_md_regions = configured_region_names or [
            "A0",
            "A1",
            "A2",
            "A3",
            "A4",
            "A5",
            "B1",
            "B2",
            "C",
            "D",
        ]
        missing_regions = [
            region
            for region in required_md_regions
            if not all(
                _valid_lookup_number(
                    tables.get(table_region_key(region, tables), {}).get(direction)
                    if isinstance(tables.get(table_region_key(region, tables)), dict)
                    else None,
                    minimum=0,
                    maximum=10,
                )
                for direction in DIRECTIONS
            )
        ]
        metadata_reviewed = lookup_is_reviewed(md_data)
        md_ready = metadata_reviewed and not missing_regions
        checks["direction_multiplier_table"] = {
            "ready": md_ready,
            "reviewed": metadata_reviewed,
            "missing_regions": missing_regions,
            "message": (
                "Reviewed Md rows cover every configured wind-region label."
                if md_ready
                else "Reviewed Md rows are missing for one or more configured wind regions."
            ),
        }
    except Exception:
        LOGGER.exception("Direction multiplier readiness check failed")
        checks["direction_multiplier_table"] = {
            "ready": False,
            "message": "Direction multiplier table is not usable; inspect the server logs.",
        }

    try:
        vr_data = load_vr_tables()
        if not isinstance(vr_data, dict) or not isinstance(vr_data.get("tables"), dict):
            raise TypeError("VR lookup data must contain a tables object")
        vr_tables = vr_data["tables"]
        vr_reviewed = lookup_is_reviewed(vr_data)
        missing_vr_regions = [
            region for region in ("A", "B", "C", "D") if not _valid_vr_table(vr_tables.get(region))
        ]
        vr_ready = vr_reviewed and not missing_vr_regions
        checks["regional_wind_speed_table"] = {
            "ready": vr_ready,
            "reviewed": vr_reviewed,
            "missing_regions": missing_vr_regions,
            "message": (
                "Reviewed VR tables cover Australian regions A-D."
                if vr_ready
                else "Reviewed VR lookup data is missing or invalid."
            ),
        }
    except Exception:
        LOGGER.exception("Regional wind speed readiness check failed")
        checks["regional_wind_speed_table"] = {
            "ready": False,
            "message": "Regional wind speed table is not usable; inspect the server logs.",
        }

    checks["terrain_height_multiplier_table"] = _standards_lookup_readiness(
        loader=load_mzcat_table,
        validator=mzcat_lookup_issues,
        label="Mz,cat Table 4.1",
    )
    checks["shielding_multiplier_table"] = _standards_lookup_readiness(
        loader=load_ms_table,
        validator=shielding_lookup_issues,
        label="Ms Table 4.2",
    )

    try:
        provider = _dem_provider()
        cache_dir = getattr(provider, "cache_dir", None)
        dem_ready = cache_dir is None or (
            Path(cache_dir).is_dir() and os.access(cache_dir, os.W_OK)
        )
        checks["dem_provider"] = {
            "ready": dem_ready,
            "provider": provider.__class__.__name__,
            "message": (
                "DEM provider and cache are usable."
                if dem_ready
                else "DEM cache is not a writable directory."
            ),
        }
    except Exception:
        LOGGER.exception("DEM provider readiness check failed")
        checks["dem_provider"] = {
            "ready": False,
            "message": "DEM provider configuration is not usable; inspect the server logs.",
        }
    checks["completed_result_signing"] = result_signing_readiness()
    ready = all(check["ready"] for check in checks.values())
    return {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
    }


def _valid_lookup_number(value: Any, *, minimum: float, maximum: float) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and minimum < float(value) <= maximum
    )


def _standards_lookup_readiness(
    *,
    loader: Callable[[], dict[str, Any]],
    validator: Callable[..., list[str]],
    label: str,
) -> dict[str, Any]:
    """Return a health check for one reviewed, digest-protected lookup table."""

    try:
        data = loader()
        issues = validator(data, require_reviewed=True)
        source = data.get("source") if isinstance(data, dict) else None
        reviewed = isinstance(source, dict) and lookup_is_reviewed(data)
        ready = not issues
        return {
            "ready": ready,
            "reviewed": reviewed,
            "values_sha256": data.get("values_sha256") if isinstance(data, dict) else None,
            "issues": issues,
            "message": (
                f"Reviewed {label} data passed structure and digest checks."
                if ready
                else f"{label} data failed review, structure, or digest checks."
            ),
        }
    except Exception:
        LOGGER.exception("%s readiness check failed", label)
        return {
            "ready": False,
            "reviewed": False,
            "issues": ["lookup data could not be loaded"],
            "message": f"{label} data is not usable; inspect the server logs.",
        }


def _valid_vr_table(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    ultimate = value.get("ultimate")
    serviceability = value.get("serviceability")
    return (
        isinstance(ultimate, dict)
        and bool(ultimate)
        and all(_valid_lookup_number(item, minimum=0, maximum=200) for item in ultimate.values())
        and isinstance(serviceability, dict)
        and bool(serviceability)
        and all(
            _valid_lookup_number(item, minimum=0, maximum=200) for item in serviceability.values()
        )
    )


def _obstruction_request_from_combined(
    request: CombinedMapRequest,
) -> ObstructionInventoryRequest:
    return ObstructionInventoryRequest(
        address=request.address,
        latitude=request.latitude,
        longitude=request.longitude,
        radius_m=request.obstruction_radius_m,
        building_height_m=request.reference_height_m,
        subject_base_rl_m=getattr(request, "base_rl_m", None),
        default_storey_height_m=request.default_storey_height_m,
        residential_storey_height_m=request.residential_storey_height_m,
        residential_two_storey_height_m=request.residential_two_storey_height_m,
        commercial_storey_height_m=request.commercial_storey_height_m,
        manual_overrides=request.manual_overrides,
        reviewed_footprints=request.reviewed_footprints,
        map_display_mode=request.map_display_mode,
        map_max_display_obstructions=request.map_max_display_obstructions,
    )


def _run_obstruction_inventory_for_site(
    request: CombinedMapRequest,
    site_result: SiteAnalysisResult,
    *,
    footprints: list[dict[str, Any]] | None = None,
) -> ObstructionInventoryResult:
    """Reuse one resolved site for terrain and obstruction calculations."""

    obstruction_request = _obstruction_request_from_combined(request)
    if footprints is None:
        result = run_obstruction_inventory(obstruction_request, resolved_site=site_result.site)
    else:
        result = run_obstruction_inventory(
            obstruction_request,
            footprints=footprints,
            resolved_site=site_result.site,
        )
    return result


def _obstruction_inventory_public_data(result: ObstructionInventoryResult) -> dict[str, Any]:
    """Return the consumer payload without repeated raw geometry or local paths."""

    return PublicObstructionInventoryResult.model_validate(result.model_dump()).model_dump(
        mode="json"
    )


def _wind_region_debug_site(
    address: str | None,
    latitude: float | None,
    longitude: float | None,
) -> SiteLocation:
    has_coords = latitude is not None and longitude is not None
    if has_coords:
        return SiteLocation(
            latitude=latitude,
            longitude=longitude,
            ground_elevation_m=0.0,
            source="debug coordinates",
            display_name=address,
        )
    if latitude is not None or longitude is not None:
        raise ValueError("Provide both latitude and longitude when using coordinates.")
    if address and address.strip():
        request = SiteAnalysisRequest(address=address, building_height_m=10)
        return run_site_analysis(request, _dem_provider()).site
    raise ValueError("Provide either address or latitude and longitude.")


def _apply_mzcat_reviews(
    evidence: TerrainCategoryEvidenceResult,
    reviews: list[MzCatReviewSelection],
) -> TerrainCategoryEvidenceResult:
    if not reviews:
        return evidence
    reviews_by_direction = {review.direction: review for review in reviews}
    reviewed_assessments = []
    for assessment in evidence.mzcat_assessment:
        review = reviews_by_direction.get(assessment.direction)
        if review is None:
            reviewed_assessments.append(assessment)
            continue
        reviewed_assessments.append(
            assessment.model_copy(
                update={
                    "final_terrain_category": review.final_terrain_category,
                    "final_mzcat": review.final_mzcat,
                    "reviewed_by": review.reviewed_by,
                    "review_notes": review.review_notes,
                    "review_status": review.review_status,
                },
            )
        )
    return evidence.model_copy(update={"mzcat_assessment": reviewed_assessments})


app = create_app()
