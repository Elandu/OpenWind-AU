"""Tests for the OpenWind-AU operator CLI."""

from __future__ import annotations

import json

import pytest

import openwind_au.api as api_module
import openwind_au.main as main_module


def readiness(*, ready: bool) -> dict:
    return {
        "status": "ready" if ready else "not_ready",
        "checks": {
            "wind_region_dataset": {
                "ready": ready,
                "message": "Production dataset is available." if ready else "Configure data.",
            },
            "completed_result_signing": {
                "ready": ready,
                "detail": "Signing is configured." if ready else "Configure signing.",
            },
        },
    }


@pytest.mark.parametrize(("ready", "expected_exit"), [(True, 0), (False, 1)])
def test_check_command_uses_shared_readiness_report(
    monkeypatch,
    capsys,
    ready: bool,
    expected_exit: int,
) -> None:
    monkeypatch.setattr(api_module, "readiness_report", lambda: readiness(ready=ready))

    exit_code = main_module.main(["check"])

    assert exit_code == expected_exit
    output = capsys.readouterr().out
    assert f"OpenWind-AU readiness: {'READY' if ready else 'NOT_READY'}" in output
    assert ("[PASS]" if ready else "[FAIL]") in output


def test_check_command_supports_machine_readable_json(monkeypatch, capsys) -> None:
    report = readiness(ready=False)
    monkeypatch.setattr(api_module, "readiness_report", lambda: report)

    exit_code = main_module.main(["check", "--json"])

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out) == report


def test_check_command_ignores_serve_environment(monkeypatch, capsys) -> None:
    report = readiness(ready=True)
    monkeypatch.setenv("OPENWIND_HOST", " ")
    monkeypatch.setenv("OPENWIND_PORT", "invalid")
    monkeypatch.setattr(api_module, "readiness_report", lambda: report)

    assert main_module.main(["check", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == report


@pytest.mark.parametrize("option", [["--host", "127.0.0.1"], ["--port", "8000"]])
def test_check_command_rejects_serve_options(option: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main_module.main(["check", *option])

    assert exc_info.value.code == 2


def test_serve_command_preserves_defaults_and_accepts_overrides(monkeypatch) -> None:
    calls = []
    monkeypatch.delenv("OPENWIND_HOST", raising=False)
    monkeypatch.delenv("OPENWIND_PORT", raising=False)
    monkeypatch.setattr(
        main_module.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs))
    )

    assert main_module.main([]) == 0
    assert main_module.main(["serve", "--host", "0.0.0.0", "--port", "8080"]) == 0

    assert calls == [
        (("openwind_au.api:app",), {"host": "127.0.0.1", "port": 8000, "reload": False}),
        (("openwind_au.api:app",), {"host": "0.0.0.0", "port": 8080, "reload": False}),
    ]


def test_serve_command_uses_environment_defaults(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("OPENWIND_HOST", "0.0.0.0")
    monkeypatch.setenv("OPENWIND_PORT", "9000")
    monkeypatch.setattr(
        main_module.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs))
    )

    assert main_module.main([]) == 0

    assert calls == [(("openwind_au.api:app",), {"host": "0.0.0.0", "port": 9000, "reload": False})]


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_serve_command_rejects_invalid_ports(port: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main_module.main(["serve", "--port", port])

    assert exc_info.value.code == 2


def test_serve_command_rejects_invalid_environment_port(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_PORT", "invalid")

    with pytest.raises(SystemExit) as exc_info:
        main_module.main([])

    assert exc_info.value.code == 2


def test_serve_command_rejects_empty_environment_host(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_HOST", " ")

    with pytest.raises(SystemExit) as exc_info:
        main_module.main([])

    assert exc_info.value.code == 2


@pytest.mark.parametrize("arguments", [["serve", "--host", " "], ["serve", "--host="]])
def test_serve_command_rejects_empty_hosts(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main_module.main(arguments)

    assert exc_info.value.code == 2


def test_json_flag_is_rejected_for_serve() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main_module.main(["serve", "--json"])

    assert exc_info.value.code == 2
