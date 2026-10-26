"""Regime classification, accelerations and mass assumptions."""

import numpy as np
import pytest
from amr_aerotwin.domain import GRAVITY_ACCEL as G
from amr_aerotwin.domain import mgu_k_power_limit_kw
from amr_aerotwin.physics.dynamics import (
    BRAKING,
    HIGH_SPEED_CORNER,
    LOW_SPEED_CORNER,
    MEDIUM_SPEED_CORNER,
    STRAIGHT,
    TRANSITION,
    classify_regimes,
    corner_speed_class,
    longitudinal_acceleration,
    vehicle_mass_kg,
)


def test_regimes_braking_takes_precedence_and_corners_use_lateral_load():
    v = np.array([30.0, 50.0, 80.0, 80.0, 85.0, 40.0])
    thr = np.array([40.0, 60.0, 80.0, 0.0, 100.0, 50.0])
    brk = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0])
    ay = np.array([3.0, 3.5, 5.0, 5.0, 0.3, 0.5]) * G
    out = classify_regimes(v, thr, brk, ay)
    assert list(out) == [LOW_SPEED_CORNER, MEDIUM_SPEED_CORNER, HIGH_SPEED_CORNER, BRAKING, STRAIGHT, TRANSITION]


def test_corner_speed_classes():
    assert [corner_speed_class(v) for v in (90, 180, 260)] == ["low", "medium", "high"]


def test_longitudinal_acceleration_of_constant_acceleration_profile():
    step, a = 5.0, 4.0
    s = np.arange(0, 2000, step)
    v = np.sqrt(20.0**2 + 2 * a * s)
    ax = longitudinal_acceleration(v, step)
    assert np.allclose(ax[2:-2], a, rtol=1e-3)


def test_vehicle_mass_uses_regulation_minimum_plus_fuel():
    assert vehicle_mass_kg(2025) == pytest.approx(805.0)
    assert vehicle_mass_kg(2026) == pytest.approx(775.0)
    assert vehicle_mass_kg(2026, qualifying=False) == pytest.approx(773.0)


def test_2026_mgu_k_taper_matches_regulation():
    p = mgu_k_power_limit_kw(np.array([250.0, 290.0, 300.0, 340.0, 342.5, 345.0, 360.0]), 2026)
    assert list(p) == [350.0, 350.0, 300.0, 100.0, 50.0, 0.0, 0.0]
    assert mgu_k_power_limit_kw(np.array([300.0]), 2025)[0] == 120.0
