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

    def fake_get(url, params, timeout):
        calls.append({"url": url, "params": params, "timeout": timeout})
        return Response()

    monkeypatch.setattr("openwind_au.dem.requests.get", fake_get)
    provider = OpenMeteoElevationProvider(base_url="https://example.test/elevation")

    assert provider.elevation(-27.520503, 152.936814) == pytest.approx(42.5)
    assert provider.elevation(-27.520503, 152.936814) == pytest.approx(42.5)
    assert len(calls) == 1
    assert calls[0]["url"] == "https://example.test/elevation"
    assert calls[0]["params"] == {"latitude": -27.520503, "longitude": 152.936814}


def test_open_meteo_elevation_provider_rejects_missing_elevation(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"generationtime_ms": 1.2}

    def fake_get(url, params, timeout):
        return Response()

    monkeypatch.setattr("openwind_au.dem.requests.get", fake_get)
    provider = OpenMeteoElevationProvider()

    with pytest.raises(RuntimeError, match="Open-Meteo elevation"):
        provider.elevation(-27.520503, 152.936814)


def test_open_meteo_elevation_provider_falls_back_to_curl(monkeypatch) -> None:
    commands = []

    def fake_get(url, params, timeout):
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

    assert provider.elevation(-27.520503, 152.936814) == pytest.approx(37)
    assert commands
    assert commands[0][-1].startswith("https://example.test/elevation?")


def test_configured_dem_provider_defaults_to_srtm(monkeypatch) -> None:
    monkeypatch.delenv("OPENWIND_DEM_PROVIDER", raising=False)

    assert isinstance(configured_dem_provider(), SRTMProvider)


def test_configured_dem_provider_accepts_open_meteo(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_DEM_PROVIDER", "open-meteo")

    assert isinstance(configured_dem_provider(), OpenMeteoElevationProvider)


def test_configured_dem_provider_rejects_unknown_provider(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_DEM_PROVIDER", "unknown")

    with pytest.raises(ValueError, match="Unsupported OPENWIND_DEM_PROVIDER"):
        configured_dem_provider()
