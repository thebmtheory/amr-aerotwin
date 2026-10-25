"""Unit tests for Module 4: Counterfactual Setup Optimizer & FIA Cross-Verification."""

import numpy as np

from amr_aerotwin.data.ingestion import align_lap_to_spatial_grid
from amr_aerotwin.modeling.optimizer import (
    optimize_setup_slsqp,
    run_fia_cross_verification_audit,
    simulate_counterfactual_setup,
)
from amr_aerotwin.physics.dynamics import estimate_vehicle_dynamics_state


def _make_test_state(official_time_s: float = 85.593) -> tuple:
    s = np.linspace(0, 5840, 1169)
    # Realistic alternating straightaways (kappa=0, speed=300 km/h) and fast/slow corners
    phase = s / 350.0
    raw = {
        "distance": s,
        "speed": 255.0 + 50.0 * np.cos(phase),
        "throttle": np.where(np.cos(phase) > -0.4, 100.0, 55.0),
        "brake": np.where(np.cos(phase) <= -0.4, 1.0, 0.0),
        "gear": np.full_like(s, 7),
        "drs": np.where(np.cos(phase) > 0.7, 1, 0),
        "x": s * 10.0,
        "y": np.where(np.cos(phase) > 0.5, 0.0, 160.0 * np.sin(phase)) * 10.0,
        "z": np.zeros_like(s),
    }
    trace = align_lap_to_spatial_grid(
        raw,
        grid_step_m=5.0,
        max_distance_m=5840.0,
        official_lap_time_s=official_time_s,
        sector_times_s=(28.500, 34.093, 23.000),
        speed_trap_kmh=318.0,
    )
    return estimate_vehicle_dynamics_state(trace)


def test_simulate_counterfactual_setup_physical_tradeoff() -> None:
    """Verify adding rear wing gains cornering time but costs straight-line speed & drag time."""
    state = _make_test_state()

    plus_wing = simulate_counterfactual_setup(state, rear_wing_clicks=1.5)
    minus_wing = simulate_counterfactual_setup(state, rear_wing_clicks=-1.5)

    # Adding wing must cost time on straights (+delta_straight_drag_s) and reduce top speed
    assert plus_wing.delta_straight_drag_s > 0.0
    assert plus_wing.top_speed_delta_kmh < 0.0
    # Adding wing must gain time in high-speed corners (negative delta)
    assert plus_wing.delta_high_speed_corners_s < 0.0

    # Dropping wing must gain time on straights (negative delta) and increase top speed
    assert minus_wing.delta_straight_drag_s < 0.0
    assert minus_wing.top_speed_delta_kmh > 0.0


def test_optimize_setup_slsqp_finds_lap_time_improvement() -> None:
    """Verify SLSQP optimizer finds a strictly faster setup than baseline (0, 0, 0)."""
    state = _make_test_state()
    opt = optimize_setup_slsqp(state)

    assert opt.expected_lap_time_gain_s < 0.0
    assert len(opt.pareto_curve) == 19
    assert not opt.simulated_result.is_ood_extrapolation


def test_fia_cross_verification_audit_passes_submillisecond_checks() -> None:
    """Verify FIA cross-check confirms 0.00ms sector & integral conservation."""
    alo = _make_test_state(85.593)
    nor = _make_test_state(85.010)
    audit = run_fia_cross_verification_audit(alo, nor)

    assert audit.all_checks_passed
    assert audit.integration_error_ms < 0.1
    assert audit.fia_sector_consistency_error_ms < 0.1
