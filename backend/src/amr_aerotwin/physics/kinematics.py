"""Module 1: Aerodynamic Thermodynamics, Track Kinematics, and Wind Yaw Vector Decomposition.

This module transforms raw spatial trajectories (X, Y, s) and meteorological telemetry
into physical vehicle-frame aerodynamic states (air density, curvature, lateral/longitudinal
accelerations, true airspeed, and aerodynamic yaw angle beta_aero).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from amr_aerotwin.domain import (
    KELVIN_OFFSET,
    R_SPECIFIC_DRY_AIR,
    AmbientState,
)


def compute_air_density_kg_m3(ambient: AmbientState) -> float:
    """Compute dry air density rho (kg/m^3) using the Ideal Gas Law: rho = P / (R_specific * T).

    Why Vehicle Science cares:
    Aerodynamic downforce (L = 0.5 * rho * v_air^2 * C_L * A) and drag scale linearly with
    air density rho. Comparing Silverstone (sea level, cool) or FP1 (hot afternoon) to
    Qualifying (cool evening) without normalizing for rho introduces a 2-4% aero error.

    Args:
        ambient: AmbientState containing pressure_mbar (hPa) and air_temp_c (Celsius).

    Returns:
        Air density rho in kg/m^3.
    """
    pressure_pa = ambient.pressure_mbar * 100.0
    temp_kelvin = ambient.air_temp_c + KELVIN_OFFSET
    return float(pressure_pa / (R_SPECIFIC_DRY_AIR * temp_kelvin))


def compute_track_heading_and_curvature(
    distance_m: NDArray[np.float64],
    x_m: NDArray[np.float64],
    y_m: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Compute instantaneous car heading angle psi(s) and signed track curvature kappa(s).

    Mathematical Formulation:
    Given parameterized spatial coordinates X(s), Y(s) with respect to arc length s:
      - Tangent vector: (dX/ds, dY/ds)
      - Heading angle (rad, mathematical convention from +X East axis):
            psi(s) = arctan2(dY/ds, dX/ds)
      - Signed planar curvature (m^-1):
            kappa(s) = (X' Y'' - Y' X'') / ((X'^2 + Y'^2)^(3/2))

    Args:
        distance_m: Monotonically increasing arc-length array s (meters), shape (N,).
        x_m: GPS X coordinate array (meters, East), shape (N,).
        y_m: GPS Y coordinate array (meters, North), shape (N,).

    Returns:
        Tuple of (heading_rad, curvature_inv_m), each of shape (N,).
    """
    dx_ds = np.gradient(x_m, distance_m)
    dy_ds = np.gradient(y_m, distance_m)
    d2x_ds2 = np.gradient(dx_ds, distance_m)
    d2y_ds2 = np.gradient(dy_ds, distance_m)

    heading_rad = np.arctan2(dy_ds, dx_ds)
    denom = np.power(dx_ds**2 + dy_ds**2, 1.5)
    denom = np.where(denom < 1e-9, 1e-9, denom)
    curvature_inv_m = (dx_ds * d2y_ds2 - dy_ds * d2x_ds2) / denom
    return heading_rad, curvature_inv_m


def decompose_aero_wind_vectors(
    speed_ms: NDArray[np.float64],
    heading_rad: NDArray[np.float64],
    ambient: AmbientState,
) -> dict[str, NDArray[np.float64]]:
    """Decompose ambient wind into car-frame Headwind, Crosswind, Airspeed, and Yaw Angle.

    Why Vehicle Science cares:
    When an F1 car rounds a high-speed corner (like Copse or Maggotts-Becketts) at speed v_car,
    an ambient crosswind v_wind creates a side-slip / aerodynamic yaw angle beta_aero.
    Under high yaw (> 4-6 deg), the underbody diffuser and rear wing experience asymmetric
    vortex shedding, causing sudden downforce loss.

    Coordinate Geometry:
    - Car heading angle `heading_rad` (psi) is measured counter-clockwise from East (+X).
      Car unit tangent vector: t_hat = (cos(psi), sin(psi))
      Car unit normal (left) vector: n_hat = (-sin(psi), cos(psi))
    - Meteorological wind direction `wind_direction_deg` is the compass angle (0=N, 90=E)
      that the wind is blowing FROM.
      In standard mathematical angle (CCW from East +X), the direction the air mass moves
      TOWARDS has velocity vector:
          w_x = -v_wind * sin(theta_met)
          w_y = -v_wind * cos(theta_met)
    - Projecting the wind onto the car's body axis:
      * Headwind component (opposing car motion, increasing aero dynamic pressure):
            v_headwind = -(w_x * cos(psi) + w_y * sin(psi))
      * Crosswind component (perpendicular to car heading):
            v_crosswind = -(w_x * (-sin(psi)) + w_y * cos(psi))
      * Effective longitudinal airspeed:
            v_air_long = max(speed_ms + v_headwind, 1.0)
      * Aerodynamic yaw angle (degrees):
            beta_aero_deg = degrees(arctan2(v_crosswind, v_air_long))

    Args:
        speed_ms: Ground speed of the car (m/s), shape (N,).
        heading_rad: Instantaneous car heading angle psi (radians, CCW from East), shape (N,).
        ambient: AmbientState containing wind_speed_ms and wind_direction_deg.

    Returns:
        Dictionary with keys:
          - 'v_headwind_ms': Headwind speed (+ means opposing car, - means tailwind)
          - 'v_crosswind_ms': Crosswind speed (m/s)
          - 'v_airspeed_ms': Effective resultant airspeed relative to car body (m/s)
          - 'beta_aero_deg': Aerodynamic yaw angle in degrees
    """
    theta_met_rad = np.radians(ambient.wind_direction_deg)
    w_x = -ambient.wind_speed_ms * np.sin(theta_met_rad)
    w_y = -ambient.wind_speed_ms * np.cos(theta_met_rad)

    v_headwind_ms = -(w_x * np.cos(heading_rad) + w_y * np.sin(heading_rad))
    v_crosswind_ms = -(-w_x * np.sin(heading_rad) + w_y * np.cos(heading_rad))

    v_air_long_ms = np.maximum(speed_ms + v_headwind_ms, 1.0)
    v_airspeed_ms = np.hypot(v_air_long_ms, v_crosswind_ms)
    beta_aero_deg = np.degrees(np.arctan2(v_crosswind_ms, v_air_long_ms))

    return {
        "v_headwind_ms": v_headwind_ms,
        "v_crosswind_ms": v_crosswind_ms,
        "v_airspeed_ms": v_airspeed_ms,
        "beta_aero_deg": beta_aero_deg,
    }
