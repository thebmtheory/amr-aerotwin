"""Cornering grip and straight-line segments measured directly from telemetry.

Limit acceleration is fitted as a line in dynamic pressure q (mu g + mu ClA q / m for a point mass) to one
near-limit point per corner. Tyre load sensitivity makes its slope and intercept effective values (a free
fit gives mu ~ 3), so grip is read only at two event-wide pressures, q_low and q_high.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.linear_model import HuberRegressor

from amr_aerotwin.domain import GRAVITY_ACCEL
from amr_aerotwin.physics.dynamics import VehicleState
from amr_aerotwin.physics.kinematics import corner_windows
from amr_aerotwin.physics.lapsim import CRR

MIN_LIMIT_LAT_G = 2.0


@dataclass(frozen=True)
class GripFit:
    """Grip line for one car, read at the event's q_low (slow corners) and q_high (fast corners), in g."""

    q_low_pa: float
    q_high_pa: float
    grip_low_g: float
    grip_high_g: float
    grip_low_ci90: tuple[float, float]
    grip_high_ci90: tuple[float, float]
    grip_low_samples: NDArray[np.float64]
    grip_high_samples: NDArray[np.float64]
    intercept_g: float
    slope_g_per_kpa: float
    aero_share_high: float  # fraction of grip at q_high attributable to the q-term
    n_points: int
    n_corners: int
    residual_sd_g: float
    points: pd.DataFrame


def corner_limit_points(
    state: VehicleState,
    corner_distance_m: NDArray[np.float64],
    window_m: float = 60.0,
    cda_for_tyre_force_m2: float = 1.3,
) -> pd.DataFrame:
    """One near-limit point per corner: where lateral acceleration peaks around the marker."""
    s = state.distance_m
    lap = state.lap
    rows = []
    # Disjoint windows: adjacent corners must not pick the same grid point as their limit point
    windows = corner_windows(s, np.asarray(corner_distance_m, dtype=float), lap.lap_length_m, window_m)
    for c_idx, win in enumerate(windows):
        if win.sum() < 5:
            continue
        flat_out = lap.throttle_pct[win].min() >= 97.0 and lap.brake[win].max() < 0.5
        idx = np.flatnonzero(win)[np.argmax(np.abs(state.ay_ms2[win]))]
        ay = abs(float(state.ay_ms2[idx]))
        # Longitudinal tyre acceleration: add back aero drag and rolling resistance
        ax = float(state.ax_propulsive_ms2[idx] + state.q_dyn_pa[idx] * cda_for_tyre_force_m2 / state.mass_kg
                   + GRAVITY_ACCEL * CRR)
        rows.append(
            {
                "corner_index": c_idx,
                "distance_m": float(s[idx]),
                "speed_kmh": float(state.speed_smooth_ms[idx] * 3.6),
                "q_pa": float(state.q_dyn_pa[idx]),
                "ay_ms2": ay,
                "ax_ms2": ax,
                "a_comb_ms2": float(np.hypot(ax, ay)),
                "flat_out": bool(flat_out),
            }
        )
    return pd.DataFrame(rows)


def _grip_line(q: NDArray[np.float64], a: NDArray[np.float64]) -> tuple[float, float]:
    """Huber fit of a = b0 + b1 q: (intercept m/s^2, slope m/s^2 per Pa)."""
    x = (q / 1000.0)[:, None]  # kPa for conditioning
    model = HuberRegressor(epsilon=1.5, alpha=0.0, max_iter=500).fit(x, a)
    return float(model.intercept_), float(model.coef_[0]) / 1000.0


def limit_points_for_fit(points: pd.DataFrame) -> pd.DataFrame:
    """Corners plausibly at the grip limit: not taken flat out (spare grip there) and above MIN_LIMIT_LAT_G."""
    return points[(~points["flat_out"]) & (points["ay_ms2"] >= MIN_LIMIT_LAT_G * GRAVITY_ACCEL)]


def fit_grip_vs_q(
    points: pd.DataFrame,
    q_low_pa: float,
    q_high_pa: float,
    n_boot: int = 400,
    seed: int = 3,
) -> GripFit | None:
    """Fit the grip line through near-limit corner points and evaluate it at q_low / q_high.

    Intervals come from a bootstrap over corners (the independent unit), not grid points.
    """
    use = limit_points_for_fit(points)
    if len(use) < 6 or use["q_pa"].max() - use["q_pa"].min() < 800.0:
        return None
    q = use["q_pa"].to_numpy()
    a = use["a_comb_ms2"].to_numpy()
    groups = use["corner_key"].to_numpy() if "corner_key" in use else use["corner_index"].to_numpy()

    b0, b1 = _grip_line(q, a)
    resid = a - (b0 + b1 * q)
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    lows, highs = [], []
    for _ in range(n_boot):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([np.flatnonzero(groups == g) for g in pick])
        if np.ptp(q[idx]) < 500.0:
            continue
        c0, c1 = _grip_line(q[idx], a[idx])
        lows.append((c0 + c1 * q_low_pa) / GRAVITY_ACCEL)
        highs.append((c0 + c1 * q_high_pa) / GRAVITY_ACCEL)
    lo_a, hi_a = np.array(lows), np.array(highs)
    high_total = b0 + b1 * q_high_pa
    return GripFit(
        q_low_pa=q_low_pa,
        q_high_pa=q_high_pa,
        grip_low_g=float((b0 + b1 * q_low_pa) / GRAVITY_ACCEL),
        grip_high_g=float(high_total / GRAVITY_ACCEL),
        grip_low_ci90=(float(np.percentile(lo_a, 5)), float(np.percentile(lo_a, 95))),
        grip_high_ci90=(float(np.percentile(hi_a, 5)), float(np.percentile(hi_a, 95))),
        grip_low_samples=lo_a,
        grip_high_samples=hi_a,
        intercept_g=float(b0 / GRAVITY_ACCEL),
        slope_g_per_kpa=float(b1 * 1000.0 / GRAVITY_ACCEL),
        aero_share_high=float(np.clip(b1 * q_high_pa / high_total, 0.0, 1.0)) if high_total > 0 else float("nan"),
        n_points=len(use),
        n_corners=len(uniq),
        residual_sd_g=float(np.std(resid) / GRAVITY_ACCEL),
        points=use.reset_index(drop=True),
    )


LINE_MARGIN_M = 20.0


def straight_segments(
    state: VehicleState,
    min_length_m: float = 200.0,
    trim_m: float = 30.0,
    max_speed_kmh: float | None = None,
    drop_line_cut: bool = False,
) -> list[NDArray[np.int64]]:
    """Index arrays of full-throttle, no-brake, low-lateral-load runs, trimmed by `trim_m` at both ends.

    Points within 20 m of the timing line are always dropped (speed jumps there); `drop_line_cut=True` also
    drops straights the line cuts in two, whose cut ends would pass for a corner exit or a braking point.
    """
    lap = state.lap
    ok = (
        (lap.throttle_pct >= 99.0)
        & (lap.brake < 0.5)
        & (np.abs(state.ay_ms2) < 0.6 * GRAVITY_ACCEL)
        & (state.speed_smooth_ms * 3.6 > 150.0)
    )
    if max_speed_kmh is not None:
        ok &= state.speed_smooth_ms * 3.6 <= max_speed_kmh
    step = lap.grid_step_m
    margin = int(round(LINE_MARGIN_M / step))
    ok[:margin] = False
    ok[len(ok) - margin:] = False
    trim = int(round(trim_m / step))
    segs: list[NDArray[np.int64]] = []
    idx = np.flatnonzero(ok)
    if len(idx) == 0:
        return segs
    breaks = np.flatnonzero(np.diff(idx) > 1)
    n = len(ok)
    for run in np.split(idx, breaks + 1):
        if drop_line_cut and (run[0] <= margin or run[-1] >= n - margin - 1):
            continue
        run = run[trim: len(run) - trim] if len(run) > 2 * trim else run[:0]
        if len(run) * step >= min_length_m:
            segs.append(run)
    return segs
