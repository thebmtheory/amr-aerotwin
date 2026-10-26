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


def test_frozen_car_data_is_detected():
    from amr_aerotwin.data.alignment import longest_frozen_run_m

    raw, t_lap = circle_lap_telemetry(speed_ripple_ms=8.0)
    lap = parse_raw_lap(raw)
    s = lap.distance_m
    sel = np.ones(len(s), dtype=bool)
    assert longest_frozen_run_m(lap, sel, s) < 20.0
    frozen = (s > 1000) & (s < 1250)
    for ch in (lap.speed_ms, lap.rpm):
        ch[frozen] = ch[frozen][0]
    assert longest_frozen_run_m(lap, sel, s) > 200.0


def test_invalid_throttle_marker_is_repaired_not_kept():
    raw, _ = circle_lap_telemetry()
    raw["throttle"][10] = 104.0
    raw["brake"][10] = 1
    raw["throttle"][20] = 104.0
    lap = parse_raw_lap(raw)
    assert lap.throttle_pct.max() <= 100.0
    assert 0.0 in lap.throttle_pct  # braking sample read as zero throttle


def test_car_data_stall_check_flags_a_held_speed_channel_only(fixture_repo):
    """A real Silverstone lap scores near zero; the same lap with its speed channel held through a
    braking zone and then jumping (a car-data stall) fails the check, and the others do not move."""
    import dataclasses

    from amr_aerotwin.modeling.validation import LAP_CHECKS, car_data_stall_kmh, check_lap
    from amr_aerotwin.pipeline.event import _load_quali_laps

    laps, *_ = _load_quali_laps(fixture_repo, 2025, "British Grand Prix")
    lo, hi = LAP_CHECKS["car_data_stall_kmh"][1:]
    clean = {d: lp.quality["car_data_stall_kmh"] for d, lp in laps.items()}
    assert all(lo <= v <= hi for v in clean.values()), clean

    d0 = sorted(laps)[0]
    lp = laps[d0]
    v = lp.speed_ms.copy()
    # Hardest braking zone: largest speed drop over 100 m; hold the pre-braking speed through it
    k = int(round(100.0 / (lp.distance_m[1] - lp.distance_m[0])))
    i = int(np.argmax(v[:-k] - v[k:]))
    v[i:i + k] = v[i]
    stalled = dict(laps)
    stalled[d0] = dataclasses.replace(lp, speed_ms=v, quality=dict(lp.quality))
    score = car_data_stall_kmh(stalled)
    assert score[d0] > hi
    stalled[d0].quality["car_data_stall_kmh"] = score[d0]
    assert not check_lap(stalled[d0]).passed
    others = [abs(score[d] - clean[d]) for d in laps if d != d0]
    assert max(others) < 10.0  # one bad lap barely moves the field median


@pytest.mark.parametrize("offset", [0.25, -0.2])
def test_a_shifted_lap_clock_is_re_timed_not_moved_along_the_track(offset):
    """The archive's lap clock can be offset from the timing line, for GPS and car data together.
    That is a time shift: after alignment every grid point must carry the true time and speed
    there. Treating the gap as a position error instead moves every channel along the track."""
    ripple, v0, period = 8.0, 60.0, 7.0
    raw0, t_lap = circle_lap_telemetry(speed_ripple_ms=ripple)
    ref = build_reference_line(parse_raw_lap(raw0), t_lap)
    raw, _ = circle_lap_telemetry(speed_ripple_ms=ripple, clock_offset_s=offset)
    lap = align_lap(parse_raw_lap(raw), _meta(t_lap), AMB, ref)
    fine = np.linspace(0, t_lap, 20001)
    dist = v0 * fine + ripple * period / (2 * np.pi) * (1 - np.cos(2 * np.pi * fine / period))
    s = lap.distance_m
    t_true = np.interp(s * dist[-1] / ref.length_m, dist, fine)
    v_true = v0 + ripple * np.sin(2 * np.pi * t_true / period)
    inner = (s > 30) & (s < ref.length_m - 30)
    assert np.max(np.abs(lap.time_s[inner] - t_true[inner])) < 0.02
    assert np.max(np.abs(lap.speed_ms[inner] - v_true[inner])) < 0.3
    assert abs(lap.quality["start_line_gap_m"]) == pytest.approx(abs(offset) * v0, rel=0.25)  # reported, not hidden


def test_sector_time_check_matches_official_sectors_and_flags_a_shifted_clock():
    """The aligned clock must read each lap's official sector times at the sector lines; a lap
    whose time channel is off in the middle of the lap (not at the line) is flagged."""
    import dataclasses

    from amr_aerotwin.modeling.validation import sector_time_errors_s

    ripple, v0, period = 8.0, 60.0, 7.0
    raw0, t_lap = circle_lap_telemetry(speed_ripple_ms=ripple)
    ref = build_reference_line(parse_raw_lap(raw0), t_lap)
    laps = {}
    for i, off in enumerate([0.0, 0.1, -0.15, 0.2, 0.05, -0.05]):
        raw, _ = circle_lap_telemetry(speed_ripple_ms=ripple, clock_offset_s=off, seed=i)
        lap = align_lap(parse_raw_lap(raw), _meta(t_lap), AMB, ref)
        # Official sectors at a third and two thirds of the lap distance, from the true motion
        fine = np.linspace(0, t_lap, 20001)
        dist = v0 * fine + ripple * period / (2 * np.pi) * (1 - np.cos(2 * np.pi * fine / period))
        t1, t2 = np.interp([dist[-1] / 3, 2 * dist[-1] / 3], dist, fine)
        meta = dataclasses.replace(lap.meta, driver=f"D{i}", sector_times_s=(t1, t2 - t1, t_lap - t2))
        laps[f"D{i}"] = dataclasses.replace(lap, meta=meta)
    err = sector_time_errors_s(laps)
    assert max(abs(v) for v in err.values()) < 0.01
    bad = laps["D3"]
    t = bad.time_s.copy()
    mid = (bad.distance_m > ref.length_m * 0.25) & (bad.distance_m < ref.length_m * 0.75)
    t[mid] += 0.3  # a clock error inside the lap: line crossings still look fine
    laps["D3"] = dataclasses.replace(bad, time_s=t)
    err = sector_time_errors_s(laps)
    assert err["D3"] == pytest.approx(0.3, abs=0.02)
    assert max(abs(v) for k, v in err.items() if k != "D3") < 0.01
