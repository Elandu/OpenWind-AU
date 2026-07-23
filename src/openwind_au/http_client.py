"""Shared outbound HTTP client identity."""

from openwind_au import __version__

APPLICATION_USER_AGENT = f"OpenWind-AU/{__version__}"

__all__ = ["APPLICATION_USER_AGENT"]
