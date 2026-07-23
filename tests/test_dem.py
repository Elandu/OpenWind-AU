"""Tests for DEM helpers."""

from __future__ import annotations

import numpy as np
import pytest

from openwind_au.dem import (
    ArrayDEMProvider,
    OpenMeteoElevationProvider,
    SRTMProvider,
    configured_dem_provider,
    srtm_tile_name,
)
from openwind_au.errors import ServiceNotReadyError
from openwind_au.http_client import APPLICATION_USER_AGENT

TEST_LATITUDE = -30.25
TEST_LONGITUDE = 135.75


def test_srtm_tile_name_for_australia() -> None:
    assert srtm_tile_name(-33.86, 151.21) == "S34E151"
    assert srtm_tile_name(-12.4, 130.8) == "S13E130"


def test_array_dem_provider_interpolates() -> None:
    dem = ArrayDEMProvider(
        origin_latitude=0,
        origin_longitude=0,
        cell_size_deg=1,
        elevations_m=np.array([[100, 200], [300, 400]], dtype=float),
    )

    assert dem.elevation(-0.5, 0.5) == pytest.approx(250)


def test_open_meteo_elevation_provider_reads_first_elevation(monkeypatch) -> None:
    calls = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"elevation": [42.5]}

    def fake_get(url, params, headers, timeout):
        calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return Response()

    monkeypatch.setattr("openwind_au.dem.requests.get", fake_get)
    provider = OpenMeteoElevationProvider(base_url="https://example.test/elevation")

    assert provider.elevation(TEST_LATITUDE, TEST_LONGITUDE) == pytest.approx(42.5)
    assert provider.elevation(TEST_LATITUDE, TEST_LONGITUDE) == pytest.approx(42.5)
    assert len(calls) == 1
    assert calls[0]["url"] == "https://example.test/elevation"
    assert calls[0]["params"] == {"latitude": TEST_LATITUDE, "longitude": TEST_LONGITUDE}
    assert calls[0]["headers"] == {"User-Agent": APPLICATION_USER_AGENT}


def test_open_meteo_elevation_provider_rejects_missing_elevation(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"generationtime_ms": 1.2}

    def fake_get(url, params, headers, timeout):
        del url, params, headers, timeout
        return Response()

    monkeypatch.setattr("openwind_au.dem.requests.get", fake_get)
    provider = OpenMeteoElevationProvider()

    with pytest.raises(RuntimeError, match="Open-Meteo elevation"):
        provider.elevation(TEST_LATITUDE, TEST_LONGITUDE)


def test_open_meteo_elevation_provider_batches_and_caches_coordinates(monkeypatch) -> None:
    calls = []

    class Response:
        def __init__(self, elevations: list[float]) -> None:
            self._elevations = elevations

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"elevation": self._elevations}

    def fake_get(url, params, headers, timeout):
        assert headers == {"User-Agent": APPLICATION_USER_AGENT}
        del url, timeout
        latitude = params["latitude"]
        count = len(str(latitude).split(",")) if isinstance(latitude, str) else 1
        calls.append(params)
        return Response([float(len(calls))] * count)

    monkeypatch.setattr("openwind_au.dem.requests.get", fake_get)
    provider = OpenMeteoElevationProvider(base_url="https://example.test/elevation")
    points = [(-33.0 + index / 10_000, 151.0) for index in range(205)]

    first = provider.elevations(points)
    second = provider.elevations(points)

    assert len(first) == 205
    assert first == second
    assert len(calls) == 3
    assert [len(str(call["latitude"]).split(",")) for call in calls] == [100, 100, 5]


def test_open_meteo_elevation_provider_falls_back_to_curl(monkeypatch) -> None:
    commands = []

    def fake_get(url, params, headers, timeout):
        del url, params, headers, timeout
        raise RuntimeError("tls failure")

    class Completed:
        returncode = 0
        stdout = '{"elevation":[37]}'
        stderr = ""

    def fake_run(command, check, capture_output, text, timeout):
        commands.append(command)
        return Completed()

    monkeypatch.setattr("openwind_au.dem.requests.get", fake_get)
    monkeypatch.setattr("openwind_au.dem.shutil.which", lambda name: "curl.exe")
    monkeypatch.setattr("openwind_au.dem.subprocess.run", fake_run)
    provider = OpenMeteoElevationProvider(base_url="https://example.test/elevation")

    assert provider.elevation(TEST_LATITUDE, TEST_LONGITUDE) == pytest.approx(37)
    assert commands
    assert commands[0][commands[0].index("--user-agent") + 1] == APPLICATION_USER_AGENT
    assert commands[0][-1].startswith("https://example.test/elevation?")


def test_configured_dem_provider_defaults_to_srtm(monkeypatch) -> None:
    monkeypatch.delenv("OPENWIND_DEM_PROVIDER", raising=False)

    assert isinstance(configured_dem_provider(), SRTMProvider)


def test_configured_dem_provider_accepts_open_meteo(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_DEM_PROVIDER", "open-meteo")

    assert isinstance(configured_dem_provider(), OpenMeteoElevationProvider)


def test_configured_dem_provider_rejects_unknown_provider(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_DEM_PROVIDER", "unknown")

    with pytest.raises(ServiceNotReadyError, match="Unsupported OPENWIND_DEM_PROVIDER"):
        configured_dem_provider()
