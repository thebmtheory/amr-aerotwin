"""Unit tests for Module 4B: G-G-V Envelope, Aero Yaw Polar, Corner Audit, and Anomaly Investigator."""

import numpy as np

from amr_aerotwin.data.ingestion import align_lap_to_spatial_grid
from amr_aerotwin.modeling.surrogate import build_surrogate_and_attribution
from amr_aerotwin.modeling.validation import (
    compute_aero_yaw_sensitivity_polar,
    compute_ggv_envelope,
    decompose_circuit_corners,
    investigate_residuals_and_anomalies,
)
from amr_aerotwin.physics.dynamics import estimate_vehicle_dynamics_state


def _make_pair() -> tuple:
    s = np.linspace(0, 3000, 601)
    phase = s / 220.0
    raw_t = {
        "distance": s,
        "speed": 225.0 + 55.0 * np.cos(phase),
        "throttle": np.where(np.cos(phase) > -0.3, 100.0, 45.0),
        "brake": np.where(np.cos(phase) <= -0.3, 1.0, 0.0),
        "gear": np.full_like(s, 6),
        "drs": np.where(np.cos(phase) > 0.6, 1, 0),
        "x": s * 10.0,
        "y": 140.0 * np.sin(phase) * 10.0,
        "z": np.zeros_like(s),
    }
    raw_b = {**raw_t, "speed": raw_t["speed"] + 5.0}
    t_tr = align_lap_to_spatial_grid(raw_t, grid_step_m=5.0, max_distance_m=3000.0)
    b_tr = align_lap_to_spatial_grid(raw_b, grid_step_m=5.0, max_distance_m=3000.0)
    return estimate_vehicle_dynamics_state(t_tr), estimate_vehicle_dynamics_state(b_tr)


def test_ggv_envelope_and_aero_yaw_polar() -> None:
    """Verify G-G-V friction envelope and virtual wind-tunnel yaw polar generation."""
    t_state, b_state = _make_pair()

    ggv = compute_ggv_envelope(t_state, b_state)
    assert len(ggv.target_ay_g) == len(ggv.target_ax_g)
    assert ggv.peak_lateral_g_benchmark >= ggv.peak_lateral_g_target
    assert "high_speed_aero_g2" in ggv.target_envelope_area_g2

    polar = compute_aero_yaw_sensitivity_polar(t_state, b_state)
    assert len(polar.yaw_bins_deg) == 21
    assert polar.target_zero_yaw_cla_m2 > 2.0
    # Downforce at +/- 5 deg yaw must be strictly lower than at 0 deg yaw
    assert polar.target_cla_curve_m2[0] < polar.target_cla_curve_m2[10]


def test_corner_phase_decomposition_and_anomaly_investigator() -> None:
    """Verify 3-phase corner breakdown and scipy.stats residual/anomaly report."""
    t_state, b_state = _make_pair()
    corners = [
        {"number": 1, "label": "Abbey", "distance_m": 450.0, "x_m": 450.0, "y_m": 20.0},
        {"number": 9, "label": "Copse", "distance_m": 1500.0, "x_m": 1500.0, "y_m": -40.0},
    ]

    c_audits = decompose_circuit_corners(t_state, b_state, corners)
    assert len(c_audits) == 2
    for ca in c_audits:
        assert np.isclose(
            ca.entry_dt_ms + ca.apex_dt_ms + ca.exit_dt_ms, ca.total_corner_dt_ms, atol=0.2
        )

    sur = build_surrogate_and_attribution(t_state, b_state)
    val_rep = investigate_residuals_and_anomalies(t_state, b_state, sur, corners)
    assert len(val_rep.calibration_nominal_levels) == 9
    assert len(val_rep.calibration_empirical_levels) == 9
    assert 0.0 <= val_rep.calibration_ece <= 0.35
    assert len(val_rep.anomalies) >= 1
