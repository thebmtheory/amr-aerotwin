"""Direct estimation of cornering grip and straight-line performance from telemetry.

Grip vs dynamic pressure
------------------------
For a point mass with constant friction, the limit acceleration is a straight line in
dynamic pressure q:  a_limit = mu g + (mu ClA / m) q. Real tyres are load-sensitive
(friction falls as load rises), so the slope and intercept of that line are *effective*
values: absolute mu and ClA cannot be separated from public telemetry (fitting them gives
mu ~ 3, which is not physical). What the data does identify well is the limit itself
inside the range of q actually driven. So for each car we fit the line through one
near-limit point per corner and report:

    grip_low_g  = a_limit(q_low)  / g     slow-corner grip (mechanical-dominated)
    grip_high_g = a_limit(q_high) / g     fast-corner grip (aero-dominated)

with q_low / q_high fixed per event (shared by all teams), so comparisons are like for
like. Corners taken flat out are excluded because the car has spare grip there.
Uncertainty is a bootstrap over corners (the independent unit), not grid points.

Drag and power on straights
---------------------------
At full throttle with no braking and negligible lateral load:

    m * a_x + m * g * Crr  =  P / v  -  q * CdA  [-  q * dCdA * DRS]

which is linear in (P, CdA, dCdA). P and CdA are strongly collinear along a straight (both
terms fall with speed), so individually they carry wide intervals; their ratio is well
determined and is reported as the drag-limited top speed v_inf = (2 P / (rho0 CdA))^(1/3)
at a standard density rho0 = 1.2 kg/m^3. This mixes power-unit output and drag, and is
labelled that way. Bootstrap resamples whole straights.

Mass is the regulation minimum plus an assumed fuel load; P is wheel power. In 2026 the
MGU-K power tapers above 290 km/h and battery state changes along a straight, so 2026 drag
fits use speeds below the taper only (`max_speed_kmh`).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.linear_model import HuberRegressor

from amr_aerotwin.domain import GRAVITY_ACCEL
from amr_aerotwin.physics.dynamics import VehicleState

CRR = 0.012
RHO_STANDARD = 1.2
MIN_LIMIT_LAT_G = 2.0


@dataclass(frozen=True)
class GripFit:
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


@dataclass(frozen=True)
class DragFit:
    power_kw: float
    cda_m2: float
    delta_cda_low_drag_m2: float
    power_ci90: tuple[float, float]
    cda_ci90: tuple[float, float]
    power_samples: NDArray[np.float64]
    cda_samples: NDArray[np.float64]
    v_inf_kmh: float
    v_inf_ci90: tuple[float, float]
    v_inf_samples: NDArray[np.float64]
    n_segments: int
    n_points: int
    residual_sd_ms2: float


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
    for c_idx, c_s in enumerate(corner_distance_m):
        d = (s - c_s + lap.lap_length_m / 2) % lap.lap_length_m - lap.lap_length_m / 2
        win = np.abs(d) <= window_m
        if win.sum() < 5:
            continue
        flat_out = lap.throttle_pct[win].min() >= 97.0 and lap.brake[win].max() < 0.5
        idx = np.flatnonzero(win)[np.argmax(np.abs(state.ay_ms2[win]))]
        ay = abs(float(state.ay_ms2[idx]))
        # Longitudinal *tyre* acceleration: remove aero drag and rolling resistance
        ax = float(state.ax_ms2[idx] + state.q_dyn_pa[idx] * cda_for_tyre_force_m2 / state.mass_kg
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
    """Robust line a = b0 + b1 q (Huber). Returns (intercept, slope)."""
    x = (q / 1000.0)[:, None]  # kPa for conditioning
    model = HuberRegressor(epsilon=1.5, alpha=0.0, max_iter=500).fit(x, a)
    return float(model.intercept_), float(model.coef_[0]) / 1000.0


def limit_points_for_fit(points: pd.DataFrame) -> pd.DataFrame:
    """Corners where the car is plausibly at the grip limit."""
    return points[(~points["flat_out"]) & (points["ay_ms2"] >= MIN_LIMIT_LAT_G * GRAVITY_ACCEL)]


def fit_grip_vs_q(
    points: pd.DataFrame,
    q_low_pa: float,
    q_high_pa: float,
    n_boot: int = 400,
    seed: int = 3,
) -> GripFit | None:
    """Fit the grip line through near-limit corner points and evaluate it at q_low / q_high."""
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


def straight_segments(
    state: VehicleState,
    min_length_m: float = 200.0,
    trim_m: float = 30.0,
    max_speed_kmh: float | None = None,
) -> list[NDArray[np.int64]]:
    """Index arrays of full-throttle, no-brake, low-lateral-load runs (trimmed at both ends)."""
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
    trim = int(round(trim_m / step))
    segs: list[NDArray[np.int64]] = []
    idx = np.flatnonzero(ok)
    if len(idx) == 0:
        return segs
    breaks = np.flatnonzero(np.diff(idx) > 1)
    for run in np.split(idx, breaks + 1):
        run = run[trim: len(run) - trim] if len(run) > 2 * trim else run[:0]
        if len(run) * step >= min_length_m:
            segs.append(run)
    return segs


def fit_drag_power(
    states: list[VehicleState],
    fit_low_drag: bool = True,
    max_speed_kmh: float | None = None,
    n_boot: int = 400,
    seed: int = 5,
) -> DragFit | None:
    """Least-squares fit of (P, CdA, dCdA) on full-throttle straights of one or more laps."""
    blocks = []
    for st in states:
        m = st.mass_kg
        for seg in straight_segments(st, max_speed_kmh=max_speed_kmh):
            v = st.speed_smooth_ms[seg]
            q = st.q_dyn_pa[seg]
            y = m * st.ax_ms2[seg] + m * GRAVITY_ACCEL * CRR
            cols = [1.0 / v, -q]
            if fit_low_drag:
                cols.append(-q * st.lap.drs[seg])
            blocks.append((np.column_stack(cols), y))
    if len(blocks) < 3:
        return None
    use_drs = fit_low_drag and any(np.any(b[0][:, 2] != 0) for b in blocks)
    if not use_drs:
        blocks = [(b[0][:, :2], b[1]) for b in blocks]

    def solve(sel: list[int]) -> NDArray[np.float64]:
        x = np.vstack([blocks[i][0] for i in sel])
        y = np.concatenate([blocks[i][1] for i in sel])
        return np.linalg.lstsq(x, y, rcond=None)[0]

    allidx = list(range(len(blocks)))
    beta = solve(allidx)
    x_all = np.vstack([b[0] for b in blocks])
    y_all = np.concatenate([b[1] for b in blocks])
    resid = y_all - x_all @ beta
    mass = states[0].mass_kg

    rng = np.random.default_rng(seed)
    boots = np.array([solve(list(rng.choice(allidx, len(allidx), replace=True))) for _ in range(n_boot)])

    def v_inf(p_w: NDArray[np.float64], cda: NDArray[np.float64]) -> NDArray[np.float64]:
        ratio = np.where(cda > 0, p_w / np.maximum(cda, 1e-6), np.nan)
        return np.cbrt(2.0 * ratio / RHO_STANDARD) * 3.6

    vinf_boot = v_inf(boots[:, 0], boots[:, 1])
    vinf_boot = vinf_boot[np.isfinite(vinf_boot)]
    return DragFit(
        power_kw=float(beta[0] / 1000.0),
        cda_m2=float(beta[1]),
        delta_cda_low_drag_m2=float(beta[2]) if use_drs else 0.0,
        power_ci90=(float(np.percentile(boots[:, 0], 5) / 1000), float(np.percentile(boots[:, 0], 95) / 1000)),
        cda_ci90=(float(np.percentile(boots[:, 1], 5)), float(np.percentile(boots[:, 1], 95))),
        power_samples=boots[:, 0] / 1000.0,
        cda_samples=boots[:, 1],
        v_inf_kmh=float(v_inf(np.array([beta[0]]), np.array([beta[1]]))[0]),
        v_inf_ci90=(float(np.percentile(vinf_boot, 5)), float(np.percentile(vinf_boot, 95))),
        v_inf_samples=vinf_boot,
        n_segments=len(blocks),
        n_points=len(y_all),
        residual_sd_ms2=float(np.std(resid) / mass),
    )
