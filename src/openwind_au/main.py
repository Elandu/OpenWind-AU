"""Command line entry point for OpenWind-AU."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from typing import Any

import uvicorn


def main(argv: Sequence[str] | None = None) -> int:
    """Run the API server or verify deployment readiness."""

    parser = argparse.ArgumentParser(
        prog="openwind-au",
        description="Run or preflight the OpenWind-AU assessment service.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("serve", "check"),
        default="serve",
        help="serve the API (default) or check deployment readiness",
    )
    parser.add_argument(
        "--host",
        type=_host,
        default=None,
        help="API bind host (default: OPENWIND_HOST or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=_port,
        default=None,
        help="API bind port (default: OPENWIND_PORT or 8000)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit machine-readable JSON for the check command",
    )
    args = parser.parse_args(argv)

    if args.command == "check":
        if args.host is not None or args.port is not None:
            parser.error("--host and --port are only valid with the serve command")
        return _run_readiness_check(json_output=args.json_output)
    if args.json_output:
        parser.error("--json is only valid with the check command")

    host = args.host
    if host is None:
        try:
            host = _host(os.environ.get("OPENWIND_HOST", "127.0.0.1"))
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
    port = args.port
    if port is None:
        try:
            port = _port(os.environ.get("OPENWIND_PORT", "8000"))
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))

    uvicorn.run("openwind_au.api:app", host=host, port=port, reload=False)
    return 0


def _port(value: str) -> int:
    """Parse one valid TCP port for argparse and environment defaults."""

    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _host(value: str) -> str:
    """Reject an empty API bind host."""

    host = value.strip()
    if not host:
        raise argparse.ArgumentTypeError("host must not be empty")
    return host


def _run_readiness_check(*, json_output: bool) -> int:
    """Print the shared readiness report and return a shell-friendly status."""

    from openwind_au.api import readiness_report

    report = readiness_report()
    if json_output:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_readiness_summary(report)
    return 0 if report.get("status") == "ready" else 1


def _print_readiness_summary(report: dict[str, Any]) -> None:
    """Render a compact operator summary without exposing private diagnostics."""

    status = str(report.get("status", "not_ready"))
    print(f"OpenWind-AU readiness: {status.upper()}")
    checks = report.get("checks")
    if not isinstance(checks, dict):
        return
    for name, raw_check in checks.items():
        check = raw_check if isinstance(raw_check, dict) else {}
        marker = "PASS" if check.get("ready") is True else "FAIL"
        detail = check.get("message") or check.get("detail") or "No detail available."
        print(f"[{marker}] {name}: {detail}")


if __name__ == "__main__":
    raise SystemExit(main())
