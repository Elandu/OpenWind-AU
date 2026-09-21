"""Small, dependency-light contracts for hosting OpenWind calculations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

JsonObject = dict[str, Any]
CalculationExecutor = Callable[[Mapping[str, Any]], JsonObject]


@dataclass(frozen=True)
class StandardReference:
    """Machine-readable reference to the standard used by a calculation."""

    name: str
    edition: str
    clauses: tuple[str, ...] = ()
    tables: tuple[str, ...] = ()

    def descriptor(self) -> JsonObject:
        return {
            "name": self.name,
            "edition": self.edition,
            "clauses": list(self.clauses),
            "tables": list(self.tables),
        }


@dataclass(frozen=True)
class CalculationDefinition:
    """One calculation exposed to a host application.

    The executor is deliberately a thin adapter around the existing OpenWind
    calculation function. Engineering formulae do not live in this registry.
    """

    id: str
    name: str
    description: str
    discipline: str
    category: str
    jurisdiction: str
    version: str
    input_schema: JsonObject
    output_schema: JsonObject
    executor: CalculationExecutor = field(repr=False, compare=False)
    standard: StandardReference | None = None

    def run(self, inputs: Mapping[str, Any]) -> JsonObject:
        """Execute this definition without altering the underlying calculation."""

        return self.executor(inputs)

    def descriptor(self) -> JsonObject:
        """Return serialisable metadata suitable for UI/API discovery."""

        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "discipline": self.discipline,
            "category": self.category,
            "jurisdiction": self.jurisdiction,
            "version": self.version,
            "standard": self.standard.descriptor() if self.standard else None,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }


@dataclass(frozen=True)
class CalculationPlugin:
    """Collection of calculations published by one engineering package."""

    id: str
    name: str
    version: str
    calculations: tuple[CalculationDefinition, ...]
    revision: str | None = None
    license: str | None = None
    source: str | None = None

    def descriptor(self) -> JsonObject:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "revision": self.revision,
            "license": self.license,
            "source": self.source,
            "calculations": [definition.descriptor() for definition in self.calculations],
        }

    def get_calculation(self, calculation_id: str) -> CalculationDefinition:
        for definition in self.calculations:
            if definition.id == calculation_id:
                return definition
        raise KeyError(f"Unknown calculation: {calculation_id}")
