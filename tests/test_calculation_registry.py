"""Regression tests for the host-facing OpenWind calculation registry."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from openwind_au.calculations import get_calculation, list_calculations, run_calculation
from openwind_au.plugin import get_plugin
from openwind_au.standard_calculations import (
    climate_change_multiplier,
    design_wind_speed,
    regional_wind_speed,
    site_wind_speed,
)


def test_plugin_exposes_stable_registry_without_starting_application() -> None:
    plugin = get_plugin()

    assert plugin.id == "au.openwind"
    assert plugin.name == "OpenWind-AU"
    assert plugin.calculations
    assert {definition.id for definition in plugin.calculations} == {
        definition["id"] for definition in list_calculations()
    }


def test_registry_regional_wind_speed_matches_existing_function() -> None:
    inputs = {"region": "A2", "ari_years": 500}

    assert run_calculation("au.wind.regional_wind_speed", inputs) == {
        "regional_wind_speed_m_s": regional_wind_speed(**inputs)
    }


def test_registry_climate_change_multiplier_matches_existing_function() -> None:
    inputs = {"region": "B2"}

    assert run_calculation("au.wind.climate_change_multiplier", inputs) == {
        "climate_change_multiplier": climate_change_multiplier("B2")
    }


def test_registry_site_wind_speed_matches_existing_function() -> None:
    inputs = {
        "vr": 57.0,
        "mc": 1.05,
        "md": 0.9,
        "mzcat": 1.0,
        "ms": 1.0,
        "mt": 1.0,
    }

    assert run_calculation("au.wind.site_wind_speed", inputs) == {
        "site_wind_speed_m_s": site_wind_speed(**inputs)
    }


def test_registry_design_wind_speed_matches_existing_function() -> None:
    inputs = {
        "theta_degrees": 20.0,
        "direction_speeds": {
            "N": 32.0,
            "NE": 41.0,
            "E": 50.0,
            "SE": 44.0,
            "S": 38.0,
            "SW": 36.0,
            "W": 34.0,
            "NW": 30.0,
        },
        "ultimate_limit_state": True,
    }

    assert run_calculation("au.wind.design_wind_speed", inputs) == asdict(
        design_wind_speed(**inputs)
    )


def test_registry_preserves_existing_validation_errors() -> None:
    with pytest.raises(ValueError, match="B1 or B2"):
        run_calculation("au.wind.climate_change_multiplier", {"region": "B"})


def test_unknown_calculation_is_rejected() -> None:
    with pytest.raises(KeyError, match="Unknown calculation"):
        get_calculation("au.wind.not-real")


def test_descriptors_do_not_expose_executor() -> None:
    definition = get_calculation("au.wind.site_wind_speed")
    descriptor = definition.descriptor()

    assert "executor" not in descriptor
    assert descriptor["standard"]["name"] == "AS/NZS 1170.2"
    assert descriptor["standard"]["edition"] == "2021"


def test_plugin_publishes_source_and_licence_provenance(monkeypatch) -> None:
    monkeypatch.setenv("OPENWIND_SOURCE_REVISION", "openwind-test-revision")

    plugin = get_plugin()
    descriptor = plugin.descriptor()

    assert descriptor["revision"] == "openwind-test-revision"
    assert descriptor["license"] == "AGPL-3.0-only"
    assert descriptor["source"] == "https://github.com/Elandu/OpenWind-AU"
