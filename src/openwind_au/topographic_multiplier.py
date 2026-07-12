"""AS/NZS 1170.2:2021 Clause 4.4 topographic multiplier calculations."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TopographicMultiplierCalculation:
    """Traceable result for one directional topographic multiplier calculation."""

    mt: float
    mh: float
    mlee: float
    elevation_factor: float
    slope_parameter: float
    l1_m: float | None
    l2_m: float | None
    x_m: float
    z_m: float
    equation: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


def calculate_topographic_multiplier(
    *,
    feature_type: str,
    h_m: float,
    lu_m: float,
    x_m: float,
    z_m: float,
    wind_region: str,
    site_elevation_m: float,
    site_is_downwind: bool = True,
) -> TopographicMultiplierCalculation:
    """Calculate Mt for an Australian site from resolved topographic geometry.

    Australia has no identified lee zones in AS/NZS 1170.2:2021, so Mlee is
    1.0. Region A0 and high-elevation Region A4 adjustments are applied after
    calculating the hill-shape multiplier Mh.
    """

    dimensions = {
        "H": h_m,
        "Lu": lu_m,
        "x": x_m,
        "z": z_m,
        "site elevation": site_elevation_m,
    }
    if any(not math.isfinite(value) for value in dimensions.values()):
        raise ValueError("Topographic dimensions and elevations must be finite numbers.")
    if z_m < 0:
        raise ValueError("Reference height z must not be negative.")
    if h_m < 0 or lu_m < 0 or x_m < 0:
        raise ValueError("Topographic dimensions H, Lu, and x must not be negative.")

    warnings: list[str] = []
    mh = 1.0
    slope_parameter = 0.0
    l1_m: float | None = None
    l2_m: float | None = None
    equation = "Mh = 1.0 (no qualifying local topographic speed-up)"

    qualifying_feature = feature_type in {"hill", "ridge", "escarpment"}
    if feature_type == "valley":
        warnings.append("Valley screening does not create a Clause 4.4 hill-shape increase.")
    elif feature_type == "no significant feature":
        pass
    elif not qualifying_feature:
        warnings.append(f"Unsupported topographic feature type {feature_type!r}; Mh set to 1.0.")
    elif h_m < 10.0:
        warnings.append("Feature height H is less than 10 m; Clause 4.4.2 sets Mh to 1.0.")
    elif lu_m <= 0:
        warnings.append("Lu is unavailable; Mh cannot exceed 1.0 without resolved geometry.")
    else:
        slope_parameter = h_m / (2.0 * lu_m)
        l1_m = max(0.36 * lu_m, 0.4 * h_m)
        l2_m = (10.0 if feature_type == "escarpment" and site_is_downwind else 4.0) * l1_m
        if slope_parameter < 0.05:
            equation = "Mh = 1.0 because H/(2Lu) < 0.05"
        elif x_m > l2_m:
            equation = "Mh = 1.0 outside the local topographic zone"
        elif slope_parameter > 0.45 and _in_steep_peak_zone(
            h_m=h_m,
            x_m=x_m,
            site_is_downwind=site_is_downwind,
        ):
            mh = 1.0 + 0.71 * (1.0 - x_m / l2_m)
            equation = "Clause 4.4.2 Equation 4.4(4)"
        else:
            mh = 1.0 + h_m / (3.5 * (z_m + l1_m)) * (1.0 - x_m / l2_m)
            equation = "Clause 4.4.2 Equation 4.4(3)"

    mlee = 1.0
    elevation_factor = 1.0
    if wind_region == "A0":
        mt = 0.5 + 0.5 * mh
        equation = f"{equation}; Clause 4.4.1 Equation 4.4(2)"
    elif wind_region == "A4" and site_elevation_m > 500.0:
        elevation_factor = 1.0 + 0.00015 * site_elevation_m
        mt = mh * mlee * elevation_factor
        equation = f"{equation}; Clause 4.4.1 Equation 4.4(1)"
    else:
        mt = max(mh, mlee)
        equation = f"{equation}; Clause 4.4.1(c)"

    return TopographicMultiplierCalculation(
        mt=mt,
        mh=mh,
        mlee=mlee,
        elevation_factor=elevation_factor,
        slope_parameter=slope_parameter,
        l1_m=l1_m,
        l2_m=l2_m,
        x_m=x_m,
        z_m=z_m,
        equation=equation,
        warnings=tuple(warnings),
    )


def _in_steep_peak_zone(*, h_m: float, x_m: float, site_is_downwind: bool) -> bool:
    peak_zone_extent_m = h_m / 4.0 if site_is_downwind else h_m / 10.0
    return x_m <= peak_zone_extent_m
