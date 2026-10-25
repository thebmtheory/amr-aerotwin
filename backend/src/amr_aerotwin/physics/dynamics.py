"""Module 2: Vehicle Dynamics State Estimation, Track Regime Classification, and De-Confounding.

This module implements:
1. Automated physical regime segmentation along the 5m spatial grid:
   - LOW_SPEED_MECH (Mechanical grip & suspension compliance dominated)
   - HIGH_SPEED_AERO (Aerodynamic downforce C_L * A dominated)
   - TRACTION_BRAKING (Longitudinal tyre slip, braking & power-unit deployment)
   - AERO_DRAG (Terminal straight-line velocity & aerodynamic drag C_D * A dominated)
2. Physics-based de-confounding of lap/sector time deltas (removing fuel mass, tyre
   age/compound degradation, and session-to-session track rubber evolution).
3. Quasi-steady-state in-situ aerodynamic metric estimation (dynamic pressure q_dyn,
   lateral/longitudinal accelerations, effective C_L*A and C_D*A proxies).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.signal import savgol_filter

from amr_aerotwin.domain import (
    CAR_DRY_MASS_KG,
    FUEL_TIME_SENSITIVITY_S_PER_KG,
    GRAVITY_ACCEL,
    AlignedTelemetryTrace,
)
from amr_aerotwin.physics.kinematics import (
    compute_air_density_kg_m3,
    compute_track_heading_and_curvature,
    decompose_aero_wind_vectors,
)

# Physical regime labels
REGIME_LOW_SPEED_MECH = "LOW_SPEED_MECH"
REGIME_HIGH_SPEED_AERO = "HIGH_SPEED_AERO"
REGIME_TRACTION_BRAKING = "TRACTION_BRAKING"
REGIME_AERO_DRAG = "AERO_DRAG"

# Baseline tyre compound pace offsets (s/lap relative to SOFT) and degradation slopes (s/lap^2)
COMPOUND_BASE_OFFSET_S: dict[str, float] = {
    "SOFT": 0.00,
    "MEDIUM": 0.45,
    "HARD": 0.95,
    "INTERMEDIATE": 4.50,
    "WET": 11.00,
}
COMPOUND_DEG_PER_LAP_S: dict[str, float] = {
    "SOFT": 0.085,
    "MEDIUM": 0.052,
    "HARD": 0.031,
    "INTERMEDIATE": 0.060,
    "WET": 0.040,
}

# Session track rubber grip evolution baseline offset relative to Qualifying (s/lap)
SESSION_TRACK_EVOLUTION_OFFSET_S: dict[str, float] = {
    "Practice 1": 1.35,
    "FP1": 1.35,
    "Practice 2": 0.75,
    "FP2": 0.75,
    "Practice 3": 0.35,
    "FP3": 0.35,
    "Sprint Qualifying": 0.25,
    "Sprint": 0.20,
    "Qualifying": 0.00,
    "Q": 0.00,
    "Race": 0.40,
    "R": 0.40,
}


@dataclass(frozen=True)
class VehicleDynamicsState:
    """Enriched physical & aerodynamic state along the 5m spatial circuit grid."""

    trace: AlignedTelemetryTrace
    rho_kg_m3: float
    heading_rad: NDArray[np.float64]
    curvature_inv_m: NDArray[np.float64]
    ax_ms2: NDArray[np.float64]
    ay_ms2: NDArray[np.float64]
    v_headwind_ms: NDArray[np.float64]
    v_crosswind_ms: NDArray[np.float64]
    v_airspeed_ms: NDArray[np.float64]
    beta_aero_deg: NDArray[np.float64]
    q_dyn_pa: NDArray[np.float64]
    regime_labels: NDArray[np.str_]
    cl_a_proxy_m2: NDArray[np.float64]
    cd_a_proxy_m2: NDArray[np.float64]


def classify_track_regimes(
    speed_ms: NDArray[np.float64],
    throttle_pct: NDArray[np.float64],
    brake_flag: NDArray[np.float64],
    curvature_inv_m: NDArray[np.float64],
) -> NDArray[np.str_]:
    """Segment every spatial grid point into one of 4 physical Vehicle Science regimes.

    Classification Rules:
    1. LOW_SPEED_MECH: Significant cornering curvature (|kappa| > 0.0018 m^-1, R < 555m)
       and ground speed < 50.0 m/s (180 km/h). Mechanical grip & suspension dominated.
    2. HIGH_SPEED_AERO: Cornering curvature (|kappa| > 0.0010 m^-1, R < 1000m) and
       ground speed >= 50.0 m/s (180 km/h). Aerodynamic downforce (C_L * A) dominated.
    3. AERO_DRAG: Straight-line zones (|kappa| <= 0.0010 m^-1) with full throttle
       (>= 95%), no braking, and high speed (>= 62.0 m/s, ~223 km/h). Drag (C_D * A) dominated.
    4. TRACTION_BRAKING: All remaining braking zones, corner exits, and initial acceleration
       zones where longitudinal tyre slip and power unit torque delivery dominate.
    """
    n = len(speed_ms)
    regimes = np.full(n, REGIME_TRACTION_BRAKING, dtype="<U20")
    abs_kappa = np.abs(curvature_inv_m)

    is_low_speed_corner = (abs_kappa > 0.0018) & (speed_ms < 50.0)
    is_high_speed_corner = (abs_kappa > 0.0010) & (speed_ms >= 50.0)
    is_aero_drag_straight = (
        (abs_kappa <= 0.0010)
        & (throttle_pct >= 95.0)
        & (brake_flag < 0.1)
        & (speed_ms >= 62.0)
    )

    regimes[is_aero_drag_straight] = REGIME_AERO_DRAG
    regimes[is_high_speed_corner] = REGIME_HIGH_SPEED_AERO
    regimes[is_low_speed_corner] = REGIME_LOW_SPEED_MECH
    return regimes


def compute_confounder_lap_offset_s(trace: AlignedTelemetryTrace) -> dict[str, float]:
    """Compute lap-level time penalties from fuel mass, tyre state, and track evolution.

    Why Vehicle Science cares:
    Raw lap times are heavily confounded by fuel load (~0.032s/kg), tyre compound/age,
    and session rubber evolution. Subtracting these physical confounders isolates the
    true underlying vehicle setup and aerodynamic performance delta.
    """
    fuel_penalty_s = float(trace.fuel_Load_kg * FUEL_TIME_SENSITIVITY_S_PER_KG)
    comp = trace.compound.upper()
    compound_offset_s = COMPOUND_BASE_OFFSET_S.get(comp, 0.25)
    deg_rate_s = COMPOUND_DEG_PER_LAP_S.get(comp, 0.055)
    tyre_age_penalty_s = float(max(0, trace.tyre_life_laps - 1) * deg_rate_s)
    track_evol_penalty_s = SESSION_TRACK_EVOLUTION_OFFSET_S.get(trace.session_type, 0.0)

    total_confounder_s = (
        fuel_penalty_s + compound_offset_s + tyre_age_penalty_s + track_evol_penalty_s
    )
    return {
        "fuel_penalty_s": fuel_penalty_s,
        "compound_offset_s": compound_offset_s,
        "tyre_age_penalty_s": tyre_age_penalty_s,
        "track_evolution_penalty_s": track_evol_penalty_s,
        "total_confounder_s": total_confounder_s,
    }


def estimate_vehicle_dynamics_state(trace: AlignedTelemetryTrace) -> VehicleDynamicsState:
    """Compute full SI-unit kinematics, aerodynamic forces, and regime classification."""
    rho = compute_air_density_kg_m3(trace.ambient)

    # Smooth GPS (x, y) with Savitzky-Golay filter (105m window = 21 points at 5m)
    # to eliminate GPS quantization jitter in the 2nd derivative curvature kappa(s)
    n_pts = len(trace.distance_m)
    win = min(25, n_pts if n_pts % 2 == 1 else n_pts - 1)
    if win >= 7:
        x_smooth = savgol_filter(trace.x_m, window_length=win, polyorder=3)
        y_smooth = savgol_filter(trace.y_m, window_length=win, polyorder=3)
        v_smooth = savgol_filter(trace.speed_ms, window_length=min(11, win), polyorder=2)
    else:
        x_smooth, y_smooth, v_smooth = trace.x_m, trace.y_m, trace.speed_ms

    heading_rad, raw_curvature = compute_track_heading_and_curvature(
        trace.distance_m, x_smooth, y_smooth
    )
    if win >= 7:
        curvature_inv_m = savgol_filter(raw_curvature, window_length=win, polyorder=2)
    else:
        curvature_inv_m = raw_curvature

    wind = decompose_aero_wind_vectors(v_smooth, heading_rad, trace.ambient)

    # Longitudinal acceleration a_x = v * dv/ds and lateral acceleration a_y = v^2 * |kappa|
    # Cap curvature at hairline minimum radius R_min = 16.0m (|kappa| <= 0.0625 m^-1)
    abs_kappa_phys = np.minimum(np.abs(curvature_inv_m), 0.022)
    dv_ds = np.gradient(v_smooth, trace.distance_m)
    ax_ms2 = np.clip(v_smooth * dv_ds, -52.0, 18.0)
    ay_ms2 = np.clip((v_smooth**2) * abs_kappa_phys, 0.0, 54.0)

    # Dynamic pressure q_dyn = 0.5 * rho * v_airspeed^2 (Pascals)
    v_air = wind["v_airspeed_ms"]
    q_dyn_pa = 0.5 * rho * (v_air**2)

    regimes = classify_track_regimes(
        v_smooth, trace.throttle_pct, trace.brake_flag, curvature_inv_m
    )

    total_mass_kg = CAR_DRY_MASS_KG + trace.fuel_Load_kg
    mu_tyre = 1.65  # Effective peak lateral tyre friction coefficient on dry slicks

    # Effective Downforce Area proxy (C_L * A in m^2) during cornering
    required_normal_force_n = (total_mass_kg * ay_ms2) / mu_tyre
    aero_downforce_n = np.maximum(0.0, required_normal_force_n - total_mass_kg * GRAVITY_ACCEL * 0.35)
    cl_a_proxy_m2 = np.clip(aero_downforce_n / np.maximum(q_dyn_pa, 200.0), 0.5, 6.5)

    # Effective Drag Area proxy (C_D * A in m^2) on full-throttle straights
    # P_tractive (~680 kW wheel power at high speed) = (F_drag + m * a_x) * v
    tractive_force_n = np.where(trace.throttle_pct >= 95.0, 680_000.0 / np.maximum(v_smooth, 30.0), 0.0)
    drag_force_n = np.maximum(200.0, tractive_force_n - total_mass_kg * np.maximum(ax_ms2, 0.0))
    cd_a_raw = drag_force_n / np.maximum(q_dyn_pa, 200.0)
    # Adjust for DRS flap open (-22% drag area reduction)
    cd_a_proxy_m2 = np.clip(
        np.where(trace.drs_active > 0, cd_a_raw * 0.88, cd_a_raw),
        0.70,
        1.85,
    )

    return VehicleDynamicsState(
        trace=trace,
        rho_kg_m3=rho,
        heading_rad=heading_rad,
        curvature_inv_m=curvature_inv_m,
        ax_ms2=ax_ms2,
        ay_ms2=ay_ms2,
        v_headwind_ms=wind["v_headwind_ms"],
        v_crosswind_ms=wind["v_crosswind_ms"],
        v_airspeed_ms=v_air,
        beta_aero_deg=wind["beta_aero_deg"],
        q_dyn_pa=q_dyn_pa,
        regime_labels=regimes,
        cl_a_proxy_m2=cl_a_proxy_m2,
        cd_a_proxy_m2=cd_a_proxy_m2,
    )
