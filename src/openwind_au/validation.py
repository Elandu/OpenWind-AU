"""Qualitative validation runner for known representative sites."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from jinja2 import Template
from pydantic import BaseModel, Field

from openwind_au.analysis import run_site_analysis
from openwind_au.dem import DEMProvider, SRTMProvider
from openwind_au.models import SiteAnalysisRequest, SiteAnalysisResult

ValidationStatus = Literal["pass", "warn", "fail"]
ExpectedFeatureType = Literal[
    "ridge",
    "hill",
    "escarpment",
    "valley",
    "no significant feature",
]

CALCULATION_BASIS_DOC_PATH = Path("docs/calculation-basis.md")
CALCULATION_BASIS_REPORT_TEXT = (
    "Calculation basis and data lineage reference: docs/calculation-basis.md."
)

VALIDATION_DISCLAIMER = (
    "Validation cases are broad qualitative checks against representative Australian terrain "
    "settings. They are not proof of AS/NZS 1170.2 compliance, design accuracy, or suitability "
    "for a specific project."
)


class ValidationCase(BaseModel):
    """Known representative site used for qualitative validation."""

    case_id: str
    site_name: str
    latitude: float = Field(ge=-44.5, le=-9.0)
    longitude: float = Field(ge=112.0, le=154.5)
    building_height_m: float = Field(gt=0)
    expected_general_terrain_description: str
    expected_topographic_behaviour: str
    notes: str
    source_reference: str
    expected_feature_types: tuple[ExpectedFeatureType, ...]


class ValidationCaseResult(BaseModel):
    """Validation outcome for one representative site."""

    case: ValidationCase
    status: ValidationStatus
    status_reasons: list[str]
    detected_feature_types: list[str]
    candidate_feature_count: int
    max_h_m: float
    max_average_upwind_slope: float
    analysis: SiteAnalysisResult


class ValidationReport(BaseModel):
    """Complete validation run report."""

    generated_at_utc: str
    disclaimer: str
    summary: dict[str, int]
    results: list[ValidationCaseResult]


DEFAULT_VALIDATION_CASES: tuple[ValidationCase, ...] = (
    ValidationCase(
        case_id="au-flat-suburban-blacktown-nsw",
        site_name="Blacktown suburban plain, NSW",
        latitude=-33.771,
        longitude=150.905,
        building_height_m=10,
        expected_general_terrain_description=(
            "Low-relief suburban terrain on the Cumberland Plain."
        ),
        expected_topographic_behaviour=(
            "Profiles should generally screen as flat or no significant feature."
        ),
        notes=(
            "Representative suburban validation case only; not tied to a specific project site."
        ),
        source_reference="Public map/topographic context for western Sydney plain.",
        expected_feature_types=("no significant feature",),
    ),
    ValidationCase(
        case_id="au-coastal-escarpment-stanwell-tops-nsw",
        site_name="Stanwell Tops / Illawarra Escarpment, NSW",
        latitude=-34.226,
        longitude=150.985,
        building_height_m=10,
        expected_general_terrain_description=(
            "Coastal escarpment setting with strong relief toward the Illawarra coast."
        ),
        expected_topographic_behaviour=(
            "At least one profile should indicate escarpment, hill, ridge, or valley behaviour."
        ),
        notes="Broad coastal-escarpment example for qualitative screening.",
        source_reference="Public map/topographic context for the Illawarra Escarpment.",
        expected_feature_types=("escarpment", "hill", "ridge", "valley"),
    ),
    ValidationCase(
        case_id="au-hilltop-mount-coot-tha-qld",
        site_name="Mount Coot-tha hilltop, QLD",
        latitude=-27.475,
        longitude=152.973,
        building_height_m=10,
        expected_general_terrain_description=(
            "Hilltop and ridgeline terrain west of central Brisbane."
        ),
        expected_topographic_behaviour=(
            "Profiles should indicate hill or ridge behaviour in at least one direction."
        ),
        notes="Representative hilltop example; qualitative behaviour only.",
        source_reference="Public map/topographic context for Mount Coot-tha.",
        expected_feature_types=("hill", "ridge", "escarpment"),
    ),
    ValidationCase(
        case_id="au-valley-kangaroo-valley-nsw",
        site_name="Kangaroo Valley valley floor, NSW",
        latitude=-34.736,
        longitude=150.535,
        building_height_m=10,
        expected_general_terrain_description=(
            "Valley-floor setting with surrounding elevated terrain."
        ),
        expected_topographic_behaviour=(
            "Profiles should indicate valley behaviour or nearby rising terrain."
        ),
        notes="Representative valley example; not a calibrated engineering benchmark.",
        source_reference="Public map/topographic context for Kangaroo Valley.",
        expected_feature_types=("valley", "hill", "ridge", "escarpment"),
    ),
    ValidationCase(
        case_id="au-inland-flat-hay-nsw",
        site_name="Hay plains inland flat site, NSW",
        latitude=-34.509,
        longitude=144.843,
        building_height_m=10,
        expected_general_terrain_description=(
            "Very low-relief inland plain terrain in the Riverina."
        ),
        expected_topographic_behaviour=(
            "Profiles should generally screen as flat or no significant feature."
        ),
        notes="Representative inland-flat validation case only.",
        source_reference="Public map/topographic context for the Hay plains.",
        expected_feature_types=("no significant feature",),
    ),
)


def run_validation_cases(
    cases: tuple[ValidationCase, ...] | list[ValidationCase] = DEFAULT_VALIDATION_CASES,
    dem_provider: DEMProvider | None = None,
    radius_m: int = 2000,
    sample_interval_m: float = 100,
) -> ValidationReport:
    """Run the normal site analysis workflow for all validation cases."""

    provider = dem_provider or SRTMProvider()
    results: list[ValidationCaseResult] = []
    for case in cases:
        request = SiteAnalysisRequest(
            latitude=case.latitude,
            longitude=case.longitude,
            building_height_m=case.building_height_m,
            radius_m=radius_m,
            sample_interval_m=sample_interval_m,
        )
        analysis = run_site_analysis(request, provider)
        results.append(evaluate_validation_case(case, analysis))

    summary = {"pass": 0, "warn": 0, "fail": 0}
    for result in results:
        summary[result.status] += 1
    return ValidationReport(
        generated_at_utc=datetime.now(UTC).isoformat(),
        disclaimer=VALIDATION_DISCLAIMER,
        summary=summary,
        results=results,
    )


def evaluate_validation_case(
    case: ValidationCase,
    analysis: SiteAnalysisResult,
) -> ValidationCaseResult:
    """Compare detected topography against broad qualitative expectations."""

    significant_features = [
        feature for feature in analysis.features if feature.feature_type != "no significant feature"
    ]
    detected_types = sorted({feature.feature_type for feature in significant_features})
    expected_types = set(case.expected_feature_types)
    max_h_m = max((feature.h_m for feature in significant_features), default=0.0)
    max_slope = max(
        (feature.average_upwind_slope for feature in significant_features),
        default=0.0,
    )

    status: ValidationStatus
    reasons: list[str]
    if expected_types == {"no significant feature"}:
        status, reasons = _evaluate_flat_expectation(significant_features, max_h_m)
    else:
        status, reasons = _evaluate_feature_expectation(
            detected_types=detected_types,
            expected_types=expected_types,
            candidate_count=len(significant_features),
        )

    return ValidationCaseResult(
        case=case,
        status=status,
        status_reasons=reasons,
        detected_feature_types=detected_types or ["no significant feature"],
        candidate_feature_count=len(significant_features),
        max_h_m=max_h_m,
        max_average_upwind_slope=max_slope,
        analysis=analysis,
    )


def validation_report_to_json(report: ValidationReport) -> dict:
    """Convert a validation report into JSON-serialisable data."""

    return json.loads(report.model_dump_json())


def render_validation_report_html(report: ValidationReport) -> str:
    """Render an HTML validation report."""

    return VALIDATION_REPORT_TEMPLATE.render(
        report=report,
        calculation_basis_reference=calculation_basis_report_reference(),
    )


def calculation_basis_report_reference() -> str | None:
    """Return the calculation-basis report note when the docs file is available."""

    repo_root = Path(__file__).resolve().parents[2]
    if (repo_root / CALCULATION_BASIS_DOC_PATH).exists():
        return CALCULATION_BASIS_REPORT_TEXT
    return None


def _evaluate_flat_expectation(
    significant_features: list,
    max_h_m: float,
) -> tuple[ValidationStatus, list[str]]:
    if not significant_features:
        return "pass", ["No significant candidate features were detected."]
    if max_h_m < 15:
        return "warn", [
            "Low-relief candidate features were detected in a site expected to be broadly flat."
        ]
    return "fail", [
        "Candidate relief is higher than expected for a broad flat-terrain validation case."
    ]


def _evaluate_feature_expectation(
    detected_types: list[str],
    expected_types: set[str],
    candidate_count: int,
) -> tuple[ValidationStatus, list[str]]:
    if not candidate_count:
        return "fail", ["No candidate topographic feature was detected."]
    overlap = expected_types.intersection(detected_types)
    if overlap:
        return "pass", [
            "Detected candidate feature type overlaps the broad expected behaviour: "
            f"{', '.join(sorted(overlap))}."
        ]
    return "warn", [
        "Candidate features were detected, but their broad type did not match the expected "
        "behaviour."
    ]


VALIDATION_REPORT_TEMPLATE = Template(
    """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>OpenWind-AU Validation Report</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 32px; color: #202124; }
    h1, h2 { color: #17324d; }
    table { border-collapse: collapse; width: 100%; margin: 16px 0; }
    th, td { border: 1px solid #d0d7de; padding: 8px; text-align: left; vertical-align: top; }
    th { background: #f6f8fa; }
    .disclaimer { border-left: 4px solid #b42318; padding: 12px; background: #fff4f2; }
    .pass { color: #047857; font-weight: 700; }
    .warn { color: #b45309; font-weight: 700; }
    .fail { color: #b42318; font-weight: 700; }
  </style>
</head>
<body>
  <h1>OpenWind-AU Validation Report</h1>
  <p class="disclaimer">{{ report.disclaimer }}</p>
  {% if calculation_basis_reference %}
  <p>{{ calculation_basis_reference }}</p>
  {% endif %}
  <p>Generated: {{ report.generated_at_utc }}</p>

  <h2>Summary</h2>
  <table>
    <tr><th>Pass</th><th>Warning</th><th>Fail</th></tr>
    <tr>
      <td class="pass">{{ report.summary.pass }}</td>
      <td class="warn">{{ report.summary.warn }}</td>
      <td class="fail">{{ report.summary.fail }}</td>
    </tr>
  </table>

  <h2>Validation Cases</h2>
  <table>
    <tr>
      <th>Status</th><th>Case</th><th>Expected terrain</th><th>Expected behaviour</th>
      <th>Detected feature types</th><th>Max H</th><th>Reasons</th><th>Source/reference</th>
    </tr>
    {% for result in report.results %}
    <tr>
      <td class="{{ result.status }}">{{ result.status }}</td>
      <td>
        <strong>{{ result.case.site_name }}</strong><br>
        {{ result.case.case_id }}<br>
        {{ "%.6f"|format(result.case.latitude) }},
        {{ "%.6f"|format(result.case.longitude) }}
      </td>
      <td>{{ result.case.expected_general_terrain_description }}</td>
      <td>{{ result.case.expected_topographic_behaviour }}</td>
      <td>{{ result.detected_feature_types|join(", ") }}</td>
      <td>{{ "%.2f"|format(result.max_h_m) }} m</td>
      <td>{{ result.status_reasons|join(" ") }}</td>
      <td>{{ result.case.source_reference }}</td>
    </tr>
    {% endfor %}
  </table>
</body>
</html>
"""
)
