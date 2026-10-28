"""Spatial alignment of laps onto a shared reference line, in SI units.

Odometers differ between cars (racing line, wheel radius), so the same raw `distance` can be 10-25 m apart
on track; each lap is projected onto one reference path and its channels resampled on that arc length.
Raw archive units: X/Y/Z in decimetres, speed in km/h, time in seconds from the line.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.interpolate import PchipInterpolator
from scipy.signal import savgol_filter
from scipy.spatial import cKDTree

from amr_aerotwin.domain import AlignedLap, AmbientState, LapMeta
from amr_aerotwin.physics.kinematics import (
    GPS_LAM,
    MIN_GPS_FIXES,
    gps_position_splines,
    gps_spline_kinematics,
    odd_window,
)


@dataclass(frozen=True)
class ReferenceLine:
    """Closed reference path sampled every `step_m` metres from 0 to `length_m` (exclusive).

    Distances are in the wheel-speed (odometer) frame so that integrating 1/v over them
    reproduces the timing channel. `scale` = odometer length / smoothed GPS arc length:
    the smoothed path cuts tight corners slightly (0.5% at Silverstone, ~2% at Monaco).
    """

    distance_m: NDArray[np.float64]
    x_m: NDArray[np.float64]
    y_m: NDArray[np.float64]
    length_m: float
    scale: float = 1.0

    @property
    def step_m(self) -> float:
        return float(self.distance_m[1] - self.distance_m[0])


@dataclass(frozen=True)
class RawLap:
    """Raw telemetry converted to SI and sorted by time."""

    time_s: NDArray[np.float64]
    distance_m: NDArray[np.float64]
    speed_ms: NDArray[np.float64]
    throttle_pct: NDArray[np.float64]
    brake: NDArray[np.float64]
    gear: NDArray[np.float64]
    drs: NDArray[np.float64]
    rpm: NDArray[np.float64]
    x_m: NDArray[np.float64]
    y_m: NDArray[np.float64]
    z_m: NDArray[np.float64]
    is_gps_fix: NDArray[np.bool_]  # original ~4 Hz position samples (the rest are interpolated)
    gap_ahead_m: NDArray[np.float64]  # distance to the car ahead on track (inf when none)


def parse_raw_lap(raw_tel: dict[str, Any]) -> RawLap:
    """Convert a raw telemetry dict to SI units, sorted by time with duplicate stamps removed."""

    def col(name: str, default: float = 0.0) -> NDArray[np.float64]:
        vals = raw_tel.get(name)
        if vals is None:
            return np.full(len(raw_tel["time"]), default, dtype=np.float64)
        return np.array([default if v in (None, "None") else v for v in vals], dtype=np.float64)

    t = col("time")
    # Throttle 104 is the timing feed's invalid-value marker; it appears almost only under
    # braking, so it is read as 0% when the brake is on and capped at 100% otherwise.
    thr = col("throttle")
    thr = np.where(thr > 100.5, np.where(col("brake") > 0.5, 0.0, 100.0), thr)
    # Between GPS fixes the archive fills in positions on the car-data timestamps (a quadratic
    # spline in time reproduces them). Original fixes are the samples whose decimetre
    # coordinates are whole numbers.
    xyz = np.column_stack([col("x", np.nan), col("y", np.nan), col("z", np.nan)])
    is_fix = np.all(np.isfinite(xyz) & (np.mod(xyz, 1.0) == 0.0), axis=1)
    order = np.argsort(t, kind="stable")
    keep = np.concatenate([[True], np.diff(t[order]) > 0])
    idx = order[keep]
    return RawLap(
        time_s=t[idx],
        distance_m=col("distance")[idx],
        speed_ms=col("speed")[idx] / 3.6,
        throttle_pct=thr[idx],
        brake=col("brake")[idx],
        gear=col("gear")[idx],
        drs=col("drs")[idx],
        rpm=col("rpm")[idx],
        x_m=col("x")[idx] / 10.0,
        y_m=col("y")[idx] / 10.0,
        z_m=col("z")[idx] / 10.0,
        is_gps_fix=is_fix[idx],
        gap_ahead_m=col("DistanceToDriverAhead", np.inf)[idx],
    )


def estimate_lap_length_m(raw: RawLap, lap_time_s: float) -> float:
    """Odometer distance at the line: last sample plus the remaining time at the last speed."""
    remaining_s = max(0.0, float(lap_time_s) - float(raw.time_s[-1]))
    return float(raw.distance_m[-1] + raw.speed_ms[-1] * remaining_s)


GPS_LAG_SEARCH_S = np.round(np.arange(-0.5, 0.5001, 0.01), 2)


def longest_frozen_run_m(raw: RawLap, sel: NDArray[np.bool_], s: NDArray[np.float64]) -> float:
    """Distance (m) covered by the longest run of samples whose speed and rpm both repeat exactly.

    Real channels never hold identical values for long (90% of laps stay under ~40 m); a
    frozen car-data stream does (Baku 2026: 140-180 m of constant speed and rpm).
    """
    v, rpm, ss = raw.speed_ms[sel], raw.rpm[sel], s[sel]
    same = (np.diff(v) == 0) & (np.diff(rpm) == 0)
    best, start = 0.0, None
    for i, flag in enumerate(np.append(same, False)):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            best = max(best, float(ss[i] - ss[start]))
            start = None
    return best


def estimate_gps_lag_s(raw: RawLap, lap_time_s: float, lam: float = GPS_LAM) -> tuple[float, float]:
    """Offset tau (s) best aligning GPS-derived speed with wheel speed, and the RMS speed error (m/s).

    A fix stamped t matches the car data at t + tau; the archive median is about +0.11 s (~9 m at 300 km/h).
    tau = 0 is kept unless a shift improves on it by 2%: the offset is not identifiable at near-constant speed.
    """
    f = raw.is_gps_fix
    if int(f.sum()) < MIN_GPS_FIXES:
        return 0.0, float("nan")
    t_eval = np.linspace(1.0, lap_time_s - 1.0, 3000)
    _, v_gps = gps_spline_kinematics(raw.time_s[f], raw.x_m[f], raw.y_m[f], lap_time_s, t_eval, lam)
    errs = [
        float(np.sqrt(np.mean((np.interp(t_eval + tau, raw.time_s, raw.speed_ms) - v_gps) ** 2)))
        for tau in GPS_LAG_SEARCH_S
    ]
    i = int(np.argmin(errs))
    i0 = int(np.argmin(np.abs(GPS_LAG_SEARCH_S)))
    if errs[i] > 0.98 * errs[i0]:
        return 0.0, errs[i0]
    return float(GPS_LAG_SEARCH_S[i]), errs[i]


def _reference_from_odometer(raw: RawLap, lap_time_s: float, step_m: float) -> ReferenceLine:
    """Fallback reference when there are too few GPS fixes: X/Y interpolated on the odometer."""
    length = estimate_lap_length_m(raw, lap_time_s)
    grid = np.arange(0.0, length, step_m)
    d = raw.distance_m
    d_ext = np.concatenate([d - length, d, d + length])
    order = np.argsort(d_ext, kind="stable")
    d_ext = d_ext[order]
    x_ext, y_ext = np.tile(raw.x_m, 3)[order], np.tile(raw.y_m, 3)[order]
    keep = np.concatenate([[True], np.diff(d_ext) > 0])
    x = np.interp(grid, d_ext[keep], x_ext[keep])
    y = np.interp(grid, d_ext[keep], y_ext[keep])
    w = odd_window(45.0, step_m)
    return ReferenceLine(grid, savgol_filter(x, w, 3, mode="wrap"), savgol_filter(y, w, 3, mode="wrap"), length)


GRID_STEP_M = 5.0  # spacing of the shared distance grid every lap is resampled onto


def build_reference_line(raw: RawLap, lap_time_s: float, step_m: float = GRID_STEP_M) -> ReferenceLine:
    """Closed reference path: shape from the lag-corrected GPS fixes, scale from the odometer.

    s = 0 is the car position at t = 0 (the timing line).
    """
    f = raw.is_gps_fix
    if int(f.sum()) < MIN_GPS_FIXES:
        return _reference_from_odometer(raw, lap_time_s, step_m)
    tau, _ = estimate_gps_lag_s(raw, lap_time_s)
    sx, sy = gps_position_splines(raw.time_s[f] + tau, raw.x_m[f], raw.y_m[f], lap_time_s, GPS_LAM)
    t_dense = np.linspace(0.0, lap_time_s, int(lap_time_s / 0.01) + 1)
    px, py = sx(t_dense), sy(t_dense)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(px), np.diff(py)))])
    length = estimate_lap_length_m(raw, lap_time_s)
    scale = length / float(cum[-1])
    grid = np.arange(0.0, length, step_m)
    geo = grid / scale
    return ReferenceLine(grid, np.interp(geo, cum, px), np.interp(geo, cum, py), length, scale)


def project_onto_reference(
    x: NDArray[np.float64], y: NDArray[np.float64], ref: ReferenceLine
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Arc length along `ref` of the closest point to each (x, y), and the lateral offset (m)."""
    pts = np.column_stack([ref.x_m, ref.y_m])
    n = len(pts)
    _, i0 = cKDTree(pts).query(np.column_stack([x, y]))
    best_s = np.zeros(len(x))
    best_off = np.full(len(x), np.inf)
    for shift in (-1, 0):  # segments (i-1, i) and (i, i+1)
        a_idx = (i0 + shift) % n
        b_idx = (a_idx + 1) % n
        a, b = pts[a_idx], pts[b_idx]
        ab = b - a
        seg_len2 = np.maximum(np.sum(ab * ab, axis=1), 1e-12)
        t = np.clip(np.sum((np.column_stack([x, y]) - a) * ab, axis=1) / seg_len2, 0.0, 1.0)
        proj = a + ab * t[:, None]
        off = np.hypot(x - proj[:, 0], y - proj[:, 1])
        s = ref.distance_m[a_idx] + t * ref.step_m
        better = off < best_off
        best_s[better] = s[better]
        best_off[better] = off[better]
    return best_s, best_off


def unwrap_lap_distance(s: NDArray[np.float64], length_m: float) -> NDArray[np.float64]:
    """Undo start/finish wrap-around and force a non-decreasing sequence (samples are time-ordered)."""
    s = s.copy()
    n = len(s)
    head = np.arange(n) < n // 4
    tail = np.arange(n) >= n - n // 4
    s[head & (s > 0.75 * length_m)] -= length_m
    s[tail & (s < 0.25 * length_m)] += length_m
    return np.maximum.accumulate(s)


def _odometer_at(t: NDArray[np.float64], raw: RawLap) -> NDArray[np.float64]:
    """Odometer distance at arbitrary times, extrapolated linearly at the current speed."""
    d = np.interp(t, raw.time_s, raw.distance_m)
    d = np.where(t < raw.time_s[0], raw.distance_m[0] + raw.speed_ms[0] * (t - raw.time_s[0]), d)
    return np.where(t > raw.time_s[-1], raw.distance_m[-1] + raw.speed_ms[-1] * (t - raw.time_s[-1]), d)


def _smooth_offset(x: NDArray[np.float64]) -> NDArray[np.float64]:
    """Outlier-resistant local-linear smoothing (unbiased at the ends, unlike a running median)."""
    n = len(x)
    med = np.array([np.median(x[max(0, i - 2): i + 3]) for i in range(n)])
    w = min(11, n - 1 if (n - 1) % 2 == 1 else n - 2)
    return savgol_filter(med, w, 1, mode="interp") if w >= 3 else med


def align_lap(
    raw: RawLap,
    meta: LapMeta,
    ambient: AmbientState,
    ref: ReferenceLine,
) -> AlignedLap:
    """Resample one lap onto the reference grid using the measured timing channel.

    Distance comes from the projected, lag-corrected GPS fixes; between fixes the high-rate odometer gives
    the shape, shifted by its smoothed, slowly drifting offset from the projected distance.
    """
    length = ref.length_m
    f = raw.is_gps_fix
    tau, lag_rms = estimate_gps_lag_s(raw, meta.lap_time_s)
    t_end = meta.lap_time_s
    if int(f.sum()) >= MIN_GPS_FIXES:
        t_fix = raw.time_s[f] + tau
        s_fix, offset = project_onto_reference(raw.x_m[f], raw.y_m[f], ref)
        s_fix = unwrap_lap_distance(s_fix, length)
        corr = _smooth_offset(s_fix - _odometer_at(t_fix, raw))
        s_raw = raw.distance_m + np.interp(raw.time_s, t_fix, corr)
        s_raw = np.maximum.accumulate(s_raw)
        # Where the car is, by GPS, at the lap's first and last timestamps, relative to the timing
        # line (reported in `quality`). In this archive the gaps are mostly an offset of the lap's
        # clock: GPS and car data move together, the start and end gaps agree, and official sector
        # times are matched when the lap is re-timed. So positions are left alone and time is
        # mapped affinely so that the car is at the line at 0 and again at the official lap time.
        od_ends = _odometer_at(np.array([0.0, t_end]), raw)
        corr_ends = np.interp([0.0, t_end], t_fix, corr)
        start_gap = float(od_ends[0] + corr_ends[0])
        end_gap = float(od_ends[1] + corr_ends[1] - length)
        sx, sy = gps_position_splines(t_fix, raw.x_m[f], raw.y_m[f], meta.lap_time_s, GPS_LAM)
    else:
        s_raw, offset = project_onto_reference(raw.x_m, raw.y_m, ref)
        s_raw = unwrap_lap_distance(s_raw, length)
        t_fix, s_fix, sx, sy = raw.time_s, s_raw, None, None
        start_gap = end_gap = float("nan")

    # Telemetry times at which the car crosses the line (extrapolated at the speed there)
    v_ends = np.maximum(np.interp([0.0, t_end], raw.time_s, raw.speed_ms), 1.0)
    t0 = -start_gap / v_ends[0] if np.isfinite(start_gap) else 0.0
    t1 = t_end - end_gap / v_ends[1] if np.isfinite(end_gap) else t_end
    if not t1 - t0 > 0.5 * t_end:
        raise ValueError(f"Line crossings inconsistent for {meta.lap_id}")
    rate = t_end / (t1 - t0)

    def retime(t: NDArray[np.float64]) -> NDArray[np.float64]:
        return (np.asarray(t, dtype=float) - t0) * rate

    inside = (s_raw > 0.0) & (s_raw < length)
    inside &= np.concatenate([[True], np.diff(s_raw) > 1e-6])
    s_in = s_raw[inside]
    if len(s_in) < 20:
        raise ValueError(f"Too few usable samples after projection for {meta.lap_id}")

    grid = ref.distance_m
    # Time: measured channel, re-timed so the car is at the line at 0 and at the official lap time
    s_t = np.concatenate([[0.0], s_in, [length]])
    t_t = np.concatenate([[0.0], retime(raw.time_s[inside]), [meta.lap_time_s]])
    mono = np.concatenate([[True], np.diff(t_t) > 0]) & np.concatenate([[True], np.diff(s_t) > 0])
    time_s = PchipInterpolator(s_t[mono], t_t[mono])(grid)

    v_in = raw.speed_ms[inside]
    speed_ms = PchipInterpolator(s_in, v_in, extrapolate=False)(grid)
    speed_ms = np.where(np.isfinite(speed_ms), speed_ms, np.interp(grid, s_in, v_in))

    def lin(ch: NDArray[np.float64]) -> NDArray[np.float64]:
        return np.interp(grid, s_in, ch[inside])

    if sx is not None:
        t_tel = t0 + time_s / rate  # back to the telemetry clock the GPS splines were built on
        x_grid, y_grid = sx(t_tel), sy(t_tel)
    else:
        x_grid, y_grid = lin(raw.x_m), lin(raw.y_m)

    # Data-quality metrics; the bounds that gate a lap are LAP_CHECKS in modeling/validation.py
    t_in = retime(raw.time_s[inside])
    pred_end = t_in[-1] + (length - s_in[-1]) / max(v_in[-1], 1.0)
    inv_v = 1.0 / np.maximum(v_in, 1.0)
    integral = float(np.sum(0.5 * (inv_v[1:] + inv_v[:-1]) * np.diff(s_in)))
    measured = float(t_in[-1] - t_in[0])
    quality = {
        "n_samples": float(len(s_in)),
        "n_gps_fixes": float(f.sum()),
        "gps_lag_s": tau,
        "gps_speed_rms_ms": lag_rms,
        "projection_rms_m": float(np.sqrt(np.mean(offset**2))),
        "max_sample_gap_m": float(np.max(np.diff(s_t))),
        "time_closure_ms": float((pred_end - meta.lap_time_s) * 1000.0),
        "start_line_gap_m": start_gap,
        "finish_line_gap_m": end_gap,
        "line_gap_mismatch_m": start_gap - end_gap,
        "speed_time_consistency_pct": float((integral - measured) / measured * 100.0),
        "speed_trap_minus_max_kmh": float(meta.speed_trap_kmh - np.max(v_in) * 3.6),
        "frozen_run_m": longest_frozen_run_m(raw, inside, s_raw),
        "throttle_max_pct": float(np.max(raw.throttle_pct[inside])),
    }

    return AlignedLap(
        meta=meta,
        ambient=ambient,
        distance_m=grid,
        time_s=time_s,
        speed_ms=speed_ms,
        throttle_pct=lin(raw.throttle_pct),
        brake=(lin(raw.brake) > 0.5).astype(np.float64),
        gear=np.rint(lin(raw.gear)),
        drs=(lin(raw.drs) > 0.5).astype(np.float64),
        rpm=lin(raw.rpm),
        x_m=x_grid,
        y_m=y_grid,
        z_m=lin(raw.z_m),
        gap_ahead_m=np.interp(grid, s_in, np.nan_to_num(raw.gap_ahead_m[inside], posinf=1e6)),
        lap_length_m=length,
        distance_scale=ref.scale,
        gps_time_s=retime(t_fix) if sx is not None else np.zeros(0),  # same clock as time_s
        gps_distance_m=s_fix if sx is not None else np.zeros(0),
        gps_x_m=raw.x_m[f] if sx is not None else np.zeros(0),
        gps_y_m=raw.y_m[f] if sx is not None else np.zeros(0),
        quality=quality,
    )
