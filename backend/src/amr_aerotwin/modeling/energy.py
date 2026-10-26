"""Energy-limited deployment ("clipping") on straights, from speed traces alone.

Why a speed *drop* is the signature
-----------------------------------
On a straight at full throttle, m dv/dt = P(v, t) / v - drag(v). If power depended only on
speed, including the 2026 regulated MGU-K taper (1800 - 5 v kW above 290 km/h), the car
would settle at an equilibrium speed and approach it from below; it would not slow down.
A sustained deceleration at full throttle with no braking and little lateral load means
power is falling with *time*: the battery has stopped deploying, or the car is harvesting
at full throttle. Active-aero and ERS state are not published (FIA data policy, 2026), so
this indirect signature is the only public view of energy management.

Metrics per straight (model-light):
- speed_drop_kmh      peak speed minus speed at the end of the straight
- decel_distance_m    metres of full-throttle deceleration (a_x < -0.3 m/s^2)
- power_deficit_kw    m * |a_x| * v averaged over the decelerating part: the minimum power
                      shortfall relative to holding speed (drag change ignored, so a
                      lower bound)
- time_loss_s         time lost against holding the peak speed to the end of the straight
                      (an upper bound on what full deployment could recover)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from amr_aerotwin.physics.dynamics import VehicleState
from amr_aerotwin.physics.vehicle_params import straight_segments

DECEL_THRESHOLD_MS2 = -0.3


def straight_energy_metrics(state: VehicleState, min_length_m: float = 300.0) -> pd.DataFrame:
    """Per-straight clipping metrics for one lap."""
    rows = []
    step = state.lap.grid_step_m
    for seg in straight_segments(state, min_length_m=min_length_m, trim_m=10.0):
        v = state.speed_smooth_ms[seg]
        ax = state.ax_ms2[seg]
        i_peak = int(np.argmax(v))
        after = slice(i_peak, len(seg))
        decel = ax[after] < DECEL_THRESHOLD_MS2
        v_after = v[after]
        deficit = state.mass_kg * np.abs(ax[after][decel]) * v_after[decel] / 1000.0
        rows.append(
            {
                "start_m": float(state.distance_m[seg[0]]),
                "length_m": float(len(seg) * step),
                "peak_speed_kmh": float(v[i_peak] * 3.6),
                "end_speed_kmh": float(v[-1] * 3.6),
                "speed_drop_kmh": float((v[i_peak] - v[-1]) * 3.6),
                "peak_position_frac": float(i_peak / max(len(seg) - 1, 1)),
                "decel_distance_m": float(np.sum(ax < DECEL_THRESHOLD_MS2) * step),
                "power_deficit_kw": float(np.mean(deficit)) if len(deficit) else 0.0,
                "time_loss_s": float(np.sum(step * (1.0 / v_after - 1.0 / v[i_peak]))),
            }
        )
    return pd.DataFrame(rows)


def lap_energy_summary(state: VehicleState) -> dict[str, float]:
    """Totals over all straights of one lap."""
    df = straight_energy_metrics(state)
    if df.empty:
        return {"n_straights": 0.0, "speed_drop_kmh": 0.0, "decel_distance_m": 0.0,
                "power_deficit_kw": 0.0, "time_loss_s": 0.0}
    return {
        "n_straights": float(len(df)),
        "speed_drop_kmh": float(df["speed_drop_kmh"].mean()),
        "decel_distance_m": float(df["decel_distance_m"].sum()),
        "power_deficit_kw": float(np.average(df["power_deficit_kw"], weights=df["decel_distance_m"] + 1e-9)),
        "time_loss_s": float(df["time_loss_s"].sum()),
    }
