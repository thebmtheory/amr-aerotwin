"""Lap simulator against analytic answers."""

import numpy as np
import pytest

from amr_aerotwin.domain import GRAVITY_ACCEL as G
from amr_aerotwin.physics.lapsim import (
    LIMIT_BRAKE,
    LIMIT_CORNER,
    VehicleParams,
    iso_lap_time_grid,
    lap_time_sensitivities,
    max_cornering_speed,
    simulate_lap,
)
from conftest import stadium_track

CAR = VehicleParams(mass_kg=800.0, cla_m2=4.5, cda_m2=1.3, mu=1.8, power_w=700e3, rho_kg_m3=1.2)


def test_corner_speed_without_aero_is_sqrt_mu_g_r():
    p = VehicleParams(800, 0.0, 1.0, 1.5, 1e5)
    assert max_cornering_speed(np.array([1 / 50.0]), p)[0] == pytest.approx(np.sqrt(1.5 * G * 50), rel=1e-9)


def test_corner_speed_with_aero_solves_the_balance_equation():
    k = 1 / 120.0
    v = max_cornering_speed(np.array([k]), CAR)[0]
    q = 0.5 * CAR.rho_kg_m3 * v**2
    assert v**2 * k == pytest.approx(CAR.mu * (G + q * CAR.cla_m2 / CAR.mass_kg), rel=1e-9)


def test_constant_radius_circle_settles_on_the_friction_ellipse():
    """On a closed circle the car must use some grip to beat drag: (ax/k a)^2 + (ay/a)^2 = 1."""
    r = 40.0
    s = np.linspace(0, 2 * np.pi * r, 600, endpoint=False)
    res = simulate_lap(s, np.full_like(s, 1 / r), CAR, lap_length_m=2 * np.pi * r)
    v = res.speed_ms[300]
    assert np.ptp(res.speed_ms) < 1e-3 * v  # steady state
    q = 0.5 * CAR.rho_kg_m3 * v**2
    a_tot = CAR.mu * (G + q * CAR.cla_m2 / CAR.mass_kg)
    a_long = q * CAR.cda_m2 / CAR.mass_kg + G * CAR.crr
    ellipse = (a_long / (CAR.long_grip_scale * a_tot)) ** 2 + (v**2 / r / a_tot) ** 2
    assert ellipse == pytest.approx(1.0, abs=0.01)
    assert v < max_cornering_speed(np.array([1 / r]), CAR)[0]
    assert res.lap_time_s == pytest.approx(2 * np.pi * r / v, rel=1e-3)


def test_long_straight_reaches_drag_limited_terminal_speed():
    p = VehicleParams(800, 4.5, 1.2, 1.8, 600e3, 1.2, crr=0.0)
    s = np.arange(0, 20000, 5.0)
    res = simulate_lap(s, np.zeros_like(s), p, closed=False)
    v_inf = (2 * p.power_w / (p.rho_kg_m3 * p.cda_m2)) ** (1 / 3)
    assert res.speed_ms[len(s) // 2] == pytest.approx(v_inf, rel=2e-3)


def test_braking_distance_without_aero_matches_kinematics():
    # Open straight ending in a very tight hairpin: braking from v_inf down to the hairpin limit.
    p = VehicleParams(800, 0.0, 1e-6, 1.5, 2e6, 1.2, crr=0.0, long_grip_scale=1.0)
    s = np.arange(0, 3000, 1.0)
    k = np.zeros_like(s)
    k[-1] = 1 / 10.0
    res = simulate_lap(s, k, p, closed=False)
    v_end = np.sqrt(1.5 * G * 10.0)
    braking = res.limit == LIMIT_BRAKE
    d = s[-1] - s[np.flatnonzero(braking)[0]]
    v0 = res.speed_ms[np.flatnonzero(braking)[0]]
    assert d == pytest.approx((v0**2 - v_end**2) / (2 * 1.5 * G), rel=0.02)


def test_sensitivity_signs_and_physical_magnitudes():
    s, k, *_ , length = stadium_track()
    sens = lap_time_sensitivities(s, k, CAR, lap_length_m=length)
    assert sens["cla_m2_plus_1pct_s"] < 0
    assert sens["cda_m2_plus_1pct_s"] > 0
    assert sens["power_w_plus_1pct_s"] < 0
    assert sens["mu_plus_1pct_s"] < 0
    assert sens["mass_plus_10kg_s"] > 0


def test_low_drag_mode_on_straights_is_faster():
    s, k, *_ , length = stadium_track()
    base = simulate_lap(s, k, CAR, lap_length_m=length).lap_time_s
    p = VehicleParams(**{**CAR.__dict__, "low_drag_cda_m2": 0.9})
    faster = simulate_lap(s, k, p, low_drag_mask=k == 0, lap_length_m=length).lap_time_s
    assert faster < base


def test_iso_grid_is_zero_at_baseline_and_monotone():
    s, k, *_ , length = stadium_track()
    pct = np.array([-5.0, 0.0, 5.0])
    grid = iso_lap_time_grid(s, k, CAR, pct, pct, lap_length_m=length)
    assert grid[1, 1] == pytest.approx(0.0, abs=1e-9)
    assert grid[2, 1] < 0 < grid[0, 1]  # more downforce faster
    assert grid[1, 2] > 0 > grid[1, 0]  # more drag slower


def test_closed_lap_has_no_start_finish_discontinuity():
    s, k, *_ , length = stadium_track()
    v = simulate_lap(s, k, CAR, lap_length_m=length).speed_ms
    assert abs(v[0] - v[-1]) < 2.0
