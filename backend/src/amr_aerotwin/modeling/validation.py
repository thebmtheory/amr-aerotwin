"""Data-quality gates and model diagnostics.

Every check here can fail. Thresholds are set from the observed spread on clean laps and
are deliberately loose enough to pass normal noise but catch broken laps (wrong layout,
pit-lane laps, GPS dropouts, mis-merged channels).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from amr_aerotwin.domain import AlignedLap

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
}

TURNING_NUMBER_TOLERANCE = 0.035


@dataclass(frozen=True)
class LapCheckResult:
    passed: bool
    failures: dict[str, float]


# Metrics that may legitimately be missing (no speed-trap reading for that lap)
OPTIONAL_CHECKS = {"speed_trap_minus_max_kmh"}


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
