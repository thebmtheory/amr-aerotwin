"""Shared synthetic generators and the offline Silverstone fixture."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from amr_aerotwin.data.repository import TelemetryRepository

FIXTURE_CACHE = Path(__file__).parent / "fixtures" / "cache"


def stadium_track(straight_m: float = 600.0, radius_m: float = 80.0, step_m: float = 5.0):
    """Closed track: straight, 180-degree left arc, straight, 180-degree left arc.

    Returns (distance grid, curvature, x, y, length).
    """
    arc = np.pi * radius_m
    length = 2 * straight_m + 2 * arc
    s = np.arange(0.0, length, step_m)
    kappa = np.zeros_like(s)
    x = np.zeros_like(s)
    y = np.zeros_like(s)
    for i, si in enumerate(s):
        if si < straight_m:
            x[i], y[i] = si, 0.0
        elif si < straight_m + arc:
            th = (si - straight_m) / radius_m
            kappa[i] = 1.0 / radius_m
            x[i], y[i] = straight_m + radius_m * np.sin(th), radius_m * (1 - np.cos(th))
        elif si < 2 * straight_m + arc:
            x[i], y[i] = straight_m - (si - straight_m - arc), 2 * radius_m
        else:
            th = (si - 2 * straight_m - arc) / radius_m
            kappa[i] = 1.0 / radius_m
            x[i], y[i] = -radius_m * np.sin(th), radius_m * (1 + np.cos(th))
    return s, kappa, x, y, length


def circle_lap_telemetry(
    radius_m: float = 300.0,
    speed_ms: float = 60.0,
    hz: float = 8.0,
    gps_hz: float = 4.0,
    gps_lag_s: float = 0.0,
    gps_noise_m: float = 0.0,
    odometer_scale: float = 1.0,
    speed_ripple_ms: float = 0.0,
    seed: int = 0,
) -> tuple[dict, float]:
    """Raw-archive-format telemetry for one lap of a circle at constant speed.

    Positions are whole decimetres at GPS fixes and linearly interpolated in between, as in
    the TracingInsights archive. `gps_lag_s` delays the GPS stream relative to car data.
    Returns (raw dict, lap time).
    """
    rng = np.random.default_rng(seed)
    period = 7.0

    def dist(tq):  # distance travelled with v(t) = v0 + ripple * sin(2 pi t / period)
        return speed_ms * tq + speed_ripple_ms * period / (2 * np.pi) * (1 - np.cos(2 * np.pi * tq / period))

    circumference = 2 * np.pi * radius_m
    fine = np.linspace(0, 2 * circumference / speed_ms, 200001)
    lap_time = float(np.interp(circumference, dist(fine), fine))
    t = np.arange(0.0, lap_time, 1.0 / hz)
    t_fix = np.arange(0.0, lap_time + 1.0, 1.0 / gps_hz)
    th_fix = dist(t_fix - gps_lag_s) / radius_m
    x_fix = np.round((radius_m * np.sin(th_fix) + rng.normal(0, gps_noise_m, len(t_fix))) * 10.0)
    y_fix = np.round((radius_m * (1 - np.cos(th_fix)) + rng.normal(0, gps_noise_m, len(t_fix))) * 10.0)
    tt = np.sort(np.concatenate([t, t_fix[t_fix < lap_time]]))
    tt = np.unique(tt)
    x = np.interp(tt, t_fix, x_fix)
    y = np.interp(tt, t_fix, y_fix)
    is_fix = np.isin(tt, t_fix)
    # Non-fix samples get a small fractional offset so they are never whole decimetres
    x = np.where(is_fix, x, x + 0.37)
    y = np.where(is_fix, y, y + 0.37)
    n = len(tt)
    v_t = speed_ms + speed_ripple_ms * np.sin(2 * np.pi * tt / period)
    raw = {
        "time": tt.tolist(),
        "distance": (dist(tt) * odometer_scale).tolist(),
        "speed": (v_t * 3.6 * odometer_scale).tolist(),
        "throttle": np.full(n, 100.0).tolist(),
        "brake": np.zeros(n).tolist(),
        "gear": np.full(n, 7).tolist(),
        "drs": np.zeros(n).tolist(),
        "rpm": np.full(n, 11000.0).tolist(),
        "x": x.tolist(),
        "y": y.tolist(),
        "z": np.where(is_fix, 100.0, 100.37).tolist(),
    }
    return raw, lap_time


@pytest.fixture(scope="session")
def fixture_repo() -> TelemetryRepository:
    return TelemetryRepository(FIXTURE_CACHE, offline=True)
