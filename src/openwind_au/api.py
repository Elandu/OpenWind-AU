"""FastAPI application for OpenWind-AU."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from openwind_au.analysis import run_site_analysis
from openwind_au.calculation_validation import (
    calculation_validation_report_to_json,
    run_calculation_validation_cases,
)
from openwind_au.dem import SRTMProvider
from openwind_au.models import (
    CombinedMapRequest,
    MzCatAssessmentResult,
    MzCatReviewSelection,
    ObstructionInventoryRequest,
    ObstructionInventoryResult,
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
    render_terrain_category_report_html,
    render_wind_workflow_report_html,
    result_to_json,
    terrain_category_map_html,
    write_pdf_report,
)
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
    regional_wind_speed_assessment,
    run_wind_region_validation_cases,
    wind_region_map_html,
)
from openwind_au.wind_region import assess_wind_region, dataset_metadata, wind_region_debug
from openwind_au.wind_workflow import run_wind_workflow

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"


def create_app() -> FastAPI:
    """Create the FastAPI app."""

    app = FastAPI(
        title="OpenWind-AU",
        description=(
            "Preliminary wind site terrain and topographic analysis for Australian buildings."
        ),
        version="0.6.0",
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

    @app.post("/api/full-analysis")
    def full_analysis(request: TerrainCategoryEvidenceRequest) -> dict:
        """Run the browser workflow in one pass to avoid duplicate obstruction queries."""

        try:
            site_result, obstruction_result, evidence = _run_terrain_category_workflow(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "site_analysis": site_result,
            "obstruction_inventory": obstruction_result,
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
            site_result, obstruction_result, evidence = _run_terrain_category_workflow(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return run_wind_workflow(
            request=request,
            site_result=site_result,
            obstruction_result=obstruction_result,
            terrain_result=evidence,
        )

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

    @app.post("/api/wind-workflow/map", response_class=HTMLResponse)
    def wind_workflow_map(request: WindWorkflowRequest) -> str:
        try:
            site_result, obstruction_result, evidence = _run_terrain_category_workflow(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
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
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return assess_wind_region(site_result.site)

    @app.post("/api/wind-region/map", response_class=HTMLResponse)
    def wind_region_map(request: SiteAnalysisRequest) -> str:
        try:
            site_result = analyse(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        assessment = assess_wind_region(site_result.site)
        return wind_region_map_html(site_result.site, assessment)

    @app.get("/api/debug/wind-region/dataset")
    def wind_region_dataset_debug() -> dict:
        try:
            return dataset_metadata()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/debug/wind-region")
    def wind_region_debug_get(
        address: str | None = Query(default=None),
        latitude: float | None = Query(default=None),
        longitude: float | None = Query(default=None),
    ) -> dict:
        try:
            site = _wind_region_debug_site(address, latitude, longitude)
            return wind_region_debug(site)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/debug/wind-region")
    def wind_region_debug_post(request: SiteAnalysisRequest) -> dict:
        try:
            site_result = analyse(request)
            return wind_region_debug(site_result.site)
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

    @app.get("/api/obstructions/debug")
    def obstruction_debug(
        address: str | None = Query(default=None),
        latitude: float | None = Query(default=None),
        longitude: float | None = Query(default=None),
        radius_m: int = Query(default=500, ge=50, le=4000),
        building_height_m: float | None = Query(default=None, gt=0),
    ) -> dict:
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
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
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
            obstruction_result = run_obstruction_inventory(
                _obstruction_request_from_combined(request)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
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
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return evidence

    @app.post("/api/mzcat/assessment", response_model=MzCatAssessmentResult)
    def mzcat_assessment(request: TerrainCategoryEvidenceRequest) -> MzCatAssessmentResult:
        try:
            _site_result, _obstruction_result, evidence = _run_terrain_category_workflow(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return MzCatAssessmentResult(
            input=evidence.input,
            site=evidence.site,
            directions=evidence.mzcat_assessment,
            recommendation_mode=request.mzcat_recommendation_mode,
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
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return terrain_category_map_html(site_result, obstruction_result, evidence)

    @app.post("/api/terrain-category/report/html", response_class=HTMLResponse)
    def terrain_category_report_html(request: TerrainCategoryReportRequest) -> str:
        try:
            _site_result, _obstruction_result, evidence = _run_terrain_category_workflow(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
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

    @app.get("/api/calculation-validation")
    def calculation_validation_report() -> Response:
        content = json.dumps(
            calculation_validation_report_to_json(run_calculation_validation_cases()),
            indent=2,
        )
        return Response(content=content, media_type="application/json")

    @app.get("/api/reference-validation/7989")
    def reference_calc_7989_validation(apply_reference_overrides: bool = False) -> Response:
        class_overrides = (
            reference_calc_7989_class_overrides() if apply_reference_overrides else []
        )
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
        site_result = run_site_analysis(request, SRTMProvider())
        obstruction_result = run_obstruction_inventory(
            _obstruction_request_from_combined(request),
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
) -> tuple[SiteAnalysisResult, ObstructionInventoryResult, TerrainCategoryEvidenceResult]:
    site_result = run_site_analysis(request, SRTMProvider())
    obstruction_result = run_obstruction_inventory(_obstruction_request_from_combined(request))
    evidence = run_terrain_category_evidence(site_result, obstruction_result)
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
        site_result = run_site_analysis(request, SRTMProvider())
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

        obstruction_result = run_obstruction_inventory(_obstruction_request_from_combined(request))
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

        evidence = run_terrain_category_evidence(site_result, obstruction_result)
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
    except ValueError as exc:
        yield event("error", 100, str(exc), {"status_code": 400})
    except RuntimeError as exc:
        yield event("error", 100, str(exc), {"status_code": 502})


def _optional_wind_region(site_result: SiteAnalysisResult) -> WindRegionAssessment | None:
    try:
        return assess_wind_region(site_result.site)
    except ValueError:
        return None


def _obstruction_request_from_combined(
    request: CombinedMapRequest,
) -> ObstructionInventoryRequest:
    return ObstructionInventoryRequest(
        address=request.address,
        latitude=request.latitude,
        longitude=request.longitude,
        radius_m=request.obstruction_radius_m,
        building_height_m=request.building_height_m,
        default_storey_height_m=request.default_storey_height_m,
        residential_storey_height_m=request.residential_storey_height_m,
        residential_two_storey_height_m=request.residential_two_storey_height_m,
        commercial_storey_height_m=request.commercial_storey_height_m,
        manual_overrides=request.manual_overrides,
        reviewed_footprints=request.reviewed_footprints,
        map_display_mode=request.map_display_mode,
        map_max_display_obstructions=request.map_max_display_obstructions,
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
        return run_site_analysis(request, SRTMProvider()).site
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
