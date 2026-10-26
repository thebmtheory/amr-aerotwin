"""Air density, path geometry (heading and curvature) and wind decomposition in the car frame."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from scipy.interpolate import make_smoothing_spline
from scipy.signal import savgol_filter

from amr_aerotwin.domain import (
    KELVIN_OFFSET,
    R_SPECIFIC_DRY_AIR,
    R_SPECIFIC_WATER_VAPOUR,
    AmbientState,
)


def saturation_vapour_pressure_pa(temp_c: float) -> float:
    """Saturation vapour pressure over water (Buck 1981), Pa."""
    return 611.21 * float(np.exp((18.678 - temp_c / 234.5) * (temp_c / (257.14 + temp_c))))


def compute_air_density_kg_m3(ambient: AmbientState) -> float:
    """Moist-air density from the partial pressures of dry air and water vapour.

    Humid air is lighter than dry air: at 25 C and 70% RH the correction is about -1%.
    """
    temp_k = ambient.air_temp_c + KELVIN_OFFSET
    p_total = ambient.pressure_mbar * 100.0
    p_vapour = (ambient.relative_humidity_pct / 100.0) * saturation_vapour_pressure_pa(ambient.air_temp_c)
    p_dry = p_total - p_vapour
    return float(p_dry / (R_SPECIFIC_DRY_AIR * temp_k) + p_vapour / (R_SPECIFIC_WATER_VAPOUR * temp_k))


def _periodic_gradient(f: NDArray[np.float64], step: float) -> NDArray[np.float64]:
    return (np.roll(f, -1) - np.roll(f, 1)) / (2.0 * step)


def compute_track_heading_and_curvature(
    distance_m: NDArray[np.float64],
    x_m: NDArray[np.float64],
    y_m: NDArray[np.float64],
    closed: bool = False,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Heading psi(s) (rad, CCW from +X/East) and signed curvature kappa(s) (1/m, + = left turn).

    kappa = (x' y'' - y' x'') / (x'^2 + y'^2)^(3/2), derivatives with respect to arc length.
    """
    if closed:
        step = float(distance_m[1] - distance_m[0])
        dx, dy = _periodic_gradient(x_m, step), _periodic_gradient(y_m, step)
        ddx, ddy = _periodic_gradient(dx, step), _periodic_gradient(dy, step)
    else:
        dx, dy = np.gradient(x_m, distance_m), np.gradient(y_m, distance_m)
        ddx, ddy = np.gradient(dx, distance_m), np.gradient(dy, distance_m)
    heading = np.arctan2(dy, dx)
    denom = np.maximum(np.power(dx**2 + dy**2, 1.5), 1e-9)
    return heading, (dx * ddy - dy * ddx) / denom


def path_curvature(
    distance_m: NDArray[np.float64],
    x_m: NDArray[np.float64],
    y_m: NDArray[np.float64],
    smooth_window_m: float = 55.0,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Heading and curvature of a closed lap after periodic Savitzky-Golay smoothing of X/Y.

    GPS positions arrive at ~4 Hz, so the second derivative is noisy without smoothing. A
    ~55 m window keeps the apex radius of slow hairpins (R ~ 15-20 m) within a few percent
    while suppressing jitter (checked by `turning_number`).
    """
    step = float(distance_m[1] - distance_m[0])
    w = max(5, int(round(smooth_window_m / step)) | 1)
    xs = savgol_filter(x_m, w, 3, mode="wrap")
    ys = savgol_filter(y_m, w, 3, mode="wrap")
    return compute_track_heading_and_curvature(distance_m, xs, ys, closed=True)


GPS_SMOOTHING_CANDIDATES = (0.05, 0.1, 0.2, 0.4)


def gps_position_splines(
    fix_time_s: NDArray[np.float64],
    fix_x_m: NDArray[np.float64],
    fix_y_m: NDArray[np.float64],
    lap_time_s: float,
    lam: float = 0.2,
):  # -> tuple[BSpline, BSpline]
    """Smoothing splines x(t), y(t) through raw GPS fixes, periodically extended by one lap.

    Fix times are wrapped into one lap first: after a lap is re-timed to its line crossings a
    few fixes fall just before 0 or after the lap time, and they belong to the neighbouring laps.
    """
    t_w = np.mod(np.asarray(fix_time_s, dtype=float), lap_time_s)
    order = np.argsort(t_w, kind="stable")
    t, x, y = t_w[order], fix_x_m[order], fix_y_m[order]
    keep = np.concatenate([[True], np.diff(t) > 1e-3])
    t, x, y = t[keep], x[keep], y[keep]
    t_ext = np.concatenate([t - lap_time_s, t, t + lap_time_s])
    return (
        make_smoothing_spline(t_ext, np.tile(x, 3), lam=lam),
        make_smoothing_spline(t_ext, np.tile(y, 3), lam=lam),
    )


def gps_spline_kinematics(
    fix_time_s: NDArray[np.float64],
    fix_x_m: NDArray[np.float64],
    fix_y_m: NDArray[np.float64],
    lap_time_s: float,
    eval_time_s: NDArray[np.float64],
    lam: float = 0.2,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Curvature and GPS-derived speed from raw ~4 Hz fixes, smoothed in *time*.

    Position error is roughly constant per fix, so smoothing x(t), y(t) gives lateral
    acceleration noise that does not grow with speed (smoothing in distance over-smooths
    hairpins and under-smooths 300 km/h corners). Returns (kappa at eval times, |v_gps|).
    """
    sx, sy = gps_position_splines(fix_time_s, fix_x_m, fix_y_m, lap_time_s, lam)
    dx, dy = sx(eval_time_s, 1), sy(eval_time_s, 1)
    ddx, ddy = sx(eval_time_s, 2), sy(eval_time_s, 2)
    speed = np.hypot(dx, dy)
    kappa = (dx * ddy - dy * ddx) / np.maximum(speed, 1.0) ** 3
    return kappa, speed


def select_gps_smoothing(
    laps: Sequence[tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], float, NDArray[np.float64], NDArray[np.float64]]],
    candidates: Sequence[float] = GPS_SMOOTHING_CANDIDATES,
) -> tuple[float, dict[float, float]]:
    """Choose the time-smoothing penalty that best reproduces the independent speed sensor.

    Each lap tuple is (fix_t, fix_x, fix_y, lap_time, grid_t, measured_speed). The score
    is the median over laps of the RMS difference between GPS-derived speed and the
    wheel-speed channel: too little smoothing amplifies GPS noise, too much cuts corners.
    """
    scores: dict[float, float] = {}
    for lam in candidates:
        errs = []
        for ft, fx, fy, lt, gt, v in laps:
            _, v_gps = gps_spline_kinematics(ft, fx, fy, lt, gt, lam)
            errs.append(float(np.sqrt(np.mean((v_gps - v) ** 2))))
        scores[lam] = float(np.median(errs))
    return min(scores, key=scores.__getitem__), scores


def consensus_curvature(curvatures: Sequence[NDArray[np.float64]]) -> NDArray[np.float64]:
    """Point-wise median curvature across many drivers' laps of the same layout.

    Racing lines at one event differ by well under a metre, while single-lap GPS noise is
    larger, so the median over ~20 laps is a far better estimate of the driven path.
    """
    return np.median(np.vstack(list(curvatures)), axis=0)


def turning_number(curvature_inv_m: NDArray[np.float64], step_m: float) -> float:
    """Total heading change / 2pi. A clean closed lap must give +1 (anticlockwise) or -1."""
    return float(np.sum(curvature_inv_m) * step_m / (2.0 * np.pi))


def decompose_aero_wind_vectors(
    speed_ms: NDArray[np.float64],
    heading_rad: NDArray[np.float64],
    ambient: AmbientState,
) -> dict[str, NDArray[np.float64]]:
    """Project ambient wind onto the car axes.

    Wind blowing FROM compass bearing theta moves the air towards (-sin theta, -cos theta)
    in (East, North). With car tangent t = (cos psi, sin psi) and left normal n = (-sin psi,
    cos psi):
      headwind   = -(w . t)            (+ opposes the car, raising airspeed)
      crosswind  = -(w . n)            (+ means air arriving from the car's left)
      yaw angle  = atan2(crosswind, v + headwind)
    """
    theta = np.radians(ambient.wind_direction_deg)
    w_x = -ambient.wind_speed_ms * np.sin(theta)
    w_y = -ambient.wind_speed_ms * np.cos(theta)

    v_headwind = -(w_x * np.cos(heading_rad) + w_y * np.sin(heading_rad))
    v_crosswind = -(-w_x * np.sin(heading_rad) + w_y * np.cos(heading_rad))
    v_long = np.maximum(speed_ms + v_headwind, 1.0)
    return {
        "v_headwind_ms": v_headwind,
        "v_crosswind_ms": v_crosswind,
        "v_airspeed_ms": np.hypot(v_long, v_crosswind),
        "beta_aero_deg": np.degrees(np.arctan2(v_crosswind, v_long)),
    }


def nearest_corner(distance_m: NDArray[np.float64], corner_distance_m: NDArray[np.float64],
                   lap_length_m: float) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
    """For every grid point: index of the nearest corner marker and the signed distance to it (m).

    Splitting the track by nearest marker gives each piece of track to one corner only, so two
    corners closer than their window widths share the track at the midpoint instead of one of
    them taking it all (or both counting it).
    """
    s = np.asarray(distance_m, dtype=float)
    c = np.asarray(corner_distance_m, dtype=float)
    d = (s[None, :] - c[:, None] + lap_length_m / 2) % lap_length_m - lap_length_m / 2
    k = np.argmin(np.abs(d), axis=0)
    return k, d[k, np.arange(len(s))]


def corner_windows(distance_m: NDArray[np.float64], corner_distance_m: NDArray[np.float64],
                   lap_length_m: float, half_width_m: float) -> list[NDArray[np.bool_]]:
    """Per corner, the grid points within `half_width_m` of its marker that are nearest to it."""
    if len(corner_distance_m) == 0:
        return []
    k, d = nearest_corner(distance_m, corner_distance_m, lap_length_m)
    return [(k == i) & (np.abs(d) <= half_width_m) for i in range(len(corner_distance_m))]
