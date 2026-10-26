"""Air density, curvature, GPS-spline kinematics and wind decomposition."""

import numpy as np
import pytest
from amr_aerotwin.domain import AmbientState
from amr_aerotwin.physics.kinematics import (
    compute_air_density_kg_m3,
    compute_track_heading_and_curvature,
    consensus_curvature,
    decompose_aero_wind_vectors,
    gps_spline_kinematics,
    select_gps_smoothing,
    turning_number,
)


def _amb(**kw):
    base = dict(air_temp_c=15.0, track_temp_c=25.0, pressure_mbar=1013.25, wind_speed_ms=0.0,
                wind_direction_deg=0.0, relative_humidity_pct=0.0)
    base.update(kw)
    return AmbientState(**base)


def test_dry_air_density_matches_isa_sea_level():
    assert compute_air_density_kg_m3(_amb()) == pytest.approx(1.2250, abs=1e-3)


def test_humid_air_is_lighter_than_dry_air():
    dry = compute_air_density_kg_m3(_amb(air_temp_c=25.0))
    wet = compute_air_density_kg_m3(_amb(air_temp_c=25.0, relative_humidity_pct=80.0))
    # Water vapour (M=18) displaces dry air (M=29): about -1% at 25 C, 80% RH
    assert -0.015 < (wet - dry) / dry < -0.005


def test_curvature_of_closed_circle_is_one_over_radius():
    r = 200.0
    s = np.linspace(0.0, 2 * np.pi * r, 600, endpoint=False)  # uniform, closed grid
    th = s / r
    _, k = compute_track_heading_and_curvature(s, r * np.cos(th), r * np.sin(th), closed=True)
    assert np.allclose(k, 1 / r, rtol=1e-3)
    assert turning_number(k, s[1] - s[0]) == pytest.approx(1.0, abs=2e-3)


def _circle_fixes(r=250.0, v=50.0, hz=4.0, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    t_lap = 2 * np.pi * r / v
    t = np.arange(0.0, t_lap, 1 / hz)
    th = v * t / r
    x = r * np.sin(th) + rng.normal(0, noise, len(t))
    y = r * (1 - np.cos(th)) + rng.normal(0, noise, len(t))
    return t, x, y, t_lap


def test_gps_spline_recovers_curvature_and_speed_on_clean_circle():
    t, x, y, t_lap = _circle_fixes()
    t_eval = np.linspace(1, t_lap - 1, 400)
    k, v = gps_spline_kinematics(t, x, y, t_lap, t_eval, lam=0.05)
    assert np.allclose(k, 1 / 250.0, rtol=0.01)
    assert np.allclose(v, 50.0, rtol=0.005)


def test_smoothing_selection_prefers_more_smoothing_for_noisier_gps():
    t, x, y, t_lap = _circle_fixes(noise=1.5, seed=1)
    t_grid = np.linspace(0, t_lap, 800)
    lam_noisy, scores = select_gps_smoothing([(t, x, y, t_lap, t_grid, np.full(800, 50.0))], (0.01, 0.1, 1.0))
    assert lam_noisy > 0.01
    assert scores[lam_noisy] == min(scores.values())


def test_consensus_curvature_rejects_a_single_outlier_lap():
    good = [np.full(100, 0.01) + 0.0001 * i for i in range(5)]
    bad = np.full(100, 0.2)
    assert np.allclose(consensus_curvature(good + [bad]), 0.0102, atol=2e-4)


def test_wind_projection_head_and_cross_wind():
    v = np.array([60.0])
    north = np.array([np.pi / 2])
    head = decompose_aero_wind_vectors(v, north, _amb(wind_speed_ms=10.0, wind_direction_deg=0.0))
    assert head["v_headwind_ms"][0] == pytest.approx(10.0)
    assert head["v_crosswind_ms"][0] == pytest.approx(0.0, abs=1e-9)
    assert head["v_airspeed_ms"][0] == pytest.approx(70.0)
    cross = decompose_aero_wind_vectors(v, north, _amb(wind_speed_ms=10.0, wind_direction_deg=90.0))
    assert cross["v_headwind_ms"][0] == pytest.approx(0.0, abs=1e-9)
    assert abs(cross["beta_aero_deg"][0]) == pytest.approx(np.degrees(np.arctan2(10, 60)))
