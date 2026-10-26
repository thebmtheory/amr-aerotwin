"""Lap alignment: GPS fix detection, lag estimation, reference geometry, projection."""

import numpy as np
import pytest

from amr_aerotwin.data.alignment import (
    align_lap,
    build_reference_line,
    estimate_gps_lag_s,
    parse_raw_lap,
    project_onto_reference,
    unwrap_lap_distance,
)
from amr_aerotwin.domain import AmbientState, LapMeta
from conftest import circle_lap_telemetry

AMB = AmbientState(20.0, 30.0, 1000.0, 0.0, 0.0)


def _meta(t):
    return LapMeta(2025, "Test", "Qualifying", "TST", "Team", 1, t, speed_trap_kmh=216.0)


def test_parse_converts_units_and_detects_gps_fixes():
    raw, _ = circle_lap_telemetry(gps_hz=4.0, hz=8.0)
    lap = parse_raw_lap(raw)
    assert lap.speed_ms[0] == pytest.approx(60.0)
    assert lap.x_m.max() == pytest.approx(300.0, abs=0.2)  # decimetres -> metres
    frac = lap.is_gps_fix.mean()
    assert 0.3 < frac < 0.7  # half the samples are original fixes


@pytest.mark.parametrize("lag", [0.0, 0.15, -0.1])
def test_gps_clock_offset_is_recovered(lag):
    # Generator delays GPS by `lag`, so a fix stamped t matches car data at t - lag.
    raw, t_lap = circle_lap_telemetry(gps_lag_s=lag, speed_ripple_ms=8.0)
    tau, rms = estimate_gps_lag_s(parse_raw_lap(raw), t_lap)
    assert tau == pytest.approx(-lag, abs=0.02)
    assert rms < 0.5


def test_gps_offset_defaults_to_zero_when_not_identifiable():
    raw, t_lap = circle_lap_telemetry(gps_lag_s=0.2)  # constant speed: no feature to match
    tau, _ = estimate_gps_lag_s(parse_raw_lap(raw), t_lap)
    assert tau == 0.0


def test_reference_length_comes_from_odometer_and_scale_is_reported():
    raw, t_lap = circle_lap_telemetry(odometer_scale=1.01)
    ref = build_reference_line(parse_raw_lap(raw), t_lap)
    assert ref.length_m == pytest.approx(2 * np.pi * 300 * 1.01, rel=2e-3)
    assert ref.scale == pytest.approx(1.01, abs=3e-3)


def test_projection_and_unwrap():
    raw, t_lap = circle_lap_telemetry()  # constant speed, so s is proportional to angle
    ref = build_reference_line(parse_raw_lap(raw), t_lap)
    quarter = ref.length_m / 4
    s, off = project_onto_reference(np.array([300.0]), np.array([300.0]), ref)
    assert s[0] == pytest.approx(quarter, abs=6.0) and off[0] < 1.0
    wrapped = np.array([ref.length_m - 3, 2, 50, 100, 200, 300, 5000, 5500])
    out = unwrap_lap_distance(wrapped, ref.length_m)
    assert out[0] < 0 and np.all(np.diff(out) >= 0)


def test_aligned_lap_is_anchored_to_official_time_and_identical_laps_have_zero_delta():
    raw, t_lap = circle_lap_telemetry(gps_noise_m=0.5)
    ref = build_reference_line(parse_raw_lap(raw), t_lap)
    a = align_lap(parse_raw_lap(raw), _meta(t_lap), AMB, ref)
    b = align_lap(parse_raw_lap(raw), _meta(t_lap), AMB, ref)
    assert a.time_s[0] == pytest.approx(0.0, abs=1e-9)
    assert a.time_s[-1] < t_lap and t_lap - a.time_s[-1] < 0.2
    assert np.allclose(a.time_s, b.time_s)
    assert np.all(np.diff(a.time_s) > 0)
    for key in ("projection_rms_m", "gps_lag_s", "finish_line_gap_m", "speed_time_consistency_pct"):
        assert key in a.quality
    assert abs(a.quality["speed_time_consistency_pct"]) < 0.5


def test_alignment_on_real_silverstone_laps_closes_on_official_gap(fixture_repo):
    from amr_aerotwin.data.repository import fastest_valid_lap, lap_ambient

    laps = fixture_repo.session_laps(2025, "British Grand Prix", "Qualifying")
    amb = fixture_repo.session_ambient(2025, "British Grand Prix", "Qualifying")
    out = {}
    ref = None
    for d in ["VER", "ALO"]:
        r = fastest_valid_lap(laps, d)
        raw = parse_raw_lap(fixture_repo.lap_telemetry(2025, "British Grand Prix", "Qualifying", d, int(r["lap"])))
        if ref is None:
            ref = build_reference_line(raw, float(r["time"]))
        meta = LapMeta(2025, "British Grand Prix", "Qualifying", d, r["team"], int(r["lap"]), float(r["time"]))
        out[d] = align_lap(raw, meta, lap_ambient(r, amb), ref)
    gap = out["ALO"].meta.lap_time_s - out["VER"].meta.lap_time_s
    assert out["ALO"].time_s[-1] - out["VER"].time_s[-1] == pytest.approx(gap, abs=0.01)
    assert 0.05 < out["ALO"].quality["gps_lag_s"] < 0.25  # the archive's car-data stream trails GPS
    assert out["ALO"].quality["projection_rms_m"] < 4.0
