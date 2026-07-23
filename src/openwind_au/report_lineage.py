"""Stable, installed-package report lineage references."""

from __future__ import annotations

from openwind_au import __version__

CALCULATION_BASIS_URL = (
    f"https://github.com/Elandu/OpenWind-AU/blob/v{__version__}/docs/calculation-basis.md"
)
CALCULATION_BASIS_REPORT_TEXT = (
    f"Calculation basis and data lineage reference: {CALCULATION_BASIS_URL}."
)
