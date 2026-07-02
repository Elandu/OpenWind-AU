"""Landcover classification metadata for terrain category screening."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LandcoverClassSpec:
    """Terrain-screening interpretation of one landcover class."""

    is_obstruction: bool
    default_height_m: float
    weight: float


# ESA WorldCover 10 m 2021 v200 defines the Map band class codes used here:
# https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200
DEFAULT_LANDCOVER_CLASS_MAP: dict[int, LandcoverClassSpec] = {
    10: LandcoverClassSpec(is_obstruction=True, default_height_m=8.0, weight=0.3),
    20: LandcoverClassSpec(is_obstruction=True, default_height_m=2.0, weight=0.2),
    30: LandcoverClassSpec(is_obstruction=False, default_height_m=0.0, weight=0.0),
    40: LandcoverClassSpec(is_obstruction=False, default_height_m=0.0, weight=0.0),
    50: LandcoverClassSpec(is_obstruction=True, default_height_m=8.0, weight=1.0),
    60: LandcoverClassSpec(is_obstruction=False, default_height_m=0.0, weight=0.0),
    70: LandcoverClassSpec(is_obstruction=False, default_height_m=0.0, weight=0.0),
    80: LandcoverClassSpec(is_obstruction=True, default_height_m=0.0, weight=0.0),
    90: LandcoverClassSpec(is_obstruction=False, default_height_m=0.0, weight=0.0),
    95: LandcoverClassSpec(is_obstruction=True, default_height_m=6.0, weight=0.3),
    100: LandcoverClassSpec(is_obstruction=False, default_height_m=0.0, weight=0.0),
}
