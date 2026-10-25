"""Unit tests for spatial grid alignment and SI unit normalization in ingestion.py."""

import numpy as np

from amr_aerotwin.data.ingestion import align_lap_to_spatial_grid


def test_align_lap_to_spatial_grid_interpolates_and_converts_units() -> None:
    """Verify two laps with different sampling distances align to the exact same 5m grid."""
    raw_alo = {
        "distance": [0.0, 10.0, 20.0, 30.0],
        "speed": [180.0, 216.0, 252.0, 288.0],  # 50, 60, 70, 80 m/s
        "throttle": [100.0, 100.0, 100.0, 100.0],
        "brake": [0, 0, 0, 0],
        "gear": [5, 6, 7, 7],
        "drs": [0, 1, 1, 1],
        "x": [0.0, 100.0, 200.0, 300.0],        # decimeters -> 0, 10, 20, 30 m
        "y": [0.0, 0.0, 0.0, 0.0],
        "z": [1000.0, 1000.0, 1000.0, 1000.0],  # decimeters -> 100 m
    }
    raw_nor = {
        "distance": [0.0, 7.5, 15.0, 30.0],
        "speed": [180.0, 207.0, 234.0, 288.0],
        "throttle": [100.0, 100.0, 100.0, 100.0],
        "brake": [0, 0, 0, 0],
        "gear": [5, 6, 6, 7],
        "drs": [0, 1, 1, 1],
        "x": [0.0, 75.0, 150.0, 300.0],
        "y": [0.0, 0.0, 0.0, 0.0],
        "z": [1000.0, 1000.0, 1000.0, 1000.0],
    }

    trace_alo = align_lap_to_spatial_grid(raw_alo, grid_step_m=5.0, max_distance_m=30.0)
    trace_nor = align_lap_to_spatial_grid(raw_nor, grid_step_m=5.0, max_distance_m=30.0)

    # Both traces must share the exact same distance marks: [0, 5, 10, 15, 20, 25]
    assert np.array_equal(trace_alo.distance_m, np.array([0.0, 5.0, 10.0, 15.0, 20.0, 25.0]))
    assert np.array_equal(trace_alo.distance_m, trace_nor.distance_m)

    # At 5.0m (halfway between 0m @ 50m/s and 10m @ 60m/s), speed_ms must be 55.0 m/s
    assert np.isclose(trace_alo.speed_ms[1], 55.0)
    # Decimeter X=100 at 10m must be converted to 10.0 meters
    assert np.isclose(trace_alo.x_m[2], 10.0)
    assert np.isclose(trace_alo.z_m[0], 100.0)
