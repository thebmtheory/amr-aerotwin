"""Unit tests for Module 1: Aerodynamic Thermodynamics, Track Kinematics, and Wind Yaw."""

import numpy as np
import pytest

from amr_aerotwin.domain import AmbientState
from amr_aerotwin.physics.kinematics import (
    compute_air_density_kg_m3,
    compute_track_heading_and_curvature,
    decompose_aero_wind_vectors,
)


def test_compute_air_density_standard_atmosphere() -> None:
    """Verify Ideal Gas Law air density at ISA sea level (15 deg C, 1013.25 mbar -> ~1.225 kg/m^3)."""
    ambient = AmbientState(
        air_temp_c=15.0,
        track_temp_c=25.0,
        pressure_mbar=1013.25,
        wind_speed_ms=5.0,
        wind_direction_deg=180.0,
    )
    rho = compute_air_density_kg_m3(ambient)
    assert np.isclose(rho, 1.2250, atol=1e-3)


def test_compute_track_heading_and_curvature_circular_corner() -> None:
    """Verify curvature kappa(s) = 1/R for a constant-radius R=200m left-hand corner."""
    radius_m = 200.0
    distance_m = np.linspace(0.0, 150.0, 151)
    theta = distance_m / radius_m
    x_m = radius_m * np.cos(theta)
    y_m = radius_m * np.sin(theta)

    heading_rad, curvature_inv_m = compute_track_heading_and_curvature(distance_m, x_m, y_m)

    assert heading_rad.shape == distance_m.shape
    assert curvature_inv_m.shape == distance_m.shape
    # Interior points should match analytical curvature 1/200 = 0.005 m^-1 closely
    assert np.allclose(curvature_inv_m[5:-5], 1.0 / radius_m, atol=1e-4)


def test_decompose_aero_wind_vectors_pure_headwind_and_crosswind() -> None:
    """Verify wind projection when driving due North (+Y, psi=pi/2) with North and East winds."""
    speed_ms = np.array([60.0, 60.0])
    # Car heading due North (+Y axis -> psi = +pi/2 radians)
    heading_rad = np.array([np.pi / 2.0, np.pi / 2.0])

    # Case 1: Wind blowing FROM North (0 deg) at 10 m/s -> pure 10 m/s headwind, 0 crosswind
    ambient_north_wind = AmbientState(
        air_temp_c=20.0,
        track_temp_c=32.0,
        pressure_mbar=1005.0,
        wind_speed_ms=10.0,
        wind_direction_deg=0.0,
    )
    res_north = decompose_aero_wind_vectors(speed_ms, heading_rad, ambient_north_wind)
    assert np.allclose(res_north["v_headwind_ms"], 10.0, atol=1e-5)
    assert np.allclose(res_north["v_crosswind_ms"], 0.0, atol=1e-5)
    assert np.allclose(res_north["v_airspeed_ms"], 70.0, atol=1e-5)
    assert np.allclose(res_north["beta_aero_deg"], 0.0, atol=1e-5)

    # Case 2: Wind blowing FROM East (90 deg) at 10 m/s -> pure 10 m/s crosswind, 0 headwind
    ambient_east_wind = AmbientState(
        air_temp_c=20.0,
        track_temp_c=32.0,
        pressure_mbar=1005.0,
        wind_speed_ms=10.0,
        wind_direction_deg=90.0,
    )
    res_east = decompose_aero_wind_vectors(speed_ms, heading_rad, ambient_east_wind)
    assert np.allclose(res_east["v_headwind_ms"], 0.0, atol=1e-5)
    assert np.allclose( np.abs(res_east["v_crosswind_ms"]), 10.0, atol=1e-5)
    expected_beta = np.degrees(np.arctan2(10.0, 60.0))
    assert np.allclose(np.abs(res_east["beta_aero_deg"]), expected_beta, atol=1e-4)
