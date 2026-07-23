"""Focused regression tests for public API production hardening."""

from __future__ import annotations

import asyncio
import inspect

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import openwind_au.api as api_module
from openwind_au import __version__
from openwind_au.geo import geocode_address, geocode_address_suggestions
from openwind_au.http_client import APPLICATION_USER_AGENT
from openwind_au.http_security import (
    COMPLETED_RESULT_REPORT_PATHS,
    DEPLOYMENT_ENVIRONMENT_ENV,
    MAX_JSON_REQUEST_BYTES,
    TRUSTED_HOSTS_ENV,
    BoundedJsonRequestMiddleware,
)
from openwind_au.models import (
    MAX_CLASS_MULTIPLIER_OVERRIDES,
    MAX_REVIEWED_GEOMETRY_POSITIONS,
    ObstructionInventoryRequest,
    ObstructionManualOverride,
    ReviewedFootprint,
    WindWorkflowRequest,
)
from openwind_au.obstructions import (
    query_building_footprints,
    query_building_footprints_with_debug,
)

SITE_PAYLOAD = {
    "latitude": -33.86,
    "longitude": 151.21,
    "building_height_m": 10.0,
}


def test_bounded_request_replay_delegates_disconnect_after_body() -> None:
    received_by_app: list[dict] = []
    original_messages = iter(
        [
            {"type": "http.request", "body": b'{"value":1}', "more_body": False},
            {"type": "http.disconnect"},
        ]
    )

    async def receive() -> dict:
        return next(original_messages)

    async def send(_message: dict) -> None:
        return None

    async def downstream(_scope: dict, replay_receive, _send) -> None:
        received_by_app.append(await replay_receive())
        received_by_app.append(await replay_receive())

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/stream",
        "headers": [(b"content-type", b"application/json")],
    }

    asyncio.run(BoundedJsonRequestMiddleware(downstream)(scope, receive, send))

    assert received_by_app == [
        {"type": "http.request", "body": b'{"value":1}', "more_body": False},
        {"type": "http.disconnect"},
    ]


def test_completed_result_report_routes_have_a_larger_bounded_body_budget() -> None:
    body = b'{"value":"1234567890"}'

    async def exercise(path: str) -> tuple[list[dict], list[dict]]:
        original_messages = iter(
            [
                {"type": "http.request", "body": body, "more_body": False},
                {"type": "http.disconnect"},
            ]
        )
        received_by_app: list[dict] = []
        sent: list[dict] = []

        async def receive() -> dict:
            return next(original_messages)

        async def send(message: dict) -> None:
            sent.append(message)

        async def downstream(_scope: dict, replay_receive, _send) -> None:
            received_by_app.append(await replay_receive())

        scope = {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"content-type", b"application/json")],
        }
        middleware = BoundedJsonRequestMiddleware(
            downstream,
            max_bytes=8,
            completed_result_max_bytes=64,
        )
        await middleware(scope, receive, send)
        return received_by_app, sent

    for path in COMPLETED_RESULT_REPORT_PATHS:
        received, sent = asyncio.run(exercise(path))
        assert received == [{"type": "http.request", "body": body, "more_body": False}]
        assert sent == []

    received, sent = asyncio.run(exercise("/api/wind-workflow"))
    assert received == []
    response_start = next(message for message in sent if message["type"] == "http.response.start")
    assert response_start["status"] == 413


def test_json_request_size_is_enforced_before_route_validation() -> None:
    client = TestClient(api_module.create_app())
    body = b'{"padding":"' + (b"x" * MAX_JSON_REQUEST_BYTES) + b'"}'

    response = client.post(
        "/api/analyse",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert len(response.content) < 200
    assert b"x" * 100 not in response.content

    content_type_bypass = client.post(
        "/api/analyse",
        content=b"x" * (MAX_JSON_REQUEST_BYTES + 1),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert content_type_bypass.status_code == 413


@pytest.mark.parametrize(
    "body, expected_detail",
    [
        (
            b'{"latitude":-33.86,"latitude":-34.0,"longitude":151.21,"building_height_m":10}',
            "duplicate object member",
        ),
        (
            b'{"latitude":-33.86,"longitude":151.21,'
            b'"building_height_m":10,"nested":{"value":1,"value":2}}',
            "duplicate object member",
        ),
        (
            b'{"latitude":-33.86,"longitude":151.21,"building_height_m":NaN}',
            "must be finite",
        ),
        (
            b'{"latitude":-33.86,"longitude":151.21,"building_height_m":Infinity}',
            "must be finite",
        ),
        (
            b'{"latitude":-33.86,"longitude":151.21,"building_height_m":1e999}',
            "must be finite",
        ),
    ],
)
def test_json_duplicate_members_and_nonfinite_numbers_are_rejected(
    body: bytes,
    expected_detail: str,
) -> None:
    response = TestClient(api_module.create_app()).post(
        "/api/analyse",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert expected_detail in response.json()["detail"]


def test_duplicate_json_is_rejected_when_content_type_is_omitted() -> None:
    response = TestClient(api_module.create_app()).post(
        "/api/analyse",
        content=(b'{"latitude":-33.86,"latitude":-34.0,"longitude":151.21,"building_height_m":10}'),
    )

    assert response.status_code == 400
    assert "duplicate object member" in response.json()["detail"]


def test_validation_errors_do_not_reflect_submitted_values_and_are_capped() -> None:
    secret = "consumer-secret-value"
    payload = {f"unknown_{index}": f"{secret}-{index}" for index in range(100)}

    response = TestClient(api_module.create_app()).post("/api/analyse", json=payload)

    assert response.status_code == 422
    assert secret not in response.text
    errors = response.json()["detail"]
    assert len(errors) == 51
    assert errors[-1]["type"] == "too_many_validation_errors"
    assert all(set(error) == {"type", "loc", "msg"} for error in errors)


def test_dynamic_responses_are_no_store_and_security_headers_cover_static() -> None:
    client = TestClient(api_module.create_app())

    dynamic = client.get("/health/live")
    static = client.get("/static/styles.css")
    plotly = client.get("/vendor/plotly.min.js")

    for response in (dynamic, static, plotly):
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Permissions-Policy"] == (
            "camera=(), geolocation=(), microphone=()"
        )
    assert dynamic.headers["Cache-Control"] == "no-store"
    assert static.headers.get("Cache-Control") != "no-store"
    assert plotly.headers["Cache-Control"] == "public, max-age=0, must-revalidate"


def test_default_trusted_hosts_keep_test_client_usable_and_reject_other_hosts() -> None:
    client = TestClient(api_module.create_app())

    assert client.get("/health/live").status_code == 200
    rejected = client.get("/health/live", headers={"Host": "attacker.example"})

    assert rejected.status_code == 400
    assert rejected.headers["Cache-Control"] == "no-store"


def test_production_requires_explicit_trusted_hosts(monkeypatch) -> None:
    monkeypatch.setenv(DEPLOYMENT_ENVIRONMENT_ENV, "production")
    monkeypatch.delenv(TRUSTED_HOSTS_ENV, raising=False)

    with pytest.raises(RuntimeError, match=TRUSTED_HOSTS_ENV):
        api_module.create_app()


def test_trusted_host_configuration_rejects_ports(monkeypatch) -> None:
    monkeypatch.setenv(TRUSTED_HOSTS_ENV, "api.example:8000")

    with pytest.raises(RuntimeError, match="omit ports"):
        api_module.create_app()


def test_production_disables_docs_and_fails_closed_when_not_ready(monkeypatch) -> None:
    readiness = {"status": "not_ready", "checks": {}}
    monkeypatch.setenv(DEPLOYMENT_ENVIRONMENT_ENV, "production")
    monkeypatch.setenv(TRUSTED_HOSTS_ENV, "api.example")
    monkeypatch.setattr(api_module, "readiness_report", lambda: readiness)
    client = TestClient(api_module.create_app(), base_url="http://api.example")

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/health/live").status_code == 200
    assert client.get("/health").status_code == 503
    assert client.post("/api/wind-workflow", json={}).status_code == 503
    assert client.post("/api/wind-workflow/result/report/html", json={}).status_code == 503
    assert client.post("/api/geocode/suggest", json={"query": "x"}).status_code == 422
    assert client.get("/health/live", headers={"Host": "attacker.example"}).status_code == 400

    readiness["status"] = "ready"
    assert client.post("/api/wind-workflow", json={}).status_code == 422


def test_request_models_reject_nonfinite_values_and_duplicate_review_ids() -> None:
    with pytest.raises(ValidationError, match="finite"):
        ObstructionInventoryRequest(
            latitude=-33.86,
            longitude=151.21,
            subject_base_rl_m=float("nan"),
        )
    with pytest.raises(ValidationError, match="finite"):
        WindWorkflowRequest(**SITE_PAYLOAD, base_rl_m=float("inf"))

    override = ObstructionManualOverride(obstruction_id="building-1", height_m=10.0)
    with pytest.raises(ValidationError, match="duplicate obstruction_id"):
        ObstructionInventoryRequest(
            latitude=-33.86,
            longitude=151.21,
            manual_overrides=[override, override],
        )


def test_reviewed_geometry_is_bounded_finite_closed_and_unique() -> None:
    ring = [
        [151.20, -33.87],
        [151.21, -33.87],
        [151.21, -33.86],
        [151.20, -33.87],
    ]
    footprint = ReviewedFootprint(
        id="reviewed-1",
        geometry={"type": "Polygon", "coordinates": [ring]},
    )

    with pytest.raises(ValidationError, match="duplicate id"):
        ObstructionInventoryRequest(
            latitude=-33.86,
            longitude=151.21,
            reviewed_footprints=[footprint, footprint],
        )
    with pytest.raises(ValidationError, match="must be closed"):
        ReviewedFootprint(
            id="open-ring",
            geometry={"type": "Polygon", "coordinates": [[*ring[:-1], [151.22, -33.85]]]},
        )
    with pytest.raises(ValidationError, match="must be finite"):
        ReviewedFootprint(
            id="nonfinite",
            geometry={
                "type": "Polygon",
                "coordinates": [
                    [
                        [151.20, -33.87],
                        [151.21, -33.87],
                        [float("nan"), -33.86],
                        [151.20, -33.87],
                    ]
                ],
            },
        )

    oversized_ring = [[151.20, -33.87]] * (MAX_REVIEWED_GEOMETRY_POSITIONS + 1)
    with pytest.raises(ValidationError, match="at most"):
        ReviewedFootprint(
            id="too-many-positions",
            geometry={"type": "Polygon", "coordinates": [oversized_ring]},
        )


def test_workflow_strings_and_override_lists_have_explicit_bounds() -> None:
    with pytest.raises(ValidationError, match="at most 200 characters"):
        WindWorkflowRequest(**SITE_PAYLOAD, project_number="x" * 201)

    overrides = [
        {
            "direction": "N",
            "terrain_category": "TC2",
            "reason": "reviewed",
        }
    ] * (MAX_CLASS_MULTIPLIER_OVERRIDES + 1)
    with pytest.raises(ValidationError, match="at most 8 items"):
        WindWorkflowRequest(**SITE_PAYLOAD, class_multiplier_overrides=overrides)


def test_outbound_user_agent_is_version_derived_and_shared() -> None:
    assert f"OpenWind-AU/{__version__}" == APPLICATION_USER_AGENT
    for function in (
        geocode_address,
        geocode_address_suggestions,
        query_building_footprints,
        query_building_footprints_with_debug,
    ):
        assert inspect.signature(function).parameters["user_agent"].default == (
            APPLICATION_USER_AGENT
        )
