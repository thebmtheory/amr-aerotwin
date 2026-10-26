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
