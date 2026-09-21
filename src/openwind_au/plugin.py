"""OpenCalcs discovery entry point for OpenWind-AU."""

from __future__ import annotations

from openwind_au import __version__
from openwind_au.calculations import CALCULATIONS, CalculationPlugin


def get_plugin() -> CalculationPlugin:
    """Return the OpenWind calculation plugin without starting any UI or server."""

    return CalculationPlugin(
        id="au.openwind",
        name="OpenWind-AU",
        version=__version__,
        calculations=CALCULATIONS,
    )
