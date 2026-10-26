"""Grip-vs-q and drag/power estimators recover known values."""

import numpy as np
import pandas as pd
import pytest

from amr_aerotwin.domain import GRAVITY_ACCEL as G
from amr_aerotwin.physics.vehicle_params import fit_grip_vs_q, limit_points_for_fit


def _points(intercept_g=2.6, slope_g_per_kpa=0.75, n=14, noise_g=0.08, seed=0):
    rng = np.random.default_rng(seed)
    q = np.linspace(300, 4800, n)
    a = (intercept_g + slope_g_per_kpa * q / 1000) * G + rng.normal(0, noise_g * G, n)
    return pd.DataFrame({"corner_index": np.arange(n), "q_pa": q, "ay_ms2": a, "ax_ms2": 0.0,
                         "a_comb_ms2": a, "flat_out": False, "speed_kmh": 0.0, "distance_m": 0.0})


def test_grip_fit_recovers_line_inside_driven_range():
    pts = _points()
    g = fit_grip_vs_q(pts, q_low_pa=800.0, q_high_pa=3500.0)
    assert g.grip_low_g == pytest.approx(2.6 + 0.75 * 0.8, abs=0.1)
    assert g.grip_high_g == pytest.approx(2.6 + 0.75 * 3.5, abs=0.1)
    assert g.grip_high_ci90[0] < 2.6 + 0.75 * 3.5 < g.grip_high_ci90[1]
    assert 0 < g.aero_share_high < 1


def test_flat_out_and_sub_limit_corners_are_excluded():
    pts = _points()
    pts.loc[0, "flat_out"] = True
    pts.loc[1, "ay_ms2"] = 1.0 * G
    assert len(limit_points_for_fit(pts)) == len(pts) - 2


def test_grip_fit_returns_none_without_a_spread_of_dynamic_pressure():
    pts = _points()
    pts["q_pa"] = 2000.0
    assert fit_grip_vs_q(pts, 1000, 3000) is None


def test_drag_power_fit_on_simulated_straights():
    from amr_aerotwin.domain import AlignedLap, AmbientState, LapMeta
    from amr_aerotwin.physics.dynamics import estimate_vehicle_state
    from amr_aerotwin.physics.vehicle_params import fit_drag_power

    # Integrate m dv/ds = P/v^2 - q CdA/v - m g Crr / v along three straights
    m, p_w, cda, rho = 805.0, 620e3, 1.35, 1.2
    step = 5.0
    v_all, thr = [], []
    for v0 in (35.0, 45.0, 55.0):
        v = v0
        for _ in range(int(900 / step)):
            a = p_w / (m * v) - 0.5 * rho * v * v * cda / m - G * 0.012
            v = np.sqrt(v * v + 2 * a * step)
            v_all.append(v)
            thr.append(100.0)
        for _ in range(int(300 / step)):  # braking/corner gap
            v_all.append(max(v_all[-1] - 1.0, 25.0))
            thr.append(0.0)
    n = len(v_all)
    s = np.arange(n) * step
    lap = AlignedLap(
        meta=LapMeta(2025, "T", "Qualifying", "X", "T", 1, float(np.sum(step / np.array(v_all)))),
        ambient=AmbientState(15.0, 30.0, 1013.25 * 1.2 / 1.225, 0.0, 0.0, 0.0),
        distance_m=s, time_s=np.cumsum(step / np.array(v_all)), speed_ms=np.array(v_all),
        throttle_pct=np.array(thr), brake=np.zeros(n), gear=np.full(n, 7.0), drs=np.zeros(n),
        rpm=np.zeros(n), x_m=s, y_m=np.zeros(n), z_m=np.zeros(n), lap_length_m=n * step,
    )
    st = estimate_vehicle_state(lap, mass_kg=m, curvature_inv_m=np.zeros(n))
    fit = fit_drag_power([st], fit_low_drag=False)
    assert fit.power_kw == pytest.approx(620.0, rel=0.05)
    assert fit.cda_m2 == pytest.approx(1.35, rel=0.06)
    v_inf = (2 * p_w / (1.2 * cda)) ** (1 / 3) * 3.6
    assert fit.v_inf_kmh == pytest.approx(v_inf, rel=0.01)
