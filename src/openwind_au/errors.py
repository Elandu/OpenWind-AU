"""Domain exceptions shared by HTTP, streaming, and MCP entry points."""

from __future__ import annotations


class ServiceNotReadyError(Exception):
    """A required deployment setting or local dataset is unavailable.

    Messages raised with this exception are safe to return to API consumers. Detailed
    filesystem or provider diagnostics should be logged before raising it.
    """
