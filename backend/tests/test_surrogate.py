"""Unit tests for Module 3: POD Reduced-Order Model and Gaussian Process Surrogate."""

import numpy as np

from amr_aerotwin.data.ingestion import align_lap_to_spatial_grid
from amr_aerotwin.modeling.surrogate import (
    PODReducedOrderModel,
    build_surrogate_and_attribution,
)
from amr_aerotwin.physics.dynamics import estimate_vehicle_dynamics_state


def test_pod_reduced_order_model_captures_dominant_variance() -> None:
    """Verify SVD/POD compresses a rank-2 synthetic speed field with ~100% variance explained."""
    s = np.linspace(0, 1000, 200)
    mode1 = np.sin(s / 100.0)
    mode2 = np.cos(s / 50.0)

    rng = np.random.default_rng(42)
    snapshots = np.array(
        [200.0 + rng.normal(10, 2) * mode1 + rng.normal(5, 1) * mode2 for _ in range(8)]
    )

    rom = PODReducedOrderModel(n_modes=2)
    res = rom.fit_transform(snapshots)

    assert res.n_modes == 2
    assert res.spatial_modes.shape == (2, 200)
    assert res.modal_coefficients.shape == (8, 2)
    assert res.cumulative_variance_ratio[-1] > 0.999
    assert res.reconstruction_rmse < 1e-6


def test_build_surrogate_and_attribution_conservation_and_calibration() -> None:
    """Verify GP surrogate attributions sum exactly to total lap delta and 90% CI is calibrated."""
    s = np.linspace(0, 2000, 401)
    raw_alo = {
        "distance": s,
        "speed": 230.0 + 35.0 * np.sin(s / 180.0),
        "throttle": np.where(np.sin(s / 180.0) > -0.2, 100.0, 40.0),
        "brake": np.where(np.sin(s / 180.0) <= -0.2, 1.0, 0.0),
        "gear": np.full_like(s, 6),
        "drs": np.where(np.sin(s / 180.0) > 0.5, 1, 0),
        "x": s * 10.0,
        "y": 120.0 * np.sin(s / 150.0) * 10.0,
        "z": np.zeros_like(s),
    }
    raw_nor = {
        **raw_alo,
        "speed": raw_alo["speed"] + 4.5,  # Benchmark is 4.5 km/h faster
    }

    alo_trace = align_lap_to_spatial_grid(raw_alo, grid_step_m=5.0, max_distance_m=2000.0)
    nor_trace = align_lap_to_spatial_grid(raw_nor, grid_step_m=5.0, max_distance_m=2000.0)

    alo_state = estimate_vehicle_dynamics_state(alo_trace)
    nor_state = estimate_vehicle_dynamics_state(nor_trace)

    res = build_surrogate_and_attribution(alo_state, nor_state, microsector_length_m=50.0)

    assert len(res.microsector_distance_m) == 40
    assert 0.80 <= res.picp_90_coverage <= 0.98
    assert res.cv_r2_score > 0.50

    attr = res.attribution_seconds
    parts_sum = (
        attr["aero_drag_s"]
        + attr["high_speed_downforce_s"]
        + attr["wind_yaw_sensitivity_s"]
        + attr["low_speed_mechanical_s"]
    )
    assert np.isclose(parts_sum, attr["total_lap_delta_s"], atol=1e-3)
