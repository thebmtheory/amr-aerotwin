"""Unit tests for Module 2: Track regime classification, de-confounding, and dynamics state."""

import numpy as np

from amr_aerotwin.data.ingestion import align_lap_to_spatial_grid
from amr_aerotwin.physics.dynamics import (
    REGIME_AERO_DRAG,
    REGIME_HIGH_SPEED_AERO,
    REGIME_LOW_SPEED_MECH,
    REGIME_TRACTION_BRAKING,
    classify_track_regimes,
    compute_confounder_lap_offset_s,
    estimate_vehicle_dynamics_state,
)


def test_classify_track_regimes_identifies_all_four_zones() -> None:
    """Verify slow corner, fast corner, braking zone, and high-speed straight classification."""
    speed_ms = np.array([35.0, 65.0, 50.0, 80.0])
    throttle_pct = np.array([60.0, 85.0, 0.0, 100.0])
    brake_flag = np.array([0.0, 0.0, 1.0, 0.0])
    curvature_inv_m = np.array([0.0040, 0.0020, 0.0002, 0.0001])

    regimes = classify_track_regimes(speed_ms, throttle_pct, brake_flag, curvature_inv_m)
    assert regimes[0] == REGIME_LOW_SPEED_MECH
    assert regimes[1] == REGIME_HIGH_SPEED_AERO
    assert regimes[2] == REGIME_TRACTION_BRAKING
    assert regimes[3] == REGIME_AERO_DRAG


def test_compute_confounder_lap_offset_s_scales_with_fuel_and_tyres() -> None:
    """Verify heavy fuel FP1 lap has larger confounder offset than low-fuel Qualifying lap."""
    raw = {
        "distance": np.linspace(0, 100, 21),
        "speed": np.full(21, 200.0),
        "throttle": np.full(21, 100.0),
        "brake": np.zeros(21),
        "gear": np.full(21, 6),
        "drs": np.zeros(21),
        "x": np.linspace(0, 1000, 21),
        "y": np.zeros(21),
        "z": np.zeros(21),
    }
    q_trace = align_lap_to_spatial_grid(
        raw, session_type="Qualifying", compound="SOFT", tyre_life_laps=1, fuel_load_kg=5.0
    )
    fp1_trace = align_lap_to_spatial_grid(
        raw, session_type="Practice 1", compound="HARD", tyre_life_laps=8, fuel_load_kg=45.0
    )

    q_conf = compute_confounder_lap_offset_s(q_trace)
    fp1_conf = compute_confounder_lap_offset_s(fp1_trace)

    assert fp1_conf["fuel_penalty_s"] > q_conf["fuel_penalty_s"] + 1.0
    assert fp1_conf["total_confounder_s"] > q_conf["total_confounder_s"] + 2.5


def test_estimate_vehicle_dynamics_state_returns_valid_physical_bounds() -> None:
    """Verify full vehicle dynamics state computation on a synthetic track segment."""
    s = np.linspace(0, 500, 101)
    raw = {
        "distance": s,
        "speed": 220.0 + 40.0 * np.sin(s / 100.0),
        "throttle": np.full_like(s, 100.0),
        "brake": np.zeros_like(s),
        "gear": np.full_like(s, 7),
        "drs": np.ones_like(s),
        "x": s * 10.0,
        "y": 50.0 * np.sin(s / 80.0) * 10.0,
        "z": np.zeros_like(s),
    }
    trace = align_lap_to_spatial_grid(raw, grid_step_m=5.0, max_distance_m=500.0)
    state = estimate_vehicle_dynamics_state(trace)

    assert state.q_dyn_pa.shape == trace.distance_m.shape
    assert np.all(state.q_dyn_pa > 0.0)
    assert np.all((state.cd_a_proxy_m2 >= 0.70) & (state.cd_a_proxy_m2 <= 1.85))
    assert np.all((state.cl_a_proxy_m2 >= 0.50) & (state.cl_a_proxy_m2 <= 6.50))
