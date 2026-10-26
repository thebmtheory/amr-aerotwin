"""Calibration recovers known parameters; autocorrelation handling; discrepancy GP."""

import numpy as np
import pytest
from amr_aerotwin.modeling.calibration import (
    calibrate_lapsim,
    effective_sample_size,
    fit_discrepancy_gp,
    lag1_autocorrelation,
    metropolis_posterior,
    posterior_lap_times,
)
from amr_aerotwin.physics.lapsim import VehicleParams, simulate_lap
from conftest import stadium_track

TRUE = VehicleParams(mass_kg=800.0, cla_m2=4.2, cda_m2=1.25, mu=1.75, power_w=640e3, rho_kg_m3=1.18, long_grip_scale=0.85)


def _track():
    # Two straights and arcs of different radii so grip, aero and power are all identifiable
    s1, k1, *_ , l1 = stadium_track(straight_m=900.0, radius_m=35.0)
    s2, k2, *_ , l2 = stadium_track(straight_m=300.0, radius_m=160.0)
    k = np.concatenate([k1, k2])
    s = np.arange(len(k)) * 5.0
    return s, k, len(k) * 5.0


def _calibrate(seed):
    s, k, length = _track()
    true = simulate_lap(s, k, TRUE, lap_length_m=length)
    obs = true.speed_ms + np.random.default_rng(seed).normal(0, 0.8, len(s))
    base = VehicleParams(800.0, 4.5, 1.3, 1.6, 700e3, 1.18)
    return s, k, length, true, calibrate_lapsim(s, k, obs, base, true.lap_time_s, lap_length_m=length)


def test_calibration_reproduces_the_lap_and_recovers_parameters():
    s, k, length, true, cal = _calibrate(0)
    for name in ("mu", "cla_m2", "cda_m2", "power_w"):
        assert cal.ci90()[name][0] == pytest.approx(getattr(TRUE, name), rel=0.15), name
    assert abs(cal.lap_time_error_s) < 0.1  # 0.1% of a 100 s lap
    # The fitted model reproduces the noise-free truth far better than the noise level
    assert np.sqrt(np.mean((cal.sim.speed_ms - true.speed_ms) ** 2)) * 3.6 < 1.5
    draws = posterior_lap_times(cal, s, k, lap_length_m=length, n_draws=60)
    assert abs(np.mean(draws) - true.lap_time_s) < 0.1


def test_grip_and_downforce_are_partially_confounded_on_one_lap():
    """mu and ClA trade off along a ridge (the same strong negative correlation seen on real laps)."""
    *_, cal = _calibrate(0)
    corr = cal.correlation()
    i, j = cal.names.index("mu"), cal.names.index("cla_m2")
    assert corr[i, j] < -0.5


def test_drag_and_power_intervals_have_reasonable_frequentist_coverage():
    hits = {"cda_m2": 0, "power_w": 0}
    seeds = range(8)
    for seed in seeds:
        *_, cal = _calibrate(seed)
        for name in hits:
            _, lo, hi = cal.ci90()[name]
            hits[name] += lo <= getattr(TRUE, name) <= hi
    for name, h in hits.items():
        assert h / len(seeds) >= 0.6, name


def test_metropolis_agrees_with_laplace_on_well_identified_problem():
    s, k, length = _track()
    true = simulate_lap(s, k, TRUE, lap_length_m=length)
    obs = true.speed_ms + np.random.default_rng(1).normal(0, 0.8, len(s))
    cal = calibrate_lapsim(s, k, obs, VehicleParams(800.0, 4.5, 1.3, 1.6, 700e3, 1.18), true.lap_time_s, lap_length_m=length)
    samples, acc = metropolis_posterior(cal, s, k, lap_length_m=length, n_steps=1200, burn_in=200)
    assert 0.1 < acc < 0.7
    ratio = samples.std(axis=0) / np.sqrt(np.diag(cal.cov_log))
    assert np.all((ratio > 0.5) & (ratio < 2.0))


def test_lag1_autocorrelation_of_ar1_and_effective_sample_size():
    rng = np.random.default_rng(2)
    phi = 0.9
    e = rng.normal(size=20000)
    x = np.zeros_like(e)
    for i in range(1, len(x)):
        x[i] = phi * x[i - 1] + e[i]
    assert lag1_autocorrelation(x) == pytest.approx(phi, abs=0.01)
    assert effective_sample_size(1000, 0.9) == pytest.approx(1000 * 0.1 / 1.9)
    assert effective_sample_size(1000, 0.0) == 1000


def test_discrepancy_gp_finds_a_localised_bias():
    s = np.arange(0, 5000, 5.0)
    bump = 15.0 / 3.6 * np.exp(-0.5 * ((s - 2500) / 60) ** 2)  # +15 km/h near 2.5 km
    resid = bump + np.random.default_rng(3).normal(0, 0.5, len(s))
    d = fit_discrepancy_gp(s, resid)
    i = int(np.argmin(np.abs(s - 2500)))
    assert d.mean_kmh[i] == pytest.approx(15.0, abs=2.5)
    assert abs(d.mean_kmh[int(np.argmin(np.abs(s - 500)))]) < 2.0
    assert np.all(d.std_kmh > 0)
