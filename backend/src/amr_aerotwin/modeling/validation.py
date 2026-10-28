"""Data-quality checks for aligned laps and corner speeds.

Thresholds come from the spread on clean laps: loose enough to pass normal noise, tight enough to catch
broken laps (wrong layout, pit-lane laps, GPS dropouts, mis-merged channels).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from amr_aerotwin.domain import GRAVITY_ACCEL, AlignedLap
from amr_aerotwin.physics.dynamics import VehicleState
from amr_aerotwin.physics.kinematics import corner_windows, gps_spline_kinematics

LAP_CHECKS: dict[str, tuple[str, float, float]] = {
    # metric: (description, lower bound, upper bound)
    "projection_rms_m": ("GPS fixes' RMS distance from the reference line (m)", 0.0, 6.0),
    # The line gaps are mostly an offset of the lap's clock (the lap is re-timed for it), so they
    # only need to agree with each other; their size is a loose sanity bound
    "finish_line_gap_m": ("GPS position vs timing line at the end of the lap (m)", -150.0, 150.0),
    "start_line_gap_m": ("GPS position vs timing line at the start of the lap (m)", -150.0, 150.0),
    "line_gap_mismatch_m": ("start gap minus end gap; a pure clock offset moves both alike (m)", -25.0, 25.0),
    "sector_time_error_s": ("aligned clock vs official sector times at the sector lines (s)", -0.15, 0.15),
    "speed_time_consistency_pct": ("integral of 1/v vs the timing channel (%)", -1.5, 1.5),
    "gps_speed_rms_ms": ("GPS-derived speed vs wheel-speed channel, RMS (m/s)", 0.0, 4.5),
    "max_sample_gap_m": ("largest gap between telemetry samples (m)", 0.0, 120.0),
    # One-sided: the trap is a single point, so it may read well below the lap's peak speed
    # (2026 clipping costs 10-20 km/h before the trap; the 2025 Las Vegas trap sits ~120 km/h
    # below peak for every car), but a trap far above the peak means a mis-merged lap
    "speed_trap_minus_max_kmh": ("speed trap minus telemetry peak speed (km/h)", -float("inf"), 8.0),
    "frozen_run_m": ("longest run of exactly repeated speed and rpm samples (m)", 0.0, 100.0),
    "car_data_stall_kmh": ("wheel vs GPS speed next to an impossible wheel-speed jump, vs the field (km/h)", -30.0, 30.0),
}

TURNING_NUMBER_TOLERANCE = 0.035
TURNING_NUMBER_HIGH = 0.05


@dataclass(frozen=True)
class LapCheckResult:
    passed: bool
    failures: dict[str, float]


# Metrics that may legitimately be missing (no speed-trap reading for that lap; too few GPS
# fixes or laps for the stall check)
OPTIONAL_CHECKS = {"speed_trap_minus_max_kmh", "car_data_stall_kmh", "sector_time_error_s", "line_gap_mismatch_m"}

STALL_DECEL_G = 7.5  # braking no F1 car reaches (peak is about 5-6 g)
STALL_ACCEL_G = 3.0  # traction-limited acceleration stays under about 2 g
STALL_WINDOW_M = 60.0
STALL_NEAR_M = 100.0


def check_lap(lap: AlignedLap) -> LapCheckResult:
    """A lap passes when every metric is inside its bounds; a missing required metric fails."""
    fails = {}
    for metric, (_, lo, hi) in LAP_CHECKS.items():
        v = lap.quality.get(metric, np.nan)
        if not np.isfinite(v):
            if metric not in OPTIONAL_CHECKS:
                fails[metric] = float("nan")
        elif not lo <= v <= hi:
            fails[metric] = float(v)
    return LapCheckResult(passed=not fails, failures=fails)


def failures_by_check(metrics: dict[str, NDArray[np.float64]]) -> dict[str, int]:
    """How many laps each check rejects, by the same rule as `check_lap` (a lap can fail several).

    `metrics` maps LAP_CHECKS metrics to one value per lap; checks with no values are left out.
    """
    out = {}
    for metric, (_, lo, hi) in LAP_CHECKS.items():
        if metric not in metrics:
            continue
        v = np.asarray(metrics[metric], dtype=float)
        finite = np.isfinite(v)
        bad = finite & ((v < lo) | (v > hi))
        if metric not in OPTIONAL_CHECKS:
            bad |= ~finite
        out[metric] = int(bad.sum())
    return out


def car_data_stall_kmh(laps: dict[str, AlignedLap], step_window_m: float = 15.0) -> dict[str, float]:
    """Per lap: wheel-minus-GPS speed (km/h, relative to the field) next to an impossible speed jump; 0 if none.

    Some archived laps have car data that stalls for 0.5-1.5 s and then jumps; timestamp jitter also makes
    jumps, but with no GPS disagreement. The field median removes GPS spline errors that all cars share.
    """
    dev = {}
    for d, lp in laps.items():
        if len(lp.gps_time_s) >= 50:
            _, v_gps = gps_spline_kinematics(lp.gps_time_s, lp.gps_x_m, lp.gps_y_m, lp.meta.lap_time_s, lp.time_s)
            dev[d] = (lp.speed_ms - v_gps) * 3.6
    if len(dev) < 5:
        return {d: float("nan") for d in laps}
    med = np.median(np.vstack(list(dev.values())), axis=0)
    out = {}
    for d, lp in laps.items():
        if d not in dev:
            out[d] = float("nan")
            continue
        s, v = lp.distance_m, lp.speed_ms
        step = float(s[1] - s[0])
        k = max(int(round(step_window_m / step)), 1)
        a = np.zeros(len(v))
        a[k // 2: k // 2 + len(v) - k] = (v[k:] ** 2 - v[:-k] ** 2) / (2.0 * (s[k:] - s[:-k])) / GRAVITY_ACCEL
        w = max(int(round(STALL_WINDOW_M / step)), 1)
        resid = np.convolve(dev[d] - med, np.ones(w) / w, mode="same")
        near = int(round(STALL_NEAR_M / step))
        best = 0.0
        for i in np.flatnonzero((a < -STALL_DECEL_G) | (a > STALL_ACCEL_G)):
            seg = resid[max(0, i - near): i + near + 1]
            j = int(np.argmax(np.abs(seg)))
            if abs(seg[j]) > abs(best):
                best = float(seg[j])
        out[d] = best
    return out


def sector_time_errors_s(laps: dict[str, AlignedLap]) -> dict[str, float]:
    """Per lap: largest error (s) of the aligned clock at the two internal sector lines; NaN without sector times.

    Each line sits at the median over laps of where the aligned clock reads the official sector time, so this
    checks the whole alignment chain against the timing loops, which are independent of telemetry.
    """
    cum = {}
    for d, lp in laps.items():
        s1, s2, _ = lp.meta.sector_times_s
        if np.isfinite(s1) and np.isfinite(s2):
            cum[d] = (s1, s1 + s2)
    if len(cum) < 5:
        return {d: float("nan") for d in laps}
    lines = [float(np.median([np.interp(c[k], laps[d].time_s, laps[d].distance_m) for d, c in cum.items()])) for k in (0, 1)]
    out = {}
    for d, lp in laps.items():
        if d not in cum:
            out[d] = float("nan")
            continue
        errs = [float(np.interp(lines[k], lp.distance_m, lp.time_s) - cum[d][k]) for k in (0, 1)]
        out[d] = max(errs, key=abs)
    return out


def geometry_ok(turning_number: float, expected_turns: int = 1) -> bool:
    """Integrated curvature must match the circuit's turn count (GPS dropouts break this).

    Suzuka's figure of eight makes zero turns. The band, 3.5% below to 5% above, is asymmetric because the
    smoothed GPS path cuts corners and reads about 1.5% high on clean laps (per-lap mean 1.015, sd 0.019).
    """
    n = abs(expected_turns)
    if n == 0:
        return abs(turning_number) <= TURNING_NUMBER_TOLERANCE
    return -TURNING_NUMBER_TOLERANCE <= abs(turning_number) / n - 1.0 <= TURNING_NUMBER_HIGH


def expected_turn_count(x_m: np.ndarray, y_m: np.ndarray) -> int:
    """Net number of turns of a closed path, from its unwrapped heading (rounded)."""
    heading = np.unwrap(np.arctan2(np.diff(np.append(y_m, y_m[0])), np.diff(np.append(x_m, x_m[0]))))
    return int(np.rint((heading[-1] - heading[0]) / (2 * np.pi)))


CORNER_WINDOW_M = 60.0
# A corner's minimum speed is used only when wheel and GPS speed agree, relative to the field median there
# (the smoothed GPS path reads low in fast corners for every car). Clean laps at Silverstone stay within
# +-14 km/h; a stuck or stepping speed channel (2026 British GP: STR at Aintree) misses by 20 km/h or more.
WHEEL_GPS_TOL_KMH = 15.0


def corner_min_speeds(state: VehicleState, corner_s: np.ndarray) -> list[dict[str, float]]:
    """Minimum speed (km/h) within +-60 m of each corner, from the wheel-speed channel and from GPS.

    GPS speed comes from the time-domain spline of raw fixes used for curvature, so it is independent of
    the car-data stream; `flag_corner_speeds` compares the two.
    """
    lap = state.lap
    out = []
    # Disjoint windows: two corners closer than 120 m (Vale, T16-T17) do not share a minimum
    for win in corner_windows(lap.distance_m, corner_s, lap.lap_length_m, CORNER_WINDOW_M):
        v_wheel = float(np.min(state.speed_smooth_ms[win]) * 3.6)
        if len(lap.gps_time_s) > 50:
            _, v_gps = gps_spline_kinematics(lap.gps_time_s, lap.gps_x_m, lap.gps_y_m, lap.meta.lap_time_s, lap.time_s[win])
            g = float(np.min(v_gps) * 3.6)
        else:
            g = float("nan")
        out.append({"wheel_kmh": v_wheel, "gps_kmh": g})
    return out


def flag_corner_speeds(vmin: dict[str, list[dict[str, float]]]) -> None:
    """Set `ok` on every (car, corner): wheel-minus-GPS within WHEEL_GPS_TOL_KMH of the field median."""
    n = len(next(iter(vmin.values())))
    for i in range(n):
        diffs = {t: v[i]["wheel_kmh"] - v[i]["gps_kmh"] for t, v in vmin.items()}
        med = float(np.nanmedian(list(diffs.values())))
        for t, v in vmin.items():
            v[i]["residual_kmh"] = diffs[t] - med
            v[i]["ok"] = bool(np.isfinite(diffs[t]) and abs(diffs[t] - med) <= WHEEL_GPS_TOL_KMH)
