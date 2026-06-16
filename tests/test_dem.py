"""Tests for DEM helpers."""

from __future__ import annotations

import numpy as np
import pytest

from openwind_au.dem import ArrayDEMProvider, srtm_tile_name


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
