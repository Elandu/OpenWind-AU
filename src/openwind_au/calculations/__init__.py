"""Host-facing calculation registry for OpenWind-AU.

The public functions in the existing OpenWind modules remain the source of truth.
This package only describes and dispatches those calculations for external hosts
such as OpenCalcs.
"""

from openwind_au.calculations.contracts import (
    CalculationDefinition,
    CalculationPlugin,
    StandardReference,
)
from openwind_au.calculations.registry import (
    CALCULATIONS,
    get_calculation,
    list_calculations,
    run_calculation,
)

__all__ = [
    "CALCULATIONS",
    "CalculationDefinition",
    "CalculationPlugin",
    "StandardReference",
    "get_calculation",
    "list_calculations",
    "run_calculation",
]
