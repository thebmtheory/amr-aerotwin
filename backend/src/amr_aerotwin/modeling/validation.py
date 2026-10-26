"""Data-quality gates and model diagnostics.

Every check here can fail. Thresholds are set from the observed spread on clean laps and
are deliberately loose enough to pass normal noise but catch broken laps (wrong layout,
pit-lane laps, GPS dropouts, mis-merged channels).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from amr_aerotwin.domain import AlignedLap
from amr_aerotwin.physics.kinematics import gps_spline_kinematics

LAP_CHECKS: dict[str, tuple[str, float, float]] = {
    # metric: (description, lower bound, upper bound)
    "projection_rms_m": ("GPS fixes' RMS distance from the reference line (m)", 0.0, 6.0),
    "finish_line_gap_m": ("GPS position vs timing line at the end of the lap (m)", -25.0, 25.0),
    "start_line_gap_m": ("GPS position vs timing line at the start of the lap (m)", -25.0, 25.0),
    "speed_time_consistency_pct": ("integral of 1/v vs the timing channel (%)", -1.5, 1.5),
    "gps_speed_rms_ms": ("GPS-derived speed vs wheel-speed channel, RMS (m/s)", 0.0, 4.5),
    "max_sample_gap_m": ("largest gap between telemetry samples (m)", 0.0, 120.0),
    # One-sided: the trap is a single point, so it may read well below the lap's peak speed
    # (2026 clipping costs 10-20 km/h before the trap; the 2025 Las Vegas trap sits ~120 km/h
    # below peak for every car), but a trap far above the peak means a mis-merged lap.
    "speed_trap_minus_max_kmh": ("speed trap minus telemetry peak speed (km/h)", -float("inf"), 8.0),
    "frozen_run_m": ("longest run of exactly repeated speed and rpm samples (m)", 0.0, 100.0),
    "car_data_stall_kmh": ("wheel vs GPS speed next to an impossible wheel-speed jump, vs the field (km/h)", -30.0, 30.0),
}

TURNING_NUMBER_TOLERANCE = 0.035


@dataclass(frozen=True)
class LapCheckResult:
    passed: bool
    failures: dict[str, float]


# Metrics that may legitimately be missing (no speed-trap reading for that lap; too few GPS
# fixes or laps for the stall check)
OPTIONAL_CHECKS = {"speed_trap_minus_max_kmh", "car_data_stall_kmh"}

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


def car_data_stall_kmh(laps: dict[str, AlignedLap], step_window_m: float = 15.0) -> dict[str, float]:
    """Per lap: wheel-minus-GPS speed (km/h, signed, relative to the field) next to an impossible jump.

    In some archived laps the car-data stream stalls: speed, throttle and brake hold their last
    values for 0.5-1.5 s while GPS shows the car braking or accelerating, then all jump at once.
    The jump implies more than STALL_DECEL_G of braking or STALL_ACCEL_G of acceleration.
    GPS-derived speed has errors of its own that every car shares at the same place (spline
    smoothing through braking zones), so each lap's wheel-minus-GPS difference is taken
    relative to the field median at the same distance and averaged over STALL_WINDOW_M. The
    score is the largest such difference within STALL_NEAR_M of a jump; 0 when there is no
    jump. Timestamp jitter also produces short jumps, but with no GPS disagreement around them.
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
        a[k // 2: k // 2 + len(v) - k] = (v[k:] ** 2 - v[:-k] ** 2) / (2.0 * (s[k:] - s[:-k])) / 9.81
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


def geometry_ok(turning_number: float, expected_turns: int = 1) -> bool:
    """Integrated curvature must match the circuit's turn count (GPS dropouts break this).

    Most circuits make one full turn; a figure-of-eight such as Suzuka makes zero. The
    expected count comes from the reference path's own heading (`expected_turn_count`).
    """
    return abs(abs(turning_number) - abs(expected_turns)) <= TURNING_NUMBER_TOLERANCE


def expected_turn_count(x_m: np.ndarray, y_m: np.ndarray) -> int:
    """Net number of turns of a closed path, from its unwrapped heading (rounded)."""
    heading = np.unwrap(np.arctan2(np.diff(np.append(y_m, y_m[0])), np.diff(np.append(x_m, x_m[0]))))
    return int(np.rint((heading[-1] - heading[0]) / (2 * np.pi)))
