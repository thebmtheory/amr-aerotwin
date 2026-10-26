"""Quasi-steady-state (QSS) point-mass lap-time simulator.

The car is a point mass on a fixed path with curvature kappa(s). At every point the tyres
can deliver a lateral acceleration of

    a_grip(v) = mu * (g + q(v) * ClA / m),       q = 0.5 * rho * v^2

and a longitudinal acceleration of `long_grip_scale * a_grip(v)`, combined on a friction
ellipse (a_x / (k a_grip))^2 + (a_y / a_grip)^2 <= 1. The solver:

1. Corner limit: v_max(s) where v^2 |kappa| = a_grip(v), solved in closed form.
2. Forward pass (acceleration): min(remaining grip, P / (m v)) minus drag and rolling loss.
3. Backward pass (braking): remaining grip plus drag and rolling loss.
4. Speed = min of the three; the lap is closed by simulating two laps and keeping the
   converged copy, so the start speed matches the end speed.

This is the standard first model used for lap-time sensitivities: it ignores load transfer,
tyre load sensitivity, gear ratios and driver behaviour, which is exactly what the
calibration discrepancy term in `modeling/calibration.py` is there to expose.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
from numpy.typing import NDArray

from amr_aerotwin.domain import GRAVITY_ACCEL

V_CAP_MS = 110.0  # numerical cap for straight-line / zero-curvature points (396 km/h)

LIMIT_CORNER = 0
LIMIT_ACCEL = 1
LIMIT_BRAKE = 2


@dataclass(frozen=True)
class VehicleParams:
    """Lumped car parameters for the point-mass model (SI)."""

    mass_kg: float
    cla_m2: float
    cda_m2: float
    mu: float
    power_w: float
    rho_kg_m3: float = 1.20
    crr: float = 0.012
    low_drag_cda_m2: float | None = None  # CdA with DRS / straight-line mode open
    long_grip_scale: float = 1.0  # longitudinal / lateral friction ratio (friction ellipse)

    def scaled(self, **factors: float) -> "VehicleParams":
        """Copy with selected fields multiplied, e.g. scaled(cla_m2=1.01)."""
        return replace(self, **{k: getattr(self, k) * v for k, v in factors.items()})


@dataclass(frozen=True)
class LapSimResult:
    distance_m: NDArray[np.float64]
    speed_ms: NDArray[np.float64]
    time_s: NDArray[np.float64]
    lap_time_s: float
    ax_ms2: NDArray[np.float64]
    ay_ms2: NDArray[np.float64]
    limit: NDArray[np.int8]  # LIMIT_CORNER / LIMIT_ACCEL / LIMIT_BRAKE


def max_cornering_speed(kappa: NDArray[np.float64], p: VehicleParams) -> NDArray[np.float64]:
    """Steady-state cornering speed: v^2 |k| = mu (g + rho v^2 ClA / (2 m)).

    Rearranged: v^2 = mu g / (|k| - mu rho ClA / (2 m)). When the denominator is <= 0, aero
    grip grows faster than the lateral demand and the corner is not grip-limited.
    """
    k = np.abs(kappa)
    denom = k - p.mu * p.rho_kg_m3 * p.cla_m2 / (2.0 * p.mass_kg)
    with np.errstate(divide="ignore", invalid="ignore"):
        v2 = np.where(denom > 1e-12, p.mu * GRAVITY_ACCEL / denom, V_CAP_MS**2)
    return np.minimum(np.sqrt(v2), V_CAP_MS)


def _passes(
    kappa: NDArray[np.float64],
    cda: NDArray[np.float64],
    v_apex: NDArray[np.float64],
    ds: float,
    p: VehicleParams,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    n = len(kappa)
    m, g, mu, rho, cla, kx = p.mass_kg, GRAVITY_ACCEL, p.mu, p.rho_kg_m3, p.cla_m2, p.long_grip_scale
    k_abs = np.abs(kappa).tolist()
    cda_l = cda.tolist()
    vap = v_apex.tolist()

    fwd = [0.0] * n
    v = vap[0]
    fwd[0] = v
    for i in range(n - 1):
        q = 0.5 * rho * v * v
        a_tot = mu * (g + q * cla / m)
        a_lat = v * v * k_abs[i]
        ratio = a_lat / a_tot
        a_grip = kx * a_tot * math.sqrt(1.0 - ratio * ratio) if ratio < 1.0 else 0.0
        a_pow = p.power_w / (m * max(v, 1.0))
        a = min(a_grip, a_pow) - q * cda_l[i] / m - g * p.crr
        v2 = v * v + 2.0 * a * ds
        v = math.sqrt(v2) if v2 > 1.0 else 1.0
        if v > vap[i + 1]:
            v = vap[i + 1]
        fwd[i + 1] = v

    bwd = [0.0] * n
    v = vap[n - 1]
    bwd[n - 1] = v
    for i in range(n - 1, 0, -1):
        q = 0.5 * rho * v * v
        a_tot = mu * (g + q * cla / m)
        a_lat = v * v * k_abs[i]
        ratio = a_lat / a_tot
        a_grip = kx * a_tot * math.sqrt(1.0 - ratio * ratio) if ratio < 1.0 else 0.0
        a_b = a_grip + q * cda_l[i] / m + g * p.crr
        v = math.sqrt(v * v + 2.0 * a_b * ds)
        if v > vap[i - 1]:
            v = vap[i - 1]
        bwd[i - 1] = v
    return np.asarray(fwd), np.asarray(bwd)


def simulate_lap(
    distance_m: NDArray[np.float64],
    kappa: NDArray[np.float64],
    p: VehicleParams,
    low_drag_mask: NDArray[np.bool_] | None = None,
    lap_length_m: float | None = None,
    closed: bool = True,
) -> LapSimResult:
    """Simulate one flying lap on a uniform grid. `lap_length_m` closes the final segment."""
    ds = float(distance_m[1] - distance_m[0])
    n = len(distance_m)
    cda = np.full(n, p.cda_m2)
    if low_drag_mask is not None and p.low_drag_cda_m2 is not None:
        cda = np.where(low_drag_mask, p.low_drag_cda_m2, p.cda_m2)
    v_apex = max_cornering_speed(kappa, p)

    if closed:
        k2, c2, va2 = np.tile(kappa, 2), np.tile(cda, 2), np.tile(v_apex, 2)
        fwd2, bwd2 = _passes(k2, c2, va2, ds, p)
        fwd, bwd = fwd2[n:], bwd2[:n]
    else:
        fwd, bwd = _passes(kappa, cda, v_apex, ds, p)

    v = np.minimum(np.minimum(fwd, bwd), v_apex)
    limit = np.full(n, LIMIT_CORNER, dtype=np.int8)
    limit[(fwd <= bwd) & (fwd < v_apex - 1e-6)] = LIMIT_ACCEL
    limit[(bwd < fwd) & (bwd < v_apex - 1e-6)] = LIMIT_BRAKE

    seg_dt = 2.0 * ds / (v[1:] + v[:-1])
    time_s = np.concatenate([[0.0], np.cumsum(seg_dt)])
    length = float(lap_length_m) if lap_length_m is not None else float(distance_m[-1] + ds)
    closing = length - float(distance_m[-1])
    v_close_end = float(v[0]) if closed else float(v[-1])
    lap_time = float(time_s[-1] + 2.0 * closing / (v[-1] + v_close_end))

    if closed:
        dv_ds = (np.roll(v, -1) - np.roll(v, 1)) / (2.0 * ds)
    else:
        dv_ds = np.gradient(v, ds)
    return LapSimResult(
        distance_m=distance_m,
        speed_ms=v,
        time_s=time_s,
        lap_time_s=lap_time,
        ax_ms2=v * dv_ds,
        ay_ms2=v**2 * kappa,
        limit=limit,
    )


SENSITIVITY_STEPS = {"cla_m2": 0.01, "cda_m2": 0.01, "power_w": 0.01, "mu": 0.01}


def lap_time_sensitivities(
    distance_m: NDArray[np.float64],
    kappa: NDArray[np.float64],
    p: VehicleParams,
    low_drag_mask: NDArray[np.bool_] | None = None,
    lap_length_m: float | None = None,
) -> dict[str, float]:
    """Lap-time change (s) for +1% ClA, CdA, power and mu, and for +10 kg (central differences)."""
    out: dict[str, float] = {}

    def lap(pp: VehicleParams) -> float:
        return simulate_lap(distance_m, kappa, pp, low_drag_mask, lap_length_m).lap_time_s

    for name, step in SENSITIVITY_STEPS.items():
        up = p.scaled(**{name: 1.0 + step})
        dn = p.scaled(**{name: 1.0 - step})
        if name == "cda_m2" and p.low_drag_cda_m2 is not None:
            up = replace(up, low_drag_cda_m2=p.low_drag_cda_m2 * (1.0 + step))
            dn = replace(dn, low_drag_cda_m2=p.low_drag_cda_m2 * (1.0 - step))
        out[f"{name}_plus_1pct_s"] = (lap(up) - lap(dn)) / 2.0
    out["mass_plus_10kg_s"] = (
        lap(replace(p, mass_kg=p.mass_kg + 10.0)) - lap(replace(p, mass_kg=p.mass_kg - 10.0))
    ) / 2.0
    # How many % of extra drag cost the same lap time as 1% of extra downforce gains
    out["cda_pct_per_cla_pct"] = -out["cla_m2_plus_1pct_s"] / max(out["cda_m2_plus_1pct_s"], 1e-9)
    return out


def iso_lap_time_grid(
    distance_m: NDArray[np.float64],
    kappa: NDArray[np.float64],
    p: VehicleParams,
    cla_pct: NDArray[np.float64],
    cda_pct: NDArray[np.float64],
    low_drag_mask: NDArray[np.bool_] | None = None,
    lap_length_m: float | None = None,
) -> NDArray[np.float64]:
    """Lap-time delta (s) vs baseline over a grid of % changes in ClA (rows) and CdA (cols)."""
    base = simulate_lap(distance_m, kappa, p, low_drag_mask, lap_length_m).lap_time_s
    grid = np.zeros((len(cla_pct), len(cda_pct)))
    for i, dl in enumerate(cla_pct):
        for j, dd in enumerate(cda_pct):
            pp = p.scaled(cla_m2=1 + dl / 100.0, cda_m2=1 + dd / 100.0)
            if p.low_drag_cda_m2 is not None:
                pp = replace(pp, low_drag_cda_m2=p.low_drag_cda_m2 * (1 + dd / 100.0))
            grid[i, j] = simulate_lap(distance_m, kappa, pp, low_drag_mask, lap_length_m).lap_time_s - base
    return grid
